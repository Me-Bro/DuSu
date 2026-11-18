# Grammar Lab tests

The Lab makes **no model call**: a Hindi sentence is shown, the learner's English answer is checked by pure code (`backend/app/lab/checker.py`) and explained from fixed templates. So every tier here is
deterministic and needs no key. Nothing here touches the app's own database: the server tiers run on a scratch MongoDB (`tests/lib/scratch_mongo.sh`, an `--internal` network).

| tier | command (repo root) | what it proves |
|---|---|---|
| pure: tense forms | `python3 tests/lab/unit_forms.py` | the classifier reads the twelve forms (aff / neg / question, irregular verbs, contractions, two-clause sentences, `by the time`, `going to`), says nothing when it cannot tell, and treats learner slips (`has went`) as what they are |
| pure: checker | `python3 tests/lab/unit_checker.py` | ok / wrong (with the exact reason) / unsure for ~80 hand-made answers; a wrong answer is never `ok`, a different-words answer is never `wrong`; `variants()` |
| pure: explanations | `python3 tests/lab/unit_explain.py` | every error code has a Hindi and an English text; every Hindi string follows the writing rules (तुम not आप, no gendered 2nd-person verbs, Devanagari + Latin terms) |
| pure: the bank | `python3 tests/lab/unit_bank.py` | for all 576 items: every accepted answer is accepted, and **no wrong version of it is ever accepted** (6,000+ generated wrong versions: a helping verb dropped or swapped, every other verb form) |
| lint | `python3 tests/lab/lint_bank.py [unit ...]` | the bank's rules (ids, counts per level, Hindi script / gender / `तू`, English reads as its unit, no duplicates, distribution per level) - `AUTHORING.md` is the guide for writing a unit |
| server | `tests/lab/run.sh` | the real HTTP layer on a scratch MongoDB: gates and switch, a set, 3 tries and what each reveals, repeat = never graded twice, stars, best never lowered, review, **no learner text stored**, 12 simultaneous answers = one graded, two taps on start = one set, rate limit, daily cap, IDOR (404), old -> new schema rehearsal, export / delete / account deletion / owner wipe, 90-day prune |
| planted bugs | `python3 tests/lab/mutants.py [pure\|server\|all]` | each of 30 deliberate bugs, one at a time in a copy of the backend, must be caught by some test |
| browser | `tests/lab/browser/run_real.sh` | a real Chromium against the real app (hub, unit, drill with a fake speech recogniser, results, summary, review, Hindi / English, layout at 360 / 390 / 1280) |

`LAB_BACKEND_DIR=baked LAB_TEST_IMAGE=dusu-backend:<tag> tests/lab/run.sh` runs the server tier against the code BAKED INTO a built image.

## Things learned (kept as pins)
* Several accepted answers with different synonyms (`living` / `staying`): diff the learner's answer against the one that shares THEIR words (fewest different words, then fewest edits), not the one nearest by token count.
* `did / does / do ... have`: `have` is the main verb, not a perfect helping verb. `have / had + had`: the second `had` is the participle.
* `\b` does not work on Devanagari (a vowel sign is not a word character): use look-arounds.
* `by the time`, `as soon as`, `the moment` are clause boundaries (the second clause is a present tense after a future main clause).
* A generated "wrong version" can be correct English (`travelling` / `traveling`, `got` / `gotten`): `_mut.py` skips those pairs.
* Writing the concurrency test found a real bug: two quick taps on "start" made two open sets (no row to lock yet) - `make_set` now takes an advisory lock per learner.
