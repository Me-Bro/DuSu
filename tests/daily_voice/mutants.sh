#!/usr/bin/env bash
# A locked screen vs the voice chats - "do the tests catch a planted bug?"  Copies the backend, plants ONE deliberate bug, runs the tier that should notice it against the copy and
# reports whether it FAILED (= the bug was caught). A mutant that survives means a check is too weak. Never touches backend/ itself.
#   tests/daily_voice/mutants.sh            every mutant (server S1-S19 ~1 min each, client K1-K17 / N1-N34 ~1-3 min each)
#   tests/daily_voice/mutants.sh S2 K5 N7   only these
# S1-S6 / K1-K17: Daily Talk + Learn (ws_selftest.py / lock.spec.cjs).  S7-S19 / N1-N34: Face-to-Face, Interview, practice, Home (ws_sessions_selftest.py / lock2.spec.cjs).
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT="tests/daily_voice/.mutants"; mkdir -p "$OUT"
declare -A FILE DESC OLD NEW SPECS RUNNER
# add ID FILE DESC OLD NEW [SCENARIOS (ONLY=) for a client mutant] [runner: the server test script or the browser spec]
add() { FILE[$1]="$2"; DESC[$1]="$3"; OLD[$1]="$4"; NEW[$1]="$5"; SPECS[$1]="${6:-}"; RUNNER[$1]="${7:-}"; }
M=app/main.py; H=test_client.html
SS=ws_sessions_selftest.py; L2=lock2.spec.cjs

# ---- server, Daily (ws_selftest.py)
add S1  $M "ping is ignored" 'elif mtype == "ping":' 'elif mtype == "ping_disabled":' "" ws_selftest.py
add S2  $M "the reconnect flag is ignored (always a greeting)" 'if data.get("reconnect") is True and session.transcript:' 'if False and session.transcript:' "" ws_selftest.py
add S3  $M "a quiet resume still counts the replayed turns" '                        session.turns = 0
                        await _send(ws, type="daily_resumed"' '                        await _send(ws, type="daily_resumed"' "" ws_selftest.py
add S4  $M "any truthy reconnect value is honoured" 'if data.get("reconnect") is True and session.transcript:' 'if data.get("reconnect") and session.transcript:' "" ws_selftest.py
add S5  $M "a quiet resume still makes the opening model call" 'await _send(ws, type="daily_resumed", lang=session.lang)' 'await session.daily_turn("", first=True); await _send(ws, type="daily_resumed", lang=session.lang)' "" ws_selftest.py
add S6  $M "a reconnect with nothing to resume is not a plain start" 'if data.get("reconnect") is True and session.transcript:' 'if data.get("reconnect") is True:' "" ws_selftest.py

# ---- server, the other chats (ws_sessions_selftest.py)
add S7  $M "any truthy reconnect value is honoured (session chats)" 'if data.get("reconnect") is True and session.mode in _RESUMABLE:' 'if data.get("reconnect") and session.mode in _RESUMABLE:' "" $SS
add S8  $M "a Face-to-Face / Interview resume keeps the replayed turn count (paid twice)" 'session.turns = 0 if session.mode in ("conversation", "interview") else _n_user' 'session.turns = _n_user' "" $SS
add S9  $M "a Practice resume resets its turn count (the rounds start over)" 'session.turns = 0 if session.mode in ("conversation", "interview") else _n_user' 'session.turns = 0' "" $SS
add S10 $M "the practice's elapsed time is ignored" 'started_at -= max(0.0, min(_el, 7200.0))' 'pass' "" $SS
add S11 $M "the replay is not bounded" 'for m in resume[-_REPLAY_LINES:]:' 'for m in resume:' "" $SS
add S12 $M "adjacent lines by one speaker are not joined" 'if lines and lines[-1]["role"] == r:' 'if False:' "" $SS
add S13 $M "Grammar Coach analyses the replayed lines again" '_gc_view(session), secs=' 'session, secs=' "" $SS
add S14 $M "the Home chat cannot resume (it opens fresh)" '_RESUMABLE = ("conversation", "interview", "practice", "home")' '_RESUMABLE = ("conversation", "interview", "practice")' "" $SS
add S15 $M "a system line from the page is accepted into the transcript" 'if r not in ("user", "assistant") or not isinstance(c, str):' 'if not isinstance(c, str):' "" $SS
add S16 $M "control characters are not stripped from replayed lines" 're:c = re\.sub\(r"\[\\x00-\\x08\\x0b-\\x1f\\x7f\]\+", " ", c\)\.strip\(\)\[:_REPLAY_CHARS\]' 'c = c.strip()[:_REPLAY_CHARS]' "" $SS
add S17 $M "a reconnect with nothing usable still claims to be resumed" '                    _n_user = _replay_into(session, data.get("resume"))
                    if session.transcript:' '                    _n_user = _replay_into(session, data.get("resume"))
                    if True:' "" $SS
add S18 $M "a resume still makes an opener model call" 'await _send(ws, type="session_resumed", mode=session.mode, lang=session.lang)' 'await session.next_ai_turn() if session.mode != "home" else None; await _send(ws, type="session_resumed", mode=session.mode, lang=session.lang)' "" $SS

# ---- client, Daily + Learn (lock.spec.cjs, only the scenarios that should notice)
add K1  $H "the screen is not restored after the unlock (the mic stays dead)" 'running = true; dailyRestoreUI();' 'running = true;' "A2,A3,A4,A5" lock.spec.cjs
add K2  $H "a lock closes the socket again (the old behaviour)" '// an in-flight reply chain stops here and never starts its next line' '// an in-flight reply chain stops here and never starts its next line
    try{ ws.close(); }catch(_){}' "A1" lock.spec.cjs
add K3  $H "a reply that lands on a locked phone is spoken" 'if(document.hidden){ dailyOrb("idle"); dState(lgt("dReplyReady")); return; }   // a locked phone: shown, not spoken' '' "A4" lock.spec.cjs
add K4  $H "a quiet reconnect is counted as a new session" '    if(!quiet){ usageInc(); refreshUsage();' '    if(true){ usageInc(); refreshUsage();' "B1" lock.spec.cjs
add K5  $H "the quiet-reconnect flag is not sent" 'reconnect: quiet && dailyTurns.length ? true : undefined' 'reconnect: undefined' "B1" lock.spec.cjs
add K6  $H "the 10-minute grace timer never ends the session" 'if(!p || !owns() || !document.hidden) return;' 'return;' "B6" lock.spec.cjs
add K7  $H "the quota case still leaves the mic dead (running is not forced)" 'if(ws && ws.readyState === 1){ running = true; if(fromReply) dailyContinue(); else startDailyListen(); return; }' 'if(ws && ws.readyState === 1){ if(fromReply) dailyContinue(); else startDailyListen(); return; }' "D1" lock.spec.cjs
add K8  $H "the lock does not stop the reply chain" 're:(function pause\(\)\{\n    if\(!p\) p = \{[^\n]*\n)    speakEpoch\+\+;[^\n]*\n' '\1' "A3" lock.spec.cjs
add K9  $H "a long lock never asks the socket if it is alive" 'if(away < LONG_MS) return Promise.resolve(true);' 'return Promise.resolve(true);' "B4" lock.spec.cjs
add K10 $H "Learn greets again after a quiet reconnect" 'if(learnQuiet){ learnResumed(); return; }   // a quiet reconnect: no greeting' '' "E2" lock.spec.cjs
add K11 $H "the line that was in flight is not re-sent" "if(dailyPendingMe && dailyPendingMe.t){   // the learner's line was in flight" "if(false){   // the learner's line was in flight" "B3" lock.spec.cjs
add K12 $H "Finish after a quiet reconnect spins for 20 s" 'if(currentMode === "daily" && $("srBody") && $("srBody").querySelector(".spin")){ try{ renderSessionResult(null); }catch(_){} }' '' "C1" lock.spec.cjs
add K13 $H "a tap on a dead socket does nothing" 're:(else startDailyListen\(\); return; \}\n)  dailyRevive\(\);' '\1' "B2" lock.spec.cjs
add K15 $H "the opening greeting is spoken to a locked phone" 'if(document.hidden){ dailyOrb("idle"); dState(lgt("dTap")); dMic(true); return; }   // a locked phone: shown, not spoken' '' "A5b" lock.spec.cjs
add K16 $H "a dropped connection leaves the mic dead" '  dMic(true); dState(lgt("dDropped"));' '' "B2" lock.spec.cjs

# ---- client, the other chats (lock2.spec.cjs)
add N1  $H "a lock does not stop the Face-to-Face recogniser" '      try{ stopListening(); }catch(_){}                                             // the conversation recogniser (its onend is removed, so it does not restart itself)' '' "T1,T2" $L2
add N2  $H "a reply that lands on a locked phone is spoken (speak is not hidden-aware)" '  if(document.hidden){ aiSpeaking = false; return; }   // a locked phone: the line is on screen, it is not spoken (VP.resume() hands the mic back)' '' "T3,T4,H1" $L2
add N3  $H "the mic is started on a hidden page" 'if(!SR || !running || document.hidden) return;   // a locked phone cannot listen (every caller - the reply loop, the Home chat'"'"'s timer - is covered here)' 'if(!SR || !running) return;' "T2,H8" $L2
add N4  $H "the screen is not restored after the unlock (the Face-to-Face mic stays dead)" '  orb("listening", lgt("orbListen"), lgt("orbListenHint"));
  stopListening(); delayedListen();' '  orb("listening", lgt("orbListen"), lgt("orbListenHint"));' "T1,T3,I1" $L2
add N5  $H "the quiet-reconnect flag is not sent (session chats)" 'reconnect:true, resume:sessReplay(),' 'resume:sessReplay(),' "T5,I2,H3" $L2
add N6  $H "the unanswered line is replayed as history too" '  if(l.length && l[l.length - 1].role === "user") l.pop();   // a line still waiting for its answer is re-sent after the resume, not replayed as history' '' "T6" $L2
add N7  $H "the line that was in flight is not re-sent (session chats)" '  if(pend){   // the learner'"'"'s line was in flight when the connection died: it is answered now (once)' '  if(false){   // the learner'"'"'s line was in flight when the connection died: it is answered now (once)' "T6,H5" $L2
add N8  $H "a quiet reconnect is counted as a new session (session chats)" '  sessReviving = true; sessNeedsTap = false; sessThen = then || (sessEnding ? "end" : "");' '  sessReviving = true; sessNeedsTap = false; sessThen = then || (sessEnding ? "end" : ""); usageInc();' "T5,H3" $L2
add N9  $H "End on a dead connection does nothing" '  if(sessFrame && (!ws || ws.readyState > 1)){ if(!document.hidden) sessRevive("end"); return; }   // no connection (a long lock took it): reconnect quietly, then finish (hidden: on return - VP.resume())' '' "T10,I3" $L2
add N10 $H "a lock closes the socket again (session chats)" '      aiSpeaking = false;
      try{ FACE.stopTalking(); Assistant.stopTalking(); }catch(_){}' '      aiSpeaking = false; try{ ws.close(); }catch(_){}
      try{ FACE.stopTalking(); Assistant.stopTalking(); }catch(_){}' "T1,H1" $L2
add N11 $H "the 10-minute grace timer never ends a session chat" 'if(!p || !owns() || !document.hidden) return;' 'return;' "T9" $L2
add N12 $H "DuSu wrapping up the interview is not remembered (a lost connection leaves the interview unfinished)" 'case "interview_done": sessEnding = true; addSys(' 'case "interview_done": addSys(' "I4" $L2
add N13 $H "a Home greeting cut short by the lock leaves the mic closed" '    if(!greetDone){ greetDone = true; aiSpeaking = false; }      // the lock cut her opening short; the words are on screen' '' "H2" $L2
add N14 $H "the Home line in flight is not re-sent (resend does not send)" '    try{ ws.send(JSON.stringify({ type:"user_text", text })); }catch(_){}
  }
  function voiceOn()' '  }
  function voiceOn()' "H5" $L2
add N15 $H "the Home chat is still ended by a lock" 'const SESS = new Set(["conversation", "interview", "practice", "home"]);' 'const SESS = new Set(["conversation", "interview", "practice"]);' "H1,H3" $L2
add N16 $H "no message when the connection cannot be re-opened" '  orb("idle", lgt("sDropped"), "");' '' "T12" $L2
add N17 $H "tapping DuSu does not retry" 'if($("orb")) $("orb").addEventListener("click", () => { if(sessNeedsTap && currentScreen() === "session") sessRevive(); });' '' "T12" $L2
add N18 $H "typing on a dead Home connection is refused instead of reconnecting" '      if(sessFrame && currentScreen() === "session"){ renderActs([]); addMsg(text, "user"); toLatest(); if(!sessReviving) sessRevive(); return true; }' '' "H4" $L2
add N19 $H "the reconnected chat does not restore the mic" '  if(currentMode === "home"){ try{ HM.resume(true); }catch(_){} return; }
  sessRestoreUI();
}' '  if(currentMode === "home"){ try{ HM.resume(true); }catch(_){} return; }
}' "T5,T6,I2" $L2
add N20 $H "an interview is ended by a lock" 'const SESS = new Set(["conversation", "interview", "practice", "home"]);' 'const SESS = new Set(["conversation", "practice", "home"]);' "I1,I2" $L2
add N21 $H "a lock that killed the connection is never noticed on return" '    if(!ok){ sessRevive(sessEnding ? "end" : ""); return; }' '    if(!ok){ return; }' "T5,T7,I2" $L2
add N22 $H "a practice conversation is ended by a lock" 'const SESS = new Set(["conversation", "interview", "practice", "home"]);' 'const SESS = new Set(["conversation", "interview", "home"]);' "P1,P2" $L2
add N23 $H "the Home chat typed in text mode switches its mic on after a lock" '  running = currentMode === "home" ? !!(window.HM && HM.voiceOn()) : true;' '  running = true;' "H6,H3" $L2
add N24 $H "a long lock never asks the socket if it is alive (session chats)" 'if(away < LONG_MS) return Promise.resolve(true);' 'return Promise.resolve(true);' "T7" $L2
add N25 $H "a Home line typed before DuSu was ready is lost after a reconnect" '    if(pendingText && wsReady){ const x = pendingText; pendingText = ""; submit(x); return; }' '' "H7" $L2
add N26 $H "the reconnect reuses the first socket's Grammar Coach reference" '    if(sessFrame.gref && window.GC && GC.enabled()) f.gref = GC.newRef();   // each socket has its own Grammar Coach reference (the first one already analysed its part)' '' "T13" $L2

add N27 $H "a long lock while the server is busy declares the socket dead after 3 s (session chats)" 'const t = setTimeout(() => fin(false), busy() ? BUSY_MS : PONG_MS);' 'const t = setTimeout(() => fin(false), PONG_MS);' "T16" $L2
add N28 $H "a fresh opener after a reconnect leaves the mic dead" '    if(m.type === "ai_text" || m.type === "home_ready"){ running = currentMode === "home" ? !!(window.HM && HM.voiceOn()) : true; sessThen = ""; sessEnding = false; }' '    if(m.type === "ai_text" || m.type === "home_ready"){ sessThen = ""; sessEnding = false; }' "T14" $L2
add N29 $H "a Home line typed during the reconnect is sent twice" '    if(sessReviving){ renderActs([]); addMsg(text, "user"); toLatest(); return true; }   // a quiet reconnect is under way: the line waits on screen and sessResumed sends it (once) when the chat is back' '' "H9" $L2
add N30 $H "End tapped during the reconnect runs ahead of the resume" '  if(sessReviving){ sessThen = "end"; return; }   // a quiet reconnect is under way: the End is sent the moment the chat is back' '' "T15" $L2
add N31 $H "a Hindi / English switch is lost on reconnect" '    if("lang" in sessFrame) f.lang = LG.lang(sessFrame.mode);   // a Hindi / English switch made since the chat opened' '' "H10" $L2
add N32 $H "a failed scoring leaves End pending for the next reconnect" 'case "practice_error": sessEnding = false; try{' 'case "practice_error": try{' "P1,P2" $L2
add N33 $H "a forced End while hidden reconnects in the background" 'if(!document.hidden) sessRevive("end"); return; }   // no connection' 'sessRevive("end"); return; }   // no connection' "T17" $L2
add K17 $H "a long lock while the server is busy declares the socket dead after 3 s (Daily)" 'const t = setTimeout(() => fin(false), busy() ? BUSY_MS : PONG_MS);' 'const t = setTimeout(() => fin(false), PONG_MS);' "B7" lock.spec.cjs
add S19 $M "a huge elapsed crashes the resume" 'except (TypeError, ValueError, OverflowError):      # a huge JSON integer overflows float()' 'except (TypeError, ValueError):' "" $SS
add N34 $H "the time the phone was locked counts as practice time" 'Math.round((Date.now() - sessT0 - sessAway) / 1000)' 'Math.round((Date.now() - sessT0) / 1000)' "P3" $L2

plant() {   # plant FILE OLD NEW into $OUT/backend  -> 0 ok, 7 does not apply
  python3 - "$OUT/backend/$1" "$2" "$3" <<'PY'
import re, sys
p, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p, encoding="utf-8").read()
if old.startswith("re:"):
    t, n = re.subn(old[3:], new, s, count=1)
    if n != 1:
        print("MUTANT DOES NOT APPLY (the code changed): ", old[:70]); sys.exit(7)
    open(p, "w", encoding="utf-8").write(t)
else:
    if old not in s:
        print("MUTANT DOES NOT APPLY (the code changed): ", old[:70]); sys.exit(7)
    open(p, "w", encoding="utf-8").write(s.replace(old, new, 1))
PY
}
fresh_copy() { rm -rf "$OUT/backend"; mkdir -p "$OUT/backend"; tar -C backend --exclude=.venv --exclude=__pycache__ --exclude='.env*' -cf - . | tar -C "$OUT/backend" -xf -; }

# the newest first (the session chats), then the Daily / Learn set
ALL=(S7 S8 S9 S10 S11 S12 S13 S14 S15 S16 S17 S18 S19 K9 K17
     N1 N2 N3 N4 N5 N6 N7 N8 N9 N10 N11 N12 N13 N14 N15 N16 N17 N18 N19 N20 N21 N22 N23 N24 N25 N26 N27 N28 N29 N30 N31 N32 N33 N34
     S1 S2 S3 S4 S5 S6 K1 K2 K3 K4 K5 K6 K7 K8 K10 K11 K12 K13 K15 K16)
WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=("${ALL[@]}")
caught=0; survived=()
for m in "${WANT[@]}"; do
  fresh_copy
  plant "${FILE[$m]}" "${OLD[$m]}" "${NEW[$m]}"; rc=$?
  [ $rc -eq 7 ] && { echo "$m  NOT APPLIED  (${DESC[$m]})"; survived+=("$m(not applied)"); continue; }
  if [[ $m == S* ]]; then
    if DV_BACKEND="$PWD/$OUT/backend" tests/daily_voice/run.sh "${RUNNER[$m]}" > "$OUT/$m.log" 2>&1; then
      echo "$m  SURVIVED   (${DESC[$m]})  <- no check noticed"; survived+=("$m")
    else echo "$m  caught     (${DESC[$m]})  -> $(grep -c '  FAIL\|Traceback' "$OUT/$m.log") failing checks / errors"; caught=$((caught+1)); fi
  else
    if ONLY="${SPECS[$m]}" DV_BACKEND="$PWD/$OUT/backend" tests/daily_voice/browser/run_real.sh "${RUNNER[$m]}" > "$OUT/$m.log" 2>&1; then
      echo "$m  SURVIVED   (${DESC[$m]})  <- the scenarios ${SPECS[$m]} did not notice"; survived+=("$m")
    else echo "$m  caught     (${DESC[$m]})  -> $(grep -c '  FAIL' "$OUT/$m.log") failing checks"; caught=$((caught+1)); fi
  fi
done
echo; echo "daily-voice mutants: ${caught} caught, ${#survived[@]} survived: ${survived[*]:-none}"
