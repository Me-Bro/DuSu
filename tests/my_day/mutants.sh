#!/usr/bin/env bash
# My Day - "do the tests catch a planted bug?"  Copies the backend, plants ONE deliberate bug in the repeating-reminder code, runs the suite against the copy
# and reports whether it FAILED (= the bug was caught). A mutant that survives means a check is too weak. Never touches backend/ itself.
#   tests/my_day/mutants.sh            all mutants
#   tests/my_day/mutants.sh M3 M5      only these
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT="tests/my_day/.mutants"; mkdir -p "$OUT"
declare -A FILE DESC OLD NEW
add() { FILE[$1]="$2"; DESC[$1]="$3"; OLD[$1]="$4"; NEW[$1]="$5"; }

SVC=app/planner/service.py; SCH=app/planner/scheduler.py; RUL=app/planner/rules.py; LL=app/planner/life_lines.py
add M1 $SVC "materializer ignores the chosen weekdays"            'if not rules.days_scheduled(rule.days, d):
            continue
        fire = tu.to_utc(d, t, p.tz)' 'if False:
            continue
        fire = tu.to_utc(d, t, p.tz)'
add M2 $SCH "send-time check ignores a changed time"               'or not rules.days_scheduled(rule.days, day) or meta.get("time") != rule.time):' 'or not rules.days_scheduled(rule.days, day)):'
add M3 $SVC "delete leaves the rings behind"                       '        await _cancel_rule_occurrences(s, uid, rule.id, OPEN_REMINDER)
        await s.delete(rule)' '        await s.delete(rule)'
add M4 $SVC "one ring can be deleted on its own"                   'if r is None or r.kind in ("test", "recurring"):                   # a repeating' 'if r is None or r.kind in ("test",):                   # a repeating'
add M5 $SVC "materializer makes rings that already passed"         '        if fire < floor:
            continue
        key = _rule_key(rule.id, d, t)' '        key = _rule_key(rule.id, d, t)'
add M6 $SVC "pause does not withdraw the waiting rings"            '            await _cancel_rule_occurrences(s, uid, rule.id)
            await s.flush()
            if rule.status == "active":' '            await s.flush()
            if rule.status == "active":'
add M7 $SVC "no duplicate guard on create"                         'ex = next((r for r in mine if key and r.client_key == key), None) or next(
            (r for r in mine if r.title.lower() == title.lower() and r.time == hhmm and r.days == days), None)' 'ex = next((r for r in mine if key and r.client_key == key), None)'
add M8 $SVC "rule lookup ignores the owner (an IDOR)"              'q = select(PlReminderRule).where(PlReminderRule.id == rid, PlReminderRule.user_id == uid)' 'q = select(PlReminderRule).where(PlReminderRule.id == rid)'
add M9 $SVC "the materializer ignores 'pause everything'"          '    if rule.status != "active" or p.paused_all:
        return 0
    t = tu.parse_hhmm(rule.time)' '    if rule.status != "active":
        return 0
    t = tu.parse_hhmm(rule.time)'
add M10 $SVC "delete_rows forgets the rules table"                 'for M in (PlEvent, PlReminder, PlReminderRule, PlHabitLog,' 'for M in (PlEvent, PlReminder, PlHabitLog,'
add M11 $SVC "an edit does not re-plan the rings"                  '            await _cancel_rule_occurrences(s, uid, rule.id)
            await s.flush()
            if rule.status == "active":
                await _materialize_rule(s, rule, p)
            _ev(s, uid, "rule", rule.id, "paused"' '            _ev(s, uid, "rule", rule.id, "paused"'
add M12 $SVC "Today forgets the repeating rules"                   '"reminders_done": reminders_done, "repeating": repeating,' '"reminders_done": reminders_done, "repeating": [],'
add M13 $LL  "DuSu is told 'none set' although rules exist"        '    elif any(isinstance(x, dict) and x.get("status") == "active" for x in (t.get("repeating") or [])):' '    elif False:'
add M14 $RUL "next_rule_fire counts today's passed time"           '        if fire >= now:
            return fire
    return None' '        return fire
    return None'
add M15 $SVC "the materializer is not locked against an edit"      '                           .order_by(PlReminderRule.id).with_for_update())).scalars().all()' '                           .order_by(PlReminderRule.id))).scalars().all()'
add M16 $SVC "EQUIVALENT BY DESIGN: key lookup removed (the unique index on (user_id, client_key) still answers a retry)" 'ex = next((r for r in mine if key and r.client_key == key), None) or next(' 'ex = next((r for r in mine if False), None) or next('
add M17 $SCH "send-time check ignores a paused rule"               'or rule.status != "active" or day is None' 'or day is None'

WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=(M1 M2 M3 M4 M5 M6 M7 M8 M9 M10 M11 M12 M13 M14 M15 M17)      # M16 is an equivalent mutant (kept as documentation): name it to run it
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
  if MD_BACKEND="$PWD/$OUT/backend" tests/my_day/run.sh selftest.py > "$OUT/$m.log" 2>&1; then
    echo "$m  SURVIVED   (${DESC[$m]})  <- the suite did not notice"; survived+=("$m")
  else
    echo "$m  caught     (${DESC[$m]})  -> $(grep -c '  FAIL' "$OUT/$m.log") failing checks"; caught=$((caught+1))
  fi
done
echo; echo "caught $caught of ${#WANT[@]}; survivors: ${survived[*]:-none}"
