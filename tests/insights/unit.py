"""Insights - tier 1: pure checks, no database (run via tests/insights/run.sh unit.py).

What is proven: the event allow-lists are consistent (a client can only ever send what it is allowed to, the server-only names cannot be faked from a browser); the
funnel lists every milestone with a label; every value the code writes fits its column (a too-narrow String(n) is only caught by a real database otherwise); the
plan / price-feel cleaners accept exactly the allowed values and nothing else (hostile input included); the index page's ETag logic (strong, weak, a list, `*`, junk) and
its build-once cache; and the "versioned asset" rule that lets a file be cached for a year.
"""

import hashlib
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, "/app")

from app import main as M                                           # noqa: E402
from app.insights import models as IM, service as svc               # noqa: E402

FAILS: list = []
N = 0


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:400]}")


def section(t):
    print(f"\n== {t}")


section("the allow-lists")
check("client and server event names do not overlap (a browser can never send a server-only milestone)", not set(svc.CLIENT_EVENTS) & set(svc.SERVER_EVENTS))
check("MILESTONES is exactly client + server", set(svc.MILESTONES) == set(svc.CLIENT_EVENTS) | set(svc.SERVER_EVENTS) and len(svc.MILESTONES) == len(set(svc.MILESTONES)))
check("the funnel shows every milestone, once, in a stated order", sorted(svc.FUNNEL_ORDER) == sorted(svc.MILESTONES), svc.FUNNEL_ORDER)
check("every milestone has a plain-English label for the owner", all(svc.LABELS.get(m) for m in svc.MILESTONES))
check("about ten counters, no more", 6 <= len(svc.MILESTONES) <= 12, len(svc.MILESTONES))
check("the three client events are exactly the screens only a client can know", set(svc.CLIENT_EVENTS) == {"keys_seen", "plans_seen", "install_accepted"}, svc.CLIENT_EVENTS)
check("plan_reserved is server-only (written by the endpoint itself, not by a beacon)", "plan_reserved" in svc.SERVER_EVENTS and "plan_reserved" not in svc.CLIENT_EVENTS)

section("column widths fit every value the code writes")
cols = lambda m: m.__table__.c                                        # noqa: E731
check("milestone names fit ev_milestones.name", max(len(m) for m in svc.MILESTONES) <= cols(IM.EvMilestone)["name"].type.length, max(len(m) for m in svc.MILESTONES))
check("a day string fits ev_days.day", len("2026-10-30") <= cols(IM.EvDay)["day"].type.length)
check("plan names fit plan_interest.plan", max(len(p) for p in svc.PLANS) <= cols(IM.PlanInterest)["plan"].type.length)
check("price opinions fit plan_interest.price_feel", max(len(f) for f in svc.FEELS) <= cols(IM.PlanInterest)["price_feel"].type.length, svc.FEELS)
check("the three tables are the three the privacy page names", {IM.EvMilestone.__tablename__, IM.EvDay.__tablename__, IM.PlanInterest.__tablename__} == {"ev_milestones", "ev_days", "plan_interest"})
check("every table is keyed by learner (so deleting the account can delete the rows)", all("user_id" in cols(m) for m in (IM.EvMilestone, IM.EvDay, IM.PlanInterest)))

section("clean_plan / clean_feel accept exactly the allowed values")
good = {"starter": "starter", "PLUS": "plus", "  Pro ": "pro"}
check("the three plans, any case, spaces and a trailing newline trimmed", all(svc.clean_plan(k) == v for k, v in good.items()) and svc.clean_plan("starter\n") == "starter")
bad = ["", None, "free", "Starter; DROP TABLE users", "starter\n\nplus", "plus pro", "ultimate", 7, 0, [], {}, ["pro"], {"plan": "pro"}, "pro" * 50, "ｐｒｏ", "pr​o", "<b>pro</b>", "../pro"]
check("everything else is refused, hostile input included", all(svc.clean_plan(b) is None for b in bad), [b for b in bad if svc.clean_plan(b) is not None])
check("price opinions: blank and the three words, nothing else", [svc.clean_feel(x) for x in ("", None, "too_high", " Fair ", "GREAT")] == ["", "", "too_high", "fair", "great"], [svc.clean_feel(x) for x in ("", None, "too_high", " Fair ", "GREAT")])
bad_f = ["cheap", "high", "too high", 3, [], {}, "great!", "fair\x00", "x" * 40]
check("an unknown price opinion is refused (None), never stored", all(svc.clean_feel(b) is None for b in bad_f), [b for b in bad_f if svc.clean_feel(b) is not None])

section("the index page: ETag matching")
E = '"0123456789abcdef01234567"'
check("the same strong tag matches", M._etag_matches(E, E))
check("a weak copy of it matches (Cloudflare turns a strong tag weak when it compresses)", M._etag_matches("W/" + E, E))
check("a list containing it matches", M._etag_matches('"zzz", W/' + E + ', "yyy"', E))
check("* matches anything", M._etag_matches("*", E))
check("a different tag does not", not M._etag_matches('"other"', E))
check("an empty or missing header does not", not M._etag_matches("", E) and not M._etag_matches(None, E))
check("junk does not", not any(M._etag_matches(j, E) for j in ("W/", "W/\"\"", ",,,", "0123456789abcdef01234567", "W/0123456789abcdef01234567", E[:-1])))
WK = "W/" + E          # the page's own tag is WEAK (Cloudflare drops a strong one when it re-encodes the page)
check("the page's own weak tag matches itself, a strong copy of it, and a list holding either", M._etag_matches(WK, WK) and M._etag_matches(E, WK) and M._etag_matches('"zzz", ' + E, WK) and M._etag_matches('"zzz", ' + WK, WK))
check("a different tag - strong or weak - does not match a weak server tag", not M._etag_matches('"other"', WK) and not M._etag_matches('W/"other"', WK))
check("an empty server tag never matches anything (there is nothing to compare)", not any(M._etag_matches(h, "") for h in ("W/", '""', 'W/""', "", None, "abc")) and M._etag_matches("*", WK))

section("the self-hosted font and the WebP logo have real content types")
import mimetypes                                                     # noqa: E402
check("importing the app registers font/woff2 and image/webp (the slim image has no mime table; Starlette would answer text/plain)", mimetypes.guess_type("/assets/fonts/inter-latin-v1.woff2")[0] == "font/woff2" and mimetypes.guess_type("/assets/icons/dusu-logo-160-v1.webp")[0] == "image/webp", (mimetypes.guess_type("a.woff2"), mimetypes.guess_type("a.webp")))
check("the file types that were already right stay right", mimetypes.guess_type("a.png")[0] == "image/png" and mimetypes.guess_type("a.js")[0] in ("text/javascript", "application/javascript") and mimetypes.guess_type("a.html")[0] == "text/html")

section("the index page is built once per file version")
d = tempfile.mkdtemp()
fake = os.path.join(d, "page.html")
open(fake, "w").write("<html>__GOOGLE_CLIENT_ID__ __AUTH_ENABLED__ __MAX_SESSIONS__</html>")
orig = M._CLIENT_HTML
from pathlib import Path                                              # noqa: E402
M._CLIENT_HTML = Path(fake)
M._INDEX.update(key=None, html="", etag="")
h1, e1 = M._index_page()
h2, e2 = M._index_page()
check("the placeholders are filled", "__GOOGLE_CLIENT_ID__" not in h1 and "__AUTH_ENABLED__" not in h1 and "__MAX_SESSIONS__" not in h1, h1)
check("a second request returns the SAME built page (no re-read, no re-build)", h1 is h2 and e1 == e2)
check("the ETag is a WEAK quoted hash of the built page (a compressing proxy keeps a weak tag and drops a strong one)", re.fullmatch(r'W/"[0-9a-f]{24}"', e1) is not None and e1 == 'W/"' + hashlib.sha256(h1.encode()).hexdigest()[:24] + '"', e1)
time.sleep(0.02)
open(fake, "w").write("<html>changed __MAX_SESSIONS__</html>")
h3, e3 = M._index_page()
check("editing the file changes both the page and the ETag on the next request", h3 != h1 and e3 != e1 and "changed" in h3)
old_mx = M.settings.max_sessions_per_day
M.settings.max_sessions_per_day = old_mx + 1
h4, e4 = M._index_page()
check("a changed setting the page is built from is picked up too", h4 != h3 and e4 != e3)
M.settings.max_sessions_per_day = old_mx
M._CLIENT_HTML = orig
M._INDEX.update(key=None, html="", etag="")

section("versioned assets (cacheable for a year) vs the rest")
for name, want in (("inter-latin-v1.woff2", True), ("dusu-192-v1.png", True), ("dusu-logo-300-v12.webp", True), ("icons/dusu-512-v1.png", True),
                   ("idle.png", False), ("logo.png", False), ("a-v1b.png", False), ("v1.png", False), ("thing-v.png", False), ("x-v1", False), ("x-v1.woff2.map", False)):
    check(f"{name}: {'immutable' if want else 'not immutable'}", bool(M._VERSIONED.search(name)) == want)

section("the learner's counters are today's: streak and sessions-today are stored raw, so a stale number must not be shown as live")
import datetime as dt
import types
from app import db as DB

_real_now = DB._ist_now
D0 = dt.date(2030, 1, 15)                                            # far from the real clock: a version that reads the real clock instead of _ist_now() cannot agree with these


def _at(day, hh=10, mm=0):
    DB._ist_now = lambda: dt.datetime.combine(day, dt.time(hh, mm), tzinfo=DB._IST)


def _p(streak, sessions, last):
    return types.SimpleNamespace(streak_days=streak, sessions_today=sessions, last_active=last)


try:
    _at(D0)
    one = dt.timedelta(days=1)
    check("practised today: the stored numbers stand (streak 4, 2 sessions)", DB._live_counters(_p(4, 2, D0)) == (4, 2))
    check("practised yesterday: the streak is alive (today's practice will extend it) and today has no sessions yet", DB._live_counters(_p(4, 2, D0 - one)) == (4, 0), DB._live_counters(_p(4, 2, D0 - one)))
    check("last practised two days ago: the streak died - both are 0", DB._live_counters(_p(4, 2, D0 - 2 * one)) == (0, 0), DB._live_counters(_p(4, 2, D0 - 2 * one)))
    check("last practised eight days ago (the audit's lapsed learner): both 0", DB._live_counters(_p(4, 2, D0 - 8 * one)) == (0, 0))
    check("never practised (no date) with a stale number: 0 and 0", DB._live_counters(_p(3, 1, None)) == (0, 0))
    check("no progress row at all: 0 and 0", DB._live_counters(None) == (0, 0))
    check("an empty row (None counters) is read as 0, not an error", DB._live_counters(_p(None, None, D0)) == (0, 0))
    _at(D0, 0, 5)                                                    # five past midnight in India: the new day has begun
    check("five minutes after IST midnight yesterday's sessions are already not today's, and the streak is alive", DB._live_counters(_p(4, 2, D0 - one)) == (4, 0))
    _at(D0, 2, 0)                                                    # 02:00 in India is still the PREVIOUS day in UTC: the app's day is the IST day
    check("the day is the IST day, not the UTC day (02:00 IST = 20:30 UTC the evening before)", DB._live_counters(_p(4, 2, D0)) == (4, 2), DB._live_counters(_p(4, 2, D0)))
    _at(D0)
    st = DB._state(DB.User(id="u1", email="e@example.com", name="N", picture=""),
                   DB.Profile(user_id="u1", onboarded=True, goal="job", comfort="", practice_time="", level="A1", scores={}, weak_areas=[]),
                   DB.Progress(user_id="u1", xp=40, coins=3, streak_days=4, sessions_today=2, daily_goal=5, badges=[], journey={}, last_active=D0 - 8 * one))
    check("_state() (the /me block) carries the live numbers and leaves every other field alone", st["progress"]["streak_days"] == 0 and st["progress"]["sessions_today"] == 0 and st["progress"]["xp"] == 40 and st["progress"]["coins"] == 3 and st["progress"]["daily_goal"] == 5, st["progress"])
finally:
    DB._ist_now = _real_now

print(f"\n{N - len(FAILS)} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
