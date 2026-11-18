#!/usr/bin/env python3
"""Talk client - planted bugs.  Each mutant is the real page with ONE deliberate bug; at least one of the named specs must FAIL on it (a spec that still passes is blind to that bug).
    tests/talk/browser/mutants.py              all mutants
    tests/talk/browser/mutants.py M3 M5        some of them
    MUT_JOBS=2 tests/talk/browser/mutants.py   how many run side by side (default 1)
A mutated copy of backend/ lives in tests/talk/browser/.mut-<pid>-<n>/ (removed afterwards; .env files are never copied).  A `static` mutant runs static.spec.cjs (no server); a `real` one
runs real.spec.cjs through run_real.sh against the copy (TK_BACKEND) with ONLY=<its scenarios>.  Exit 0 only when every mutant was caught."""
import concurrent.futures as cf, hashlib, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "../../.."))

# (name, [("static"|"real", "scenario ids"), ...], what is broken, text that occurs exactly once in test_client.html, what it becomes)
M = [
    ("M1", [("real", "B1"), ("static", "")], "the Hindi subtitle is put INSIDE the bubble (the replay would send it to the model)",
     'el.classList.add("tk-m"); el.appendChild(h("div", { class:"tk-sub", lang:"hi" }, hi.slice(0, 600)));', 'el.querySelector(".bubble").appendChild(h("div", { class:"tk-sub", lang:"hi" }, hi.slice(0, 600)));'),
    ("M2", [("real", "B3")], "the correction card is put inside the learner's bubble",
     "user.after(card);   // directly under the learner's own bubble", '(user.querySelector(".bubble") || user).appendChild(card);'),
    ("M3", [("real", "A8")], "Hindi to English is sent to the talk mode instead of opening Daily Talk",
     'if(S.support === "hi"){ navTo("/daily-talk"); return; }', 'if(false){ navTo("/daily-talk"); return; }'),
    ("M4", [("real", "B1")], "the start frame always says support:\"hi\"",
     "topic_id:topic.id, support, hour:", 'topic_id:topic.id, support:"hi", hour:'),
    ("M5", [("real", "E1"), ("static", "")], "the Hindi subtitle is set with innerHTML",
     'el.classList.add("tk-m"); el.appendChild(h("div", { class:"tk-sub", lang:"hi" }, hi.slice(0, 600)));', 'el.classList.add("tk-m"); const sd = h("div", { class:"tk-sub", lang:"hi" }); sd.innerHTML = hi; el.appendChild(sd);'),
    ("M6", [("real", "D1"), ("static", "")], "the global Hindi / English switch reaches the Talk chat (Talk made switchable)",
     "const SWITCHABLE = { home:true };", "const SWITCHABLE = { home:true, talk:true };"),
    ("M7", [("real", "B3")], "the correction card is drawn while DuSu is still speaking",
     "whenSpeechEnds(() => drawFix(fix, user));", "drawFix(fix, user);"),
    ("M8", [("real", "C1")], "a retry that sends nothing (the same-words resend sends an empty line)",
     'try{ ws.send(JSON.stringify({ type:"user_text", text: line })); }catch(_){ return false; }\n    return true;\n  }\n  sessRevive();', 'try{ ws.send(JSON.stringify({ type:"user_text", text: "" })); }catch(_){ return false; }\n    return true;\n  }\n  sessRevive();'),
    ("M9", [("real", "B5")], "a revive that loses the topic",
     "sessFrame = f; sessT0 = Date.now();   // kept: a screen lock", 'sessFrame = Object.assign({}, f, { topic_id:"" }); sessT0 = Date.now();   // kept: a screen lock'),
    ("M10", [("real", "A11")], "the Talk entry points are drawn while the switch is off",
     'const e = $g("tkEntry"); if(e) e.hidden = !on;', 'const e = $g("tkEntry"); if(e) e.hidden = false;'),
    ("M11", [("real", "B5")], "the replay reads the whole message, not the bubble (a subtitle would be sent back)",
     'const t = ((m.querySelector(".bubble") || {}).textContent || "").trim();', 'const t = (m.textContent || "").replace(/^Du/, "").replace(/^🙂/, "").trim();'),
    ("M12", [("real", "B3")], "the correction card goes to the end of the feed, not under the learner's line",
     "user.after(card);   // directly under the learner's own bubble", '$g("feed").appendChild(card);'),
    ("M13", [("real", "B4")], "a \"likely\" fix is worded as a firm \"sure\"",
     'c:f.c === "sure" ? "sure" : "likely"', 'c:"sure"'),
    ("M14", [("real", "B3")], "Try again does not start the microphone",
     "    if(st) st.textContent = C.support === \"en_sub\" ? CH.hi.trying : CH.en.trying;\n    startListening();", "    if(st) st.textContent = C.support === \"en_sub\" ? CH.hi.trying : CH.en.trying;"),
    ("M15", [("real", "B3")], "Hear it speaks the fragment, not the corrected sentence",
     'try{ speak(f.full, "en"); }catch(_){}', 'try{ speak(f.f, "en"); }catch(_){}'),
    ("M16", [("real", "B2")], "a stray subtitle is drawn at English only",
     'if(el && hi && C.support === "en_sub"){', "if(el && hi){"),
    ("M17", [("real", "A3")], "the level choice is not remembered on the server",
     'api("POST", "/prefs", { support:id }).then(', 'Promise.resolve().then('),
    ("M18", [("real", "A2")], "tapping a starter also sends it (starts the chat)",
     "onclick:() => { S.hint = pickIdx(i); paintHint(); } }", "onclick:() => { S.hint = pickIdx(i); paintHint(); startChat(S.topic, S.support); } }"),
    ("M19", [("real", "B7")], "`ended` moves a Talk learner off the session-result screen",
     'currentMode === "conversation" || currentMode === "daily" || currentMode === "talk") && currentScreen() === "sessionResult"', 'currentMode === "conversation" || currentMode === "daily") && currentScreen() === "sessionResult"'),
    ("M20", [("real", "B5"), ("static", "")], "a locked Talk chat is not paused / revived (VP does not own it)",
     'const SESS = new Set(["conversation", "interview", "practice", "home", "talk"]);', 'const SESS = new Set(["conversation", "interview", "practice", "home"]);'),
    ("M21", [("real", "A12"), ("static", "")], "/talk is not a rollout-flagged route (a cold link is judged before /me answers)",
     '["/grammar-lab", "grammar_lab"], ["/talk", "talk_v3"], ["/home-chat", "home_ai"]', '["/grammar-lab", "grammar_lab"], ["/home-chat", "home_ai"]'),
    ("M22", [("real", "A1")], "the grammar-focus chip opens the Lab hub, not the unit",
     'navTo("/grammar-lab/" + focus)', 'navTo("/grammar-lab")'),
    ("M23", [("real", "B7")], "the end-of-chat list shows every fix, not the top three",
     "const top = topFixes(3);", "const top = topFixes(9);"),
    ("M24", [("real", "B1")], "the chat counts as two sessions",
     "usageInc(); refreshUsage();   // count the chat now that it actually started, like Face-to-Face", "usageInc(); usageInc(); refreshUsage();   // count the chat now that it actually started, like Face-to-Face"),
    ("M25", [("real", "B6")], "the subtitle toggle is not remembered",
     'try{ localStorage.setItem(K_SUB, subOn ? "1" : "0"); }catch(_){}', ""),
    ("M26", [("real", "A2")], "Escape does not close the starter hint",
     'if(e.key !== "Escape") return;', 'if(e.key !== "Escape_") return;'),
    ("M27", [("real", "A2")], "a starter's Hear button speaks the Hindi",
     "onclick:() => hear(s.en) }", "onclick:() => hear(s.hi) }"),
    ("M28", [("real", "A13")], "a second routing pass wipes the card that was just drawn",
     "if(currentScreen() === \"tk\" && S.state && S.topic && Date.now() - S.at < 6000) return;", ""),
    ("M29", [("real", "E1")], "the reason of a correction is set with innerHTML",
     'f.r ? h("span", { lang:"en" }, f.r) : null', 'f.r ? (() => { const sp = h("span", { lang:"en" }); sp.innerHTML = f.r; return sp; })() : null'),
    ("M30", [("real", "E2")], "the topic title is set with innerHTML",
     'h("h3", { class:"tk-h", id:"tkTopicEn", lang:"en" }, pick(tp.title, "en")),', '(() => { const hh = h("h3", { class:"tk-h", id:"tkTopicEn", lang:"en" }); hh.innerHTML = pick(tp.title, "en"); return hh; })(),'),
    ("M31", [("real", "B1")], "the mic is not told to listen in en-US for Talk (the chat would listen in Hindi)",
     "recog.lang = LG.stt(LG.lang(currentMode));", 'recog.lang = LG.stt(currentMode === "talk" ? "hi" : LG.lang(currentMode));'),
    ("M32", [("real", "B1")], "the opener's subtitle is spoken aloud",
     'speak(m.text, m.lang);\n    if(fix){ C.fixes.push(fix);', 'speak(m.text + " " + (m.hi || ""), m.lang);\n    if(fix){ C.fixes.push(fix);'),
    ("M33", [("real", "A8")], "Hindi to English stops being Daily Talk: it sends the talk-mode frame as well",
     'if(S.support === "hi"){ navTo("/daily-talk"); return; }', 'if(S.support === "hi"){ navTo("/daily-talk"); try{ startChat(S.topic, "en"); }catch(_){} return; }'),
    ("M35", [("real", "B9")], "a Talk chat ignores the free daily session limit",
     "    if(overLimit()){ limitNote(); return; }\n    currentMode = \"talk\";", "    currentMode = \"talk\";"),
    ("M34", [("real", "A11")], "with the switch off a /talk deep link stays on the empty Talk screen",
     "ROUTES[BASE] = { enter: () => { if(!enabled()){ try{ goHome(); }catch(_){} return; } open(); } };", "ROUTES[BASE] = { enter: () => { open(); } };"),
]


def run(cmd, env=None):
    return subprocess.run(cmd, env=dict(os.environ, **(env or {})), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout


def seen_by_docker(directory, path):
    """Docker's file sharing can show a container the file as it was a moment ago: wait until a container reads the SAME bytes this script just wrote."""
    want = hashlib.sha256(open(path, "rb").read()).hexdigest()
    for _ in range(60):
        if want in run(["docker", "run", "--rm", "-v", directory + ":/m:ro", "alpine:3", "sha256sum", "/m/test_client.html"]):
            return True
        time.sleep(1)
    return False


def one(idx, item):
    name, specs, desc, old, new = item
    mut = os.path.join(HERE, ".mut-%d-%d" % (os.getpid(), idx))
    shutil.rmtree(mut, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "backend"), os.path.join(mut, "backend"), ignore=shutil.ignore_patterns(".venv", "__pycache__", ".env", ".env.*"))
    path = os.path.join(mut, "backend", "test_client.html")
    try:
        s = open(path, encoding="utf-8").read()
        if s.count(old) != 1:
            return name, desc, None, f"the text to mutate occurs {s.count(old)} times"
        open(path, "w", encoding="utf-8").write(s.replace(old, new))
        if not seen_by_docker(os.path.join(mut, "backend"), path):
            return name, desc, None, "Docker never showed the mutated file"
        verdicts = []
        for kind, scen in specs:
            if kind == "static":
                out = run(["bash", os.path.join(HERE, "run.sh"), "static.spec.cjs"], {"HTML_SRC": "/repo/tests/talk/browser/" + os.path.basename(mut) + "/backend/test_client.html"})
                verdict, tag = "talk-static:" in out, "static"
            else:
                out = run(["bash", os.path.join(HERE, "run_real.sh"), "real.spec.cjs"], {"TK_BACKEND": os.path.join(mut, "backend"), "ONLY": scen})
                verdict, tag = "talk (real browser, real server):" in out, "real " + scen
            if os.environ.get("MUT_LOG"):
                os.makedirs(os.environ["MUT_LOG"], exist_ok=True)
                open(os.path.join(os.environ["MUT_LOG"], f"{name}-{tag.replace(' ', '_')}.log"), "w", encoding="utf-8").write(out)
            fails = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")]
            crashed = ("SPEC CRASHED" in out)
            if not verdict and not crashed:
                verdicts.append((tag, None, out.strip()[-160:]))
                continue
            verdicts.append((tag, (fails[0][:110] if fails else ("(spec crashed)" if crashed else "")), None) if (fails or crashed) else (tag, "", None))
            if fails or crashed:
                return name, desc, True, f"{tag}: {fails[0][:110] if fails else '(crashed)'}"
        if any(v[1] is None for v in verdicts):
            return name, desc, None, "no verdict (infrastructure?): " + "; ".join(str(v) for v in verdicts)
        return name, desc, False, "all of " + ", ".join(v[0] for v in verdicts) + " still pass"
    finally:
        shutil.rmtree(mut, ignore_errors=True)


def main():
    want = set(sys.argv[1:])
    items = [(i, m) for i, m in enumerate(M) if not want or m[0] in want]
    jobs = int(os.environ.get("MUT_JOBS", "1"))
    survivors = []
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(one, i, m): m[0] for i, m in items}
        for f in cf.as_completed(futs):
            name, desc, caught, detail = f.result()
            if caught is None:
                print(f"?? {name} ({desc}): {detail}"); survivors.append(name + "(no verdict)")
            else:
                print(("caught    " if caught else "SURVIVED  ") + f"{name} ({desc})   -> {detail}")
                if not caught:
                    survivors.append(name)
            sys.stdout.flush()
    print("\nsurvivors:", " ".join(survivors) or "none")
    sys.exit(1 if survivors else 0)


main()
