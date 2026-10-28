#!/usr/bin/env bash
# Daily Talk / Learn vs a locked screen - "do the tests catch a planted bug?"  Copies the backend, plants ONE deliberate bug, runs the tier that should notice it against the copy and
# reports whether it FAILED (= the bug was caught). A mutant that survives means a check is too weak. Never touches backend/ itself.
#   tests/daily_voice/mutants.sh            all server mutants (S1-S6, ~1 min each) and all client mutants (K1-K16, ~1-2 min each)
#   tests/daily_voice/mutants.sh S2 K5      only these
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT="tests/daily_voice/.mutants"; mkdir -p "$OUT"
declare -A FILE DESC OLD NEW SPECS
add() { FILE[$1]="$2"; DESC[$1]="$3"; OLD[$1]="$4"; NEW[$1]="$5"; SPECS[$1]="${6:-}"; }   # SPECS = the scenarios (ONLY=) that should catch a client mutant
M=app/main.py; H=test_client.html

# ---- server (ws_selftest.py)
add S1  $M "ping is ignored" 'elif mtype == "ping":' 'elif mtype == "ping_disabled":'
add S2  $M "the reconnect flag is ignored (always a greeting)" 'if data.get("reconnect") is True and session.transcript:' 'if False and session.transcript:'
add S3  $M "a quiet resume still counts the replayed turns" '                        session.turns = 0
                        await _send(ws, type="daily_resumed"' '                        await _send(ws, type="daily_resumed"'
add S4  $M "any truthy reconnect value is honoured" 'if data.get("reconnect") is True and session.transcript:' 'if data.get("reconnect") and session.transcript:'
add S5  $M "a quiet resume still makes the opening model call" 'await _send(ws, type="daily_resumed", lang=session.lang)' 'await session.daily_turn("", first=True); await _send(ws, type="daily_resumed", lang=session.lang)'
add S6  $M "a reconnect with nothing to resume is not a plain start" 'if data.get("reconnect") is True and session.transcript:' 'if data.get("reconnect") is True:'

# ---- client (lock.spec.cjs, only the scenarios that should notice)
add K1  $H "the screen is not restored after the unlock (the mic stays dead)" 'running = true; dailyRestoreUI();' 'running = true;' "A2,A3,A4,A5"
add K2  $H "a lock closes the socket again (the old behaviour)" '// an in-flight reply chain stops here and never starts its next line' '// an in-flight reply chain stops here and never starts its next line
    try{ ws.close(); }catch(_){}' "A1"
add K3  $H "a reply that lands on a locked phone is spoken" 'if(document.hidden){ dailyOrb("idle"); dState(lgt("dReplyReady")); return; }   // a locked phone: shown, not spoken' '' "A4"
add K4  $H "a quiet reconnect is counted as a new session" '    if(!quiet){ usageInc(); refreshUsage();' '    if(true){ usageInc(); refreshUsage();' "B1"
add K5  $H "the quiet-reconnect flag is not sent" 'reconnect: quiet && dailyTurns.length ? true : undefined' 'reconnect: undefined' "B1"
add K6  $H "the 10-minute grace timer never ends the session" 'if(!p || !owns() || !document.hidden) return;' 'return;' "B6"
add K7  $H "the quota case still leaves the mic dead (running is not forced)" 'if(ws && ws.readyState === 1){ running = true; if(fromReply) dailyContinue(); else startDailyListen(); return; }' 'if(ws && ws.readyState === 1){ if(fromReply) dailyContinue(); else startDailyListen(); return; }' "D1"
add K8  $H "the lock does not stop the reply chain" 're:(function pause\(\)\{\n    if\(!p\) p = \{[^\n]*\n)    speakEpoch\+\+;[^\n]*\n' '\1' "A3"
add K9  $H "a long lock never asks the socket if it is alive" 'if(away < LONG_MS) return Promise.resolve(true);' 'return Promise.resolve(true);' "B4"
add K10 $H "Learn greets again after a quiet reconnect" 'if(learnQuiet){ learnResumed(); return; }   // a quiet reconnect: no greeting' '' "E2"
add K11 $H "the line that was in flight is not re-sent" "if(dailyPendingMe && dailyPendingMe.t){   // the learner's line was in flight" "if(false){   // the learner's line was in flight" "B3"
add K12 $H "Finish after a quiet reconnect spins for 20 s" 'if(currentMode === "daily" && $("srBody") && $("srBody").querySelector(".spin")){ try{ renderSessionResult(null); }catch(_){} }' '' "C1"
add K13 $H "a tap on a dead socket does nothing" 're:(else startDailyListen\(\); return; \}\n)  dailyRevive\(\);' '\1' "B2"
add K14 $H "Face-to-Face is paused instead of ended on lock" 'return (sc === "daily" && currentMode === "daily") || (sc === "learning" && currentMode === "learning");' 'return (sc === "daily" && currentMode === "daily") || (sc === "learning" && currentMode === "learning") || sc === "session";' "F1"
add K15 $H "the opening greeting is spoken to a locked phone" 'if(document.hidden){ dailyOrb("idle"); dState(lgt("dTap")); dMic(true); return; }   // a locked phone: shown, not spoken' '' "A5b"
add K16 $H "a dropped connection leaves the mic dead" '  dMic(true); dState(lgt("dDropped"));' '' "B2"

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

WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=(S1 S2 S3 S4 S5 S6 K1 K2 K3 K4 K5 K6 K7 K8 K9 K10 K11 K12 K13 K14 K15 K16)
caught=0; survived=()
for m in "${WANT[@]}"; do
  fresh_copy
  plant "${FILE[$m]}" "${OLD[$m]}" "${NEW[$m]}"; rc=$?
  [ $rc -eq 7 ] && { echo "$m  NOT APPLIED  (${DESC[$m]})"; survived+=("$m(not applied)"); continue; }
  if [[ $m == S* ]]; then
    if DV_BACKEND="$PWD/$OUT/backend" tests/daily_voice/run.sh ws_selftest.py > "$OUT/$m.log" 2>&1; then
      echo "$m  SURVIVED   (${DESC[$m]})  <- no check noticed"; survived+=("$m")
    else echo "$m  caught     (${DESC[$m]})  -> $(grep -c '  FAIL\|Traceback' "$OUT/$m.log") failing checks / errors"; caught=$((caught+1)); fi
  else
    if ONLY="${SPECS[$m]}" DV_BACKEND="$PWD/$OUT/backend" tests/daily_voice/browser/run_real.sh lock.spec.cjs > "$OUT/$m.log" 2>&1; then
      echo "$m  SURVIVED   (${DESC[$m]})  <- the scenarios ${SPECS[$m]} did not notice"; survived+=("$m")
    else echo "$m  caught     (${DESC[$m]})  -> $(grep -c '  FAIL' "$OUT/$m.log") failing checks"; caught=$((caught+1)); fi
  fi
done
echo; echo "daily-voice mutants: ${caught} caught, ${#survived[@]} survived: ${survived[*]:-none}"
