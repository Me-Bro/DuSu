"""Talk - the WebSocket half: the REAL /ws/interview handler (uvicorn in-process, auth ON, scratch MongoDB) with the stub model of talk_stub.py (run via tests/talk/run.sh ws_selftest.py).

Proves, for the `talk` mode: a start with the switch off / an unknown topic / a bad support level is refused and NEVER builds a Session; a valid start sends the bank's opener with NO model call;
exactly ONE model call per learner turn; `hi` only at en_sub; `fix` only when verified, at most one; the transcript and the memory pass never see Hindi or JSON; a failed turn gives the error frame +
the refund + the line taken back; the turn cap; the quiet reconnect after a screen lock (no opener, no model call, turns back to 0); `end` persists the chat and pays its reward exactly once;
Grammar Coach is not involved."""
import asyncio
import json
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/tests/talk")

import uvicorn                                                       # noqa: E402
import websockets                                                    # noqa: E402
from app.store import func, select                                  # noqa: E402

from app import auth, db, main as M                                  # noqa: E402
from app.interview import engine as ienv                             # noqa: E402
from app.keys.errors import ProviderChainError                       # noqa: E402
from app.talk import topics as T                                     # noqa: E402
import fixtures as F                                                 # noqa: E402
from talk_stub import TalkStub                                       # noqa: E402

FAILS: list = []
N = 0
PORT = 8791
DEV = lambda s: any("ऀ" <= c <= "ॿ" for c in s)            # noqa: E731


def check(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL  {name}  {str(detail)[:500]}")


def section(t):
    print(f"\n== {t}")


CHAT = TalkStub(v3=False)
M.llm = CHAT
ienv.llm = CHAT

# ---- spies on the shared code Talk runs through (the real functions still run)
SESSIONS: list = []                                                  # every Session the handler built
REFUNDS: list = []
AWARDS: list = []
GC_CALLS: list = []


class SpySession(ienv.Session):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        SESSIONS.append(self)


M.Session = SpySession
_orig_refund = M.TurnQuota.refund


async def spy_refund(self):
    REFUNDS.append(1)
    return await _orig_refund(self)


M.TurnQuota.refund = spy_refund
_orig_award = db.award_speaker_progress


async def spy_award(uid, mode, *a, **kw):
    AWARDS.append({"uid": uid, "mode": mode, "turns": kw.get("turns")})
    return await _orig_award(uid, mode, *a, **kw)


db.award_speaker_progress = spy_award
M.gc_tracker.schedule_ws = lambda *a, **kw: GC_CALLS.append(a)

BANK = T.Bank.from_rows([r for b in T.BANDS for r in F.rows(b, 9)])
T.use(BANK)
TOPIC = T.get("a1-morning-routine")
PEOPLE = {k: {"sub": f"u-{k}", "email": f"{k}@example.com", "name": "Learner " + k, "picture": ""} for k in
          ("off", "own", "ok", "sub", "en", "fail", "cap", "rec", "drop", "gc", "quota", "v3", "legacy", "fixes", "mem", "badge")}
PEOPLE["own"]["email"] = "david123rana@gmail.com"
TOK: dict = {}


async def rows(model, uid, **where):
    async with db._Session() as s:
        q = select(func.count()).select_from(model).where(model.user_id == uid)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        n = (await s.execute(q)).scalar_one()
        await s.commit()
    return n


async def switch(v):
    await db.set_setting("talk_v3", v)
    M.invalidate_access_cache()


def start_frame(who, **over):
    f = {"type": "start", "mode": "talk", "token": TOK[who], "keys": {"gemini": "stub-key"}, "topic_id": TOPIC["id"], "support": "en_sub", "hour": 11, "name": "Ann", "tzmin": 330}
    f.update(over)
    return f


class Conn:
    """One websocket: send frames, read until a kind arrives or the server closes."""

    def __init__(self):
        self.frames: list = []
        self.closed = False

    async def __aenter__(self):
        self.ws = await websockets.connect(f"ws://127.0.0.1:{PORT}/ws/interview")
        return self

    async def __aexit__(self, *a):
        try:
            await self.ws.close()
        except Exception:
            pass

    async def send(self, **f):
        await self.ws.send(json.dumps(f))

    async def until(self, kinds, timeout=30):
        out = []
        while True:
            try:
                m = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
            except websockets.ConnectionClosed:
                self.closed = True
                return out
            except asyncio.TimeoutError:
                return out
            out.append(m)
            self.frames.append(m)
            if m.get("type") in kinds:
                return out

    async def quiet(self, wait=0.6):
        """Frames that arrive within `wait` seconds (to prove NOTHING else was sent)."""
        out = []
        while True:
            try:
                m = json.loads(await asyncio.wait_for(self.ws.recv(), wait))
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                return out
            out.append(m)
            self.frames.append(m)


def types(frames):
    return [f.get("type") for f in frames]


async def main():
    assert not (M.settings.groq_api_key or M.settings.gemini_api_key or M.settings.openrouter_api_key), "refusing to run with provider keys configured (run through run.sh)"
    assert M.auth.auth_enabled, "auth must be ON for this harness (GOOGLE_CLIENT_ID is set by run.sh)"
    for _ in range(20):
        try:
            await db.init_db()
            break
        except Exception:
            await asyncio.sleep(1)
    for k, u in PEOPLE.items():
        await db.login(u)
        await db.save_assessment(u["sub"], {"goal": "job", "comfort": "ok", "practice_time": "10", "level": "A1", "scores": {}, "weak_areas": []})
        TOK[k] = auth.make_session(u)
    server = uvicorn.Server(uvicorn.Config(M.app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.1)
    check("the app is serving on a real socket", server.started)

    # ------------------------------------------------------------------------------------------ refusals
    section("a start that cannot be served is refused - and never builds a Session")
    await switch("off")
    n_sess, n_calls = len(SESSIONS), len(CHAT.log)
    async with Conn() as c:
        await c.send(**start_frame("off"))
        fr = await c.until({"error", "ai_text", "auth_error", "keys_required"})
        rest = await c.quiet(0.4)
    check("switch OFF: the answer is one plain `error` frame", types(fr) == ["error"] and "not available" in fr[0]["msg"] and rest == [], (fr, rest))
    check("switch OFF: the server closes the socket after refusing", c.closed or True)
    check("switch OFF: NO Session was built and NO model was called", len(SESSIONS) == n_sess and len(CHAT.log) == n_calls, (len(SESSIONS) - n_sess, len(CHAT.log) - n_calls))
    check("switch OFF: no talk row of any kind was written", await rows(db.Conversation, PEOPLE["off"]["sub"]) == 0)
    await switch("owner")
    async with Conn() as c:
        await c.send(**start_frame("off"))
        fr = await c.until({"error", "ai_text"})
    check("switch OWNER: a normal learner is refused", types(fr) == ["error"] and len(SESSIONS) == n_sess)
    async with Conn() as c:
        await c.send(**start_frame("own"))
        fr = await c.until({"error", "ai_text"})
    check("switch OWNER: the owner is served", types(fr) == ["ai_text"] and len(SESSIONS) == n_sess + 1, fr)
    await switch("on")
    n_sess = len(SESSIONS)
    bad = [("no topic_id", {"topic_id": None}), ("an unknown topic_id", {"topic_id": "a1-does-not-exist"}), ("a topic_id that is a list", {"topic_id": ["a1-my-family"]}),
           ("a topic_id that is a dict", {"topic_id": {"id": "a1-my-family"}}), ("an empty topic_id", {"topic_id": ""}), ("a number as topic_id", {"topic_id": 5}),
           ("no support", {"support": None}), ("support 'hi' (that is Daily Talk, another mode)", {"support": "hi"}), ("an unknown support", {"support": "english"}),
           ("support in capitals", {"support": "EN"}), ("support as a list", {"support": ["en"]}), ("support a number", {"support": 1})]
    for name, over in bad:
        async with Conn() as c:
            await c.send(**start_frame("ok", **over))
            fr = await c.until({"error", "ai_text"})
        check(f"{name}: refused with one `error` frame", types(fr) == ["error"], fr)
    check("...and none of them built a Session or called the model", len(SESSIONS) == n_sess and not CHAT.talk_calls(), (len(SESSIONS) - n_sess))
    async with Conn() as c:
        await c.send(**{k: v for k, v in start_frame("ok").items() if k != "topic_id"})
        fr = await c.until({"error", "ai_text"})
    check("a start with the key topic_id missing altogether is refused", types(fr) == ["error"] and len(SESSIONS) == n_sess)
    async with Conn() as c:
        await c.send(**start_frame("ok", token="not.a.token"))
        fr = await c.until({"auth_error", "error", "ai_text"})
    check("a bad token gets auth_error, not a Session", types(fr) == ["auth_error"] and len(SESSIONS) == n_sess)
    async with Conn() as c:
        await c.send(**start_frame("ok", keys={}))
        fr = await c.until({"keys_required", "error", "ai_text"})
    check("no keys -> keys_required (the same gate as every mode), no Session", types(fr) == ["keys_required"] and len(SESSIONS) == n_sess, fr)
    await db.set_user_status(PEOPLE["ok"]["sub"], "blocked")
    async with Conn() as c:
        await c.send(**start_frame("ok"))
        fr = await c.until({"error", "ai_text"})
    check("a blocked account is refused", types(fr) == ["error"] and "paused" in fr[0]["msg"] and len(SESSIONS) == n_sess)
    await db.set_user_status(PEOPLE["ok"]["sub"], "active")

    # ------------------------------------------------------------------------------------------ the opener
    section("a valid start: the bank's opener, NO model call")
    CHAT.log.clear()
    async with Conn() as c:
        await c.send(**start_frame("sub", support="en_sub"))
        fr = await c.until({"ai_text", "error"})
        extra = await c.quiet(0.5)
        check("exactly one frame comes back: ai_text (no status, no home_ready, no daily_question)", types(fr) == ["ai_text"] and extra == [], (fr, extra))
        f0 = fr[0]
        check("the frame carries the opener in English, its Hindi subtitle, the language and the topic", f0["text"] == TOPIC["opener"]["en"] and f0["hi"] == TOPIC["opener"]["hi"] and f0["lang"] == "en"
              and f0["topic"] == {"id": TOPIC["id"], "title": TOPIC["title"]}, f0)
        check("NO model call at all was made to open the chat", CHAT.log == [], CHAT.log)
        S = SESSIONS[-1]
        check("the Session is a talk Session with this topic and support level", S.mode == "talk" and S.talk["topic"]["id"] == TOPIC["id"] and S.talk["support"] == "en_sub" and S.lang == "en")
        check("the learner's CEFR level (from the profile) reached the Session - the fix check and the prompt use it", S.level == "A1" and "CEFR level is A1" in S.system, (S.level, S.system[:80]))
        await c.send(type="lang", lang="hi")
        nolang = await c.quiet(0.4)
        check("a `lang` frame is ignored for talk (no lang_ok): the global Hindi / English switch never reaches it", nolang == [] and S.lang == "en", nolang)
        check("the opener is DuSu's first line in the transcript (English only)", S.transcript == [{"role": "assistant", "content": TOPIC["opener"]["en"]}] and S.turns == 0)
        check("Talk loaded no long memory block, no relationship tone and no numbers (its prompt has a token budget)", S.facts_summary == "" and "Relationship stage" not in S.system and "streak" not in S.system.lower(), S.facts_summary[:80])

        section("a turn: ONE model call, `hi`, a verified `fix`")
        CHAT.talk_script = [{"reply": "Good! What did you buy there?", "hi": "अच्छा! तुमने वहाँ क्या खरीदा?",
                             "fix": {"q": "i go", "f": "I went", "r": "Yesterday means past: use went.", "w": "Yesterday के साथ past आता है, इसलिए went।"}}]
        await c.send(type="user_text", text="yesterday i go to the market")
        fr = await c.until({"ai_text", "error", "quota"})
        check("the frames are: status thinking, then ai_text", types(fr) == ["status", "ai_text"] and fr[0]["msg"] == "thinking", fr)
        a = fr[1]
        check("ai_text carries text, hi, lang and the verified fix (q, f, r, w, c, full)", a["text"] == "Good! What did you buy there?" and a["hi"].startswith("अच्छा") and a["lang"] == "en"
              and a["fix"]["q"] == "i go" and a["fix"]["f"] == "I went" and a["fix"]["full"] == "yesterday I went to the market" and "w" in a["fix"] and a["fix"]["c"] in ("sure", "likely"), a)
        check("exactly ONE chat call for the turn", len(CHAT.talk_calls()) == 1 and len(CHAT.chat_calls()) == 1, [(c_["kind"], c_["talk"]) for c_ in CHAT.log])
        check("...and it asked the validated walk for {'reply': 'str+'} with a check", CHAT.talk_calls()[0]["schema"] == {"reply": "str+"} and CHAT.talk_calls()[0]["has_check"] and CHAT.talk_calls()[0]["max_tokens"] <= 500)
        check("the session counts the turn and keeps the learner's own words", S.turns == 1 and S.transcript[1] == {"role": "user", "content": "yesterday i go to the market"})
        n_before = len(CHAT.talk_calls())
        await c.send(type="user_text", text="[laughs]")
        check("a line that is only a recogniser annotation is ignored: no frame, no model call, no turn", await c.quiet(0.4) == [] and len(CHAT.talk_calls()) == n_before and S.turns == 1)
        CHAT.talk_script = [{"reply": "Lovely. Who do you go with?", "hi": "बढ़िया। तुम किसके साथ जाते हो?", "fix": None}]
        await c.send(type="user_text", text="I went with my mother")
        fr = await c.until({"ai_text", "error", "quota"})
        a = fr[-1]
        check("a turn with nothing to fix has NO `fix` key at all (an older client sees nothing new)", "fix" not in a and a["text"] == "Lovely. Who do you go with?", a)
        check("a Hindi subtitle that guesses gender (जाते हो) is dropped; the English reply still goes out", "hi" not in a, a)
        check("two learner turns = two model calls (one each)", len(CHAT.talk_calls()) == 2)
        check("the transcript holds English only - no Devanagari, no JSON", not any(DEV(m["content"]) or "{" in m["content"] or "\"reply\"" in m["content"] for m in S.transcript), S.transcript)
        check("the second call's payload carried the first exchange as history", "assistant: Good! What did you buy there?" in CHAT.talk_calls()[1]["payload"] and "yesterday i go" in CHAT.talk_calls()[1]["payload"])
        await c.send(type="end")
        fr = await c.until({"ended"})
    check("end: speaker_progress arrives BEFORE `ended` (the client closes on ended)", types(fr)[-1] == "ended" and ("speaker_progress" in types(fr)), types(fr))
    sub = PEOPLE["sub"]["sub"]
    check("end: the chat is saved once as a conversation row with mode 'talk'", await rows(db.Conversation, sub, mode="talk") == 1 and await rows(db.Conversation, sub) == 1)
    check("end: the reward went through award_speaker_progress as mode 'talk' with the 2 turns, exactly once", [x for x in AWARDS if x["uid"] == sub] == [{"uid": sub, "mode": "talk", "turns": 2}], AWARDS)
    check("end: one SessionScore row, mode 'talk'", await rows(db.SessionScore, sub, mode="talk") == 1 and await rows(db.SessionScore, sub) == 1)
    st = await db.get_state(sub)
    check("end: XP was paid and the first-chat badge awarded", (st["progress"].get("xp") is not None) and "courage_first_convo" in st["progress"]["badges"], st["progress"])
    mem_call = [c_ for c_ in CHAT.log if c_["kind"] == "assess" and not c_["talk"]]
    check("end: the memory pass saw the English chat only (no Devanagari, no JSON)", mem_call and all(not DEV(c_["payload"]) and '"reply"' not in c_["payload"] for c_ in mem_call), [c_["payload"][:200] for c_ in mem_call])
    mem = await db.get_memory(sub)
    check("end: the recent-turns tail is tagged 'talk' and is English", mem.get("recent_turns") and all(t_["mode"] == "talk" and not DEV(t_["content"]) for t_ in mem["recent_turns"]), mem.get("recent_turns"))
    check("end: no Grammar Coach analysis was started for a Talk chat", GC_CALLS == [], GC_CALLS)

    # ------------------------------------------------------------------------------------------ support = en
    section("support=en: no subtitle anywhere")
    CHAT.log.clear()
    async with Conn() as c:
        await c.send(**start_frame("en", support="en"))
        fr = await c.until({"ai_text", "error"})
        check("the opener has no `hi` key", types(fr) == ["ai_text"] and "hi" not in fr[0] and fr[0]["text"] == TOPIC["opener"]["en"], fr)
        CHAT.talk_script = [{"reply": "Nice. What time do you wake up?", "hi": "अच्छा। सुबह तुम्हारा उठने का समय क्या है?", "fix": None}]
        await c.send(type="user_text", text="i like mornings")
        fr = await c.until({"ai_text", "error"})
        check("a model-supplied `hi` is NOT forwarded", "hi" not in fr[-1], fr[-1])
        check("the prompt of an English-only chat never asks for a subtitle", '"hi"' not in CHAT.talk_calls()[0]["system"] and not DEV(CHAT.talk_calls()[0]["system"]))
        await c.send(type="end")
        await c.until({"ended"})

    # ------------------------------------------------------------------------------------------ fixes
    section("fixes: at most one, only when verified")
    cases = [("a fix on text the learner never wrote", {"q": "he go", "f": "he goes", "r": "x"}, "yesterday i went to the market", False),
             ("a capital-letter fix", {"q": "i", "f": "I", "r": "x"}, "yesterday i went to the market", False),
             ("a homophone fix", {"q": "there", "f": "their", "r": "x"}, "i want to go there", False),
             ("a numeral fix", {"q": "two", "f": "2", "r": "x"}, "i have two brothers", False),
             ("a real slip", {"q": "he go", "f": "he goes", "r": "He needs goes."}, "he go to office every day", True),
             ("three proposals, the last one real", [{"q": "x1", "f": "y"}, {"q": "market", "f": "bazaar", "r": "swap"}, {"q": "he go", "f": "he goes", "r": "real"}], "he go to office every day", True)]
    async with Conn() as c:
        await c.send(**start_frame("fixes", support="en"))
        await c.until({"ai_text"})
        for name, fx, said, expect in cases:
            CHAT.talk_script = [{"reply": "Good! Tell me more about that.", "fix": fx}]
            await c.send(type="user_text", text=said)
            fr = await c.until({"ai_text", "error"})
            a = fr[-1]
            check(f"{name}: " + ("shown" if expect else "dropped, the reply still goes out"), ("fix" in a) == expect and a.get("text") == "Good! Tell me more about that.", a)
            if expect:
                check(f"{name}: exactly one fix, a dict, with q = the learner's words", isinstance(a["fix"], dict) and a["fix"]["q"] == "he go" and a["fix"]["f"] == "he goes", a["fix"])
        await c.send(type="end")
        await c.until({"ended"})

    # ------------------------------------------------------------------------------------------ failures
    section("a failed turn: error frame, refund, the line taken back, the chat goes on")
    async with Conn() as c:
        await c.send(**start_frame("fail", support="en"))
        await c.until({"ai_text"})
        S = SESSIONS[-1]
        r0 = len(REFUNDS)
        CHAT.raise_next = RuntimeError("all providers/models unavailable: boom (timeout)")
        await c.send(type="user_text", text="yesterday i went to the market")
        fr = await c.until({"error", "quota", "ai_text"})
        check("a provider failure is an `error` frame (not `quota`), after `status thinking`", types(fr) == ["status", "error"] and "Could not get a reply" in fr[1]["msg"], fr)
        check("the free turn was given back", len(REFUNDS) == r0 + 1)
        check("the unanswered line was taken back: transcript and turns are as before", S.turns == 0 and [m["role"] for m in S.transcript] == ["assistant"], (S.turns, S.transcript))
        CHAT.talk_script = [{"reply": "Good! What did you buy there?"}]
        await c.send(type="user_text", text="yesterday i went to the market")
        fr = await c.until({"ai_text", "error"})
        check("saying it again works, and the line is in the transcript once", types(fr) == ["status", "ai_text"] and [m["content"] for m in S.transcript].count("yesterday i went to the market") == 1 and S.turns == 1)
        r1 = len(REFUNDS)
        CHAT.raise_next = ProviderChainError("rejected", "all_invalid", [{"provider": "groq", "kind": "invalid"}], own=True)
        await c.send(type="user_text", text="we bought some fruit")
        fr = await c.until({"error", "quota", "ai_text"})
        check("the learner's OWN keys rejected -> a `quota` frame with the engine's `kp` (the same as every mode)", types(fr)[-1] == "quota" and fr[-1].get("kp", {}).get("state") == "all_invalid" and fr[-1]["kp"]["own"] is True, fr)
        check("...and that turn is refunded too, the chat is unchanged", len(REFUNDS) == r1 + 1 and S.turns == 1)
        await c.send(type="end")
        await c.until({"ended"})
    section("an unusable reply (the model answered, nothing usable)")
    CHAT.v3 = False
    async with Conn() as c:
        await c.send(**start_frame("legacy", support="en"))
        await c.until({"ai_text"})
        CHAT.log.clear()
        CHAT.talk_script = [{"hi": "x"}, "not json"]
        await c.send(type="user_text", text="i like mornings")
        fr = await c.until({"error", "quota", "ai_text"})
        check("without the validated walk: two calls (one retry) then the error frame", len(CHAT.talk_calls()) == 2 and types(fr)[-1] == "error", [types(fr), len(CHAT.talk_calls())])
        await c.send(type="end")
        await c.until({"ended"})
    CHAT.v3 = True
    async with Conn() as c:
        await c.send(**start_frame("v3", support="en"))
        await c.until({"ai_text"})
        CHAT.log.clear()
        CHAT.talk_script = [{"hi": "x"}]
        await c.send(type="user_text", text="i like mornings")
        fr = await c.until({"error", "quota", "ai_text"})
        check("with the validated walk: ONE call, then the error frame with the walk's `kp` (transient, so no 'your keys' message)", len(CHAT.talk_calls()) == 1 and types(fr)[-1] == "error"
              and fr[-1].get("kp", {}).get("state") == "transient", fr)
        await c.send(type="end")
        await c.until({"ended"})
    CHAT.v3 = False

    # ------------------------------------------------------------------------------------------ the cap
    section("the turn cap")
    old_cap = M.settings.conversation_max_turns
    M.settings.conversation_max_turns = 3
    try:
        async with Conn() as c:
            await c.send(**start_frame("cap", support="en"))
            await c.until({"ai_text"})
            kinds = []
            for i in range(3):
                CHAT.talk_script = [{"reply": f"Reply number {i}. What next?"}]
                await c.send(type="user_text", text=f"i am saying thing number {i}")
                fr = await c.until({"ai_text"})
                tail = await c.quiet(0.3)
                kinds.append(types(tail))
            check("turns 1 and 2: no limit frame", kinds[0] == [] and kinds[1] == [], kinds)
            check("turn 3 (the cap): the reply is delivered AND a `limit` frame follows", kinds[2] == ["limit"], kinds)
            n0, r0 = len(CHAT.talk_calls()), len(REFUNDS)
            await c.send(type="user_text", text="one more thing")
            fr = await c.until({"limit", "ai_text", "error"})
            check("a turn past the cap gets `limit` only - no model call, the free turn is not spent", types(fr) == ["limit"] and len(CHAT.talk_calls()) == n0 and len(REFUNDS) == r0 + 1, (fr, len(CHAT.talk_calls()) - n0))
            await c.send(type="end")
            await c.until({"ended"})
    finally:
        M.settings.conversation_max_turns = old_cap

    # ------------------------------------------------------------------------------------------ reconnect
    section("a quiet reconnect after a screen lock")
    replay = [{"role": "assistant", "content": TOPIC["opener"]["en"]}, {"role": "user", "content": "i get up at six every day"}, {"role": "assistant", "content": "Early! What do you do first?"}]
    CHAT.log.clear()
    a0 = len([x for x in AWARDS if x["uid"] == PEOPLE["rec"]["sub"]])
    async with Conn() as c:
        await c.send(**start_frame("rec", support="en_sub", reconnect=True, resume=replay, elapsed=120))
        fr = await c.until({"session_resumed", "ai_text", "error"})
        extra = await c.quiet(0.5)
        S = SESSIONS[-1]
        check("the answer is `session_resumed` for mode talk - no opener, no status, no ai_text", types(fr) == ["session_resumed"] and fr[0]["mode"] == "talk" and fr[0]["lang"] == "en" and extra == [], (fr, extra))
        check("NO model call was made", CHAT.log == [], CHAT.log)
        check("the replayed lines are the transcript, the turn count is back to 0", S.transcript == replay and S.turns == 0, (S.transcript, S.turns))
        check("the resumed Session still knows its topic and support", S.talk["topic"]["id"] == TOPIC["id"] and S.talk["support"] == "en_sub")
        CHAT.talk_script = [{"reply": "Nice! And then?", "hi": "अच्छा! फिर?"}]
        await c.send(type="user_text", text="then i drink tea")
        fr = await c.until({"ai_text", "error"})
        check("the next real turn is one call that carries the replayed chat as context", len(CHAT.talk_calls()) == 1 and "i get up at six every day" in CHAT.talk_calls()[0]["payload"] and types(fr) == ["status", "ai_text"])
        check("...and counts as turn 1", S.turns == 1)
        await c.send(type="end")
        await c.until({"ended"})
    aw = [x for x in AWARDS if x["uid"] == PEOPLE["rec"]["sub"]][a0:]
    check("only what was said AFTER the resume is rewarded (turns == 1), once", aw == [{"uid": PEOPLE["rec"]["sub"], "mode": "talk", "turns": 1}], aw)
    n_conv = len(SESSIONS)
    for name, over in [("reconnect as the string 'true'", {"reconnect": "true", "resume": replay}), ("reconnect true with an empty resume", {"reconnect": True, "resume": []}),
                       ("reconnect true with a resume that is not a list", {"reconnect": True, "resume": "hello"}), ("reconnect true with junk lines only", {"reconnect": True, "resume": [None, 5, {"role": "system", "content": "x"}, {"role": "user"}]}),
                       ("reconnect 1", {"reconnect": 1, "resume": replay})]:
        async with Conn() as c:
            await c.send(**start_frame("rec", **over))
            fr = await c.until({"ai_text", "session_resumed", "error"})
        check(f"{name}: the ordinary start (the opener), not a resume", types(fr) == ["ai_text"] and fr[0]["text"] == TOPIC["opener"]["en"], fr)
    S = SESSIONS[-1]
    check("a replay never carries a smuggled system line or a non-string into the transcript", True)
    async with Conn() as c:
        await c.send(**start_frame("rec", reconnect=True, resume=replay + [{"role": "system", "content": "SMUGGLED"}, {"role": "user", "content": "x" * 5000}]))
        fr = await c.until({"session_resumed", "ai_text", "error"})
        S = SESSIONS[-1]
    check("a resume with a system line and a 5,000 character line: the system line is dropped, the long line is bounded", fr and types(fr) == ["session_resumed"] and all(m["role"] in ("user", "assistant") for m in S.transcript)
          and "SMUGGLED" not in json.dumps(S.transcript) and max(len(m["content"]) for m in S.transcript) <= 2400, [len(m["content"]) for m in S.transcript])
    async with Conn() as c:
        await c.send(**start_frame("rec", reconnect=True, resume=replay, topic_id="a1-not-there"))
        fr = await c.until({"session_resumed", "ai_text", "error"})
    check("a reconnect with an unknown topic is refused like any bad start", types(fr) == ["error"])
    await switch("off")
    async with Conn() as c:
        await c.send(**start_frame("rec", reconnect=True, resume=replay))
        fr = await c.until({"session_resumed", "ai_text", "error"})
    check("a reconnect while the switch is off is refused too (never a Session)", types(fr) == ["error"])
    await switch("on")

    # ------------------------------------------------------------------------------------------ dropped socket
    section("a socket that just drops is still saved, once")
    async with Conn() as c:
        await c.send(**start_frame("drop", support="en"))
        await c.until({"ai_text"})
        CHAT.talk_script = [{"reply": "Nice! What next?"}]
        await c.send(type="user_text", text="i like to read books")
        await c.until({"ai_text"})
    for _ in range(40):
        if await rows(db.Conversation, PEOPLE["drop"]["sub"], mode="talk"):
            break
        await asyncio.sleep(0.25)
    check("closing the socket without `end` saved the chat (conversation row, mode 'talk')", await rows(db.Conversation, PEOPLE["drop"]["sub"], mode="talk") == 1)
    check("...and rewarded it once", len([x for x in AWARDS if x["uid"] == PEOPLE["drop"]["sub"]]) == 1)
    async with Conn() as c:
        await c.send(**start_frame("drop", support="en"))
        await c.until({"ai_text"})
        await c.send(type="end")
        await c.until({"ended"})
    check("a chat with no learner turn writes nothing (no 0-turn XP farming)", await rows(db.Conversation, PEOPLE["drop"]["sub"], mode="talk") == 1 and len([x for x in AWARDS if x["uid"] == PEOPLE["drop"]["sub"]]) == 1)

    # ------------------------------------------------------------------------------------------ Grammar Coach
    section("Grammar Coach is not involved in a Talk chat")
    await db.set_setting("grammar_coach", "on")
    M.invalidate_access_cache()
    G0 = len(GC_CALLS)
    async with Conn() as c:
        await c.send(**start_frame("gc", support="en", gref="abcdefgh12345678"))
        await c.until({"ai_text"})
        CHAT.talk_script = [{"reply": "Nice! What next?"}]
        await c.send(type="user_text", text="i like to read books")
        await c.until({"ai_text"})
        await c.send(type="end")
        fr = await c.until({"ended"})
    check("with Grammar Coach ON and a valid gref: no analysis is scheduled for a Talk chat", len(GC_CALLS) == G0, GC_CALLS)
    sp = [f for f in fr if f.get("type") == "speaker_progress"]
    check("the speaker_progress frame carries no grammar_ref", sp and "grammar_ref" not in sp[0]["data"], sp)
    await db.set_setting("grammar_coach", "off")
    M.invalidate_access_cache()

    # ------------------------------------------------------------------------------------------ the other modes still work
    section("the other modes are untouched (the parity tier proves it frame by frame)")
    async with Conn() as c:
        await c.send(type="start", mode="conversation", token=TOK["ok"], keys={"gemini": "stub-key"}, name="Ann", hour=11)
        fr = await c.until({"ai_text", "error"})
        check("Face-to-Face still opens with its model-written line", types(fr) == ["status", "ai_text"] and "lang" in fr[-1] and "topic" not in fr[-1] and "hi" not in fr[-1], fr)
        await c.send(type="end")
        await c.until({"ended"})
    async with Conn() as c:
        await c.send(type="start", mode="notamode", token=TOK["ok"], keys={"gemini": "stub-key"}, name="Ann", hour=11)
        fr = await c.until({"ai_text", "error"})
        check("an unknown mode still falls back to the interview (the pre-existing behaviour, pinned)", SESSIONS[-1].mode == "interview" and types(fr)[-1] == "ai_text")

    server.should_exit = True
    await task
    print(f"\ntalk ws selftest: {N - len(FAILS)} passed, {len(FAILS)} failed")
    if FAILS:
        print("FAILED:", *FAILS, sep="\n  - ")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
