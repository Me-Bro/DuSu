"""Talk - planted bugs.  Each mutant puts one (or two, for a bug that has two halves) deliberate bug into a COPY of the backend and runs the tier of tests that must notice it; a mutant nobody notices
is a hole in the tests.
Usage:  python3 tests/talk/mutants.py [pure|engine|http|ws|wire|all] [P1 E2 S3 ...]      (repo root; the engine / http / ws tiers need docker + the test image, as tests/talk/run.sh does)

Tiers:  pure   = unit_topics.py + unit_reply.py on the copy (no docker)      engine = unit_engine.py in the container
        http   = selftest.py (HTTP layer, scratch MongoDB)                   ws     = ws_selftest.py (the real WebSocket handler, scratch MongoDB)
        wire   = wire_walk.py (the real provider walk with fake providers)
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORK = os.path.join(ROOT, "tests", "talk", ".mut")
A = "backend/app/"

# id, tier, description, [(file under backend/app/, old, new), ...]   - every `old` must occur exactly once in its file
# (One EQUIVALENT mutant is deliberately not listed: switching off ONLY the "quote is located in the message" check changes nothing, because the corrected-message post-condition
#  - a second, independent layer - drops the same fix. R9 switches both off and is caught, which proves each layer has a test that disables the other.)
M = [
    # ---------------------------------------------------------------------------------------------------------- the bank: validation and selection (pure)
    ("P1", "pure", "the validator lets an आप form through", [("talk/topics.py", "        if _AAP.match(t):", "        if False:")]),
    ("P2", "pure", "the validator lets a verb that guesses gender (करते हो) through", [("talk/topics.py", '        if _GEND_HO_PREV.match(a) and (b == "हो" or', '        if False and (b == "हो" or')]),
    ("P3", "pure", "today's topic ignores the day (the same topic every day)", [("talk/topics.py", "    return copy.deepcopy(order[_date(date_ist if date_ist is not None else ist_today()).toordinal() % len(order)])", "    return copy.deepcopy(order[0])")]),
    ("P4", "pure", "every learner gets the same order of topics", [("talk/topics.py", '    order = _order(str(uid or ""), band, pool)\n    return copy.deepcopy(order[', '    order = _order("", band, pool)\n    return copy.deepcopy(order[')]),
    ("P5", "pure", "an A2 learner is put in the A1 band", [("talk/topics.py", '    if s == "A2":\n        return "A2"', '    if s == "A2":\n        return "A1"')]),
    ("P6", "pure", "get() hands out the live row of the bank (no copy)", [("talk/topics.py", "    return copy.deepcopy(t) if t else None", "    return t")]),
    ("P7", "pure", "the id prefix is no longer checked against the band", [("talk/topics.py", "    elif isinstance(tid, str) and ID_RE.match(tid) and tid.split(\"-\", 1)[0] != band.lower():", "    elif False:")]),
    ("P8", "pure", "a missing band module crashes the loader", [("talk/topics.py", "            if e.name == full:\n                missing.append(name)", "            if e.name == full:\n                raise")]),
    ("P9", "pure", "alternatives may include the excluded topic", [("talk/topics.py", '    cand = [t for t in _order(str(uid or ""), band, pool) if t["id"] not in exc]', '    cand = [t for t in _order(str(uid or ""), band, pool)]')]),
    ("P10", "pure", "the danda hides a gendered verb again (it lies inside the Devanagari block)", [("talk/topics.py", "[\u0900-\u0963\u0966-\u097F]+", "[\u0900-\u097F]+")]),
    ("P11", "pure", "the same opener may appear twice in the bank", [("talk/topics.py", '        if ok_ in openers:\n            errs.append(f"{t[\'id\']}: the same opener as {openers[ok_]}")\n            continue', '        if False:\n            continue')]),
    # ---------------------------------------------------------------------------------------------------------- the reply: cleaning and fix verification (pure)
    ("R1", "pure", "Grammar Coach's artifact filter is bypassed (a capital letter / homophone / numeral 'fix' is shown)", [("grammar/verify.py", "        if is_artifact_only(qk, fk):\n            continue\n        # ---- 5 rule id", "        if False:\n            continue\n        # ---- 5 rule id")]),
    ("R2", "pure", "a free word swap that no rule check backs is shown as a mistake", [("talk/reply.py", '        if m.conf != "sure" and not grammar_edit(m.quote, m.fix):', "        if False:")]),
    ("R3", "pure", "more than the first three proposed fixes are looked at", [("talk/reply.py", "    for c in cands[:3]:", "    for c in cands[:99]:")]),
    ("R4", "pure", "a fix whose corrected message fails the post-conditions is still shown", [("talk/reply.py", "        if not full:\n            continue", "        if not full:\n            full = msg")]),
    ("R5", "pure", "a Devanagari sentence is no longer stripped from DuSu's English reply", [("talk/reply.py", "    if _DEV.search(t):\n        t = ", "    if False:\n        t = ")]),
    ("R6", "pure", "the Hindi writing rules are not applied to the subtitle", [("talk/reply.py", "    if T.hindi_problems(t):\n        return None\n    return t", "    return t")]),
    ("R7", "pure", "the walk's check accepts a Hindi-only reply", [("talk/reply.py", "    if letters < 2 or T.dev_share(r) >= 0.5:", "    if letters < 2:")]),
    ("R8", "pure", "the subtitle is forwarded at support=en", [("talk/reply.py", '    if support == "en_sub":\n        hi = clean_hi(', '    if True:\n        hi = clean_hi(')]),
    ("R9", "pure", "the fix is not located in the learner's message (any quote is accepted) - and the corrected-message post-condition, a second layer, is off too", [("talk/reply.py", "        marks = verify.verify_marks(msg, [{\"q\": q, \"f\": f, \"r\": \"\", \"c\": \"s\", \"w\": \"\"}], level=lvl,", "        marks = verify.verify_marks(msg + ' ' + q, [{\"q\": q, \"f\": f, \"r\": \"\", \"c\": \"s\", \"w\": \"\"}], level=lvl,"),
                                                                                                                                                                                        ("talk/reply.py", "        if not full:\n            continue", "        if not full:\n            full = msg")]),
    ("R10", "pure", "the English prompt still asks for the Hindi subtitle", [("interview/prompts.py", "    shape = ('{\"reply\": \"<English>\", \"hi\": \"<Hindi>\", \"fix\": null}' if sub else", "    shape = ('{\"reply\": \"<English>\", \"hi\": \"<Hindi>\", \"fix\": null}' if True else")]),
    ("R11", "pure", "the prompt's chat window grows (the token budget is blown)", [("talk/reply.py", "HISTORY_LINES, HISTORY_CHARS = 8, 200", "HISTORY_LINES, HISTORY_CHARS = 30, 600")]),
    ("R12", "pure", "the `w` (Hindi reason) of a fix is forwarded without the writing rules", [("talk/reply.py", "    if not t or len(t) > REASON_HI_MAX or not _DEV.search(t) or T.dev_share(t) < T.MIN_DEV_SHARE or T.hindi_problems(t):\n        return \"\"", "    if not t:\n        return \"\"")]),
    # ---------------------------------------------------------------------------------------------------------- the engine (container, no database)
    ("E1", "engine", "every turn makes two model calls", [("interview/engine.py", "            if shaped:\n                break\n        if not shaped:", "            if False:\n                break\n        if not shaped:")]),
    ("E2", "engine", "Hindi enters the transcript (the subtitle is appended to DuSu's line)", [("interview/engine.py", '        self.transcript.append({"role": "assistant", "content": shaped["text"]})\n        return shaped', '        self.transcript.append({"role": "assistant", "content": shaped["text"] + " " + shaped.get("hi", "")})\n        return shaped')]),
    ("E3", "engine", "the opener makes a model call", [("interview/engine.py", '            op = topic["opener"]\n            out = {"text": op["en"]}', '            await llm.assess(self.system, "x", schema=TR.SCHEMA)\n            op = topic["opener"]\n            out = {"text": op["en"]}')]),
    ("E4", "engine", "a failed turn leaves the learner's line in the transcript", [("interview/engine.py", '        if not shaped:\n            _log_turn("talk")', '        if not shaped:\n            self.transcript.append({"role": "user", "content": ans})\n            self.turns += 1\n            _log_turn("talk")')]),
    ("E5", "engine", "the opener carries a Hindi subtitle at every support level", [("interview/engine.py", '            if support == "en_sub":\n                out["hi"] = op["hi"]', '            if True:\n                out["hi"] = op["hi"]')]),
    ("E6", "engine", "the validated walk gets no schema (a reply without `reply` would pass)", [("interview/engine.py", "temperature=0.6, schema=TR.SCHEMA, check=TR.check)", "temperature=0.6, check=TR.check)")]),
    ("E7", "engine", "the output budget goes over 500 tokens", [("talk/reply.py", 'MAX_TOKENS = {"en_sub": 480, "en": 320}', 'MAX_TOKENS = {"en_sub": 900, "en": 320}')]),
    ("E8", "engine", "Talk's session language is Hindi", [("lang.py", '          "talk": "en"}', '          "talk": "hi"}')]),
    ("E9", "engine", "Talk joins the switchable modes (it would obey the global Hindi / English choice)", [("lang.py", 'SWITCHABLE = ("home",)', 'SWITCHABLE = ("home", "talk")')]),
    ("E10", "engine", "an unverified fix is attached to the reply", [("talk/reply.py", '    fix = verify_fix(message, data.get("fix"), level=level, support=support, source=source)\n    if fix:', '    fix = data.get("fix") if isinstance(data.get("fix"), dict) else None\n    if fix:')]),
    # ---------------------------------------------------------------------------------------------------------- the real provider walk (fake providers, no stub of llm)
    ("W1", "wire", "the walk is not given Talk's check (a Hindi-only reply would reach the English voice)", [("interview/engine.py", "temperature=0.6, schema=TR.SCHEMA, check=TR.check)", "temperature=0.6, schema=TR.SCHEMA)")]),
    ("W2", "wire", "the walk is given neither Talk's schema nor its check (a reply without `reply` is 'usable'; schema and check each also catch it alone: layered)", [("interview/engine.py", "temperature=0.6, schema=TR.SCHEMA, check=TR.check)", "temperature=0.6)")]),
    ("W3", "wire", "Talk asks the validated walk twice (its own retry loop is not dropped when the walk is on)", [("interview/engine.py", "            if attempt == 1 and v3:\n                break                       # the validated walk asked every model for a usable object already; a second walk would meet the same models, held back\n            ask = payload if attempt == 0 else (payload + \"\\n\\n(Your last reply was not a valid JSON object with a non-empty English \"", "            if False:\n                break                       # the validated walk asked every model for a usable object already; a second walk would meet the same models, held back\n            ask = payload if attempt == 0 else (payload + \"\\n\\n(Your last reply was not a valid JSON object with a non-empty English \"")]),
    ("W4", "engine", "a talk turn is not prefer_fast (it gets the slow heavy-call limits)", [("interview/engine.py", "max_tokens=TR.MAX_TOKENS[support], prefer_fast=True,", "max_tokens=TR.MAX_TOKENS[support], prefer_fast=False,")]),
    # ---------------------------------------------------------------------------------------------------------- the WebSocket wiring (real handler, scratch MongoDB)
    ("S1", "ws", "a `talk` start with the switch off builds a Session anyway", [("main.py", "                    if not await talk_v3_enabled(_email):\n                        await _send(ws, type=\"error\", msg=\"Talk is not available for this account yet.\")", "                    if False:\n                        await _send(ws, type=\"error\", msg=\"Talk is not available for this account yet.\")")]),
    ("S2", "ws", "an unknown topic is silently replaced by the first one", [("main.py", '                    _tk_topic = talk_topics.get(data.get("topic_id"))\n', '                    _tk_topic = talk_topics.get(data.get("topic_id")) or talk_topics.all_topics()[0]\n')]),
    ("S3", "ws", "support 'hi' (Daily Talk's level) is accepted by the talk mode", [("main.py", "                    if _tk_support not in talk_topics.TALK_SUPPORTS:", "                    if _tk_support not in talk_topics.SUPPORTS:")]),
    ("S4", "ws", "_RESUMABLE forgets talk (a reconnect becomes a fresh opener)", [("main.py", '_RESUMABLE = ("conversation", "interview", "practice", "home", "talk")', '_RESUMABLE = ("conversation", "interview", "practice", "home")')]),
    ("S5", "ws", "after a resume the turn count is not reset (the first socket's turns are rewarded twice)", [("main.py", 'session.turns = 0 if session.mode in ("conversation", "interview", "talk") else _n_user', 'session.turns = 0 if session.mode in ("conversation", "interview") else _n_user')]),
    ("S6", "ws", "the XP bonus entry for talk is missing (it is booked as Face-to-Face)", [("db.py", '               "talk": 15}', '               }')]),
    ("S7", "ws", "a failed talk turn does not give the free turn back", [("main.py", '                        # a failed turn leaves the session as it was (the learner\'s line is added only once DuSu has answered), so a retry is not said twice\n                        await _turn_failed(e, "error", msg="Could not get a reply — please try again.")', '                        # a failed turn leaves the session as it was (the learner\'s line is added only once DuSu has answered), so a retry is not said twice\n                        await _send(ws, type="error", msg="Could not get a reply — please try again.")')]),
    ("S8", "ws", "the turn cap is not enforced for talk", [("main.py", "                    if session.turns >= settings.conversation_max_turns:\n                        await turn_quota.refund()", "                    if False:\n                        await turn_quota.refund()")]),
    ("S9", "ws", "Grammar Coach is wired into a Talk chat at all three layers: the mode list, the persist hook and the session gate (a second analysis, a second charge)", [("main.py", '        if _gc_on and session.mode in ("conversation", "interview"):', '        if _gc_on and session.mode in ("conversation", "interview", "talk"):'),
                                                                                                 ("main.py", 'if uid and db.db_enabled and _gref and mode in ("conversation", "interview", "practice") \\', 'if uid and db.db_enabled and _gref and mode in ("conversation", "interview", "practice", "talk") \\'),
                                                                                                 ("grammar/gating.py", '_SESSION_OK_EN = ("conversation", "interview")', '_SESSION_OK_EN = ("conversation", "interview", "talk")')]),
    ("S10", "ws", "Talk does not earn the first-chat badge", [("main.py", 'if session.mode in ("conversation", "daily", "talk"): badges.append("courage_first_convo")', 'if session.mode in ("conversation", "daily"): badges.append("courage_first_convo")')]),
    ("S11", "ws", "the learner's CEFR level is not loaded for talk (the fix check and the prompt run level-blind)", [("main.py", "                        facts, ictx = await asyncio.gather(db.get_memory(uid), db.interview_context(uid))", "                        facts, ictx = await db.get_memory(uid), {}")]),
    ("S12", "ws", "the opener is not put in the transcript (the model never knows what it said)", [("interview/engine.py", '            self.transcript.append({"role": "assistant", "content": op["en"]})\n            return out', "            return out")]),
    ("S13", "ws", "talk is not saved with its own mode name (the summary row says 'conversation')", [("main.py", "                await db.add_conversation(uid, session.mode, mem.get(\"summary\", \"\"))", "                await db.add_conversation(uid, \"conversation\" if session.mode == \"talk\" else session.mode, mem.get(\"summary\", \"\"))")]),
    # ---------------------------------------------------------------------------------------------------------- the HTTP side (real HTTP layer, scratch MongoDB)
    ("H1", "http", "the gate serves a learner while the switch is off", [("talk/api.py", "    if not await M.talk_v3_enabled(email):", "    if False:")]),
    ("H2", "http", "a blocked account may use Talk", [("talk/api.py", '        if (await db.get_user_flags(uid)).get("status") == "blocked":', '        if (await db.get_user_flags(uid)).get("status") == "zzz":')]),
    ("H3", "http", "any string is accepted as the support level", [("talk/service.py", "    if support not in T.SUPPORTS:\n        raise Invalid(\"support\")", "    if False:\n        raise Invalid(\"support\")")]),
    ("H4", "http", "one learner sees another learner's saved level", [("talk/service.py", "        mem = await s.get(db.Memory, uid)\n        await s.commit()\n    facts = (mem.facts or {}) if mem is not None else {}", "        mem = (await s.execute(select(db.Memory).limit(1))).scalars().first()\n        await s.commit()\n    facts = (mem.facts or {}) if mem is not None else {}")]),
    ("H5", "http", "Talk is in the Home registry for everyone (no `needs`)", [("home_content.py", '"route": "/talk", "status": "live", "needs": "talk_v3"', '"route": "/talk", "status": "live", "needs": None')]),
    ("H6", "http", "saving the level wipes the rest of the memory", [("talk/service.py", '        f["talk_prefs"] = {**cur, "support": support}', '        f = {"talk_prefs": {**cur, "support": support}}')]),
    ("H7", "http", "no rate limit", [("talk/api.py", "    if len(q) >= REQS_PER_MIN:", "    if False:")]),
    ("H8", "http", "the default support level ignores the learner's level", [("talk/topics.py", '    return DEFAULT_SUPPORT[band_for_level(level)]', '    return "en_sub"')]),
    ("H9", "http", "a Talk chat does not count toward the weekly Face-to-Face mission", [("db.py", 'elif metric == "conversation_sessions" and mode in ("conversation", "talk"):', 'elif metric == "conversation_sessions" and mode == "conversation":')]),
    ("H10", "http", "the admin switch for talk_v3 is not saved", [("main.py", '        await db.set_setting("talk_v3", inp.talk_v3 if inp.talk_v3 in ("off", "owner", "on") else "off")', "        pass")]),
    ("H11", "http", "talk_v3 reads 'owner' as 'everyone'", [("main.py", '    if m == "owner":\n        return await staged_visible(email)\n    return False\n\n\nasync def notifications_mode()', '    if m == "owner":\n        return True\n    return False\n\n\nasync def notifications_mode()')]),
]

TIERS = {"pure": ["unit_topics.py", "unit_reply.py"], "engine": ["unit_engine.py"], "http": ["selftest.py"], "ws": ["ws_selftest.py"], "wire": ["wire_walk.py"]}


def run(cmd, cwd, env=None, timeout=900):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def first_fail(out: str) -> str:
    lines = out.splitlines()
    return (next((ln for ln in lines if ln.startswith("  FAIL")), None) or next((ln for ln in lines if "Traceback" in ln), None) or "exit code != 0").strip()[:100]


def main():
    tier = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("pure", "engine", "http", "ws", "wire", "all") else "all"
    want = [a for a in sys.argv[1:] if a in {m[0] for m in M}]
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    caught, survived = 0, []
    for mid, mtier, desc, edits in M:
        if (tier != "all" and mtier != tier) or (want and mid not in want):
            continue
        d = os.path.join(WORK, mid)
        shutil.copytree(os.path.join(ROOT, "backend"), os.path.join(d, "backend"), ignore=shutil.ignore_patterns(".venv", "__pycache__", ".env*", "*.pyc", "users.db"))
        applied = True
        for rel, old, new in edits:
            path = os.path.join(d, "backend", "app", rel)
            src = open(path, encoding="utf-8").read()
            if src.count(old) != 1:
                print(f"{mid:4} NOT APPLIED ({src.count(old)} matches in {rel})  {desc}")
                survived.append(mid + "(not applied)")
                applied = False
                break
            open(path, "w", encoding="utf-8").write(src.replace(old, new))
        if not applied:
            shutil.rmtree(d, ignore_errors=True)
            continue
        how = ""
        if mtier == "pure":
            os.makedirs(os.path.join(d, "tests", "talk"))
            for f in os.listdir(os.path.join(ROOT, "tests", "talk")):
                if f.endswith(".py") and f != "mutants.py":
                    shutil.copy(os.path.join(ROOT, "tests", "talk", f), os.path.join(d, "tests", "talk", f))
            for t in TIERS["pure"]:
                rc, out = run([sys.executable, f"tests/talk/{t}"], d, timeout=300)
                if rc != 0:
                    how = f"{t}: " + first_fail(out)
                    break
        else:
            for t in TIERS[mtier]:
                args = ["tests/talk/run.sh"] + (["--nomongo"] if mtier == "engine" else []) + [t]
                rc, out = run(args, ROOT, {"TALK_BACKEND_DIR": os.path.join(d, "backend")}, timeout=900)
                if rc != 0:
                    how = f"{t}: " + first_fail(out)
                    break
        if how:
            caught += 1
            print(f"{mid:4} caught     ({desc})  -> {how}", flush=True)
        else:
            survived.append(mid)
            print(f"{mid:4} SURVIVED   ({desc})  <- no test noticed", flush=True)
        shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(WORK, ignore_errors=True)
    print(f"\nmutants: {caught} caught, {len(survived)} survived: {' '.join(survived) or 'none'}")
    print("finished")
    sys.exit(1 if survived else 0)


main()
