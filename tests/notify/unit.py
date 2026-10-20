"""Notifications - tier 1: the PURE rules (no database, no network, no clock except an argument).

Run via:  docker run --rm -i -v "$PWD/backend":/app -v "$PWD/tests":/tests dusu-ri-test python /tests/notify/unit.py
(or tests/notify/run.sh unit.py - it only needs the test image; the scratch Postgres it starts is not used here).

What is proven: who gets which nudge and when (windows, priority, caps, quiet hours, time zones, DST), the send-time re-check, the ignore-three
back-off, every sentence in both languages (no unresolved placeholders, no gendered Hindi toward the learner, limits, hostile names), the payload, the
signed receipt token (and that it cannot be confused with My Day's action token), and that every string the feature writes fits its column.
Plain Python; prints PASS / FAIL per check and exits non-zero on any failure.
"""

import datetime as dt
import json
import re
import sys

sys.path.insert(0, "/app")

from app.notify import models as NM, rules as R, tokens as TK        # noqa: E402
from app.planner import push as PP, timeutil as tu                   # noqa: E402

UTC = dt.timezone.utc
FAILS: list[str] = []
N = 0


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:300]}")


def section(t):
    print(f"\n== {t}")


def at(y, mo, d, h=0, mi=0, s=0):
    return dt.datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def D(y, mo, d):
    return dt.date(y, mo, d)


def ist(y, mo, d, h, mi=0):
    return tu.to_utc(D(y, mo, d), dt.time(h, mi), "Asia/Kolkata")


# A learner who is onboarded, practised yesterday on a 5-day streak, wants the 19:00 default, India time.
def snap(**kw):
    s = {"uid": "u1", "tz": "Asia/Kolkata", "quiet_on": True, "quiet_start": "22:00", "quiet_end": "07:00", "hide": False, "enabled": True,
         "kinds": {"practice": True, "streak": True, "weekly": True}, "nudge_time": "19:00", "onboarded": True, "streak_days": 5,
         "last_active": D(2026, 10, 20), "xp": 100, "last_letter": None, "active_days": set(), "lang": "hi", "name": "Asha", "recent": []}
    s.update(kw)
    return s


WED = D(2026, 10, 21)                                                # a Wednesday
SUN = D(2026, 10, 25)                                                # the Sunday after


def main():
    # ------------------------------------------------------------------ small cleaners
    section("cleaners")
    check("clean_time accepts HH:MM", R.clean_time("07:05") == "07:05" and R.clean_time("19:00") == "19:00")
    check("clean_time rejects letters, empty and no-colon input", all(R.clean_time(x) is None for x in ("ab:cd", "", "soon", "1900", None)))
    check("clean_time rejects 25:00 / 12:60 / None / ints", R.clean_time("25:00") is None and R.clean_time("12:60") is None and R.clean_time(None) is None and R.clean_time(1900) is None)
    check("clean_kinds defaults to all on", R.clean_kinds(None) == {"practice": True, "streak": True, "weekly": True})
    check("clean_kinds ignores unknown keys and non-booleans", R.clean_kinds({"practice": False, "evil": True, "weekly": "no", "streak": 0}) == {"practice": False, "streak": True, "weekly": True})
    check("clean_kinds keeps the current value for a missing kind", R.clean_kinds({"weekly": False}, {"practice": False, "streak": True}) == {"practice": False, "streak": True, "weekly": False})
    check("first_name takes the first word", R.first_name("Asha Rana") == "Asha")
    check("first_name keeps Devanagari and its marks", R.first_name("आशा राणा") == "आशा" and R.first_name("श्रेया") == "श्रेया")
    check("first_name drops digits and emoji", R.first_name("Asha7") == "Asha" and R.first_name("A\U0001F600sha") == "Asha")
    nm = R.first_name("<script>alert(1)</script>")
    check("first_name never lets markup through", "<" not in nm and ">" not in nm and "(" not in nm, nm)
    check("first_name caps the length", len(R.first_name("A" * 100)) == 20)
    check("first_name of nothing is empty", R.first_name(None) == "" and R.first_name("") == "" and R.first_name("   ") == "" and R.first_name("123") == "" and R.first_name(5) == "")
    check("first_name keeps hyphen and apostrophe", R.first_name("Mary-Jane") == "Mary-Jane" and R.first_name("O'Neil") == "O'Neil")
    check("ist_date uses the IST day boundary", R.ist_date(at(2026, 10, 20, 18, 29)) == D(2026, 10, 20) and R.ist_date(at(2026, 10, 20, 18, 31)) == D(2026, 10, 21))

    # ------------------------------------------------------------------ streak alive
    section("a streak is alive only if they were last active today or yesterday")
    check("last active today: alive", R.alive_streak(5, WED, WED) == 5)
    check("last active yesterday: alive", R.alive_streak(5, D(2026, 10, 20), WED) == 5)
    check("last active two days ago: lapsed (the stored number is stale)", R.alive_streak(5, D(2026, 10, 19), WED) == 0)
    check("never active / no streak / junk: 0", R.alive_streak(5, None, WED) == 0 and R.alive_streak(0, WED, WED) == 0 and R.alive_streak(-3, WED, WED) == 0 and R.alive_streak(None, WED, WED) == 0)

    # ------------------------------------------------------------------ which daily kind
    section("the daily kind: streak beats practice, one slot a day")
    check("live streak, not practised today: streak", R.pick_daily_kind(snap(), WED) == "streak")
    check("practised today: nothing", R.pick_daily_kind(snap(last_active=WED), WED) is None)
    check("a streak of 1 is not worth defending: practice", R.pick_daily_kind(snap(streak_days=1), WED) == "practice")
    check("a lapsed streak: practice", R.pick_daily_kind(snap(last_active=D(2026, 10, 17)), WED) == "practice")
    check("never practised: practice", R.pick_daily_kind(snap(last_active=None, streak_days=0), WED) == "practice")
    check("streak switched off: falls back to practice", R.pick_daily_kind(snap(kinds={"practice": True, "streak": False, "weekly": True}), WED) == "practice")
    check("practice switched off, streak on, streak alive: streak", R.pick_daily_kind(snap(kinds={"practice": False, "streak": True, "weekly": True}), WED) == "streak")
    check("practice switched off, no streak: nothing", R.pick_daily_kind(snap(streak_days=1, kinds={"practice": False, "streak": True, "weekly": True}), WED) is None)
    check("both switched off: nothing", R.pick_daily_kind(snap(kinds={"practice": False, "streak": False, "weekly": True}), WED) is None)
    check("not onboarded: nothing", R.pick_daily_kind(snap(onboarded=False), WED) is None)

    # ------------------------------------------------------------------ weekly
    section("the weekly note")
    check("due: activity, active this week, no letter yet", R.weekly_due(snap(), SUN))
    check("not due: too little xp", not R.weekly_due(snap(xp=19), SUN) and R.weekly_due(snap(xp=20), SUN))
    check("not due: not active for 8 days", not R.weekly_due(snap(last_active=D(2026, 10, 17)), SUN) and R.weekly_due(snap(last_active=D(2026, 10, 18)), SUN))
    check("not due: never active", not R.weekly_due(snap(last_active=None), SUN))
    check("not due: the last letter is 6 days old, due at 7", not R.weekly_due(snap(last_letter=D(2026, 10, 19)), SUN) and R.weekly_due(snap(last_letter=D(2026, 10, 18)), SUN))
    check("not due: the letter was made today", not R.weekly_due(snap(last_letter=SUN), SUN))
    check("not due: the kind is off / not onboarded", not R.weekly_due(snap(kinds={"practice": True, "streak": True, "weekly": False}), SUN) and not R.weekly_due(snap(onboarded=False), SUN))

    # ------------------------------------------------------------------ ignored three in a row
    section("three ignored nudges in a row -> a week's rest, unless they come back")
    now = at(2026, 10, 21, 13, 30)

    def rec(days_ago, opened=False):
        t = now - dt.timedelta(days=days_ago)
        return {"sent_at": t, "opened_at": t + dt.timedelta(minutes=5) if opened else None}

    three = [rec(1), rec(2), rec(3)]
    check("fewer than three delivered: never paused", not R.is_paused(snap(recent=three[:2]), now) and not R.is_paused(snap(recent=[]), now))
    check("three ignored: paused", R.is_paused(snap(recent=three), now))
    check("one of the three was opened: not paused", not R.is_paused(snap(recent=[rec(1), rec(2, True), rec(3)]), now))
    check("they practised on the day of one of them: not paused", not R.is_paused(snap(recent=three, active_days={R.ist_date(now - dt.timedelta(days=2))}), now))
    check("they practised AFTER the newest nudge: not paused", not R.is_paused(snap(recent=three, last_active=R.ist_date(now)), now))
    old_la = D(2026, 10, 10)                                         # they have not practised since
    check("a week after the newest: the pause is over", not R.is_paused(snap(recent=[rec(7), rec(8), rec(9)], last_active=old_la), now)
          and R.is_paused(snap(recent=[rec(6), rec(7), rec(8)], last_active=old_la), now))
    check("only the three newest count", R.is_paused(snap(recent=three + [rec(4, True), rec(5, True)]), now))

    # ------------------------------------------------------------------ slots: windows, quiet hours, time zones
    section("slots: open from 20 minutes before to 90 minutes after, on the learner's own clock")
    fire = ist(2026, 10, 21, 19, 0)                                  # 13:30 UTC
    check("India 19:00 is 13:30 UTC", fire == at(2026, 10, 21, 13, 30))
    check("21 minutes before: closed", R.slots(snap(), fire - dt.timedelta(minutes=21))["daily"] is None)
    check("20 minutes before: open", R.slots(snap(), fire - dt.timedelta(minutes=20))["daily"] == (fire, "day:2026-10-21"))
    check("90 minutes after: still open", R.slots(snap(), fire + dt.timedelta(minutes=90))["daily"] is not None)
    check("91 minutes after: closed (a late nudge is worse than none)", R.slots(snap(), fire + dt.timedelta(minutes=91))["daily"] is None)
    check("disabled: no slots at all", R.slots(snap(enabled=False), fire) == {"daily": None, "weekly": None})
    check("a custom time is honoured", R.slots(snap(nudge_time="07:30"), ist(2026, 10, 21, 7, 30))["daily"] is not None and R.slots(snap(nudge_time="07:30"), fire)["daily"] is None)
    check("a junk nudge time falls back to 19:00", R.slots(snap(nudge_time="soon"), fire)["daily"] is not None)
    # quiet hours 22:00-07:00
    late = ist(2026, 10, 21, 23, 0)
    check("23:00 is inside quiet hours and the release is tomorrow: no slot today", R.slots(snap(nudge_time="23:00"), late)["daily"] is None)
    early = R.slots(snap(nudge_time="06:00"), ist(2026, 10, 21, 7, 0))["daily"]
    check("06:00 is inside quiet hours: moved to 07:00 the same day", early is not None and early[0] == ist(2026, 10, 21, 7, 0), early)
    check("quiet hours off: 23:00 stays", R.slots(snap(nudge_time="23:00", quiet_on=False), late)["daily"] is not None)
    # weekly only on Sunday, at 10:00
    check("weekly slot on Sunday 10:00", R.slots(snap(), ist(2026, 10, 25, 10, 0))["weekly"] == (ist(2026, 10, 25, 10, 0), "weekly:2026-W43"))
    check("no weekly slot on a Wednesday", R.slots(snap(), ist(2026, 10, 21, 10, 0))["weekly"] is None)
    check("the weekly key is the ISO week (Mon 26 Oct is the next one)", R.slots(snap(), ist(2026, 11, 1, 10, 0))["weekly"][1] == "weekly:2026-W44")
    # another time zone: New York, EDT (UTC-4) until 1 Nov 2026
    ny = snap(tz="America/New_York")
    f_ny = tu.to_utc(D(2026, 10, 21), dt.time(19, 0), "America/New_York")
    check("New York 19:00 EDT = 23:00 UTC", f_ny == at(2026, 10, 21, 23, 0))
    check("slot opens on the New York clock", R.slots(ny, f_ny)["daily"] == (f_ny, "day:2026-10-21") and R.slots(ny, ist(2026, 10, 21, 19, 0))["daily"] is None)
    # the day the clocks go back in New York (Sun 1 Nov 2026): 19:00 is 00:00 UTC on the 2nd (EST, UTC-5)
    f_dst = tu.to_utc(D(2026, 11, 1), dt.time(19, 0), "America/New_York")
    check("DST: 19:00 on the day clocks go back is 00:00 UTC next day", f_dst == at(2026, 11, 2, 0, 0), f_dst)
    check("DST: the slot still opens exactly once", R.slots(ny, f_dst)["daily"] == (f_dst, "day:2026-11-01"))
    # the key follows the learner's LOCAL day, not UTC: 19:00 in Sydney (UTC+11) on the 22nd is 08:00 UTC the 22nd, but 03:30 India on the 22nd
    syd = snap(tz="Australia/Sydney")
    f_syd = tu.to_utc(D(2026, 10, 22), dt.time(19, 0), "Australia/Sydney")
    check("the day key is the learner's local day", R.slots(syd, f_syd)["daily"] == (f_syd, "day:2026-10-22"), R.slots(syd, f_syd))

    # ------------------------------------------------------------------ plan_today
    section("plan_today: what is made, once")
    p = R.plan_today(snap(), fire)
    check("a streak learner at 19:00: one streak row", len(p) == 1 and p[0]["kind"] == "streak" and p[0]["fire_at"] == fire and p[0]["dedupe_key"] == "day:2026-10-21" and p[0]["url"] == "/", p)
    check("planning twice gives the same row (idempotent)", R.plan_today(snap(), fire) == p)
    check("no streak: a practice row", R.plan_today(snap(streak_days=0, last_active=None), fire)[0]["kind"] == "practice")
    check("already practised: nothing", R.plan_today(snap(last_active=WED), fire) == [])
    check("paused: nothing", R.plan_today(snap(recent=[rec(1), rec(2), rec(3)]), fire) == [])
    check("disabled: nothing", R.plan_today(snap(enabled=False), fire) == [])
    sun10 = ist(2026, 10, 25, 10, 0)
    pw = R.plan_today(snap(), sun10)
    check("Sunday 10:00: the weekly note (the 19:00 nudge is not open yet)", [x["kind"] for x in pw] == ["weekly"], pw)
    sun19 = ist(2026, 10, 25, 19, 0)
    pd = R.plan_today(snap(last_active=D(2026, 10, 24)), sun19)
    check("Sunday 19:00: the daily nudge only (the weekly window closed at 11:30)", [x["kind"] for x in pd] == ["streak"], pd)
    check("practised today but the letter is due: the weekly still goes (it is not a practice nudge)", [x["kind"] for x in R.plan_today(snap(last_active=SUN), sun10)] == ["weekly"])
    check("the weekly respects its own switch while the daily kinds stay on", R.plan_today(snap(kinds={"practice": True, "streak": True, "weekly": False}), sun10) == [])

    # ------------------------------------------------------------------ the send-time re-check
    section("still_wanted: re-checked at SEND time")
    check("a test is always wanted", R.still_wanted("test", snap(enabled=False), fire) == (True, "test"))
    check("a normal nudge: wanted, as the streak kind", R.still_wanted("streak", snap(), fire) == (True, "streak"))
    check("they practised in the meantime: cancelled 'done'", R.still_wanted("streak", snap(last_active=WED), fire) == (False, "done"))
    check("switched off in the meantime: cancelled 'off'", R.still_wanted("practice", snap(enabled=False), fire) == (False, "off"))
    check("the streak lapsed after the row was made: goes out as practice", R.still_wanted("streak", snap(last_active=D(2026, 10, 17), streak_days=5), fire) == (True, "practice"))
    check("...and not at all if practice is off too", R.still_wanted("streak", snap(last_active=D(2026, 10, 17), kinds={"practice": False, "streak": True, "weekly": True}), fire) == (False, "off"))
    check("quiet hours at send time: cancelled 'quiet'", R.still_wanted("practice", snap(), ist(2026, 10, 21, 23, 30)) == (False, "quiet"))
    check("paused at send time: cancelled 'paused'", R.still_wanted("practice", snap(recent=[rec(1), rec(2), rec(3)]), fire) == (False, "paused"))
    check("the weekly: wanted when still due, 'not_due' once the letter exists", R.still_wanted("weekly", snap(), sun10) == (True, "weekly")
          and R.still_wanted("weekly", snap(last_letter=SUN), sun10) == (False, "not_due"))
    check("the weekly is not blocked by 'practised today'", R.still_wanted("weekly", snap(last_active=SUN), sun10) == (True, "weekly"))

    # ------------------------------------------------------------------ the words
    section("the words: every sentence, both languages")
    GENDERED = ("रहे हो", "सकते हो", "बोलोगे", "करोगे", "रही हो", "सकती हो", "बोलोगी", "करोगी", "गए", "गयी", "तू ", "तेरा", "तेरी", "करता", "करती हूँ")
    seen = set()
    for kind in ("practice", "streak", "weekly", "test"):
        for lang in ("hi", "en"):
            for n_ in range(len(R.COPY[kind][lang])):
                for name in ("Asha", "", "आशा"):
                    # find a (uid, day) that selects variant n_
                    for k in range(400):
                        if R._pick(f"u{k}", "2026-10-21", len(R.COPY[kind][lang])) == n_:
                            t, b = R.render(kind, lang, name, 7, False, f"u{k}", "2026-10-21")
                            break
                    seen.add((kind, lang, n_, name))
                    check(f"{kind}/{lang}/#{n_}/{name or 'noname'}: no placeholder left, limits kept", "{" not in t + b and "}" not in t + b and 0 < len(t) <= 60 and 0 < len(b) <= 160, (t, b))
                    if lang == "hi":
                        check(f"{kind}/hi/#{n_}/{name or 'noname'}: Devanagari, no gendered form toward the learner", re.search(r"[ऀ-ॿ]", t + b) and not any(g in b + t for g in GENDERED), (t, b))
                    if kind == "streak":
                        check(f"streak/{lang}/#{n_}: carries the number", "7" in t + b, (t, b))
    check("every variant of every kind was exercised", len(seen) == sum(len(R.COPY[k][lg]) for k in R.COPY for lg in ("hi", "en")) * 3)
    t, b = R.render("practice", "en", "", 0, False, "u1", "2026-10-21")
    check("English with no name starts a capital sentence", b[:1].isupper(), b)
    t, b = R.render("practice", "en", "Asha", 0, False, "u1", "2026-10-21")
    check("English with a name leads with it", b.startswith("Asha, "), b)
    t, b = R.render("practice", "hi", "Asha", 0, False, "u1", "2026-10-21")
    check("Hindi with a name leads with it and a danda", b.startswith("Asha। "), b)
    check("deterministic for one learner on one day", R.render("practice", "hi", "Asha", 0, False, "u1", "2026-10-21") == R.render("practice", "hi", "Asha", 0, False, "u1", "2026-10-21"))
    days = {R.render("practice", "hi", "Asha", 0, False, "u1", f"2026-10-{d:02d}") for d in range(1, 29)}
    check("the wording varies from day to day", len(days) >= 2, days)
    hs = [R.render(k, lg, "Asha", 9, True, "u1", "2026-10-21") for k in ("practice", "streak", "weekly") for lg in ("hi", "en")]
    check("lock-screen privacy: nothing personal (no name, no number, no streak)", all("Asha" not in a + b and "9" not in a + b and "streak" not in (a + b).lower() for a, b in hs), hs)
    check("lock-screen privacy: the hidden text is one generic line per language", set(hs) == {R.HIDDEN["hi"], R.HIDDEN["en"]}, set(hs))
    check("a test notification is never hidden (it must say it is a test)", "test" in R.render("test", "en", "", 0, True, "u1", "2026-10-21")[0].lower())
    hostile = R.render("practice", "en", "<img src=x onerror=alert(1)>", 0, False, "u1", "2026-10-21")
    check("a hostile name never reaches the text as markup", "<" not in hostile[0] + hostile[1] and "=" not in hostile[1], hostile)
    check("an unknown language falls back to Hindi (the default)", R.render("practice", "fr", "Asha", 0, False, "u1", "2026-10-21") == R.render("practice", "hi", "Asha", 0, False, "u1", "2026-10-21"))
    check("an unknown kind falls back to the practice copy rather than raising", R.render("nonsense", "en", "", 0, False, "u1", "2026-10-21")[0] in {v[0] for v in R.COPY["practice"]["en"]})

    # ------------------------------------------------------------------ payload + url
    section("the payload that is pushed")
    raw = R.build_payload(12, "DuSu", "आज की practice बाकी है।", "/", TK.make_ack(12))
    pl = json.loads(raw.decode("utf-8"))
    check("valid JSON, well under the 4 KB push limit", len(raw) < 1000, len(raw))
    check("it carries the id, the in-app path and a receipt token, and no buttons", pl["data"]["nid"] == 12 and pl["data"]["url"] == "/" and TK.read_ack(pl["data"]["ack"]) == 12 and pl["actions"] == [] and pl["tag"] == "nt12", pl)
    check("Devanagari survives the encoding", "आज की practice" in raw.decode("utf-8"))
    check("safe_url keeps in-app paths", R.safe_url("/") == "/" and R.safe_url("/my-day/tasks") == "/my-day/tasks")
    check("safe_url refuses anything else", all(R.safe_url(u) == "/" for u in ("https://evil.example/", "//evil.example", "javascript:alert(1)", "/a?b=c", "/a b", "", None, 5, "/" + "a" * 80)))

    # ------------------------------------------------------------------ tokens
    section("the receipt token")
    tk = TK.make_ack(77)
    check("a fresh token reads back", TK.read_ack(tk) == 77)
    check("it is short", len(tk) < 90, len(tk))
    check("an expired token is refused", TK.read_ack(TK.make_ack(77, ttl=60, now=1000.0), now=1061.0) is None and TK.read_ack(TK.make_ack(77, ttl=60, now=1000.0), now=1059.0) == 77)
    check("a tampered body or signature is refused", TK.read_ack(tk[:-2] + ("A" if tk[-1] != "A" else "B") + "x") is None and TK.read_ack("x" + tk) is None)
    b, sig = tk.split(".")
    other = TK._b64(b"78|ack|99999999999")
    check("a token for another id with this signature is refused", TK.read_ack(other + "." + sig) is None)
    check("garbage never raises", all(TK.read_ack(x) is None for x in (None, "", ".", "a.b", 5, b"bytes", "a" * 5000, "!!!.???", {"a": 1})))
    mine, theirs = PP.make_token(77, "done"), TK.make_ack(77)
    check("My Day's action token is not accepted here", TK.read_ack(mine) is None)
    check("this receipt is not accepted as a My Day action", PP.read_token(theirs) is None)

    # ------------------------------------------------------------------ column widths
    section("every string the feature writes fits its column (a too-long value is a 500 that only a real database shows)")
    cols = {c.name: c.type.length for c in NM.NtOutbox.__table__.columns if hasattr(c.type, "length") and c.type.length}
    check("kind values", all(len(k) <= cols["kind"] for k in ("practice", "streak", "weekly", "test")), cols)
    check("status values", all(len(k) <= cols["status"] for k in ("scheduled", "sending", "sent", "cancelled")))
    check("push_state values", all(len(k) <= cols["push_state"] for k in ("none", "accepted", "failed", "no_subscription")))
    whys = ("blocked", "switch_off", "stale", "no_data", "no_device", "push_failed", "off", "quiet", "done", "paused", "not_due", "OperationalError", "InterfaceError")
    check("why values (the code also truncates exception names to 24)", all(len(k[:24]) <= cols["why"] for k in whys))
    check("dedupe keys (daily, weekly, a test with microseconds)", all(len(k) <= cols["dedupe_key"] for k in ("day:2026-10-21", "weekly:2026-W43", "test:20261021T133000123456")))
    t, b = R.render("streak", "hi", "A" * 100, 100000, False, "u" * 64, "2026-10-21")
    check("rendered text is clipped to the title / body columns", len(t) <= cols["title"] and len(b) <= cols["body"], (len(t), len(b)))
    check("url fits", cols["url"] >= 60)
    check("nudge_time fits", NM.NtPrefs.__table__.c.nudge_time.type.length >= 5)

    print(f"\n{N - len(FAILS)} / {N} checks passed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
        sys.exit(1)


main()
