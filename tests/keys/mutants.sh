#!/usr/bin/env bash
# Keys - "do the tests catch a planted bug?"  Copies the backend, plants ONE deliberate bug in the key engine, the key endpoints or the wiring, runs the tiers in order against
# the copy (unit, the validated-walk unit tier, parity, the DB-backed tiers, the WebSocket tiers) and reports whether any of them FAILED (= the bug was caught). A mutant that survives means a check is too weak.
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
PRV=app/providers/openrouter_provider.py; PROBE=app/keys/probe.py; MAIN=app/main.py; DB=app/db.py; NSV=app/notify/service.py

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

# --- "AI busy" (the walker's second pass, per-model limits, the model memory, the frames, the refund, the early warning)
add M45 $MAIN "any failure the key engine classified is called quota again (the mislabel: a busy provider became 'your keys hit their limit')" '        return is_keys_problem(kp)' '        return True'
add M46 $MAIN "a failed turn keeps costing a free daily turn" '            await turn_quota.refund()' '            pass'
add M47 $MAIN "a failed Face-to-Face turn leaves the unanswered line on the server (a resend is said twice)" '                    del session.transcript[n_before:]      # the line DuSu could not answer is taken back, so the learner saying it again (or the page re-sending it) is not said twice
                    session.turns = turns_before' '                    pass'
add M48 $ERR "DuSu's own keys are shown to the learner as key rows with the real reason" '        if not self.own:
            out = {"state": "transient", "own": False, "keys": [], "now": now_i}' '        if False:
            out = {"state": "transient", "own": False, "keys": [], "now": now_i}'
add M49 $PRV "a REJECTED key earns a second pass" '    if kind == "invalid":
        gate.mark_invalid(name, fp, now, http=out.http, expired=out.expired)' '    if kind == "invalid":
        w.want(1.0)
        gate.mark_invalid(name, fp, now, http=out.http, expired=out.expired)'
add M50 $PRV "Groq and Gemini are treated as one limit per provider again (no per-model fall-through)" 'PER_MODEL_LIMITS = frozenset({"gemini", "groq"})' 'PER_MODEL_LIMITS = frozenset()'
add M51 $PRV "a model the provider says does not exist is asked again on every turn" '        gate.mark_model_gone(name, fp, model, now, http=out.http)' '        pass'
add M52 $PRV "a background caller (Grammar Coach, cool=False) waits for the second pass" 'if pass_no == 0 and cool and w.wait is not None' 'if pass_no == 0 and w.wait is not None'
add M53 $PRV "the failure log line carries what the provider wrote (it can echo the learner's words)" '    _log_failure(state, byok, attempts)
    raise ProviderChainError(last_err, state, keys, own=byok)' '    _log_failure(state, byok, attempts + [str(w.last_err)])
    raise ProviderChainError(last_err, state, keys, own=byok)'
add M54 $PROBE "an alias (gemini-flash-lite-latest) is judged against the provider's list (a false 'model missing' alarm)" '                miss = [m for m in p["models"] if m not in have and not m.endswith("-latest")]' '                miss = [m for m in p["models"] if m not in have]'
add M55 $GATE "re-adding a key leaves what was believed about its models" '    for k in [k for k in _models if k[0] == provider and k[1] == fp]:
        _models.pop(k, None)' '    pass'
add M56 $ERR "a daily limit gets a countdown (waiting will not help)" '            elif kind == "limited" and k.get("scope") in ("minute", "upstream", ""):' '            elif kind == "limited":'
add M57 $PRV "the second pass ignores the 30 s ceiling" 'deadline - time.time() >= w.wait + _REPASS_MIN_LEFT_S' 'True'
add M58 $PRV "a model that answers again stays remembered as limited" '                        gate.model_ok(name, fp, model)' '                        pass'
add M59 $PRV "the early probe cannot reach a model whose own memory still says limited" '            gate.probe_soonest_model(name, fp, p["models"], time.time())' '            pass'
add M61 $MAIN "/health lists a learner's own key's gone models too" 'keys_gate.gone_models({keys_gate.fingerprint(p["name"], p["key"]) for p in settings.providers()}, time.time())' 'keys_gate.gone_models({k[1] for k in keys_gate._models}, time.time())'
add M62 $PRV "the same failure line is printed on every failed turn" '    if now - _fail_logged.get(line, 0.0) < _LOG_EVERY_S:
        return' '    pass'
add M63 $PRV "OpenRouter's busy-upstream 429 gates the whole key again (the second free model is never asked)" '        if name in PER_MODEL_LIMITS or out.scope == "upstream":' '        if name in PER_MODEL_LIMITS:'
add M64 $PROBE "DuSu's own key is never asked to chat (a key that lists models but is refused every call reads ok)" '        if st == "ok" and p["name"] != "openrouter":' '        if False:'
add M65 $PROBE "a passing chat failure (a hiccup, a limit) turns a healthy server key red" '            if c["kind"] in ("forbidden", "invalid"):
                st = c["kind"]' '            if c["kind"] != "ok":
                st = "forbidden"'
add M66 $MAIN "the owner's view of DuSu's own keys is sent to every learner" '        if kp and kp.get("own") is False and role_for(_email) == "owner":' '        if kp and kp.get("own") is False:'
add M67 $PROBE "a key-shaped string in a provider's reason reaches the owner's alert" '    msg = _KEYISH.sub("<key>", " ".join(msg.split()))' '    msg = " ".join(msg.split())'
add M68 $PROBE "the provider's reason is cut in the middle of a word / link" '        msg = msg[:WHY_MAX].rsplit(" ", 1)[0].rstrip(".,;:") + "…"' '        msg = msg[:WHY_MAX] + "…"'
add M69 $PROBE "the owner's dashboard never gets the provider's reason for a refused chat" '                out[p["name"]].update(status=st, http=c["http"], chat=c["kind"], why=c.get("why", ""))' '                out[p["name"]].update(status=st, http=c["http"], chat=c["kind"])'

# ----------------------------------------------------------------------------------------------------------------------------- client mutants (browser specs, slow)
# ---- the validated walk (settings.chain_v3), the request parameters, the save-time probe, the level-test fixes
ENG=app/interview/engine.py
add M70 $PRV "an unusable reply counts as usable (accept is never asked)" '                        reason = "empty" if not text else accept(text, finish)' '                        reason = "empty" if not text else None'
add M71 $PRV "an unusable reply is not remembered (the same model is asked first on the next call)" '                    gate.mark_bad(name, fp, model, cls, time.time(), reason)
' '                    pass
'
add M72 $PRV "after an unusable reply the walk asks the provider's SIBLING model before any other provider" '                    if first_pass:                                        # ANOTHER PROVIDER first (a different family, its own budget); this one'"'"'s other models follow in the second pass
                        if mi + 1 < len(p["models"]):
                            w.retry_now = True
                        break' '                    if first_pass:
                        pass'
add M73 $PRV "the sibling pass never happens after an unusable reply" '            if w.retry_now and deadline - time.time() >= _REPASS_MIN_LEFT_S:' '            if False and w.retry_now and deadline - time.time() >= _REPASS_MIN_LEFT_S:'
add M74 $PRV "a SINGLE held-back model with nothing else to ask is not asked (the learner is locked out)" '            if (accept is not None or v3) and w.asked == 0 and w.skipped_bad:' '            if (accept is not None or v3) and w.asked == 0 and w.skipped_bad > 1:'
add M75 $PRV "a model that is held back is asked anyway" '                if accept is not None and not w.ignore_bad and ((name, model) in w.bad_models or gate.bad_blocked(name, fp, model, cls, time.time()) is not None):' '                if False and accept is not None and not w.ignore_bad and ((name, model) in w.bad_models or gate.bad_blocked(name, fp, model, cls, time.time()) is not None):'
add M76 $PRV "a JSON reply cut off by the token limit is accepted when its start parses" '        if finish == "length" and not _closed_object(t):
            return "truncated"' '        if False:
            return "truncated"'
add M77 $ERR "an unusable reply is reported as 'your keys are limited'" '        super().__init__(last_err, "transient", keys, own)' '        super().__init__(last_err, "all_limited", keys, own)'
add M78 $GATE "what is held against a model for JSON is held against it for prose too" '    st = _bad.get((provider, fp, model, cls))
    if st is not None and now < st.until:' '    st = _bad.get((provider, fp, model, "json"))
    if st is not None and now < st.until:'
add M79 $PRV "one usable reply does not clear what was held against the model" '                            gate.bad_ok(name, fp, model, cls)                     # a usable reply: whatever was held against this model for this kind of call is over' '                            pass'
add M80 $GATE "the hold on a model never grows (always 20 s)" '    st.until = now + min(BAD_MAX_S, BAD_BASE_S * (2 ** min(st.strikes - 1, 10)))' '    st.until = now + BAD_BASE_S'
add M81 $PRV "Groq's reasoning settings are sent on every call, scoring included" '                if chat and v3:                           # a per-turn CHAT call' '                if True:                                  # a per-turn CHAT call'
add M82 $PRV "a model that refused the settings is sent them again" '                    if ce and not gate.param_unsupported(name, model, time.time()):' '                    if ce:'
add M83 $PRV "a 400 about our settings is never remembered" '                    if sent and out.kind == "bad_request" and _rejects_params(e, sent):' '                    if False:'
add M84 $PROBE "an EMPTY answer to the save-time probe counts as a working key" '                if not text and fin != "length":' '                if False:'
add M115 $PROBE "a reasoning model cut off by the token limit while thinking does not count as a working key" '                if not text and fin != "length":' '                if not text:'
add M116 $PROBE "a 400 that names the reasoning settings is read as a bad key (no retry without them)" '                    if use_ce and classify.classify(provider, e0, now).kind == "bad_request" and op._rejects_params(e0, ce):' '                    if False:'
add M85 $PRV "an unusable reply is counted as a request that told us nothing" '                    if text:                                              # it ANSWERED, but there is nothing to use: the request counted and the key works
                        ledger.settle(tok, "ok", t_in, t_out)' '                    if text:                                              # it ANSWERED, but there is nothing to use: the request counted and the key works
                        ledger.settle(tok, "other", t_in, t_out)'
add M86 $PRV "the validated walk runs for the per-key walker alone (engine 1) too" 'accept if ctx.engine >= 2 else None, cls)' 'accept, cls)'
add M87 $PRV "assess raises when nothing is usable instead of returning the failure shape" '        except BadReplyError as e:
            _last_bad.set(e)
            return {"error": "scoring_parse_failed", "raw": ""}
        _last_bad.set(None)
        return _extract_json(text)

    async def score' '        except BadReplyError as e:
            raise
        _last_bad.set(None)
        return _extract_json(text)

    async def score'
add M88 $MAIN "the level test's passed comes from the model again (the unlock disagrees with the screen)" '    out = {"score": score, "passed": score >= 70,' '    out = {"score": score, "passed": bool(result.get("passed", score >= 70)),'
add M89 $MAIN "the level test accepts any level" '    level: int = Field(ge=1, le=db.MAX_LEVEL)' '    level: int'
add M90 $MAIN "engine_level ignores key_health (the validated walk runs for a learner without the per-key engine)" '    if not await key_health_enabled(email):
        return 0
    return 2 if await chain_v3_enabled(email) else 1' '    return 2 if await chain_v3_enabled(email) else 1'
add M91 $MAIN "lesson/evaluate returns the parse-failure sentinel as HTTP 200 again" '        raise key_error(llm.last_bad() or RuntimeError("no usable verdict"), 502, "Could not evaluate, please try again", check_quota=False)
    return d' '        return d
    return d'
add M92 $SVC "a deep Test says 'works' when no model of the key answered" '            elif cp.kind != "ok":
                results[p] = "unreachable"' '            elif False:
                results[p] = "unreachable"'
add M93 $SVC "a key whose models answer with nothing is saved as working" '        elif cp.kind != "ok":
            status = "unknown"' '        elif False:
            status = "unknown"'
add M94 $ENG "Home asks a second time after the validated walk already tried every model" '            if attempt == 1 and v3:
                break' '            if False:
                break'
add M95 $MAIN "the level-check generator asks three times even with the validated walk" 'for _ in range(1 if llm.v3_active() else 3):' 'for _ in range(3):'
add M96 $MAIN "a level test nobody could score records a failed 0% attempt" '        raise key_error(llm.last_bad() or RuntimeError("no usable score"), 502, "Could not score the test, please try again", check_quota=False)' '        result = {"score": 0, "message": ""}'

# ---- time budgets, the breaker and the order of the providers (the validated walk, M1b)
add M97  $PRV "an interactive attempt gets the SDK's default 20 s instead of its own limit" '                    kw = {"timeout": max(_MIN_ATTEMPT_S, rem if last_provider else min(_attempt_timeout(cls, chat), rem))} if v3 else {}' '                    kw = {}'
add M98  $PRV "an attempt is not cut to what is left of the walk (a walk can run past its ceiling)" 'rem if last_provider else min(_attempt_timeout(cls, chat), rem)' 'rem if last_provider else _attempt_timeout(cls, chat)'
add M111 $PRV "the LAST provider is cut at the short limit although there is nowhere else to go" 'rem if last_provider else min(_attempt_timeout(cls, chat), rem)' 'min(_attempt_timeout(cls, chat), rem)'
add M112 $PRV "Groq's reasoning settings are sent by the per-key walker alone (engine 1) too" '                if chat and v3:                           # a per-turn CHAT call' '                if chat:                                  # a per-turn CHAT call'
add M99  $PRV "a heavy call (scoring, extraction) gets the short interactive limit" '    return _ATTEMPT_S.get(cls, 11.0) if interactive else _ATTEMPT_HEAVY_S' '    return _ATTEMPT_S.get(cls, 11.0)'
add M100 $GATE "failures to answer are not counted: the breaker never opens" '    if kind == "transient":
        h.consec += 1' '    if kind == "transient":
        h.consec += 0'
add M101 $PRV "an open breaker is not consulted: the model is asked anyway" '                    if hv == "skip" and not w.ignore_bad:' '                    if False:'
add M102 $GATE "the breaker probe is not single-flight (every caller hits a model that was failing)" '    if now < h.until:
        return "skip"
    if h.inflight and now - h.inflight_at < INFLIGHT_STALE_S:
        return "skip"
    h.inflight, h.inflight_at = True, now
    return "probe"' '    if now < h.until:
        return "skip"
    h.inflight, h.inflight_at = True, now
    return "probe"'
add M103 $GATE "a usable reply does not close the breaker" '    h.consec = h.opened = 0
    h.until = 0.0
    h.inflight = False
    h.last_at = now' '    h.inflight = False
    h.last_at = now'
add M104 $PRV "an unusable reply opens the breaker like a timeout (a model that ANSWERS badly is treated as dead)" 'gate.health_fail(name, model, cls, "bad", time.time())' 'gate.health_fail(name, model, cls, "transient", time.time())'
add M105 $PRV "the providers are asked in the configured order whatever their health" '        rank = {n: i for i, n in enumerate(gate.order_by_health([p["name"] for p in chain], time.time()))}' '        rank = {n: i for i, n in enumerate([p["name"] for p in chain])}'
add M106 $PRV "the health order is applied to the per-key walker alone (engine 1) too" '    if v3:                                           # best-first by how each provider is doing now' '    if True:                                         # best-first by how each provider is doing now'
add M107 $GATE "the bands are so narrow that two close scores flip the order (flapping)" 'HEALTH_BAND = 4 ' 'HEALTH_BAND = 1000 '
add M108 $GATE "a stale reading never drifts back toward the prior (a demoted provider is never tried again)" '    if h.last_at and now - h.last_at > HEALTH_STALE_S:' '    if False:'
add M109 $GATE "a provider whose every model has its breaker open still scores like a healthy one" '    if open_n == len(vals):
        return 0.0' '    if False:
        return 0.0'
add M110 $PRV "when every breaker is open and nothing else is left, nothing is asked at all" '            if (accept is not None or v3) and w.asked == 0 and w.skipped_bad:' '            if False and (accept is not None or v3) and w.asked == 0 and w.skipped_bad:'

add M113 $PRV "a BACKGROUND call (Grammar Coach) holds a model of DuSu's own chain back for everyone's chat" '                    if byok or cool:                                      # a background call (cool=False) on DuSu'"'"'s own chain must not hold a model back for everyone'"'"'s chat' '                    if True:                                              # a background call (cool=False) on DuSu'"'"'s own chain must not hold a model back for everyone'"'"'s chat'
add M114 $PRV "a walk asks a model again that already answered unusably in the SAME walk (when the gate does not remember it)" 'if accept is not None and not w.ignore_bad and ((name, model) in w.bad_models or gate.bad_blocked(name, fp, model, cls, time.time()) is not None):' 'if accept is not None and not w.ignore_bad and (gate.bad_blocked(name, fp, model, cls, time.time()) is not None):'

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

WANT=("$@"); [ ${#WANT[@]} -eq 0 ] && WANT=($(for i in $(seq 1 59) $(seq 61 116); do echo M$i; done))
caught=0; survived=()
for m in "${WANT[@]}"; do
  fresh_copy
  plant "${FILE[$m]}" "${OLD[$m]}" "${NEW[$m]}"; rc=$?
  [ $rc -eq 7 ] && { echo "$m  NOT APPLIED  (${DESC[$m]})"; survived+=("$m(not applied)"); continue; }
  hit=""
  for t in chain_unit.py chain_selftest.py chain_ws.py unit.py parity.py selftest.py ws_selftest.py; do
    if ! KY_BACKEND="$PWD/$OUT/backend" tests/keys/run.sh "$t" > "$OUT/$m.$t.log" 2>&1; then hit="$t"; break; fi
  done
  if [ -z "$hit" ]; then echo "$m  SURVIVED   (${DESC[$m]})  <- no tier noticed"; survived+=("$m")
  else echo "$m  caught     (${DESC[$m]})  -> $hit: $(grep -c '  FAIL\|Traceback' "$OUT/$m.$hit.log") failing checks / errors"; caught=$((caught+1)); fi
done
echo; echo "server mutants: ${caught} caught, ${#survived[@]} survived: ${survived[*]:-none}"
