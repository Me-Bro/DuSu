#!/usr/bin/env bash
# Notifications - "do the tests catch a planted bug?"  Copies the backend, plants ONE deliberate bug in the notification code, runs the unit tier and then the
# scratch-Postgres tier against the copy and reports whether either FAILED (= the bug was caught). A mutant that survives means a check is too weak.
# Never touches backend/ itself.
#   tests/notify/mutants.sh            all mutants
#   tests/notify/mutants.sh M3 M5      only these
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT="tests/notify/.mutants"; mkdir -p "$OUT"
declare -A FILE DESC OLD NEW
add() { FILE[$1]="$2"; DESC[$1]="$3"; OLD[$1]="$4"; NEW[$1]="$5"; }

RUL=app/notify/rules.py; SVC=app/notify/service.py; API=app/notify/api.py; TOK=app/notify/tokens.py
add M1  $RUL "a live streak never beats the generic practice nudge" '        return "streak"
    return "practice" if kinds.get("practice", True) else None' '        return "practice"
    return "practice" if kinds.get("practice", True) else None'
add M2  $RUL "the send-time check ignores that they already practised" '    if snap.get("last_active") == today:
        return False, "done"' '    if False:
        return False, "done"'
add M3  $RUL "the ignore-three back-off is never applied" '    if len(recent) < IGNORED_LIMIT:
        return False
    active_days' '    if True:
        return False
    active_days'
add M4  $RUL "a nudge may go out hours late (the window and the stale rule are huge)" 'LATE_GRACE_MIN = 90' 'LATE_GRACE_MIN = 90000'
add M5  $SVC "the tap beacon ignores whose notification it is (an IDOR)" 'NtOutbox.id == nid, NtOutbox.user_id == uid, NtOutbox.opened_at.is_(None)' 'NtOutbox.id == nid, NtOutbox.opened_at.is_(None)'
add M6  $SVC "delivery ignores the rollout switch" '        elif not await _truthy(enabled_fn(user.email)):
            out = _cancel(r, "switch_off")' '        elif False:
            out = _cancel(r, "switch_off")'
add M7  $RUL "the weekly note ignores the letter gap" '    return last_letter is None or (today - last_letter).days >= LETTER_GAP_DAYS' '    return True'
add M8  $RUL "quiet hours are ignored at send time" '        if qs and qe and tu.in_quiet(tu.local_now(tz, now).time(), qs, qe):
            return False, "quiet"' '        if False:
            return False, "quiet"'
add M9  $SVC "a blocked account is still planned for" '            if (status or "active") == "blocked":
                continue' '            if False:
                continue'
add M10 $SVC "lock-screen privacy is ignored" 'snap["name"], streak, snap["hide"], r.user_id, day)' 'snap["name"], streak, False, r.user_id, day)'
add M11 $SVC "preference updates are not validated" 'if not isinstance(body["kinds"], dict) or any(k not in rules.KINDS or not isinstance(v, bool) for k, v in body["kinds"].items()):
                raise Invalid("kinds")' 'if False:
                raise Invalid("kinds")'
add M12 $TOK "the receipt signature is not checked" '        if not hmac.compare_digest(_b64(hmac.new(_key(), body, hashlib.sha256).digest()[:16]), sig):
            return None' '        if False:
            return None'
add M13 $SVC "a dead subscription is never removed" '        if gone:
            await s.execute(delete(PlPushSub).where(PlPushSub.id.in_(gone)))' '        if False:
            await s.execute(delete(PlPushSub).where(PlPushSub.id.in_(gone)))'
add M14 $SVC "a failing push service is retried forever" '        if attempts < MAX_ATTEMPTS:                                # every send failed' '        if True:                                # every send failed'
add M15 $SVC "deleting an account forgets the preferences table" '    for M in (NtOutbox, NtPrefs):
        await s.execute(delete(M).where(M.user_id.in_(uids)))' '    for M in (NtOutbox,):
        await s.execute(delete(M).where(M.user_id.in_(uids)))'
add M16 $SVC "the test button has no rate limit" '        if recent:
            raise LimitReached("test")' '        if False:
            raise LimitReached("test")'
add M17 $API "the receipt endpoint has no rate limit" '    if len(hits) >= 60:' '    if len(hits) >= 600000:'
add M18 $SVC "a learner who switched notifications off is still planned for" '"enabled": True if enabled is None else bool(enabled), "tz": tz,' '"enabled": True, "tz": tz,'
add M19 $RUL "the weekly note goes out any day, not only Sunday" '    if tu.local_now(tz, now).weekday() == WEEKLY_WEEKDAY:' '    if True:'
add M20 $SVC "planning is not idempotent (no conflict handling)" '                                    .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"]).returning(NtOutbox.id))' '                                    .returning(NtOutbox.id))'
add M21 $SVC "the owner-stage switch is not consulted when planning" '            if (sl["daily"] is None and sl["weekly"] is None) or not await _truthy(enabled_fn(email)):' '            if (sl["daily"] is None and sl["weekly"] is None):'

WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=(M1 M2 M3 M4 M5 M6 M7 M8 M9 M10 M11 M12 M13 M14 M15 M16 M17 M18 M19 M20 M21)
caught=0; survived=()
for m in "${WANT[@]}"; do
  rm -rf "$OUT/backend"; mkdir -p "$OUT/backend"
  tar -C backend --exclude=.venv --exclude=__pycache__ --exclude='.env*' -cf - . | tar -C "$OUT/backend" -xf -
  python3 - "$OUT/backend/${FILE[$m]}" "${OLD[$m]}" "${NEW[$m]}" <<'PY'
import sys
p, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p).read()
if old not in s:
    print("MUTANT DOES NOT APPLY (the code changed): ", old[:60]); sys.exit(7)
open(p, "w").write(s.replace(old, new, 1))
PY
  [ $? -eq 7 ] && { echo "$m  NOT APPLIED  (${DESC[$m]})"; survived+=("$m(not applied)"); continue; }
  # the unit tier is pure and fast; the integration tier is the real judge
  if NT_BACKEND="$PWD/$OUT/backend" tests/notify/run.sh unit.py > "$OUT/$m.unit.log" 2>&1 && NT_BACKEND="$PWD/$OUT/backend" tests/notify/run.sh selftest.py > "$OUT/$m.log" 2>&1; then
    echo "$m  SURVIVED   (${DESC[$m]})  <- the suite did not notice"; survived+=("$m")
  else
    echo "$m  caught     (${DESC[$m]})  -> $(cat "$OUT/$m.unit.log" "$OUT/$m.log" 2>/dev/null | grep -c '  FAIL\|Traceback') failing checks / errors"; caught=$((caught+1))
  fi
done
echo; echo "caught $caught of ${#WANT[@]}; survivors: ${survived[*]:-none}"
