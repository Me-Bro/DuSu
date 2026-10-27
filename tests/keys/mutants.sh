#!/usr/bin/env bash
# Keys - "do the tests catch a planted bug?"  Copies the backend, plants ONE deliberate bug in the key engine, the key endpoints or the wiring, runs the tiers in order against
# the copy (unit, parity, the DB-backed tier, the WebSocket tier) and reports whether any of them FAILED (= the bug was caught). A mutant that survives means a check is too weak.
# Never touches backend/ itself.
#   tests/keys/mutants.sh            all server mutants (~25 s each when caught early, ~2 min when it survives every tier)
#   tests/keys/mutants.sh M3 M5      only these
#   tests/keys/mutants.sh --client   the client mutants (each runs a browser spec, ~4 minutes)
set -uo pipefail
cd "$(dirname "$0")/../.."
OUT="tests/keys/.mutants"; mkdir -p "$OUT"
declare -A FILE DESC OLD NEW TIER
add() { FILE[$1]="$2"; DESC[$1]="$3"; OLD[$1]="$4"; NEW[$1]="$5"; }

CLS=app/keys/classify.py; GATE=app/keys/gate.py; ERR=app/keys/errors.py; LED=app/keys/ledger.py; SVC=app/keys/service.py; API=app/keys/api.py
PRV=app/providers/openrouter_provider.py; MAIN=app/main.py; DB=app/db.py; NSV=app/notify/service.py

add M1  $CLS "a 401 is not read as a rejected key" '    if status == 401:
        return Outcome("invalid", http=401, expired="expired" in text)' '    if status == 401:
        return Outcome("bad_request", http=401)'
add M2  $CLS "a Gemini 400 'API key not valid' is not recognised" '        if any(w in text for w in _INVALID_WORDS):
            return Outcome("invalid", http=400, expired="expired" in text)' '        if False:
            return Outcome("invalid", http=400, expired="expired" in text)'
add M3  $CLS "a daily limit is not recognised as a daily limit" '    if any(w in text for w in _DAY_WORDS):
        return "day"' '    if False:
        return "day"'
add M4  $CLS "any unknown 4xx marks the key invalid" '    if 400 <= status < 500:
        return Outcome("bad_request", http=status)' '    if 400 <= status < 500:
        return Outcome("invalid", http=status)'
add M5  $CLS "a timeout is read as a rejected key" 'or "timed out" in text or "timeout" in text:
            return Outcome("transient")' 'or "timed out" in text or "timeout" in text:
            return Outcome("invalid", http=401)'
add M6  $CLS "the provider's own retry-after header is ignored" '    ra = _num(_header(headers, "retry-after"))' '    ra = None'
add M7  $CLS "a retired model (404) marks the key invalid" '    if status in (404, 410):
        return Outcome("model_gone", http=status)' '    if status in (404, 410):
        return Outcome("invalid", http=status)'
add M8  $CLS "the word 'generate' reads as a rate limit" 'rate limit|rate_limit|resource_exhausted' 'rate|resource_exhausted'
add M9  $GATE "the gate is keyed by provider NAME again (one learner's limit gates everyone)" '    return hmac.new(_KEYS_SECRET, f"{provider}|{key}".encode("utf-8"), hashlib.sha256).hexdigest()[:12]' '    return provider'
add M10 $GATE "a half-open probe is not single-flight (concurrent callers all hit a limited key)" '    if st.inflight and now - st.inflight_at < INFLIGHT_STALE_S:
        return "skip"
    st.inflight, st.inflight_at = True, now
    return "probe"' '    st.inflight, st.inflight_at = True, now
    return "probe"'
add M11 $GATE "a rejected key is only skipped for 90 seconds" 'INVALID_RECHECK_S = 6 * 3600' 'INVALID_RECHECK_S = 90'
add M12 $GATE "a success does not clear a limit" '    changed = st.status != "ok"
    _state.pop((provider, fp), None)' '    changed = st.status != "ok"'
add M13 $GATE "a cancelled probe never gives its slot back" '    st = _state.get((provider, fp))
    if st is not None:
        st.inflight = False' '    st = _state.get((provider, fp))
    if st is not None:
        pass'
add M14 $GATE "several early probes may run at once" '    for provider, fp in candidates:                           # ONE probe in flight per chain: while one runs, nobody else starts another
        st = _state.get((provider, fp))
        if st is not None and st.inflight and now - st.inflight_at < INFLIGHT_STALE_S:
            return None' '    for provider, fp in []:
        st = None
        if False:
            return None'
add M15 $ERR "a limit on the shared free pool counts as the learner's own limit" '        if k == "limited" and r.get("scope") == "upstream":
            k = "transient"' '        if False:
            k = "transient"'
add M16 $ERR "kp carries the provider's error text" '        return {"state": self.state, "keys": out, "now": int(now if now is not None else time.time())}' '        return {"state": self.state, "keys": out, "now": int(now if now is not None else time.time()), "text": str(self.last_error)}'
add M17 $PRV "a cancelled attempt is not settled in the ledger" '                finally:
                    if not done:
                        ledger.settle(tok, "other")' '                finally:
                    pass'
add M18 $LED "the key fingerprint is missing from the usage key (two keys of a learner merge)" '    k = (uid, classify.quota_day(provider, time.time() if now is None else now), provider, fp)' '    k = (uid, classify.quota_day(provider, time.time() if now is None else now), provider, "")'
add M19 $LED "one unwritable row (a deleted learner) is retried forever and blocks the batch" '    except (IntegrityError, DataError):
        state["dropped"] += 1                               # nobody'"'"'s row any more' '    except ZeroDivisionError:
        state["dropped"] += 1                               # nobody'"'"'s row any more'
add M20 $CLS "Gemini's quota day is the UTC day" '    if provider == "gemini":
        try:
            from zoneinfo import ZoneInfo
            return dt.datetime.fromtimestamp(now, ZoneInfo' '    if False:
        try:
            from zoneinfo import ZoneInfo
            return dt.datetime.fromtimestamp(now, ZoneInfo'
add M21 $SVC "saving a key replaces everything else (no merge)" '        after = {k: v for k, v in mutate(dict(before)).items() if v}' '        after = {k: v for k, v in mutate({}).items() if v}'
add M22 $SVC "removing a key leaves its status row behind" '        await s.execute(delete(KhStatus).where(KhStatus.user_id == uid, KhStatus.provider == provider))' '        pass'
add M23 $SVC "the status payload shows the key itself" '"masked": gate.mask(key),' '"masked": key,'
add M24 $SVC "a key the provider rejects is stored anyway" '    if pr.kind in ("invalid", "forbidden"):
        return {"ok": False, "result": {"provider": provider, "status": pr.kind, "expired": pr.expired}}' '    if False:
        return {"ok": False, "result": {"provider": provider, "status": pr.kind, "expired": pr.expired}}'
add M25 $SVC "a shallow re-check clears a limit that has not ended" '        if status == "ok" and cur["status"] in ("limited", "forbidden") and not cur.get("stale") and not deep:' '        if False:'
add M26 $SVC "a limit that ran its course still shows as limited" '        if until is not None and now > until:' '        if False:'
add M27 $PRV "cool=False (Grammar Coach) gates a SERVER key everyone needs" '        if byok or cool:                              # cool=False (Grammar Coach) on the server chain must not gate a key everyone'"'"'s chat needs' '        if True:'
add M28 $PRV "a timeout tries the provider's next model (another 20 s)" '    if kind == "transient" and not out.http:
        return "leave"' '    if kind == "transient" and not out.http:
        return "next"'
add M29 $MAIN "a browser key beats the one the learner saved (stale copy on another phone)" '                if pname in merged or pname not in keys_svc.PROVIDERS:
                    continue' '                if pname not in keys_svc.PROVIDERS:
                    continue'
add M30 $PRV "no early probe when every key is limited" '    if all(gate.peek(p["name"], fp, now) == "skip" for p, fp in entries):' '    if False:'
add M31 $PRV "a successful attempt is not counted as ok (and loses its tokens)" '                        ledger.settle(tok, "ok", t_in, t_out)
                        done = True' '                        done = True'
add M32 $PRV "a gated key is still tried (no fail-fast)" '        if v == "skip":
            st = gate.get(name, fp)' '        if False:
            st = gate.get(name, fp)'
add M33 $MAIN "the failure frames lose their kp" '    return {"kp": kp} if kp else {}' '    return {}'
add M34 $MAIN "an HTTP key problem keeps the site's own status and no kp" '    if kp and kp["state"] in ("all_invalid", "all_limited", "no_keys"):
        return KeyProblem(429, "quota", kp)' '    if False:
        return KeyProblem(429, "quota", kp)'
add M35 $DB "a legacy github entry counts as a second key" '_KEY_PROVIDERS = ("groq", "gemini", "openrouter")' '_KEY_PROVIDERS = ("groq", "gemini", "openrouter", "github")'
add M36 $MAIN "/health probes the providers on every request" '    sk = {n: v.get("status", "unknown") for n, v in keys_probe.cached_server_health().items()}      # the last zero-quota probe of OUR keys (never probes here)' '    sk = {n: v.get("status", "unknown") for n, v in (await keys_probe.refresh_server_health()).items()}'
add M37 $MAIN "the older /keys/verify still replaces everything" '            if await key_health_enabled(claims.get("email", "")):
                # MERGE, never replace' '            if False:
                # MERGE, never replace'
add M38 $API "saving has no rate limit" '    _rate(uid, "save", 8, 60.0)' '    _rate(uid, "save", 8000000, 60.0)'
add M39 $API "the /keys endpoints ignore the rollout switch" '    if not db.db_enabled or (need_switch and not await M.key_health_enabled(email)):' '    if not db.db_enabled:'
add M40 $DB "deleting an account leaves the key-health rows" '        from .keys import service as _ky
        await _ky.delete_rows(s, [user_id])' '        from .keys import service as _ky'
add M41 $NSV "this_device is always true (a stale subscription looks fine)" '            this_device = bool((await s.execute(select(func.count()).select_from(PlPushSub).where(PlPushSub.user_id == uid, PlPushSub.endpoint == endpoint[:700]))).scalar() or 0)' '            this_device = True'
add M42 $NSV "a test notification's journey can be read by anyone" '        r = (await s.execute(select(NtOutbox).where(NtOutbox.id == nid, NtOutbox.user_id == uid, NtOutbox.kind == "test"))).scalar_one_or_none()' '        r = (await s.execute(select(NtOutbox).where(NtOutbox.id == nid, NtOutbox.kind == "test"))).scalar_one_or_none()'
add M43 $SVC "a replaced key's old status row is kept" '        await s.execute(delete(KhStatus).where(KhStatus.user_id == uid, KhStatus.provider == provider, KhStatus.fp != fp))' '        pass'
add M44 $PRV "a provider that answers with an empty body is not counted at all" '                    ledger.settle(tok, "other", t_in, t_out)         # an empty answer: it cost a request and told us nothing about the key
                    done = True' '                    done = True'

# ----------------------------------------------------------------------------------------------------------------------------- client mutants (browser specs, slow)
declare -A CFILE CDESC COLD CNEW CSPEC
cadd() { CFILE[$1]="$2"; CDESC[$1]="$3"; COLD[$1]="$4"; CNEW[$1]="$5"; CSPEC[$1]="$6"; }
H=test_client.html
cadd C1 $H "the pop-up is not deduped" '    if(seen && seen.sig === sig && Date.now() - seen.at < REPEAT_MS) return true;      // the same news, told a moment ago' '' keys.spec.cjs
cadd C2 $H "the fetch wrapper does not look at HTTP error bodies" 'res.clone().json().then(d => { if(d && d.kp) problem(d.kp, "http"); }).catch(() => {});' 'res.clone().json().then(d => {}).catch(() => {});' keys.spec.cjs
cadd C3 $H "a stale answer overwrites a newer one" 'function take(my, payload){ if(my < appliedSeq) return false;' 'function take(my, payload){ if(false) return false;' keys.spec.cjs
cadd C4 $H "a saved key stays in a hidden input" 'if(inp.value) inp.value = ""; }    // a saved key is shown masked only' '}    // a saved key is shown masked only' keys.spec.cjs
cadd C5 $H "the install pill is drawn when the app is already installed" '    const on = enabled() && !installedLike(mode());' '    const on = enabled();' install.spec.cjs
cadd C6 $H "install does not yield to a key problem" '  const ORDER = ["key", "install", "nt", "wa"];' '  const ORDER = ["install", "key", "nt", "wa"];' install.spec.cjs
cadd C7 $H "the Android app (TWA) is not recognised" 'function inTwa(){ try{ return sessionStorage.getItem("dusu_twa") === "1" || document.referrer.indexOf("android-app://") === 0; }catch(_){ return false; } }' 'function inTwa(){ return false; }' install.spec.cjs
cadd C8 $H "the WhatsApp link is used without re-checking it" 'const link = () => { const u = (typeof userState !== "undefined" && userState && userState.community && userState.community.whatsapp) || ""; return SAFE.test(u) ? u : ""; };' 'const link = () => (typeof userState !== "undefined" && userState && userState.community && userState.community.whatsapp) || "";' install.spec.cjs

plant() {   # plant FILE OLD NEW into $OUT/backend  -> 0 ok, 7 does not apply
  python3 - "$OUT/backend/$1" "$2" "$3" <<'PY'
import sys
p, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p).read()
if old not in s:
    print("MUTANT DOES NOT APPLY (the code changed): ", old[:70]); sys.exit(7)
open(p, "w").write(s.replace(old, new, 1))
PY
}
fresh_copy() { rm -rf "$OUT/backend"; mkdir -p "$OUT/backend"; tar -C backend --exclude=.venv --exclude=__pycache__ --exclude='.env*' -cf - . | tar -C "$OUT/backend" -xf -; }

if [ "${1:-}" = "--client" ]; then
  shift; WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=(C1 C2 C3 C4 C5 C6 C7 C8)
  caught=0; survived=()
  for m in "${WANT[@]}"; do
    fresh_copy
    plant "${CFILE[$m]}" "${COLD[$m]}" "${CNEW[$m]}"; rc=$?
    [ $rc -eq 7 ] && { echo "$m  NOT APPLIED  (${CDESC[$m]})"; survived+=("$m(not applied)"); continue; }
    if KY_BACKEND="$PWD/$OUT/backend" tests/keys/browser/run_real.sh "${CSPEC[$m]}" > "$OUT/$m.log" 2>&1; then
      echo "$m  SURVIVED   (${CDESC[$m]})  <- the spec did not notice"; survived+=("$m")
    else
      echo "$m  caught     (${CDESC[$m]})  -> $(grep -c '  FAIL' "$OUT/$m.log") failing checks"; caught=$((caught+1))
    fi
  done
  echo; echo "client mutants: ${caught} caught, ${#survived[@]} survived: ${survived[*]:-none}"; exit 0
fi

WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=($(for i in $(seq 1 44); do echo M$i; done))
caught=0; survived=()
for m in "${WANT[@]}"; do
  fresh_copy
  plant "${FILE[$m]}" "${OLD[$m]}" "${NEW[$m]}"; rc=$?
  [ $rc -eq 7 ] && { echo "$m  NOT APPLIED  (${DESC[$m]})"; survived+=("$m(not applied)"); continue; }
  hit=""
  for t in unit.py parity.py selftest.py ws_selftest.py; do
    if ! KY_BACKEND="$PWD/$OUT/backend" tests/keys/run.sh "$t" > "$OUT/$m.$t.log" 2>&1; then hit="$t"; break; fi
  done
  if [ -z "$hit" ]; then echo "$m  SURVIVED   (${DESC[$m]})  <- no tier noticed"; survived+=("$m")
  else echo "$m  caught     (${DESC[$m]})  -> $hit: $(grep -c '  FAIL\|Traceback' "$OUT/$m.$hit.log") failing checks / errors"; caught=$((caught+1)); fi
done
echo; echo "server mutants: ${caught} caught, ${#survived[@]} survived: ${survived[*]:-none}"
