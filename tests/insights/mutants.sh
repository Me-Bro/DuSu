#!/usr/bin/env bash
# Insights - "do the tests catch a planted bug?"  Copies the backend, plants ONE deliberate bug in the insights code (or the cache-validator / Ranks / delete code in main.py / db.py), runs the
# unit tier, then the scratch-Postgres tier, then the WebSocket tier against the copy, stopping at the first one that FAILS (= the bug was caught). A mutant that survives
# all three means a check is too weak. Never touches backend/ itself.
#   tests/insights/mutants.sh            all mutants
#   tests/insights/mutants.sh M3 M5      only these
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT="tests/insights/.mutants"; mkdir -p "$OUT"
declare -A FILE DESC OLD NEW
add() { FILE[$1]="$2"; DESC[$1]="$3"; OLD[$1]="$4"; NEW[$1]="$5"; }

SVC=app/insights/service.py; API=app/insights/api.py; MAIN=app/main.py; KAPI=app/keys/api.py
add M1  $SVC "a milestone name outside the allow-list is accepted by the service" 'if not (uid and db.db_enabled) or name not in MILESTONES:
        return False
    k = (uid, name)' 'if not (uid and db.db_enabled):
        return False
    k = (uid, name)'
add M2  $SVC "no in-memory memory of a milestone (every call hits the database)" '    if k in _seen:
        return False
    try:' '    if False:
        return False
    try:'
add M3  $SVC "no in-memory memory of the active day" 'if not (uid and db.db_enabled) or not day or _day_seen.get(uid) == day:' 'if not (uid and db.db_enabled) or not day:'
add M4  $SVC "a repeated milestone overwrites the FIRST time" 'on_conflict_do_nothing(index_elements=["user_id", "name"]))
            await s.commit()
        fresh = bool(r.rowcount)' 'on_conflict_do_update(index_elements=["user_id", "name"], set_={"first_at": db._now()}))
            await s.commit()
        fresh = bool(r.rowcount)'
add M5  $SVC "a tap with no price opinion erases the earlier opinion" '        if feel:
            upd["price_feel"] = feel' '        upd["price_feel"] = feel'
add M6  $SVC "any string is a plan" '    p = v.strip().lower()
    return p if p in PLANS else None' '    p = v.strip().lower()
    return p or None'
add M7  $SVC "the funnel cohort ignores when tracking began" 'cohort_from = max(window_start, tracking_since) if tracking_since else window_start' 'cohort_from = window_start'
add M8  $SVC "Day-1 return counts ANY later day, not day 1" "AND d.day = to_char((u.created_at AT TIME ZONE 'Asia/Kolkata')::date + CAST(:n AS integer), 'YYYY-MM-DD'))) AS returned" "AND d.day > to_char((u.created_at AT TIME ZONE 'Asia/Kolkata')::date, 'YYYY-MM-DD'))) AS returned"
add M9  $SVC "deleting an account forgets the plan reservations" '    for M in (EvMilestone, EvDay, PlanInterest):
        await s.execute(delete(M).where(M.user_id.in_(uids)))' '    for M in (EvMilestone, EvDay):
        await s.execute(delete(M).where(M.user_id.in_(uids)))'
add M10 $SVC "deleting an account leaves the in-memory memory of it" '    for u in uids:
        _day_seen.pop(u, None)
        for n in MILESTONES:
            _seen.discard((u, n))' '    for u in uids:
        pass'
add M11 $API "POST /ev accepts the server-only milestones too" 'name in svc.CLIENT_EVENTS and _rate' 'name in svc.MILESTONES and _rate'
add M12 $API "POST /ev needs no login" '    _c, uid = _who(authorization, str(body.get("token", "")))
    name = str(body.get("name") or "")' '    try:
        _c, uid = _who(authorization, str(body.get("token", "")))
    except HTTPException:
        return Response(status_code=204)
    name = str(body.get("name") or "")'
add M13 $API "POST /ev has no rate limit" 'and _rate(uid, "ev", 30, 60.0) and' 'and'
add M14 $API "a reservation can be redirected to another learner by a body field" '    claims, uid = await _plan_gate(authorization, str(body.get("token", "")))
    plan = svc.clean_plan(body.get("plan"))' '    claims, uid = await _plan_gate(authorization, str(body.get("token", "")))
    uid = str(body.get("user_id") or uid)
    plan = svc.clean_plan(body.get("plan"))'
add M15 $SVC "GET /plans/interest returns everybody's reservations" 'select(PlanInterest).where(PlanInterest.user_id == uid).order_by(PlanInterest.created_at)' 'select(PlanInterest).order_by(PlanInterest.created_at)'
add M16 $API "a blocked account can still reserve" '        if (await db.get_user_flags(uid)).get("status") == "blocked":
            raise HTTPException(403, "Your access has been paused. Please contact the admin.")
    except HTTPException:' '        if False:
            raise HTTPException(403, "Your access has been paused. Please contact the admin.")
    except HTTPException:'
add M17 $MAIN "GET /me no longer records the active day" '    _ev_day(uid)                              # insights: this learner opened the app today (Day-1 / Day-7 return is a join on it)
' ''
add M18 $MAIN "a blank spoken line counts as the first sentence" '                text = (data.get("text") or "").strip()
                if not text:
                    continue
                _ev(uid, "first_sentence")' '                text = (data.get("text") or "").strip()
                _ev(uid, "first_sentence")
                if not text:
                    continue
                _ev(uid, "first_sentence")'
add M19 $MAIN "a session with no turn still counts as a first session" '        if session.turns <= 0:
            return
        _ev(uid, "first_session")' '        _ev(uid, "first_session")
        if session.turns <= 0:
            return'
add M20 $MAIN "one stored key already counts as the second key" '    if n >= 2:
        _ev(uid, "key2_saved")' '    if n >= 1:
        _ev(uid, "key2_saved")'
add M21 $MAIN "a weak ETag (the page's own tag, or what a compressing proxy sends) never matches" '    return bool(want) and any(t.strip().removeprefix("W/") == want for t in h.split(","))' '    return bool(want) and any(t.strip() == want for t in h.split(","))'
add M22 $MAIN "the built page is never refreshed after the file changes" '    if _INDEX["key"] != key:' '    if _INDEX["key"] is None:'
add M23 $MAIN "every asset is declared immutable" '        if resp.status_code == 200 and _VERSIONED.search(path):' '        if resp.status_code == 200:'
add M24 $MAIN "a 304 forgets the validators" '        return Response(status_code=304, headers=headers)' '        return Response(status_code=304)'
add M25 $API "POST /ev ignores the kill switch" ' and await M.insights_on():
        await svc.milestone(uid, name)
    return Response(status_code=204)' ':
        await svc.milestone(uid, name)
    return Response(status_code=204)'
add M26 $MAIN "the owner funnel is open to any signed-in learner" '    _require_owner(token, authorization)
    if not db.db_enabled:
        raise HTTPException(400, "Database required")
    try:
        return await insights.funnel(days)' '    if not db.db_enabled:
        raise HTTPException(400, "Database required")
    try:
        return await insights.funnel(days)'
add M27 $KAPI "saving a key through /keys/save records no milestone" '    await M._ev_keys(uid)                                    # insights: first / second key saved (a milestone is written once)
' ''
add M28 $SVC "the funnel counts D1 against everyone, not only those whose day 1 has passed" "AND (u.created_at AT TIME ZONE 'Asia/Kolkata')::date + CAST(:n AS integer) < (now() AT TIME ZONE 'Asia/Kolkata')::date" "AND true"

add M29 $MAIN "a deep link (the SPA fallback) is served without validators, so re-opening it re-downloads the page" '        raise HTTPException(404, "Not found")
    return _page(request)' '        raise HTTPException(404, "Not found")
    return _page(None)'
add M30 $MAIN "a signed-out visit to /leaderboard is served without validators" '        if _wants_html(request):
            return _page(request)
        raise HTTPException(401, "Not signed in")
    if not db.db_enabled:
        return {"top": [], "you": None}' '        if _wants_html(request):
            return _page(None)
        raise HTTPException(401, "Not signed in")
    if not db.db_enabled:
        return {"top": [], "you": None}'

DBF=app/db.py
add M31 $DBF "Ranks lists accounts with no XP again (audit UI-12)" '            .where(Progress.xp > 0)                           # a board of people who have earned something (audit UI-12): accounts with no XP are not "ranked"
' ''
add M32 $DBF "deleting an account (db.delete_user) forgets the insights rows" '        from .insights import service as _ev
        await _ev.delete_rows(s, [user_id])
        for tbl in (Conversation, Memory, Progress, Profile, UserKey, Feedback, UsageDaily,
                    SessionScore, WeeklyStat, SeasonAward, PracticeAttempt):
            await s.execute(delete(tbl).where(tbl.user_id == user_id))
        u = await s.get(User, user_id)' '        for tbl in (Conversation, Memory, Progress, Profile, UserKey, Feedback, UsageDaily,
                    SessionScore, WeeklyStat, SeasonAward, PracticeAttempt):
            await s.execute(delete(tbl).where(tbl.user_id == user_id))
        u = await s.get(User, user_id)'

add M33 $DBF "yesterday's sessions are still shown as today's" '    if last != today:
        sessions = 0
        if last != today - dt.timedelta(days=1):
            streak = 0
    return streak, sessions' '    if last != today:
        if last != today - dt.timedelta(days=1):
            streak = 0
    return streak, sessions'
add M34 $DBF "a streak that died a week ago stays alive" '    if last != today:
        sessions = 0
        if last != today - dt.timedelta(days=1):
            streak = 0
    return streak, sessions' '    if last != today:
        sessions = 0
    return streak, sessions'
add M35 $DBF "the app day is the UTC day, not the IST day" '    today = _ist_now().date()
    last = prog.last_active
    if last != today:
        sessions = 0' '    today = dt.datetime.now(dt.timezone.utc).date()
    last = prog.last_active
    if last != today:
        sessions = 0'
add M36 $DBF "/me shows the stored counters, not today's" '"xp": prog.xp, "coins": prog.coins, "streak_days": streak_now,
            "sessions_today": sessions_now, "daily_goal": prog.daily_goal,' '"xp": prog.xp, "coins": prog.coins, "streak_days": prog.streak_days,
            "sessions_today": prog.sessions_today, "daily_goal": prog.daily_goal,'
add M37 $DBF "the Home streak chip reads the stored streak" '"streak": _live_counters(prog)[0],' '"streak": streak,'
add M38 $DBF "the owner dashboard shows the stored counters" '"streak_days": _live_counters(prog)[0],
                "sessions_today": _live_counters(prog)[1],' '"streak_days": (prog.streak_days if prog else 0) or 0,
                "sessions_today": (prog.sessions_today if prog else 0) or 0,'

add M39 $MAIN "the page's ETag is STRONG again (Cloudflare drops it: no browser ever holds it, repeat opens are never a 304)" '        _INDEX.update(key=key, html=html, etag='"'"'W/"'"'"' + hashlib' '        _INDEX.update(key=key, html=html, etag='"'"'"'"'"' + hashlib'
add M40 $MAIN "the self-hosted font and the WebP logo are served as text/plain again (no content type registered)" 'mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/webp", ".webp")' 'pass'
add M41 $MAIN "a weak validator is compared against the server's tag WITH its W/ prefix (the page's own weak tag never matches its own copy)" '    want = (etag or "").strip().removeprefix("W/")' '    want = (etag or "").strip()'

add M42 test_client.html "an email address is written into the page markup again (Cloudflare rewrites it, injects a blocking script and drops the ETag)" '<a id="helpMail" style="color:var(--ink-faint)"></a>' '<a id="helpMail" href="mailto:support@ranabrothers.online" style="color:var(--ink-faint)">support@ranabrothers.online</a>'

WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=(M1 M2 M3 M4 M5 M6 M7 M8 M9 M10 M11 M12 M13 M14 M15 M16 M17 M18 M19 M20 M21 M22 M23 M24 M25 M26 M27 M28 M29 M30 M31 M32 M33 M34 M35 M36 M37 M38 M39 M40 M41 M42)
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
  # unit (pure, fast) -> scratch Postgres -> real WebSocket; the first failing tier means "caught"
  rm -f "$OUT/$m.log"
  tier=""
  for t in unit.py selftest.py ws_selftest.py; do
    if INS_BACKEND="$PWD/$OUT/backend" tests/insights/run.sh $t >> "$OUT/$m.log" 2>&1; then :; else tier="$t"; break; fi
  done
  if [ -z "$tier" ]; then
    echo "$m  SURVIVED   (${DESC[$m]})  <- the suite did not notice"; survived+=("$m")
  else
    echo "$m  caught by $tier  (${DESC[$m]})  -> $(grep -c '  FAIL\|Traceback' "$OUT/$m.log") failing checks / errors"; caught=$((caught+1))
  fi
done
echo; echo "caught $caught of ${#WANT[@]}; survivors: ${survived[*]:-none}"
