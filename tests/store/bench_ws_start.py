"""How long does the server take to OPEN a chat? (start -> the opener frame) in Home, Face-to-Face and Daily Talk, on a learner who has some history.

DB-agnostic on purpose (only `db.*` calls and the real /ws/interview handler served by uvicorn in-process, scripted fake providers): run it on the OLD tree against a scratch
Postgres and on the NEW tree against a scratch Mongo and compare. Prints milliseconds only.   tests/store/bench_ws_start.sh old|new
"""
import asyncio
import json
import os
import statistics
import sys
import time

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/keys")

import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402

from world import World, install, ok                                 # noqa: E402

from app import auth, db, main as M                                  # noqa: E402

PORT = 8771
WORLD = World()
WORLD.chat_reply = lambda messages, provider, key: ok(json.dumps({"reply": "Hello there", "intent": "general_conversation", "suggest": [], "english": "I went out",
                                                                  "reply_hindi": "Accha", "next_question_hindi": "Aur?", "tip": "", "mood": "ok", "context": {}}))
install(WORLD)
RUNS = int(os.environ.get("BENCH_RUNS", "25"))


def frame(tok, mode):
    base = {"type": "start", "token": tok, "mode": mode, "hour": 11, "day": "2026-11-16", "name": "Ann", "role": "Data Analyst", "lang": "en"}
    if mode == "home":
        base.update({"opening": "Good evening! How was your day?", "tzmin": 330, "plan": False, "lang": "hi"})
    return base


OPENERS = {"home": "home_ready", "conversation": "ai_text", "daily": "daily_question"}


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key), "refusing to run with provider keys configured"
    M.auth.auth_enabled = True
    for _ in range(30):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    await db.set_setting("home_ai", "on")
    M.invalidate_access_cache()
    users, tok = {}, {}
    for i in range(8):
        n = f"b{i}"
        users[n] = {"sub": f"bench-{n}", "email": f"{n}@example.com", "name": "Learner Lee", "picture": ""}
        await db.login(users[n])
        await db.save_assessment(users[n]["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "B1", "scores": {}, "weak_areas": []})
        await db.save_user_keys(users[n]["sub"], {"groq": f"gsk_{n}" + "G" * 30 + "xGq", "gemini": f"AIza{n}" + "M" * 30 + "xMq"}, verified=True)
        for k in range(6):                                              # some history, like a real learner (82 conversations / 22 learners in production)
            await db.add_conversation(users[n]["sub"], "conversation", f"They talked about their day number {k}: cricket, a job interview and a trip to Jaipur.")
        await db.merge_facts(users[n]["sub"], {"interests": {"sports": "cricket"}, "profession": "analyst", "dream": "a good job", "notes": ["likes cricket", "has an interview soon"]}, [])
        await db.save_checkin(users[n]["sub"], "good")
        tok[n] = auth.make_session(users[n])
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    URL = f"ws://127.0.0.1:{PORT}/ws/interview"
    print(f"{RUNS} chats opened per mode, on a learner with 6 saved conversations and some memory:")
    for mode, opener in OPENERS.items():
        lat = []
        for r in range(RUNS):
            n = f"b{r % 8}"
            async with websockets.connect(URL) as ws:
                t = time.monotonic()
                await ws.send(json.dumps(frame(tok[n], mode)))
                while True:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 30))
                    if m.get("type") == opener or m.get("type") in ("error", "quota", "keys_required", "auth_error", "home_error"):
                        break
                lat.append((time.monotonic() - t) * 1000)
                assert m.get("type") == opener, m
            await asyncio.sleep(0.15)
        lat.sort()
        print(f"   {mode:<13s} start -> {opener:<15s} p50 {statistics.median(lat):6.0f} ms | p95 {lat[int(len(lat) * 0.95) - 1]:6.0f} ms | max {lat[-1]:6.0f} ms")
    # the page-load path: the requests the app makes when it opens (HTTP, through a real socket)
    import httpx
    print(f"{RUNS} runs of each page-load request, same learners:")
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=60) as c:
        for path in ("/me", "/leaderboard", "/league", "/missions", "/home/features?lang=hi", "/practice/history", "/keys/status"):
            lat = []
            for r in range(RUNS):
                n = f"b{r % 8}"
                t = time.monotonic()
                resp = await c.get(path, headers={"Authorization": "Bearer " + tok[n]})
                lat.append((time.monotonic() - t) * 1000)
                assert resp.status_code in (200, 404), (path, resp.status_code)
            lat.sort()
            print(f"   GET {path:<26s} p50 {statistics.median(lat):6.0f} ms | p95 {lat[int(len(lat) * 0.95) - 1]:6.0f} ms | max {lat[-1]:6.0f} ms")
    server.should_exit = True
    await task
    try:
        await __import__("app.store", fromlist=["close"]).close()
    except Exception:
        pass
    os._exit(0)


asyncio.run(main())
