"""Tiny test harness shared by the Grammar Coach unit files: check(name, cond, detail), section(title), done() -> exit code."""
import sys

FAILS: list[str] = []
N = 0


def section(title: str) -> None:
    print(f"\n== {title}")


def check(name: str, cond, detail="") -> bool:
    global N
    N += 1
    ok = bool(cond)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else '  ' + str(detail)[:300]}")
    if not ok:
        FAILS.append(name)
    return ok


def done(label: str) -> int:
    print(f"\n{label}: {N - len(FAILS)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
    return 1 if FAILS else 0


def main(label: str) -> None:
    sys.exit(done(label))
