"""The Play Store closed-test daily report (PLAYSTORE_CLOSED_TEST_PLAN.md, Appendix B) - READ-ONLY, for the MongoDB database.

It is the MongoDB version of the five SQL queries that used to run against `dusu-db-1` (Postgres). It only ever SELECTs: no `login`, no write of any kind. Counts and minutes only -
never a conversation (Q5 is the feedback learners typed into the Help screen, no emails).

  # from the repo root; the testers file is git-ignored (one email per line, any case)
  TESTERS=$(grep '@' playstore-testers.csv | tr -d '\\r' | paste -sd, -)
  docker exec -i -e TESTERS="$TESTERS" dusu-backend-1 python - --start 2026-10-10 < backend/scripts/playstore_report.py
  # (once an image that contains this file is deployed:  docker exec -e TESTERS="$TESTERS" dusu-backend-1 python /app/scripts/playstore_report.py --start 2026-10-10)

  --start YYYY-MM-DD   first day counted (default: 14 days ago)      --only q1,q3     run just these queries      --testers-file PATH   instead of $TESTERS

Output is psql-style (`|` separated, a header row, a blank line between queries) so it can be pasted into a sheet.
  Q1 status ladder per tester     Q2 per tester: sessions, active days, minutes, modes   Q3 cohort roll-up (owner excluded)
  Q4 sessions by mode             Q5 feedback since --start (no emails)
`usage_daily` stays empty in the growth phase, so `session_scores` is the engagement ledger; Learn sessions are not recorded. Days are UTC days, as the SQL's `date()` was.
"""
import argparse
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db                                                        # noqa: E402
from app.main import OWNER_EMAILS                                          # noqa: E402
from app.store import select                                               # noqa: E402

UTC = dt.timezone.utc


def _args():
    ap = argparse.ArgumentParser(description="Play Store closed-test daily report (read-only)")
    ap.add_argument("--start", default=(dt.datetime.now(UTC) - dt.timedelta(days=14)).date().isoformat())
    ap.add_argument("--only", default="", help="comma list: q1,q2,q3,q4,q5 (default: all)")
    ap.add_argument("--testers-file", default="")
    return ap.parse_args()


def _emails(a) -> list[str]:
    raw = open(a.testers_file).read() if a.testers_file else os.environ.get("TESTERS", "")
    out: list[str] = []
    for x in raw.replace(",", "\n").splitlines():
        x = x.strip().strip('"').lower()
        if "@" in x and x not in out:
            out.append(x)
    return out


def _print(title: str, header: list[str], rows: list[list]) -> None:
    print(f"-- {title}")
    print("|".join(header))
    for r in rows:
        print("|".join("" if v is None else str(v) for v in r))
    print()


def _day(d) -> str | None:
    return d.astimezone(UTC).date().isoformat() if isinstance(d, dt.datetime) else None


async def main() -> None:
    a = _args()
    want = {x.strip().lower() for x in a.only.split(",") if x.strip()} or {"q1", "q2", "q3", "q4", "q5"}
    try:
        start = dt.datetime.fromisoformat(a.start).replace(tzinfo=UTC)
    except ValueError:
        sys.exit("--start must be YYYY-MM-DD")
    if not db.db_enabled:
        sys.exit("no database configured (MONGODB_URI is empty)")
    testers = _emails(a)
    if not testers and want & {"q1", "q2", "q3"}:
        sys.exit("no tester emails: set TESTERS=a@x.com,b@y.com (or --testers-file)")
    owners = {e.lower() for e in OWNER_EMAILS}

    async with db._Session() as s:
        users_all = (await s.execute(select(db.User.id, db.User.email, db.User.last_seen))).all()
        sessions = (await s.execute(select(db.SessionScore.user_id, db.SessionScore.created_at, db.SessionScore.minutes, db.SessionScore.mode)
                                    .where(db.SessionScore.created_at >= start))).all()
        verified = {r[0]: bool(r[1]) for r in (await s.execute(select(db.UserKey.user_id, db.UserKey.verified))).all()}
        fb = (await s.execute(select(db.Feedback.created_at, db.Feedback.kind, db.Feedback.text).where(db.Feedback.created_at >= start)
                              .order_by(db.Feedback.created_at))).all() if "q5" in want else []

    by_email = {}
    for uid, email, last_seen in users_all:
        by_email.setdefault((email or "").lower(), (uid, last_seen))                       # lower(email) -> (id, last_seen)
    per_user: dict[str, dict] = {}
    for uid, created, minutes, mode in sessions:
        d = per_user.setdefault(uid, {"n": 0, "mins": 0.0, "days": set(), "modes": set()})
        d["n"] += 1
        d["mins"] += float(minutes or 0)
        d["days"].add(_day(created))
        d["modes"].add(mode)

    if "q1" in want:                                                                          # status ladder: invited -> signed in -> access -> ACTIVE
        rows = []
        for e in testers:
            u = by_email.get(e)
            if u is None:
                status, n, mins, seen = "1-invited-never-signed-in", 0, 0.0, None
            else:
                p = per_user.get(u[0], {"n": 0, "mins": 0.0})
                n, mins, seen = p["n"], p["mins"], _day(u[1])
                status = "4-ACTIVE" if n > 0 else ("3-has-access-never-spoke" if verified.get(u[0]) else "2-signed-in-stuck-before-access")
            rows.append([e, status, n, round(mins, 1), seen])
        rows.sort(key=lambda r: (r[1], r[0]))
        _print(f"Q1  status ladder per tester (sessions since {a.start})", ["email", "status", "sessions", "minutes", "last_seen"], rows)

    if "q2" in want:                                                                          # per tester since start (signed-in testers only, like the INNER JOIN)
        rows = []
        for e in testers:
            u = by_email.get(e)
            if u is None:
                continue
            p = per_user.get(u[0], {"n": 0, "mins": 0.0, "days": set(), "modes": set()})
            rows.append([e[:4] + "***", p["n"], len(p["days"]), round(p["mins"], 1), len(p["modes"])])
        rows.sort(key=lambda r: (-r[1], -r[2]))
        _print(f"Q2  per tester since {a.start}", ["tester", "sessions", "active_days", "minutes", "modes_used"], rows)

    if "q3" in want:                                                                          # cohort roll-up, owner excluded
        ids = [by_email[e][0] for e in testers if e in by_email and e not in owners]
        ps = [per_user.get(i, {"n": 0, "days": set()}) for i in ids]
        _print("Q3  cohort roll-up (owner excluded)", ["testers_signed_in", "with_a_session", "active_5plus_days", "total_sessions"],
               [[len(ids), sum(1 for p in ps if p["n"] >= 1), sum(1 for p in ps if len(p["days"]) >= 5), sum(p["n"] for p in ps)]])

    if "q4" in want:                                                                          # every learner, not only testers
        modes: dict[str, int] = {}
        for _uid, _c, _m, mode in sessions:
            modes[mode] = modes.get(mode, 0) + 1
        _print(f"Q4  sessions by mode since {a.start}", ["mode", "sessions"], sorted(([m, n] for m, n in modes.items()), key=lambda r: (-r[1], r[0])))

    if "q5" in want:                                                                          # what learners typed into Help & Feedback, no emails
        _print(f"Q5  feedback since {a.start} (no emails)", ["day", "kind", "text"],
               [[(c.astimezone(UTC).strftime("%m-%d") if isinstance(c, dt.datetime) else ""), k, (t or "").replace("\n", " ")[:160]] for c, k, t in fb])

    try:
        await db.store.close()
    except Exception:                                                                         # noqa: BLE001
        pass


asyncio.run(main())
