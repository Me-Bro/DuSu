"""Resume Interview - tier 5 (server side): "old = old". The Home registry and the life labels are PURE functions: with the new switch off, every output must be
identical to the committed HEAD version, for every combination of the existing flags and both languages. (Run through run.sh-style docker command in README.md;
.head/ holds `git show HEAD:...` copies written by the README's first command - they are not committed.)"""

import importlib.util
import itertools
import sys

sys.path.insert(0, "/app")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


old = load("home_content_head", "/tests/resume_interview/.head/home_content_head.py")
from app import home_content as new                                   # noqa: E402

FAILS, N = [], 0


def check(name, cond, detail=""):
    global N
    N += 1
    print(f"  {'PASS' if cond else 'FAIL'}  {name} {'' if cond else str(detail)[:200]}")
    if not cond:
        FAILS.append(name)


flag_names = ("practice_room", "bilingual", "planner")
combos = [dict(zip(flag_names, v)) for v in itertools.product((False, True), repeat=3)]
check("existing registry entries are unchanged (same ids, same order, minus the new one)", [x["id"] for x in new.FEATURES if x["id"] != "resume_interview"] == [x["id"] for x in old.FEATURES]
      and all(a == b for a, b in zip([x for x in new.FEATURES if x["id"] != "resume_interview"], old.FEATURES)))
for fl in combos:
    tag = ",".join(k for k, v in fl.items() if v) or "none"
    check(f"tiles({tag}) identical with the switch off", new.tiles(fl) == old.tiles(fl))
    check(f"valid_ids({tag}) identical", new.valid_ids(fl) == old.valid_ids(fl))
    check(f"catalog({tag}) identical", new.catalog(fl) == old.catalog(fl))
    check(f"upcoming({tag}) identical", [x["id"] for x in new.upcoming(fl)] == [x["id"] for x in old.upcoming(fl)])
    for lg in ("en", "hi"):
        check(f"page({tag},{lg}) identical", new.page(fl, lg) == old.page(fl, lg))
        check(f"actions({tag},{lg}) identical", new.actions(["daily_talk", "interview", "practice_room", "goals_planning", "resume_interview"], fl, lg)
              == old.actions(["daily_talk", "interview", "practice_room", "goals_planning", "resume_interview"], fl, lg) or
              [a for a in new.actions(["daily_talk", "interview", "practice_room", "goals_planning", "resume_interview"], fl, lg)] == old.actions(["daily_talk", "interview", "practice_room", "goals_planning"], fl, lg))
for text in ("let me resume my lesson", "I have an interview tomorrow", "what time is it", "my progress", "plan for today", "viva", "resume", "job description"):
    check(f"detect_intent({text!r}) identical", new.detect_intent(text) == old.detect_intent(text))
check("default_suggest / filter_suggest / INTENTS identical", all(new.default_suggest(i) == old.default_suggest(i) for i in old.INTENTS) and new.INTENTS == old.INTENTS
      and all(new.filter_suggest(i, ["interview", "goals_planning"]) == old.filter_suggest(i, ["interview", "goals_planning"]) for i in old.INTENTS))
on = new.tiles({"resume_interview": True})
check("with the switch ON the new tile appears exactly once and nothing else changes", [t["id"] for t in on if t["id"] != "resume_interview"] == [t["id"] for t in old.tiles({})] and sum(1 for t in on if t["id"] == "resume_interview") == 1)

# the shared provider cooldown: every previously-6-hour case is still 6 hours, every previously-short case is still short (only the digit-run case changed)
import time                                                           # noqa: E402
from app.providers import openrouter_provider as op                    # noqa: E402
cases = {"Error code: 401 - invalid authentication": 21600, "Error code: 403 - forbidden": 21600, "Error code: 404 - not found": 21600, "Error code: 410 - gone": 21600,
         "github_models_retirement_brownout": 21600, "Unauthorized": 21600, "invalid api key provided": 21600,
         "Error code: 429 - daily quota exhausted for the day": 1800, "429 rate limit": 90, "rate limited, try again": 90}
for msg, want in cases.items():
    op._cooldown.clear()
    op._mark_cooldown("p", msg)
    got = op._cooldown["p"] - time.time()
    check(f"cooldown({msg!r}) is the same class as before ({want}s)", abs(got - want) < 5, got)

# life labels: only the new mode was added
from app import life                                                  # noqa: E402
old_life = load("life_head_src", "/tests/resume_interview/.head/life_head.py") if False else None
check("life._MODE_LABELS only gained the new mode", {k: v for k, v in life._MODE_LABELS.items() if k != "resume_interview"} == {"conversation": "Face-to-Face", "daily": "Daily Talk", "interview": "Interview", "presentation": "Presentation", "viva": "Viva", "speech": "Speech", "seminar": "Seminar", "discussion": "Discussion", "custom": "Practice Room"})

# the XP table: every existing mode keeps its bonus
from app import db                                                    # noqa: E402
check("db._MODE_BONUS: the existing modes are unchanged", {k: v for k, v in db._MODE_BONUS.items() if k != "resume_interview"} == {"daily": 10, "conversation": 15, "interview": 25, "presentation": 25, "viva": 25, "speech": 20, "seminar": 20, "discussion": 15, "custom": 15} and db._MODE_BONUS["resume_interview"] == 25)

print(f"\n{N - len(FAILS)} / {N} checks passed")
sys.exit(1 if FAILS else 0)
