#!/usr/bin/env python3
"""Grammar Lab client - planted bugs.  Each mutant is the real page with ONE deliberate bug; the named spec must FAIL on it (a spec that still passes is blind to that bug).
    tests/lab/browser/mutants.py            all mutants
    tests/lab/browser/mutants.py M3 M5      some of them
A mutated copy of backend/ lives in tests/lab/browser/.mut-<pid>/ (removed afterwards).  `static` mutants run static.spec.cjs (no server); `real` ones run real.spec.cjs through run_real.sh against the copy
(LAB_BACKEND).  Exit 0 only when every mutant was caught."""
import hashlib, os, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "../../.."))
MUT = os.path.join(HERE, ".mut-%d" % os.getpid())      # per process: several runs may go side by side

# (name, spec, what is broken, text that occurs exactly once in test_client.html, what it becomes)
M = [
    ("M1", "static", "innerHTML in the module", 'put(body(), spinner(t("loading")));\n    let d;', 'body().innerHTML = "<b>" + t("loading") + "</b>"; put(body(), spinner(t("loading")));\n    let d;'),
    ("M2", "static", "a Hindi string says आप", 'howH:"कैसे काम करता है"', 'howH:"आप कैसे काम करता है"'),
    ("M3", "static", "a key is missing in the English table", 'noBank:"The sentences are not ready yet. Check again later.", ', ''),
    ("M4", "real", "a double tap is not guarded", '    if(S.busy) return;\n    const D = S.set, it = curItem(); if(!D || !it || it.done) return;\n    const ta = $g("glIn")', '    const D = S.set, it = curItem(); if(!D || !it || it.done) return;\n    const ta = $g("glIn")'),
    ("M5", "real", "a network failure loses the typed text", 'S.err = eText(e); paintDrill(); return;\n    }\n    if(ep !== S.epoch) return;\n    S.busy = false; applyResult(it, r);\n  }\n  async function showAnswer',
     'S.err = eText(e); S.draft = ""; paintDrill(); return;\n    }\n    if(ep !== S.epoch) return;\n    S.busy = false; applyResult(it, r);\n  }\n  async function showAnswer'),
    ("M6", "real", "the language choice is not remembered", 'pref = l; try{ localStorage.setItem(K_LANG, l); }catch(_){}', 'pref = l;'),
    ("M7", "real", "the exact changes are never drawn", 'if((ex.changes || []).length) kids.push(', 'if(false) kids.push('),
    ("M8", "real", "Try again does not clear the box", 'function tryAgain(){ S.res = null; S.draft = "";', 'function tryAgain(){ S.res = null;'),
    ("M9", "real", "the heard text cannot be edited", 'kids.push(lab, ta, h("p", { class:"gl-hint"', 'if(S.heard) ta.readOnly = true; kids.push(lab, ta, h("p", { class:"gl-hint"'),
    ("M10", "real", "an off switch does not send the route Home", 'if(isOff(e)){ goHome(); return; } put(b,', 'if(isOff(e)){ put(b, h("p", null, "x")); return; } put(b,'),
    ("M11", "real", "the Review card never shows", 'if(H.review_due > 0) kids.push', 'if(false) kids.push'),
    ("M12", "real", "the mic keeps listening in a hidden tab", 'function stopVoiceOutside(){ const was = S.listening; stopVoice();', 'function stopVoiceOutside(){ const was = S.listening;'),
    ("M13", "real", "the summary's right count is the wrong count", 't("sRight", { n:s.right || 0 })', 't("sRight", { n:s.wrong || 0 })'),
    ("M14", "real", "server text is parsed as HTML (explanation headline)", 'if(ex.headline) kids.push(h("p", { class:"gl-head", lang:L }, ex.headline));', 'if(ex.headline){ const hp = h("p", { class:"gl-head", lang:L }); hp.innerHTML = ex.headline; kids.push(hp); }'),
    ("M15", "real", "the answer is not shown after the third miss", 'if(done){\n      const main = String(r.target || r.model || "")', 'if(done && v === "ok"){\n      const main = String(r.target || r.model || "")'),
    ("M16", "real", "the Hindi / English toggle asks the server again instead of redrawing", 'paintHeader(); if(S.view === "hub" || S.view === "unit" || S.view === "drill" || S.view === "summary") paintBody();', 'paintHeader(); if(S.view === "drill" && S.res){ api("POST", "/show", { set:S.set.set, item:curItem().id }).catch(() => {}); } paintBody();'),
    ("M17", "real", "a Hindi answer uses up a try on screen (the message card replaces the box)", 'if(v === "empty" || v === "lang") return null;', 'if(v === "empty" || v === "lang") return h("div", { class:"gl-card gl-res bad", id:"glResult" }, "x");'),
    ("M18", "real", "the level chips start the wrong level", 'onclick:() => startLevel(u.unit, l) }', 'onclick:() => startLevel(u.unit, "easy") }'),
]


def run(cmd, env=None):
    return subprocess.run(cmd, env=dict(os.environ, **(env or {})), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout


def seen_by_docker(directory, path):
    """Docker's file sharing can show a container the file as it was a moment ago: wait until a container reads the SAME bytes this script just wrote (a mutant that was never really served would
    look like a bug the spec cannot see)."""
    want = hashlib.sha256(open(path, "rb").read()).hexdigest()
    for _ in range(60):
        if want in run(["docker", "run", "--rm", "-v", directory + ":/m:ro", "alpine:3", "sha256sum", "/m/test_client.html"]):
            return True
        time.sleep(1)
    return False


def main():
    want = set(sys.argv[1:])
    survivors = []
    try:
        for name, kind, desc, old, new in M:
            if want and name not in want:
                continue
            shutil.rmtree(MUT, ignore_errors=True)
            shutil.copytree(os.path.join(REPO, "backend"), os.path.join(MUT, "backend"), ignore=shutil.ignore_patterns(".venv", "__pycache__"))
            path = os.path.join(MUT, "backend", "test_client.html")
            s = open(path, encoding="utf-8").read()
            if s.count(old) != 1:
                print(f"?? {name}: the text to mutate occurs {s.count(old)} times"); survivors.append(name + "(unplantable)"); continue
            open(path, "w", encoding="utf-8").write(s.replace(old, new))
            if not seen_by_docker(os.path.join(MUT, "backend"), path):
                print(f"?? {name}: Docker never showed the mutated file"); survivors.append(name + "(not served)"); continue
            if kind == "static":
                out = run(["bash", os.path.join(HERE, "run.sh"), "static.spec.cjs"], {"HTML_SRC": "/repo/tests/lab/browser/" + os.path.basename(MUT) + "/backend/test_client.html"})
            else:
                out = run(["bash", os.path.join(HERE, "run_real.sh"), "real.spec.cjs"], {"LAB_BACKEND": os.path.join(MUT, "backend")})
            if os.environ.get("MUT_LOG"):
                os.makedirs(os.environ["MUT_LOG"], exist_ok=True)
                open(os.path.join(os.environ["MUT_LOG"], name + ".log"), "w", encoding="utf-8").write(out)
            fails = [l for l in out.splitlines() if l.strip().startswith("FAIL")]
            reached = ("# A. the hub" in out) or ("# 1. DOM calls only" in out)
            verdict = ("lab-real:" in out) or ("lab-static:" in out)
            crashed = reached and not verdict                      # the spec started and died on the bug (a timeout waiting for something the bug removed)
            if not fails and not crashed and not verdict:
                print(f"?? {name}: the run produced no verdict (infrastructure?): {out.strip()[-160:]!r}"); survivors.append(name + "(no verdict)"); continue
            caught = bool(fails) or crashed
            print(("caught    " if caught else "SURVIVED  ") + f"{name} ({desc})" + (f"   -> {fails[0].strip()[:120]}" if fails else ("   -> (crashed)" if crashed else "")))
            sys.stdout.flush()
            if not caught:
                survivors.append(name)
    finally:
        shutil.rmtree(MUT, ignore_errors=True)
    print("\nsurvivors:", " ".join(survivors) or "none")
    sys.exit(1 if survivors else 0)


main()
