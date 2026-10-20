"""Grammar Coach - tier 1: every pure unit file in one go. Run: `PYTHONPATH=backend python3 tests/grammar/unit.py` (or in the test image with /app on the path).
Each unit_*.py is a self-contained script that exits non-zero on any failure; this runner executes them all and sums the result."""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ)
env.setdefault("PYTHONPATH", os.path.join(HERE, "..", "..", "backend"))
rc = 0
for f in sorted(glob.glob(os.path.join(HERE, "unit_*.py"))):
    p = subprocess.run([sys.executable, f], env=env, capture_output=True, text=True)
    last = [ln for ln in p.stdout.strip().splitlines() if ln.strip()][-1:] or ["(no output)"]
    print(f"{os.path.basename(f):26s} {'OK  ' if p.returncode == 0 else 'FAIL'} {last[0]}")
    if p.returncode:
        rc = 1
        print(p.stdout[-1500:], p.stderr[-800:])
sys.exit(rc)
