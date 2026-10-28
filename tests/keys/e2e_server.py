"""Keys - the REAL app (uvicorn + a scratch Postgres, the real key engine and the real flush loop running) for a REAL browser to talk to.

Every AI provider is a scripted fake (tests/keys/world.py, installed through `_http_client_factory`), driven from the browser spec through a few CONTROL routes that exist
ONLY in this test process: POST /__world/behave, POST /__world/reset, POST /__world/calls. Seeds learners with stored keys in the states a screen has to show, switches the
key engine, the key screens, Install + WhatsApp and Notifications ON, writes the session tokens for the spec to `/tests/keys/.e2e/tokens.json` (git-ignored) and serves on :8000.
Started by browser/run_real.sh - never run against production.
"""

import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import uvicorn                                                      # noqa: E402
from fastapi import Request                                         # noqa: E402
from sqlalchemy import update                                       # noqa: E402

from world import (World, install, ok, err, R, completion, GROQ_401, GROQ_429_TPD, GROQ_429_TPM, GEMINI_400_KEY, GEMINI_400_EXPIRED, GEMINI_429_DAY, GEMINI_429_MIN,      # noqa: E402
                   GEMINI_503, OPENROUTER_401, OPENROUTER_429_DAY, OPENROUTER_429_UPSTREAM, conn)
import httpx                                                        # noqa: E402

from app import auth, db, main as M                                 # noqa: E402
from app.keys import gate, ledger                                   # noqa: E402

assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key or M.settings.github_token), \
    "provider keys must be blank (run through run_real.sh)"

JSON_REPLY = json.dumps({"reply": "Hello there, nice to meet you.", "intent": "general_conversation", "suggest": [], "english": "I went to the market", "reply_hindi": "Bahut accha",
                         "next_question_hindi": "Aur batao?", "tip": "", "mood": "ok", "context": {}, "summary": "They chatted.", "facts": {}, "events": [], "no_hindi": False,
                         "asked_question": False, "next_hook": "", "pass": True, "feedback": "good"})

CHAT_ERR = {
    "limited": {"groq": (429, GROQ_429_TPD), "gemini": (429, GEMINI_429_DAY), "openrouter": (429, OPENROUTER_429_DAY)},
    "limited_min": {"groq": (429, GROQ_429_TPM), "gemini": (429, GEMINI_429_MIN), "openrouter": (429, OPENROUTER_429_UPSTREAM)},
    "upstream": {"groq": (429, GROQ_429_TPM), "gemini": (429, GEMINI_429_MIN), "openrouter": (429, OPENROUTER_429_UPSTREAM)},
    "invalid": {"groq": (401, GROQ_401), "gemini": (400, GEMINI_400_KEY), "openrouter": (401, OPENROUTER_401)},
    "expired": {"groq": (401, {"error": {"message": "API key expired", "code": "invalid_api_key"}}), "gemini": (400, GEMINI_400_EXPIRED), "openrouter": (401, OPENROUTER_401)},
    "down": {"groq": (503, {"error": {"message": "boom"}}), "gemini": (503, GEMINI_503), "openrouter": (503, {"error": {"message": "boom"}})},
}


class Control(World):
    """The fake providers, with a behaviour per provider (or per exact key) that the browser spec flips at run time."""

    def __init__(self):
        super().__init__()
        self.behave: dict = {}

    def mode(self, provider, key):
        return self.behave.get((provider, key)) or self.behave.get((provider, "*")) or "ok"

    async def handler(self, req: httpx.Request) -> httpx.Response:
        from world import PROVIDER_OF
        provider = PROVIDER_OF.get(req.url.host, "?")
        auth_h = req.headers.get("authorization", "")
        key = auth_h[7:] if auth_h.lower().startswith("bearer ") else ""
        path = req.url.path
        kind = "chat" if path.endswith("/chat/completions") else "key" if path.endswith("/key") else "models"
        mode = self.mode(provider, key)
        self.calls.append((provider, key, kind, ""))
        if mode == "unreachable":
            raise httpx.ConnectError("connection refused")
        if mode == "ok":
            if kind == "chat":
                try:
                    msgs = json.loads(req.content or b"{}").get("messages") or []
                except Exception:
                    msgs = []
                wants_json = bool(msgs) and str(msgs[-1].get("content", "")).endswith("Return ONLY the JSON object.")
                hdr = {"x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": str(14400 - sum(1 for c in self.calls if c[0] == "groq" and c[2] == "chat")),
                       "x-ratelimit-reset-requests": "1m30s"} if provider == "groq" else {}
                return httpx.Response(200, json=completion(JSON_REPLY if wants_json else "Nice to meet you. Tell me more about that?"), headers=hdr, request=req)
            if kind == "key":
                return httpx.Response(200, json={"data": {"label": "k", "usage": 0, "limit": None, "is_free_tier": True}}, request=req)
            return httpx.Response(200, json={"data": []}, request=req)
        table = CHAT_ERR.get(mode)
        if table is None:
            return httpx.Response(200, json=completion("OK"), request=req)
        status, body = table[provider]
        if kind != "chat" and mode in ("limited", "limited_min", "upstream"):          # a limit does not stop the zero-quota probe: the key is real
            return httpx.Response(200, json={"data": []} if kind == "models" else {"data": {"is_free_tier": True}}, request=req)
        return httpx.Response(status, json=body, request=req)


WORLD = Control()
install(WORLD)

NAMES = ["new", "two", "three", "bad", "lim", "mix", "ph", "wa", "pr", "fresh", "tester", "plain", "i18n", "cap", "dev", "zero", "nt1", "nt2", "wa2", "wa3", "inst1", "inst2"] + [f"lk{i}" for i in range(1, 11)]       # lk1..lk10: the daily_voice spec (one fresh learner per scenario)
ZERO = {"zero", "inst1", "inst2"}                       # learners who have NOT practised yet (xp 0): Home prompts that wait for a first practice must stay away


async def seed():
    for _ in range(30):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    users = {n: {"sub": f"e2e-{n}", "email": f"{n}@example.com", "name": f"{n.title()} Learner", "picture": ""} for n in NAMES}
    users["owner"] = {"sub": "e2e-owner", "email": "david123rana@gmail.com", "name": "Owner", "picture": ""}
    for u in users.values():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A2", "scores": {}, "weak_areas": []})
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()
    async with db._Session() as s:
        for n in NAMES:
            await s.execute(update(db.Progress).where(db.Progress.user_id == f"e2e-{n}").values(xp=0 if n in ZERO else 40, streak_days=0 if n in ZERO else 3,
                                                                                             last_active=None if n in ZERO else today - dt.timedelta(days=1)))
        await s.commit()
    # learners with keys already stored (saved the way the app saves them: sealed)
    stored = {"two": ["groq", "gemini"], "three": ["groq", "gemini", "openrouter"], "bad": ["groq", "gemini"], "lim": ["groq", "gemini"], "mix": ["groq", "gemini", "openrouter"],
              "ph": ["groq", "gemini"], "wa": ["groq", "gemini"], "pr": ["groq", "gemini"], "tester": ["groq", "gemini"], "plain": ["groq", "gemini"], "i18n": ["groq", "gemini"],
              "cap": ["groq", "gemini"], "dev": ["groq", "gemini"], "nt2": ["groq", "gemini"], **{f"lk{i}": ["groq", "gemini"] for i in range(1, 11)}}
    keys = {}
    for n, provs in stored.items():
        k = {"groq": f"gsk_{n}" + "G" * 28 + "9fA2", "gemini": f"AIza{n}" + "M" * 28 + "Xy71", "openrouter": f"sk-or-v1-{n}" + "O" * 28 + "Q7xP"}
        keys[n] = k
        await db.save_user_keys(f"e2e-{n}", {p: k[p] for p in provs}, verified=len(provs) >= 2)
    for k, v in (("key_health", "on"), ("keys_ui", "on"), ("install_mode", "on"), ("notifications", "on"), ("bilingual", "on"), ("planner", "on"), ("home_ai", "off"),
                 ("whatsapp_group", "https://chat.whatsapp.com/TestInviteCode0123456789")):
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    # `plain` has the engine on but the screens off (a per-learner stage is exercised through the dashboard in the spec); `tester` is an early-access tester
    await db.early_add("tester@example.com")
    os.makedirs("/tests/keys/.e2e", exist_ok=True)
    out = {k: {"token": auth.make_session(u), "user": u, "keys": keys.get(k)} for k, u in users.items()}
    json.dump(out, open("/tests/keys/.e2e/tokens.json", "w"))
    await db._engine.dispose()                                       # connections made in THIS event loop must not be reused by uvicorn's own loop


# ---------------------------------------------------------------------------------------------- control routes (test process only)
@M.app.post("/__world/behave")
async def world_behave(request: Request):
    b = await request.json()
    prov, key, mode = b.get("provider"), b.get("key") or "*", b.get("mode") or "ok"
    WORLD.behave[(prov, key)] = mode
    if b.get("clear_gate"):
        gate.reset_all()
    return {"ok": True, "behave": {f"{k[0]}|{k[1][:12]}": v for k, v in WORLD.behave.items()}}


@M.app.post("/__world/reset")
async def world_reset(request: Request):
    WORLD.behave.clear()
    WORLD.calls.clear()
    gate.reset_all()
    from app.providers import openrouter_provider as op
    op._cooldown.clear()
    try:
        b = await request.json()
    except Exception:
        b = {}
    for k, v in (b.get("settings") or {}).items():
        await db.set_setting(k, v)
    M.invalidate_access_cache()
    return {"ok": True}


@M.app.post("/__world/calls")                                        # POST: a GET would be swallowed by the app's catch-all route that serves the page
async def world_calls(request: Request):
    b = await request.json()
    provider, kind, key = b.get("provider", ""), b.get("kind", ""), b.get("key", "")
    rows = [c for c in WORLD.calls if (not provider or c[0] == provider) and (not kind or c[2] == kind) and (not key or c[1] == key)]
    return {"n": len(rows), "by": {f"{p}:{k}": sum(1 for c in rows if c[0] == p and c[2] == k) for p in {c[0] for c in rows} for k in {c[2] for c in rows}}}


@M.app.post("/__world/flush")
async def world_flush():
    await ledger.flush()
    return {"ok": True}


# the push service is a fake too: it accepts everything and remembers the payloads, so the spec can read the notification a phone would have received
from app.planner import push as PP                                  # noqa: E402
PUSHES: list = []


async def fake_send(sub, payload):
    PUSHES.append({"endpoint": sub["endpoint"], "payload": json.loads(payload.decode("utf-8")) if isinstance(payload, (bytes, bytearray)) else payload})
    return ("ok", 201)


PP.send = fake_send


@M.app.post("/__world/pushes")
async def world_pushes(request: Request):
    b = await request.json()
    if b.get("clear"):
        PUSHES.clear()
    return {"pushes": PUSHES}


asyncio.run(seed())
uvicorn.run(M.app, host="0.0.0.0", port=8000, log_level="warning")
