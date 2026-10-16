# Grammar Coach - tests

Everything here runs on scratch infrastructure: the unit tier is pure Python, the rest uses a throwaway Postgres container, stub models and blank provider keys. **Never** point any of it at `dusu-db-1`.

| Tier | Run | What it proves |
|---|---|---|
| 1 unit | `PYTHONPATH=backend python3 tests/grammar/unit.py` | segmenter, gates, verifier, scoring / rule states / deltas, the 41-rule catalogue, the 19 rule checks (`unit_detectors.py`), the gold set's shape + the real-model runner's metrics (`unit_gold.py`) |
| 1b rule checks vs gold | `PYTHONPATH=backend python3 tests/grammar/solo_gold.py` | offline (no model): the solo rule checks' false positives on the clean gold sentences (must be none) and recall per rule |
| 2 scratch Postgres | `tests/grammar/run.sh selftest.py` | the real HTTP layer + the detached analysis with a stub model: privacy choice, claim pattern, IDOR matrix, caps, all delete cascades (account, wipe, Practice attempt, pruned attempt, interview), `/analyze` for Practice and Job Interview Practice |
| 3 WebSocket | `tests/grammar/run.sh ws_harness.py` | the real `/ws/interview` with the switch OFF vs ON: every non-grammar model call, frame and DB write identical; a dropped socket still analysed; Interview / Practice / Hindi paths |
| 4 browser, real app | `tests/grammar/browser/run_real.sh` | real Chromium -> real server -> scratch DB: Face-to-Face with a fake recogniser, report, keep / counts choice, sheet, contest, drills, settings, Hindi shows nothing, looks at 360 / 390 / 1280 |
| 5 old = old (client) | `ORIG_HTML_HOST=$PWD/tests/grammar/.orig.html tests/grammar/browser/run.sh oldnew.spec.cjs` | with the switch OFF the pre-feature page (`git show HEAD:backend/test_client.html > tests/grammar/.orig.html`, take the merge-base when you re-baseline) and the new page are identical: text, element order, static DOM, pixels - including session, session result and the interview report |
| 6 planted bugs | `python3 tests/grammar/mutants.py [M01 ...]` | 24 deliberate bugs, one at a time in a COPY of `backend/`; the suite must fail each (all caught). The plan asked for 35+ - add more engine mutants as the engine grows |
| 7 real model (owner-run) | `GC_REAL=1 GC_CHAIN=default python3 tests/grammar/real_model.py` | the gold set through the real provider chain; prints the ship-gate verdict (plan section 15). Uses the owner's real free-tier quota, so it is never run by CI. Chains: `default`, `gemini`, `groq+openrouter`, `gemini+openrouter`; `GC_RUNS` (3), `GC_SLEEP`, `GC_ONLY`, `GC_LIMIT`, `GC_OUT` (ids and statuses only, never text) |

First time for the browser tiers: see `tests/my_day/README.md` (Playwright modules in `~/.cache/dusu-ri-pwrun`) and the test image `dusu-ri-test`.
Docker here only bind-mounts paths under the repo, not `/tmp`. Screenshots land in `~/.cache/dusu-gc-shots`.

Gotchas: learners in tests need an assessed level (`db.save_assessment(... "level": "B1")`) - an unassessed learner is A1 and the A2+ rules are correctly not shown to them; on Chrome text a finding the rule checks do not back is only "likely" and is never applied or counted; routes added to the e2e server after import sit behind the SPA catch-all (move them to the front).
