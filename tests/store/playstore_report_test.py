"""The Play Store daily report (backend/scripts/playstore_report.py) on a scratch MongoDB: synthetic learners and sessions, the script run EXACTLY as the runbook runs it (a subprocess,
script on stdin, tester emails in $TESTERS), its output compared with hand-computed numbers. Also proves it is read-only (every collection's document count is unchanged).
Run via tests/store/run.sh playstore_report_test.py"""
import asyncio
import datetime as dt
import os
import subprocess
import sys

sys.path.insert(0, "/app")

from app import db, store                                        # noqa: E402

UTC = dt.timezone.utc
FAILS = []
N = 0


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:300]}")


def at(day, h=10):
    return dt.datetime(2026, 10, day, h, 0, tzinfo=UTC)


async def user(sub, email):
    await db.login({"sub": sub, "email": email, "name": sub, "picture": ""})


async def sess(sub, mode, day, minutes=2.0):
    async with db._Session() as s:
        s.add(db.SessionScore(user_id=sub, mode=mode, created_at=at(day), minutes=minutes))
        await s.commit()


async def counts():
    d = store.core.database()
    return {n: await d[n].count_documents({}) for n in sorted(await d.list_collection_names()) if n != "counters"}


def run_report(args, testers):
    env = dict(os.environ, TESTERS=testers)
    p = subprocess.run([sys.executable, "-", *args], input=open("/app/scripts/playstore_report.py").read(), capture_output=True, text=True, env=env, cwd="/app", timeout=120)
    return p.returncode, p.stdout, p.stderr


def table(out, title_start):
    """The rows (list of lists) of the block whose title starts with `title_start`."""
    lines = out.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith("-- " + title_start))
    rows = []
    for ln in lines[i + 2:]:
        if not ln.strip():
            break
        rows.append(ln.split("|"))
    return lines[i + 1].split("|"), rows


async def main():
    await db.init_db()
    owner = "david123rana@gmail.com"
    await user("o", owner)
    await user("a1", "active.one@example.com")            # 3 sessions on 3 days, daily + conversation, + one BEFORE the start (must not count)
    await user("a2", "Active.Two@Example.com")            # mixed case in the database, 6 sessions on 6 days incl. interview
    await user("k", "has.access@example.com")             # verified keys, never spoke
    await user("st", "stuck@example.com")                 # signed in, nothing else
    await user("x", "not.a.tester@example.com")           # one conversation session, not in the tester list
    await db.save_user_keys("k", {"groq": "gsk_" + "G" * 30 + "xGq"}, verified=True)
    await sess("a1", "daily", 11, 3.0); await sess("a1", "conversation", 12, 4.0); await sess("a1", "daily", 13, 5.0); await sess("a1", "daily", 5, 9.0)      # day 5 is before --start
    for d_, m_ in ((11, "daily"), (12, "daily"), (13, "conversation"), (14, "interview"), (15, "daily"), (16, "daily")):
        await sess("a2", m_, d_, 2.5)
    await sess("x", "conversation", 12, 7.0)
    await sess("o", "daily", 12, 1.0)
    async with db._Session() as s:
        s.add(db.Feedback(user_id="a1", email="active.one@example.com", kind="feedback", text="Great app\nlove it", created_at=at(12)))
        s.add(db.Feedback(user_id="a2", email="active.two@example.com", kind="help", text="x" * 300, created_at=at(14)))
        s.add(db.Feedback(user_id="a1", email="active.one@example.com", kind="feedback", text="too old", created_at=at(3)))
        await s.commit()
    before = await counts()
    testers = ",".join([owner, "active.one@example.com", "active.two@example.com", "has.access@example.com", "stuck@example.com", "never.signed.in@example.com", "ACTIVE.ONE@example.com"])

    rc, out, err = run_report(["--start", "2026-10-10"], testers)
    check("the report runs as the runbook runs it (script on stdin, $TESTERS) and exits 0", rc == 0, err[-300:])
    check("it prints all five blocks", all(f"-- Q{i}" in out for i in range(1, 6)), out[:200])

    h, rows = table(out, "Q1")
    st = {r[0]: r for r in rows}
    check("Q1 header", h == ["email", "status", "sessions", "minutes", "last_seen"], h)
    check("Q1 a tester who never signed in", st["never.signed.in@example.com"][1] == "1-invited-never-signed-in", st.get("never.signed.in@example.com"))
    check("Q1 signed in but nothing else = stuck before access", st["stuck@example.com"][1] == "2-signed-in-stuck-before-access", st.get("stuck@example.com"))
    check("Q1 verified keys, never spoke = has access", st["has.access@example.com"][1] == "3-has-access-never-spoke", st.get("has.access@example.com"))
    check("Q1 active tester: 3 sessions since the start (the one before it is not counted), 12.0 minutes", st["active.one@example.com"][1:4] == ["4-ACTIVE", "3", "12.0"], st.get("active.one@example.com"))
    check("Q1 an email stored in mixed case matches the lower-case list; 6 sessions, 15.0 minutes", st["active.two@example.com"][1:4] == ["4-ACTIVE", "6", "15.0"], st.get("active.two@example.com"))
    check("Q1 the same tester listed twice (different case) appears once", len(rows) == 6, len(rows))
    check("Q1 sorted by status then email", [r[1] for r in rows] == sorted(r[1] for r in rows), [r[1] for r in rows])
    check("Q1 last_seen is a date", all(r[4] == "" or len(r[4]) == 10 for r in rows), rows[:2])

    h, rows = table(out, "Q2")
    check("Q2 header", h == ["tester", "sessions", "active_days", "minutes", "modes_used"], h)
    check("Q2 emails are masked to 4 letters + ***", all(r[0].endswith("***") and len(r[0]) == 7 for r in rows), rows)
    check("Q2 only signed-in testers, most sessions first", [r[1] for r in rows][:2] == ["6", "3"], rows)
    by = {r[0]: r for r in rows}
    check("Q2 active_days = distinct UTC days (3 for a1), modes_used 2", by["acti***"][1:] in (["6", "6", "15.0", "3"], ["3", "3", "12.0", "2"]), rows)

    h, rows = table(out, "Q3")
    check("Q3 cohort (owner excluded): 4 testers signed in, 2 with a session, 1 with 5+ days, 9 sessions", rows == [["4", "2", "1", "9"]], rows)

    h, rows = table(out, "Q4")
    modes = {r[0]: int(r[1]) for r in rows}
    check("Q4 sessions by mode since the start, EVERY learner (owner and non-testers included)", modes == {"daily": 7, "conversation": 3, "interview": 1}, modes)

    h, rows = table(out, "Q5")
    check("Q5 feedback since the start only, no emails, newlines flattened, 160 characters", len(rows) == 2 and rows[0][:2] == ["10-12", "feedback"] and "\n" not in rows[0][2]
          and len(rows[1][2]) == 160 and "@" not in out.split("-- Q5")[1], rows)

    rc, out2, err2 = run_report(["--start", "2026-10-10", "--only", "q4"], testers)
    check("--only q4 prints just that block", rc == 0 and "-- Q4" in out2 and "-- Q1" not in out2, out2[:150])
    rc, out3, err3 = run_report(["--start", "2026-10-10"], "")
    check("no tester emails = a clear error, not a crash", rc != 0 and "TESTERS" in err3, err3[-200:])
    rc, out4, err4 = run_report(["--start", "not-a-date"], testers)
    check("a bad --start = a clear error", rc != 0 and "--start" in err4, err4[-200:])
    after = await counts()
    check("READ-ONLY: not one document was added, changed in count or removed", before == after, (before, after))
    print(f"\n{N - len(FAILS)} / {N} checks passed")
    await store.close()
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
