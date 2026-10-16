"""Grammar Coach - planted-bug run. One deliberate bug at a time is applied to a COPY of backend/ (never the real tree); the suite must FAIL for each.
  python3 tests/grammar/mutants.py            # all
  python3 tests/grammar/mutants.py M07 M12    # some
Tiers: "unit" = the pure unit files (host python, seconds) - "db" = selftest.py on a scratch Postgres (docker) - "ws" = ws_harness.py (docker).
A mutant that is not CAUGHT is a weak spot in the TESTS; one whose pattern is not found is reported as STALE (the code moved - fix the table)."""
import os
import shutil
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.join(REPO, "tests", "grammar")
G = "app/grammar/"

M = [  # (id, file, old, new, tier, what)
    ("M01", G + "verify.py", "        if not _bounds(rid, qk, fk):", "        if False:", "unit", "edit bounds removed"),
    ("M02", G + "verify.py", "        if is_artifact_only(qk, fk):", "        if False:", "unit", "artifact-only filter off"),
    ("M03", G + "verify.py", "def _guard(rule: str, qk: list[str], fk: list[str]) -> bool:\n", "def _guard(rule: str, qk: list[str], fk: list[str]) -> bool:\n    return True\n", "unit", "rule-class guard accepts anything"),
    ("M04", G + "verify.py", "def _allowed_at(rule: catalog.Rule, level) -> bool:\n", "def _allowed_at(rule: catalog.Rule, level) -> bool:\n    return True\n", "unit", "level eligibility ignored"),
    ("M05", G + "scoring.py", "MIN_CHECKED = 6", "MIN_CHECKED = 0", "unit", "minimum-evidence sentences removed"),
    ("M06", G + "scoring.py", "MIN_WORDS = 40", "MIN_WORDS = 0", "unit", "minimum-evidence words removed"),
    ("M07", G + "scoring.py", "DELTA_MIN_CHECKED = 40", "DELTA_MIN_CHECKED = 1", "unit", "deltas with tiny samples"),
    ("M08", G + "scoring.py", "per100 = round(100.0 * errors / words_checked, 1) if words_checked > 0 else None", "per100 = round(100.0 * errors / words_total, 1) if words_total > 0 else None", "unit", "per-100 over all words, not checked words"),
    ("M09", G + "gating.py", "    if sent.n_words <= 2 or n == 0:", "    if sent.n_words <= 0 or n == 0:", "unit", "too-short gate loosened"),
    ("M10", G + "engine.py", "first=first, cool=False)", "first=first, cool=True)", "db", "a grammar 429 would cool a provider for everyone"),
    ("M11", G + "service.py", 'quote=redact(m["quote"])[:160] if keep else ""', 'quote=redact(m["quote"])[:160] if True else ""', "db", "counts-only still stores the quote"),
    ("M12", G + "service.py", '    if prefs["choice"] == "":\n        _hold(uid, analysis, sid)', '    if False:\n        _hold(uid, analysis, sid)', "db", "the first result is not held for the choice"),
    ("M13", G + "service.py", '    if choice == "keep":\n        hit = _held.pop((uid, sid), None)', '    if False:\n        hit = _held.pop((uid, sid), None)', "db", "keep writes nothing"),
    ("M14", G + "service.py", "r = (await s.execute(select(GcSession).where(GcSession.user_id == uid, GcSession.client_key == key))).scalars().first()\n", "r = (await s.execute(select(GcSession).where(GcSession.client_key == key))).scalars().first()\n", "db", "by_ref ignores the owner (IDOR)"),
    ("M15", G + "service.py", "        if sr is None or sr.user_id != uid:", "        if sr is None:", "db", "a foreign sentence can be contested"),
    ("M16", G + "api.py", "    if need_enabled and not await M.grammar_coach_enabled(email):", "    if False:", "db", "switch off still serves the API"),
    ("M17", "app/db.py", "        await _gc.delete_rows(s, [user_id])", "        pass", "db", "deleting an account leaves Grammar Coach rows"),
    ("M18", "app/db.py", "    await _gc.delete_by_ref(user_id, f\"pa:{int(attempt_id)}\")", "    pass", "db", "deleting a Practice attempt leaves its sentences"),
    ("M24", "app/db.py", "            await _gc.delete_by_ref(user_id, f\"pa:{int(oid)}\")", "            pass", "db", "pruning a Practice attempt leaves its sentences"),
    ("M19", "app/resume_interview/service.py", '    await _gc.delete_by_ref(uid, f"ri:{int(sid)}")', "    pass", "db", "deleting an interview leaves its sentences"),
    ("M20", "app/main.py", '        if _gc_on and session.mode in ("conversation", "interview"):', '        if session.mode in ("conversation", "interview"):', "ws", "switch off still starts an analysis"),
    ("M21", "app/main.py", '                        sp["grammar_ref"] = f"ws:{_gref}"', '                        pass', "ws", "speaker_progress loses grammar_ref"),
    ("M22", "app/main.py", "                    and gc_gating.session_gate(mode, (_practice_cfg or {}).get(\"plang\"), _lang).ok:", "                    and True:", "ws", "Hindi practice sessions analysed"),
    ("M23", "app/main.py", "_gref = gc_tracker.valid_gref(data.get(\"gref\"))", "_gref = str(data.get(\"gref\") or \"\")", "ws", "gref not validated"),
]


def run(cmd, env=None, cwd=REPO, timeout=900):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def one(mid, rel, old, new, tier, what):
    dst = os.path.join(HERE, ".mut", mid, "backend")
    shutil.rmtree(os.path.dirname(dst), ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "backend"), dst, ignore=shutil.ignore_patterns(".venv", ".env*", "__pycache__", "*.apk"))
    p = os.path.join(dst, rel)
    s = open(p, encoding="utf-8").read()
    if s.count(old) < 1:
        return "STALE", "pattern not found"
    open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
    try:
        if tier == "unit":
            env = dict(os.environ, PYTHONPATH=dst)
            r = run([sys.executable, os.path.join(HERE, "unit.py")], env=env)
        else:
            env = dict(os.environ, GC_BACKEND_DIR=dst)
            r = run([os.path.join(HERE, "run.sh"), "selftest.py" if tier == "db" else "ws_harness.py"], env=env)
        out = r.stdout + r.stderr
        caught = r.returncode != 0
        return ("CAUGHT" if caught else "SURVIVED"), (out.strip().splitlines()[-1] if out.strip() else "")
    finally:
        shutil.rmtree(os.path.dirname(dst), ignore_errors=True)


if __name__ == "__main__":
    want = set(sys.argv[1:])
    res = []
    for mid, rel, old, new, tier, what in M:
        if want and mid not in want:
            continue
        st, last = one(mid, rel, old, new, tier, what)
        res.append((mid, st))
        print(f"{mid} {st:9s} [{tier}] {what}   {last[:100] if st != 'CAUGHT' else ''}", flush=True)
    bad = [m for m, s in res if s != "CAUGHT"]
    print(f"\n{len(res) - len(bad)} of {len(res)} planted bugs caught" + (f"; NOT caught: {bad}" if bad else ""))
    sys.exit(1 if bad else 0)
