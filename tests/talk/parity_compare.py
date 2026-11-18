"""Talk - "old = old", the comparing half (pure; run after parity.sh).  Reads tests/talk/.out/parity_{old,new_off,new_on}.json written by parity_ws.py and proves:

  * for EVERY pre-existing mode (and the quiet reconnects, an unknown mode, an end with no turns): the frames the client received, every model call with its full input, and the database
    effects are IDENTICAL on the old code, on the new code with the Talk switch OFF and with it ON;
  * /me and Know About differ ONLY by the additive `talk_v3` flag (and, with the switch on, the Talk tile / card);
  * `mode: "talk"` with the switch OFF is a refusal (the old code silently turned it into an interview - that is the one deliberate difference, and the proof that it is a difference);
  * the pure registries (Home registry, language registry, every old prompt) are identical to the old code.
Run:  python3 tests/talk/parity_compare.py"""
import importlib.util
import itertools
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tests", "talk"))
from _h import check, section, main                      # noqa: E402

OUT = os.path.join(ROOT, "tests", "talk", ".out")
OLD_BACKEND = os.environ.get("TALK_BASELINE", os.path.join(ROOT, "tests", ".baselines", "lab-done", "backend"))


def load(label):
    with open(os.path.join(OUT, f"parity_{label}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def first_diff(a, b, path=""):
    if type(a) != type(b):
        return f"{path}: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{path}/{k}: only in the second"
            if k not in b:
                return f"{path}/{k}: only in the first"
            d = first_diff(a[k], b[k], f"{path}/{k}")
            if d:
                return d
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return ""
    return "" if a == b else f"{path}: {str(a)[:120]!r} vs {str(b)[:120]!r}"


try:
    OLD, OFF, ON = load("old"), load("new_off"), load("new_on")
except FileNotFoundError as e:
    print("run tests/talk/parity.sh first:", e)
    sys.exit(2)

COMPARED = [n for n in OLD["scenarios"] if n != "talk_start"]
section(f"every pre-existing scenario: old = new (switch off) = new (switch on)  [{len(COMPARED)} scenarios]")
check("the old run recorded the scenarios", len(COMPARED) == 11 and all(OLD["scenarios"][n]["frames"] for n in COMPARED if n != "end_without_turns" or True), COMPARED)
def home_catalog_only(a, c):
    """The ONE legitimate difference with the switch ON: the Home companion's feature catalogue (inside its system prompt) lists Talk. Everything else of every call is equal, and the only
    lines the ON prompt has that the old one lacks are about Talk; no line of the old prompt is lost."""
    if len(a) != len(c):
        return False
    changed = 0
    for x, y in zip(a, c):
        if {k: v for k, v in x.items() if k != "system"} != {k: v for k, v in y.items() if k != "system"}:
            return False
        lo, ln = x["system"].splitlines(), y["system"].splitlines()
        added = [ln_ for ln_ in ln if ln_ not in lo]
        if not set(lo) <= set(ln) or not all("talk" in ln_.lower() for ln_ in added):
            return False
        changed += bool(added)
    return changed >= 1                       # at least one call (the catalogue-carrying system prompt) really carries the Talk line


for n in COMPARED:
    for part in ("frames", "model_calls", "effects"):
        a, b, c = OLD["scenarios"][n][part], OFF["scenarios"][n][part], ON["scenarios"][n][part]
        if (n, part) == ("home", "model_calls"):
            check(f"{n}: {part} identical old / switch OFF  [{len(a)}]", a == b, first_diff(a, b))
            check(f"{n}: {part} with the switch ON differ ONLY by the Talk lines of the feature catalogue  [{len(a)}]", home_catalog_only(a, c), first_diff(a, c))
            continue
        check(f"{n}: {part} identical (old / off / on)  [{len(a) if hasattr(a, '__len__') else ''}]", a == b == c, first_diff(a, b) or first_diff(a, c))
check("the scenarios really exercised the model (a parity of empty runs would prove nothing)", sum(len(OLD["scenarios"][n]["model_calls"]) for n in COMPARED) >= 25, sum(len(OLD["scenarios"][n]["model_calls"]) for n in COMPARED))
check("...and the frames (a conversation, an interview report, a daily turn, a translation, a home turn, a practice report are all there)", all(any(f.get("type") == t for f in OLD["scenarios"][n]["frames"]) for n, t in
      (("conversation", "ai_text"), ("interview", "report"), ("daily", "daily_turn"), ("learning", "translation"), ("home", "home_turn"), ("conversation_reconnect", "session_resumed"), ("daily_reconnect", "daily_resumed"))),
      [(n, [f.get("type") for f in OLD["scenarios"][n]["frames"]]) for n in COMPARED][:12])
check("...and the rewards (XP and conversation rows were written in the old run)", OLD["scenarios"]["conversation"]["effects"]["conversations"] >= 1 and OLD["scenarios"]["conversation"]["effects"]["session_scores"] >= 1, OLD["scenarios"]["conversation"]["effects"])

section("/me and Know About: only the additive talk_v3 flag differs")
def scrub(me):                     # the account is created at the moment of each run
    me = json.loads(json.dumps(me))
    if isinstance(me.get("user"), dict):
        for k in ("created_at", "last_seen"):
            me["user"].pop(k, None)
    return me


me_o, me_f, me_n = scrub(OLD["me"]), scrub(OFF["me"]), scrub(ON["me"])
check("/me answered 200 in all three runs", OLD["me_status"] == OFF["me_status"] == ON["me_status"] == 200)
check("the old /me has no talk_v3; the new one has it, False while the switch is off", "talk_v3" not in me_o and me_f.get("talk_v3") is False and me_n.get("talk_v3") is True)
strip = lambda d, *ks: {k: v for k, v in d.items() if k not in ks}                        # noqa: E731
check("switch OFF: /me equals the old /me except for talk_v3", strip(me_f, "talk_v3") == me_o, first_diff(strip(me_f, "talk_v3"), me_o))
check("switch ON: /me equals the OFF one except for talk_v3 and the Talk tile", strip(me_n, "talk_v3", "home_tiles") == strip(me_f, "talk_v3", "home_tiles"), first_diff(strip(me_n, "talk_v3", "home_tiles"), strip(me_f, "talk_v3", "home_tiles")))
check("switch OFF: the Home tiles are exactly the old ones (no Talk tile)", me_f.get("home_tiles") == me_o.get("home_tiles") and not any(t["id"] == "talk" for t in me_f.get("home_tiles", [])))
check("switch ON: the tiles are the old ones plus exactly one (talk, route /talk)", [t for t in me_n["home_tiles"] if t["id"] != "talk"] == me_o["home_tiles"] and [t["route"] for t in me_n["home_tiles"] if t["id"] == "talk"] == ["/talk"])
check("switch OFF: Know About is identical to the old page", OFF["home_features"] == OLD["home_features"], first_diff(OFF["home_features"], OLD["home_features"]))
check("switch ON: Know About has the old cards plus Talk", [f for f in ON["home_features"]["features"] if f["id"] != "talk"] == OLD["home_features"]["features"] and any(f["id"] == "talk" for f in ON["home_features"]["features"]))

section("`mode: talk`: the old code silently made an interview of it; with the switch off the new code refuses")
t_old, t_off, t_on = (X["scenarios"]["talk_start"] for X in (OLD, OFF, ON))
check("OLD (the bug being closed): an unknown mode became an interview - a model-written opener and a saved chat", any(f.get("type") == "ai_text" for f in t_old["frames"]) and t_old["model_calls"], [f.get("type") for f in t_old["frames"]])
check("NEW, switch OFF: ONE `error` frame, no model call, nothing saved", [f.get("type") for f in t_off["frames"]] == ["error"] and t_off["model_calls"] == [] and t_off["effects"]["conversations"] == 0 and t_off["effects"]["session_scores"] == 0, t_off["frames"])
check("NEW, switch ON: the bank's opener (a topic block in the frame), no model call for it", t_on["frames"] and t_on["frames"][0].get("type") == "ai_text" and "topic" in t_on["frames"][0] and t_on["frames"][0]["lang"] == "en", t_on["frames"][:1])

section("the pure registries equal the old code")


def load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


sys.path.insert(0, os.path.join(ROOT, "backend"))
old_hc = load_by_path("home_content_old", os.path.join(OLD_BACKEND, "app", "home_content.py"))
from app import home_content as new_hc                    # noqa: E402
names = ("practice_room", "bilingual", "planner", "resume_interview", "grammar_coach", "grammar_lab")
combos = [dict(zip(names, v)) for v in itertools.product((False, True), repeat=len(names))]
check("every old registry entry is unchanged (same order, byte for byte); Talk is the only new one", [x for x in new_hc.FEATURES if x["id"] != "talk"] == old_hc.FEATURES and sum(1 for x in new_hc.FEATURES if x["id"] == "talk") == 1)
ok = True
for fl in combos:
    for extra in ({}, {"talk_v3": False}):
        f2 = {**fl, **extra}
        same = (new_hc.tiles(f2) == old_hc.tiles(fl) and new_hc.valid_ids(f2) == old_hc.valid_ids(fl) and new_hc.catalog(f2) == old_hc.catalog(fl)
                and [x["id"] for x in new_hc.upcoming(f2)] == [x["id"] for x in old_hc.upcoming(fl)] and all(new_hc.page(f2, lg) == old_hc.page(fl, lg) for lg in ("en", "hi")))
        ok = ok and same
check(f"tiles / valid_ids / catalog / upcoming / page (en + hi) identical with the switch off, for all {len(combos)} flag combinations", ok)
check("with the switch ON the tile list is the old one plus Talk and nothing else changes", all([t for t in new_hc.tiles({**fl, "talk_v3": True}) if t["id"] != "talk"] == old_hc.tiles(fl) for fl in combos))
check("detect_intent is identical for 12 sample sentences", all(new_hc.detect_intent(t) == old_hc.detect_intent(t) for t in ("what time is it", "my progress", "plan for today", "viva", "practice speaking", "talk about my day", "hello", "मेरा progress", "talk", "let us talk", "daily talk", "face to face")))
old_lang = load_by_path("lang_old", os.path.join(OLD_BACKEND, "app", "lang.py"))
from app import lang as new_lang                          # noqa: E402
check("lang.SWITCHABLE is unchanged (Talk is deliberately NOT switchable)", new_lang.SWITCHABLE == old_lang.SWITCHABLE == ("home",))
check("lang.LEGACY: every old mode is unchanged; Talk is one added entry, English", {k: v for k, v in new_lang.LEGACY.items() if k != "talk"} == old_lang.LEGACY and new_lang.LEGACY["talk"] == "en")
check("session_lang() is identical for every old mode, every requested language and both switch states", all(new_lang.session_lang(m, r, s) == old_lang.session_lang(m, r, s)
      for m in ("conversation", "interview", "daily", "learning", "home", "practice", "notamode") for r in ("hi", "en", None, "x", 5) for s in (True, False)))
check("talk is never switchable, whatever the client asks", all(new_lang.session_lang("talk", r, s) == "en" for r in ("hi", "en", None, "x") for s in (True, False)))
check("lang.LINES / SEED / MIN_TURN_CHARS are unchanged", new_lang.LINES == old_lang.LINES and new_lang.SEED == old_lang.SEED and new_lang.MIN_TURN_CHARS == old_lang.MIN_TURN_CHARS)

old_pr = load_by_path("prompts_old", os.path.join(OLD_BACKEND, "app", "interview", "prompts.py"))
from app.interview import prompts as new_pr               # noqa: E402
consts = [k for k, v in vars(old_pr).items() if isinstance(v, (str, list, tuple, dict)) and not k.startswith("__")]
bad = [k for k in consts if getattr(new_pr, k, None) != getattr(old_pr, k)]
check(f"every prompt constant of the old module is byte-identical in the new one ({len(consts)} checked)", not bad and len(consts) > 20, bad)
args = [("interviewer_system", ("Ann", "Data Analyst", "facts", "good"), {"level": "B1", "career_goal": "x", "past_interview_count": 2, "past_interview_avg": 61.5, "lang": "en"}),
        ("interviewer_system", ("Ann", "Data Analyst", "facts", "good"), {"level": "A1", "lang": "hi"}),
        ("conversation_system", ("Ann", "facts", "tired"), {"lang": "en"}), ("conversation_system", ("Ann", "facts", "tired"), {"lang": "hi"}),
        ("scorer_system", ("en",), {}), ("scorer_system", ("hi",), {}),
        ("home_system", ("Ann", "hi", "morning", 9, "memory", True, False, "CATALOG", ("a", "b"), "good"), {"now_text": "Mon", "planner_on": True}),
        ("home_system", ("Ann", "en", "night", 23, "", False, True, "CATALOG", ("a", "b")), {})]
same_calls = [(fn, getattr(new_pr, fn)(*a, **kw) == getattr(old_pr, fn)(*a, **kw)) for fn, a, kw in args]
check("interviewer / conversation / scorer / home prompt BUILDERS give identical text for 8 argument sets", all(ok_ for _, ok_ in same_calls), [fn for fn, ok_ in same_calls if not ok_])
check("the only new prompt symbols are Talk's (talk_system and its helpers)", sorted(set(n for n in vars(new_pr) if not n.startswith("__")) - set(n for n in vars(old_pr) if not n.startswith("__"))) == ["_TALK_BAND", "_TALK_STYLE", "talk_system"], sorted(set(vars(new_pr)) - set(vars(old_pr))))

main("parity_compare")
