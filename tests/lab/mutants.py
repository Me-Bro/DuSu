"""Grammar Lab - planted bugs.  Each mutant puts ONE deliberate bug into a COPY of the backend and runs the tests; a mutant nobody notices is a hole in the tests.
Usage:  python3 tests/lab/mutants.py [pure|server|all] [M1 M5 ...]      (run from the repo root; the server tier needs docker + the scratch MongoDB of run.sh)
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORK = os.path.join(ROOT, "tests", "lab", ".mut")
PURE = ["unit_forms.py", "unit_checker.py", "unit_explain.py", "unit_bank.py"]

# id, tier, file (under backend/app/lab/ unless it starts with app/), description, old, new
M = [
    ("M1", "pure", "checker.py", "a wrong verb form is no longer evidence of a mistake", 'WRONG_PREFIX = ("tense:", "be:", "have:", "do:", "will:", "aux:", "extra_aux:", "missing_aux:", "overreg:", "vf:")', 'WRONG_PREFIX = ("tense:", "be:", "have:", "do:", "will:", "aux:", "extra_aux:", "missing_aux:", "overreg:")'),
    ("M2", "pure", "checker.py", "a different tense is no longer evidence of a mistake", 'WRONG_PREFIX = ("tense:", ', 'WRONG_PREFIX = ('),
    ("M3", "pure", "checker.py", "any answer with the same word count is accepted", "        if S == A or is_artifact_only(S, A):", "        if S == A or is_artifact_only(S, A) or len(S) == len(A):"),
    ("M4", "pure", "forms.py", "will / shall are not read as the future", "        if t in FUT:\n            w = _after(ts, i)", "        if t in ('zzz',):\n            w = _after(ts, i)"),
    ("M5", "pure", "forms.py", "has / have + V3 is not read as a perfect", '                if _perf_at(ts, j):\n                    return {"present_perfect"}', '                if False:\n                    return {"present_perfect"}'),
    ("M6", "pure", "checker.py", "the verb form the word in front asks for is ignored", '    return want if want and want in kt else ""', '    return ""'),
    ("M7", "pure", "forms.py", "'going to' is not read as 'will'", "def _going_to(ts: list[str]) -> list[str]:\n    \"\"\"`am/is/are going to <verb>` -> `will <verb>` (a valid way to say the future; a motion `going to the market` is left alone).\"\"\"\n    out: list[str] = []", "def _going_to(ts: list[str]) -> list[str]:\n    return ts\n    out: list[str] = []"),
    ("M8", "pure", "bank/__init__.py", "a time phrase after since / by is moved like any other", "                if head.split()[-1].lower() in _GOVERNS:", "                if False:"),
    ("M9", "pure", "checker.py", "the nearest accepted answer is chosen by token count only (not by the learner's own words)", "    _, _, _, best_a, best, edits = min(scored, key=lambda c: c[:3])", "    _, _, _, best_a, best, edits = min(scored, key=lambda c: (c[2], c[1]))"),
    ("M10", "pure", "checker.py", "a 'had never gone' vs 'been' is read as a missing helping verb again", '                elif A[j] == "been" and "v3" in F.kinds(S[i]) and not', '                elif False and A[j] == "been" and "v3" in F.kinds(S[i]) and not'),
    ("M11", "pure", "forms.py", "did + have reads have as the perfect helping verb", ' and not any(x in DO for x in ts[:i]):       # `did / does / do ... have` = have is the main verb', ':       # `did / does / do ... have` = have is the main verb'),
    ("M12", "pure", "forms.py", "a when-clause at the start reads as a question", "    if ts[0] not in _WH:\n        return False\n    i = 1", "    if ts[0] not in _WH:\n        return False\n    return True\n    i = 1"),
    ("M13", "pure", "explain.py", "the 3rd-person rule text is lost", '    "s_third": ("he / she / it (एकवचन) के साथ Present Simple में verb में -s / -es लगता है।", "With he / she / it the Present Simple verb takes -s / -es."),', '    "s_third": ("", ""),'),
    ("M14", "pure", "explain.py", "the Hindi text says आप", '"Question में helping verb subject से पहले आता है।"', '"आप Question में helping verb subject से पहले रखें।"'),
    ("M15", "pure", "forms.py", "by the time is not a clause boundary", '("by", "the", "time", "that"), ("by", "the", "time"), ', ''),
    ("M16", "server", "service.py", "a repeated request is graded again", "        if cur.get(\"done\"):                                            # a repeated request: the stored outcome, never a second grading", "        if False:                                            # a repeated request"),
    ("M17", "server", "service.py", "a set of someone else can be answered (IDOR)", "        row = (await s.execute(select(GlSet).where(GlSet.id == sid, GlSet.user_id == uid).with_for_update())).scalars().first()\n        if row is None or it.id not in (row.items or []):\n            await s.commit()\n            raise NotFound()\n        results = dict(row.results or {})\n        cur = dict(results.get(it.id) or {\"tries\": 0, \"done\": False})\n        if cur.get(\"done\"):                                            # a repeated", "        row = (await s.execute(select(GlSet).where(GlSet.id == sid).with_for_update())).scalars().first()\n        if row is None or it.id not in (row.items or []):\n            await s.commit()\n            raise NotFound()\n        results = dict(row.results or {})\n        cur = dict(results.get(it.id) or {\"tries\": 0, \"done\": False})\n        if cur.get(\"done\"):                                            # a repeated"),
    ("M18", "server", "service.py", "the 90% star threshold is 91", "STAR_PCT = (60, 80, 90) ", "STAR_PCT = (60, 80, 91) "),
    ("M19", "server", "service.py", "a miss never reaches the review list", '    if v in ("wrong", "shown"):\n        await s.execute(pg_insert(GlReview)', '    if False:\n        await s.execute(pg_insert(GlReview)'),
    ("M20", "server", "service.py", "the best result is overwritten by a worse one", "        if graded and (stars, pct) > (int(prog.stars or 0), int(prog.best_pct or 0)):", "        if graded:"),
    ("M21", "server", "service.py", "two taps on start make two sets", '        await s.advisory_lock("gl:" + uid) ', '        pass '),
    ("M22", "server", "service.py", "delete_rows forgets the review table", "for M in GL_TABLES:\n        await s.execute(delete(M).where(M.user_id.in_(uids)))", "for M in GL_TABLES[1:]:\n        await s.execute(delete(M).where(M.user_id.in_(uids)))"),
    ("M23", "server", "service.py", "an unsure answer counts as a miss", '    if v in ("wrong", "shown"):\n        await s.execute(pg_insert(GlReview)', '    if v in ("wrong", "shown", "unsure"):\n        await s.execute(pg_insert(GlReview)'),
    ("M24", "server", "service.py", "four tries instead of three", "MAX_TRIES = 3 ", "MAX_TRIES = 4 "),
    ("M25", "server", "service.py", "the set payload carries the English answers", '"items": [{"id": i, "hi": its[i].hi, "done"', '"items": [{"id": i, "hi": its[i].hi, "en": list(its[i].en), "done"'),
    ("M26", "server", "service.py", "the answer is shown on the first wrong answer", '        if cur.get("done"):\n            out["target"] = r.get("target") if verdict == "ok" else it.en[0]', '        if True:\n            out["target"] = r.get("target") if verdict == "ok" else it.en[0]'),
    ("M27", "server", "api.py", "a blocked account can use the Lab", '            if (await db.get_user_flags(uid)).get("status") == "blocked":', '            if False:'),
    ("M28", "server", "api.py", "no rate limit on checking", "    if len(q) >= CHECKS_PER_MIN:", "    if False:"),
    ("M29", "server", "service.py", "the learner's typed answer is stored in the set", '        cur["tries"] = int(cur["tries"]) + 1\n        if verdict == "ok":', '        cur["tries"] = int(cur["tries"]) + 1\n        cur["said"] = said\n        if verdict == "ok":'),
    ("M30", "server", "service.py", "after the last unit the path wraps to the first unit",
     '    if ui + 1 >= len(catalog.UNITS):                                   # the last level of the last unit: nothing comes after it (never wrap to the first unit)\n        return {"unit": unit, "level": level, "reason": "path_end"}\n    return {"unit": catalog.UNITS[ui + 1], "level": "easy", "reason": "next_unit"}',
     '    return {"unit": catalog.UNITS[(ui + 1) % len(catalog.UNITS)], "level": "easy", "reason": "next_unit"}'),
]


def run(cmd, cwd, env=None, timeout=900):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def main():
    tier = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("pure", "server", "all") else "all"
    want = [a for a in sys.argv[1:] if a.startswith("M")]
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    caught, survived = 0, []
    for mid, mtier, fname, desc, old, new in M:
        if (tier != "all" and mtier != tier) or (want and mid not in want):
            continue
        d = os.path.join(WORK, mid)
        shutil.copytree(os.path.join(ROOT, "backend"), os.path.join(d, "backend"), ignore=shutil.ignore_patterns(".venv", "__pycache__", ".env*", "*.pyc", "users.db"))
        path = os.path.join(d, "backend", "app", "lab", fname) if not fname.startswith("app/") else os.path.join(d, "backend", fname)
        src = open(path).read()
        if src.count(old) != 1:
            print(f"{mid:4} NOT APPLIED ({src.count(old)} matches)  {desc}")
            survived.append(mid + "(not applied)")
            continue
        open(path, "w").write(src.replace(old, new))
        how = ""
        if mtier == "pure":
            os.makedirs(os.path.join(d, "tests", "lab"))
            for f in os.listdir(os.path.join(ROOT, "tests", "lab")):
                if f.endswith(".py"):
                    shutil.copy(os.path.join(ROOT, "tests", "lab", f), os.path.join(d, "tests", "lab", f))
            for t in PURE:
                rc, out = run([sys.executable, f"tests/lab/{t}"], d, timeout=300)
                if rc != 0:
                    how = f"{t}: " + (next((l for l in out.splitlines() if "FAIL" in l), "failed")).strip()[:90]
                    break
        else:
            rc, out = run(["tests/lab/run.sh"], ROOT, {"LAB_BACKEND_DIR": os.path.join(d, "backend")}, timeout=900)
            if rc != 0:
                how = "selftest: " + (next((l for l in out.splitlines() if "FAIL" in l or "Traceback" in l), "failed")).strip()[:90]
        if how:
            caught += 1
            print(f"{mid:4} caught     ({desc})  -> {how}")
        else:
            survived.append(mid)
            print(f"{mid:4} SURVIVED   ({desc})  <- no test noticed")
        shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"\nmutants: {caught} caught, {len(survived)} survived: {' '.join(survived) or 'none'}")
    print("finished")
    sys.exit(1 if survived else 0)


main()
