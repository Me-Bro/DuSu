'use strict';
/*
 * "The AI did not answer" - what the learner sees and can do. Real Chromium -> a WebSocket proxy -> the REAL server (scratch Postgres, scripted fake providers).
 *
 * Before: one failed turn showed the SAME problem twice (a small amber banner at the very top that vanished after 10 s, and - on Home - a grey English sentence in the chat),
 * left the mic dead (Face-to-Face / Interview / Practice talk had no way to continue at all) and lost the words (Home: retype, Daily / Learn: speak again).
 * Now ONE bottom pop-up says what happened in plain words, counts down honestly (the provider's own wait when it gave one), resends the SAME words once by itself and keeps a
 * button for the learner; "Later" leaves a handle (a chip on Home, a tap on DuSu on the voice screens). It is never the learner's key, never a banner, never English in a Hindi chat.
 *
 *   tests/daily_voice/browser/run_real.sh busy.spec.cjs        ONLY=B1,B5 runs just those scenarios
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('the AI did not answer: one pop-up, a countdown, the same words again');
const { T, sleep, until } = L;

const PROVIDERS = ['groq', 'gemini', 'openrouter'];
const allDown = async () => { for (const p of PROVIDERS) await L.behave(p, 'down'); };
const allOk = async () => { for (const p of PROVIDERS) await L.behave(p, 'ok'); };
const sheetOn = page => L.vis(page, '#kySheet.on');
const bannerUp = page => page.evaluate(() => { const b = document.getElementById('notifBar'); return !!b && !b.hidden && getComputedStyle(b).display !== 'none'; });
const feedSys = page => page.evaluate(() => [...document.querySelectorAll('#feed .sysmsg')].map(e => e.textContent.trim()));
const dailySys = page => page.evaluate(() => [...document.querySelectorAll('#dailyFeed .sysmsg')].map(e => e.textContent.trim()));
const count = page => L.txt(page, '#kyCount');
const title = page => L.txt(page, '#kyTitle');
const rows = page => page.evaluate(() => document.querySelectorAll('#kySheet .ky-k').length);
const chip = page => L.vis(page, '#hmRetry');
const keysText = page => L.txt(page, '#kyKeys');
const planCard = page => L.vis(page, '#kySheet .ky-plan');
const blocks = page => page.evaluate(() => ({ keys: !!document.getElementById('kyKeys') && document.getElementById('kyKeys').children.length > 0, sections: document.querySelectorAll('#kySheet .ky-sec').length, rows: document.querySelectorAll('#kySheet .ky-k').length }));
const later = page => page.click('#kySheet .ky-pop-acts .btn:last-child');
const tryNow = page => page.click('#kySheet .ky-pop-acts .btn.primary');
const userTexts = P => P.conns.flatMap(c => c.out('user_text')).map(j => j.text);
const en = who => L.post('/lang', { token: L.TOK[who].token, lang: 'en' });
const hi = who => L.post('/lang', { token: L.TOK[who].token, lang: 'hi' });

async function scenario(browser, name, who, fn, o = {}) {
  if (process.env.ONLY && !process.env.ONLY.split(',').some(k => name.startsWith(k + ' '))) return;
  T.section(name);
  let ctx;
  try {
    await allOk();
    await (o.lang === 'hi' ? hi(who) : en(who));
    ctx = await L.ctxFor(browser, who, o);
    const P = await L.proxy(ctx);
    const page = await L.boot(ctx, '/');
    await fn({ page, P, who, ctx });
    const e = await page.evaluate(() => ({ errors: window.__errors, rejections: window.__rejections }));
    T.eq(e.errors, [], name + ': no script error');
    T.eq(e.rejections, [], name + ': no unhandled rejection');
  } catch (e) {
    T.ok(false, name + ': the scenario threw: ' + String((e && e.message) || e).slice(0, 300));
  } finally {
    try { await ctx.close(); } catch (e) { /* closed */ }
    await allOk();
    await L.post('/__world/serverkeys', { on: false });                              // a scenario that threw must not leave DuSu's own chain switched on for the next one
  }
}

/** The page shows exactly what it should for "the AI did not answer": one pop-up, no banner, a countdown from the server's own number. */
async function checkSheet(page, label, o = {}) {
  T.ok(await until(() => sheetOn(page), 25000), label + ': the pop-up opens');
  T.ok(!(await bannerUp(page)), label + ': the small top banner is NOT shown');
  T.ok(/taking longer than usual|आने में देर/.test((await title(page)) || ''), label + ': the title says the reply is late (' + JSON.stringify(await title(page)) + ')');
  const full = (await L.txt(page, '#kySheet')) || '';
  T.ok(!/keys are fine|keys ठीक हैं|AI is busy|AI busy/.test(full), label + ': no jargon and no claim DuSu cannot know ("AI busy", "your keys are fine")');
  T.ok(/isn't your fault|कोई गलती नहीं/.test(full), label + ': it says plainly that it is not the learner\'s fault');
  if (o.countdown !== false) T.ok(/(^|\D)[56](\D|$)/.test((await count(page)) || ''), label + ': the countdown starts from the server\'s number (6, ticking): ' + JSON.stringify(await count(page)));
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    await L.post('/__world/reset', { settings: { home_ai: 'on', practice_room: 'on', bilingual: 'on' } });

    // ================================================================================================ B. Home chat
    await scenario(browser, 'B1 Home chat (typed): one pop-up, no banner, no English line; the countdown sends the SAME words again and the answer arrives', 'lk1', async ({ page, P }) => {
      await allDown();
      await L.openHome(page, { typed: 'Hh', noWait: true });
      await checkSheet(page, 'B1');
      T.eq(await rows(page), 2, 'B1: the learner\'s own two keys are listed (Groq, Gemini) - every key, not only the broken ones');
      T.ok(await planCard(page), 'B1: a gentle way to the plans is on the pop-up');
      T.eq(await feedSys(page), [], 'B1: NO second message in the chat (it used to print the server\'s English sentence)');
      T.ok(await chip(page), 'B1: the words stay on screen with a "send again" chip');
      const f = P.last.in('home_error')[0];
      T.ok(f && f.kp && f.kp.state === 'transient' && f.kp.own === true && f.kp.retry_in === 6, 'B1: the server frame is home_error (never quota) with kp transient, own, retry_in 6: ' + JSON.stringify(f && f.kp));
      T.eq(P.last.in('quota').length, 0, 'B1: no quota frame at all');
      T.eq(await L.userN(page), 1, 'B1: the learner\'s line is on screen once');
      const a0 = await L.aiN(page);
      await allOk();                                                                // the AI is back before the countdown ends
      T.ok(await until(() => L.aiN(page).then(n => n > a0), 15000), 'B1: after the countdown the SAME words went out again and DuSu answered (a new line from her)');
      T.ok(await until(async () => !(await sheetOn(page)), 4000), 'B1: the pop-up closed by itself');
      T.ok(!(await chip(page)), 'B1: the chip is gone');
      T.eq(userTexts(P), ['Hh', 'Hh'], 'B1: exactly two user_text frames, the same words');
      T.eq(await L.userN(page), 1, 'B1: still ONE bubble for the learner (nothing was typed or shown twice)');
      T.ok(!(await bannerUp(page)), 'B1: no banner at the end either');
    });

    await scenario(browser, 'B1b the provider is wholly down, so a check cannot answer: the chips say "Couldn\'t check right now" - never Working on an old check, never Checking for ever', 'lk23', async ({ page }) => {
      const rc = await fetch(L.BASE + '/keys/recheck', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + L.TOK.lk23.token }, body: '{}' }).then(r => r.json());
      T.ok(rc.keys.length === 2 && rc.keys.every(k => k.status === 'ok'), 'B1b: first both keys are checked while the providers are fine: both are ok on the server (an OLD "Working" that the pop-up must not repeat)');
      await allDown();
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => sheetOn(page), 25000), 'B1b: the pop-up opens');
      T.ok(await until(async () => (((await keysText(page)) || '').match(/Couldn't check right now/g) || []).length === 2, 8000), 'B1b: both keys: "Couldn\'t check right now": ' + JSON.stringify(await keysText(page)));
      T.ok(!/Working|Your keys are working/.test((await L.txt(page, '#kySheet')) || ''), 'B1b: and nothing says Working');
    });

    await scenario(browser, 'B2 Home chat: a second failure keeps the button and stops there (no loop); the button then works', 'lk2', async ({ page, P }) => {
      await allDown();
      await L.openHome(page, { typed: 'Hello there', noWait: true });
      await checkSheet(page, 'B2');
      T.ok(await until(() => userTexts(P).length === 2, 15000), 'B2: the automatic retry went out once');
      T.ok(await until(async () => /Still no answer|अब भी जवाब नहीं आया/.test((await L.txt(page, '#kySheet')) || '') && (await count(page)) === null, 20000), 'B2: still failing -> "Still no answer", NO countdown');
      await sleep(9000);
      T.eq(userTexts(P).length, 2, 'B2: nothing was sent behind the learner\'s back after that (9 s later: still two)');
      T.ok(await sheetOn(page), 'B2: the pop-up is still there, with its button');
      const a0 = await L.aiN(page);
      await allOk();
      await tryNow(page);
      T.ok(await until(() => L.aiN(page).then(n => n > a0), 15000), 'B2: the button sent the same words again and DuSu answered');
      T.ok(await until(async () => !(await sheetOn(page)), 4000), 'B2: the pop-up closed');
      T.eq(userTexts(P), ['Hello there', 'Hello there', 'Hello there'], 'B2: three frames, always the same words');
    });

    await scenario(browser, 'B3 Home chat: "Later" leaves the chip; the chip sends the same words again', 'lk3', async ({ page, P }) => {
      await allDown();
      await L.openHome(page, { typed: 'Good morning', noWait: true });
      await checkSheet(page, 'B3');
      await later(page); await sleep(400);
      T.ok(!(await sheetOn(page)), 'B3: Later closes the pop-up');
      T.ok(await chip(page), 'B3: the chip is still there');
      await sleep(8000);
      T.eq(userTexts(P).length, 1, 'B3: after "Later" nothing is sent by itself (the countdown died with the pop-up)');
      const a0 = await L.aiN(page);
      await allOk();
      await page.click('#hmRetry');
      T.ok(await until(() => L.aiN(page).then(n => n > a0), 15000), 'B3: the chip sent the same words again and DuSu answered');
      T.ok(!(await chip(page)), 'B3: the chip is gone');
      T.eq(userTexts(P), ['Good morning', 'Good morning'], 'B3: the same words');
    });

    await scenario(browser, 'B4 Home chat (voice): the mic stays off while the pop-up is open, then carries on after the answer', 'lk4', async ({ page, P }) => {
      await L.openHome(page);
      await allDown();
      await page.evaluate(() => window.__say('how are you today'));
      await checkSheet(page, 'B4');
      const starts = await page.evaluate(() => window.__srStarts);
      await sleep(2500);
      T.eq(await page.evaluate(() => window.__srStarts), starts, 'B4: no recogniser starts while the pop-up is open (the learner decides first)');
      T.ok(!(await L.listening(page)), 'B4: nothing listens');
      await allOk();
      T.ok(await until(() => L.aiN(page).then(n => n >= 2), 15000), 'B4: the same words went out again and DuSu answered');
      T.ok(await until(() => L.listening(page), 10000), 'B4: and the mic is back after she has spoken');
      T.eq(userTexts(P), ['how are you today', 'how are you today'], 'B4: the same words twice, nothing else');
    });

    // ================================================================================================ C. Face-to-Face / Interview / a Practice viva
    await scenario(browser, 'C1 Face-to-Face: a failed turn - one pop-up, the orb says "Try again", the SAME words go out once, the voice loop carries on', 'lk5', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I like cricket a lot'), 'C1: a normal turn works first');
      T.ok(await until(() => L.listening(page), 10000), 'C1: the mic is back');
      const sys0 = await feedSys(page);                                             // (Face-to-Face shows a headphones tip of its own)
      await allDown();
      await page.evaluate(() => window.__say('my favourite food is biryani'));
      await checkSheet(page, 'C1');
      T.eq(await feedSys(page), sys0, 'C1: no second message in the chat (nothing was added)');
      T.eq(await L.txt(page, '#stateLabel'), 'Try again', 'C1: the orb says what to do (it used to say "Error")');
      T.eq(await L.txt(page, '#stateHint'), 'Tap DuSu', 'C1: ... and how');
      const f = P.last.in('error').slice(-1)[0];
      T.ok(f && f.kp && f.kp.state === 'transient', 'C1: an `error` frame with kp transient (never quota)');
      T.ok(!(await L.listening(page)), 'C1: the mic is off while the pop-up is open');
      await allOk();
      T.ok(await until(() => L.aiN(page).then(n => n >= 3), 20000), 'C1: after the countdown DuSu answered the same words');
      T.ok(await until(() => L.listening(page), 10000), 'C1: and the voice loop is back');
      T.eq(userTexts(P), ['I like cricket a lot', 'my favourite food is biryani', 'my favourite food is biryani'], 'C1: the failed line went out twice - and ONLY that line');
      T.eq(await L.userN(page), 2, 'C1: two learner bubbles on screen (not three)');
    });

    await scenario(browser, 'C2 Face-to-Face: "Later", then a tap on DuSu sends the same words again', 'lk6', async ({ page, P }) => {
      await L.openTalk(page);
      await allDown();
      await page.evaluate(() => window.__say('I work in Pune'));
      await checkSheet(page, 'C2');
      await later(page); await sleep(500);
      T.eq(await L.txt(page, '#stateLabel'), 'Try again', 'C2: the orb still says "Try again"');
      await allOk();
      await page.click('#orb');
      T.ok(await until(() => L.aiN(page).then(n => n >= 2), 15000), 'C2: a tap on DuSu sent the same words again and she answered');
      T.ok(await until(() => L.listening(page), 10000), 'C2: the mic is back');
      T.eq(userTexts(P), ['I work in Pune', 'I work in Pune'], 'C2: the same words');
    });

    await scenario(browser, 'C3 Face-to-Face: the OPENING fails (the server closes the chat) - the pop-up offers to open it again', 'lk7', async ({ page, P }) => {
      await allDown();
      await L.openTalk(page, { noWait: true });
      await checkSheet(page, 'C3');
      await allOk();
      T.ok(await until(() => L.aiN(page).then(n => n >= 1), 20000), 'C3: after the countdown the chat was opened again and DuSu greeted');
      T.ok(await until(() => L.listening(page), 10000), 'C3: and the mic listens');
      T.ok(await until(async () => !(await sheetOn(page)), 4000), 'C3: the pop-up closed');
      T.ok(P.conns.length >= 2, 'C3: a new socket was used (' + P.conns.length + ')');
    });

    await scenario(browser, 'C4 Interview: a failed turn is retried with the same words', 'lk8', async ({ page, P }) => {
      await L.openInterview(page);
      await allDown();
      await page.evaluate(() => window.__say('I have three years of experience in backend development'));
      await checkSheet(page, 'C4');
      await allOk();
      T.ok(await until(() => L.aiN(page).then(n => n >= 2), 15000), 'C4: the interviewer answered the same words');
      T.eq(userTexts(P), ['I have three years of experience in backend development', 'I have three years of experience in backend development'], 'C4: the same words');
    });

    await scenario(browser, 'C5 Practice viva: a failed turn is retried with the same words', 'lk9', async ({ page, P }) => {
      await L.openViva(page);
      await allDown();
      await page.evaluate(() => window.__say('a database stores structured data'));
      await checkSheet(page, 'C5');
      await allOk();
      T.ok(await until(() => L.aiN(page).then(n => n >= 2), 15000), 'C5: the examiner answered the same words');
      T.eq(userTexts(P).length, 2, 'C5: two frames, one line');
    });

    // ================================================================================================ D. Daily Talk and Learn
    await scenario(browser, 'D1 Daily Talk: a failed turn - one pop-up, no system line in the chat, the SAME words go out again, the answer lands on the same bubble', 'lk10', async ({ page, P }) => {
      await L.openDaily(page);
      await allDown();
      await page.evaluate(() => { window.__utter.push('main bazaar gaya tha'); });
      await page.click('#dailyMic');
      await checkSheet(page, 'D1');
      T.eq(await dailySys(page), [], 'D1: no second message in the chat');
      T.eq(await L.txt(page, '#dailyState'), 'Tap the mic and try again.', 'D1: only the short "tap the mic" cue under the mic');
      T.ok(await L.micOn(page), 'D1: the mic is handed back');
      T.eq((await L.bubbles(page)).me, 1, 'D1: the learner\'s words are on screen once');
      await allOk();
      T.ok(await until(() => page.evaluate(() => !document.getElementById('dailyCard').hidden), 15000), 'D1: after the countdown the same words were answered (the card shows)');
      T.ok(await until(async () => !(await sheetOn(page)), 4000), 'D1: the pop-up closed');
      T.eq(await L.bubbles(page), { me: 1, ai: 2 }, 'D1: one learner bubble, the greeting and ONE answer (nothing duplicated)');
      T.eq(userTexts(P), ['main bazaar gaya tha', 'main bazaar gaya tha'], 'D1: the same words twice');
    });

    await scenario(browser, 'D2 Daily Talk: the OPENING fails - the pop-up opens it again', 'lk11', async ({ page, P }) => {
      await allDown();
      await L.openDaily(page, { noWait: true });
      await checkSheet(page, 'D2');
      await allOk();
      T.ok(await until(() => page.evaluate(() => document.querySelectorAll('#dailyFeed .msg.ai').length >= 1), 20000), 'D2: after the countdown DuSu greeted');
      T.ok(await until(() => L.micOn(page), 12000), 'D2: and the mic is handed over');
      T.ok(await until(async () => !(await sheetOn(page)), 4000), 'D2: the pop-up closed');
    });

    await scenario(browser, 'D3 Learn: a failed translation - one pop-up, nothing spoken in English, the same words are translated again', 'lk12', async ({ page, P }) => {
      await page.evaluate(() => startLearning());
      T.ok(await until(() => page.evaluate(() => !document.getElementById('micBtn').disabled), 15000), 'D3: Learn handed the mic over');
      await allDown();
      await page.evaluate(() => { window.__utter.push('mujhe market jaana hai'); });
      const spoken0 = (await L.spoken(page)).length;
      await page.click('#micBtn');
      await checkSheet(page, 'D3');
      T.eq((await L.spoken(page)).slice(spoken0).filter(t => /unavailable|Translation/i.test(t)), [], 'D3: the failure is NOT spoken aloud in English');
      T.eq(await L.txt(page, '#learnState'), 'Translation failed — tap the mic to try again.', 'D3: the short cue under the mic');
      await allOk();
      T.ok(await until(() => page.evaluate(() => !document.getElementById('transCard').hidden), 15000), 'D3: after the countdown the same words were translated');
      T.ok(await until(async () => !(await sheetOn(page)), 4000), 'D3: the pop-up closed');
      T.eq(userTexts(P), ['mujhe market jaana hai', 'mujhe market jaana hai'], 'D3: the same words twice');
    });

    // ================================================================================================ E. whose keys, whose fault
    await scenario(browser, 'E1 DuSu\'s OWN keys, seen by the OWNER: each key valid or invalid with the provider\'s own reason - and nobody else gets it', 'owner', async ({ page, P }) => {
      await L.post('/__world/serverkeys', { on: true });
      await L.behave('groq', 'invalid'); await L.behave('gemini', 'forbidden'); await L.behave('openrouter', 'ok');
      const hh = (await L.post('/__world/serverhealth')).body.health;
      T.ok(hh.groq.status === 'invalid' && hh.gemini.status === 'forbidden' && hh.openrouter.status === 'ok', 'E1: DuSu\'s own keys, checked now: Groq rejected, Gemini refused every chat call, OpenRouter ok: ' + JSON.stringify(hh));
      await L.behave('openrouter', 'chat_down');
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => sheetOn(page), 30000), 'E1: the pop-up opens');
      const f = P.last.in('home_error')[0];
      T.ok(f && f.kp && f.kp.state === 'transient' && f.kp.own === false && Array.isArray(f.kp.keys) && f.kp.keys.length === 0, 'E1: kp says own false and carries no keys: ' + JSON.stringify(f && f.kp && { s: f.kp.state, o: f.kp.own, k: f.kp.keys }));
      T.ok(f && f.kp.server && f.kp.server.groq.status === 'invalid' && f.kp.server.gemini.status === 'forbidden' && f.kp.server.openrouter.status === 'ok', 'E1: ... plus `server`: the owner\'s own view of DuSu\'s three keys: ' + JSON.stringify(f && f.kp.server));
      T.ok(!/gsk_|AIza|sk-or/.test(JSON.stringify(P.last.frames.filter(x => x.dir === 'in').map(x => x.j))), 'E1: no key text anywhere in what the server sent');
      const full = (await L.txt(page, '#kySheet')) || '';
      T.ok(/only you see this/.test(full), 'E1: the section says only the owner sees it');
      T.eq(await rows(page), 3, 'E1: three rows: Groq, Gemini, OpenRouter');
      T.ok(/Groq[\s\S]*Rejected/.test(full) && /Gemini[\s\S]*Blocked/.test(full) && /OpenRouter[\s\S]*Working/.test(full), 'E1: Groq Rejected, Gemini Blocked, OpenRouter Working - valid or invalid, said plainly: ' + JSON.stringify(full.slice(0, 500)));
      T.ok(/Invalid API Key/.test(full), 'E1: Groq\'s own words are shown');
      T.ok(/free tier is not available for this project/.test(full), 'E1: Google\'s own words are shown - the reason the Gemini key is refused');
      T.ok(/backend\/\.env/.test(full), 'E1: and what to do about it');
      T.ok(!(await planCard(page)), 'E1: no plan card for the owner');
      T.eq((await blocks(page)).keys, false, 'E1: no "your keys" section either (these are not the owner\'s own keys)');
      await L.shot(page, 'busy-owner-390');
      await L.post('/__world/serverkeys', { on: false });
    });

    await scenario(browser, 'E2 their OWN keys, one rejected and the AI busy: the pop-up still lists the rejected key with Replace', 'lk13', async ({ page, P }) => {
      await L.behave('groq', 'invalid'); await L.behave('gemini', 'chat_down');
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => sheetOn(page), 25000), 'E2: the pop-up opens');
      T.ok(await until(async () => /Rejected/.test((await keysText(page)) || '') && /Working/.test((await keysText(page)) || ''), 12000), 'E2: after a real check: Groq Rejected, Gemini Working: ' + JSON.stringify(await keysText(page)));
      T.eq(await rows(page), 2, 'E2: both keys are listed');
      const full = (await L.txt(page, '#kySheet')) || '';
      T.ok(/Groq[\s\S]*Rejected/.test(full) && /Gemini[\s\S]*Working/.test(full), 'E2: it names Groq as Rejected and Gemini as Working');
      T.ok(!/Your keys are working/.test(full), 'E2: and does NOT claim all is well');
      T.ok(/one of your keys also needs attention/.test(full), 'E2: the sentence says so');
      await page.click('#kySheet .ky-rep');
      T.ok(await until(async () => (await L.screen(page)) === 'keys', 8000), 'E2: Replace opens the Keys screen');
    });

    await scenario(browser, 'E3 their own keys are all fine and the AI is busy: each key says Working after a REAL check, and the pop-up says so', 'lk20', async ({ page }) => {
      await L.behave('groq', 'chat_down'); await L.behave('gemini', 'chat_down');
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => sheetOn(page), 25000), 'E3: the pop-up opens');
      T.ok(await until(async () => (((await keysText(page)) || '').match(/Working/g) || []).length === 2, 12000), 'E3: Groq and Gemini both say Working (the providers were asked, at no cost): ' + JSON.stringify(await keysText(page)));
      // The chips can already say Working from the last known status while the real check is still on its way (the header then says "Checking..."): the sentence is claimed only once the
      // providers have answered, so it is WAITED for - asserting it the instant the chips appear failed once in a 33-suite run when the status had loaded before the pop-up opened (E3b pins that order).
      T.ok(await until(async () => /Your keys are working\. The free AI service is just busy\./.test((await L.txt(page, '#kySheet')) || ''), 12000), 'E3: "Your keys are working. The free AI service is just busy." - now something DuSu KNOWS');
      T.ok(!/Replace/.test((await L.txt(page, '#kySheet')) || ''), 'E3: nothing to replace');
      T.ok(await planCard(page), 'E3: the plan card is there');
      await L.shot(page, 'busy-keys-ok-390');
    });

    // The real check is HELD open (the page's own request is parked until released): while it runs the keys block says it is checking and DuSu does not claim "Your keys are working";
    // when the providers have answered ok the sentence appears and the header stops saying "checking". This is the order E3 used to race against.
    await scenario(browser, 'E3b the sentence "Your keys are working" is claimed only AFTER the real check has answered - while it runs the keys block says it is checking', 'lk30', async ({ page }) => {
      let release; const held = new Promise(r => { release = r; });
      let asked = 0;
      await page.route('**/keys/recheck', async route => { asked++; await held; try { await route.continue(); } catch (e) { /* the page closed while it was held */ } });
      await L.behave('groq', 'chat_down'); await L.behave('gemini', 'chat_down');
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => sheetOn(page), 25000), 'E3b: the pop-up opens');
      T.ok(await until(async () => asked > 0, 8000), 'E3b: the pop-up asks the server to check the keys for real (and that answer is parked)');
      await sleep(700);                                                             // long enough for a premature claim to be painted
      const heading = () => L.txt(page, '#kyKeys .ky-sec-t');                       // the block's own heading - a key chip can say "Checking..." too, so the heading is read on its own
      T.ok(/Checking|जाँच/.test((await heading()) || ''), 'E3b: while the check runs the heading of the keys block says so: ' + JSON.stringify(await heading()));
      T.ok(!/Your keys are working/.test((await L.txt(page, '#kySheet')) || ''), 'E3b: and DuSu does NOT claim "Your keys are working" yet - that is only said after the providers answered');
      release();
      T.ok(await until(async () => /Your keys are working\. The free AI service is just busy\./.test((await L.txt(page, '#kySheet')) || ''), 12000), 'E3b: once the providers answered ok the sentence appears');
      T.ok(!/Checking|जाँच/.test((await keysText(page)) || ''), 'E3b: and nothing in the keys block says it is checking any more (heading and chips)');
      T.eq((((await keysText(page)) || '').match(/Working/g) || []).length, 2, 'E3b: both keys say Working');
    });

    await scenario(browser, 'E5 a learner on DuSu\'s keys (the quota phase): no key list, no provider names, no owner view - and the plan card', 'lk21', async ({ page, P }) => {
      await L.post('/__world/reset', { settings: { access_phase: 'quota' } });
      await L.post('/__world/serverkeys', { on: true });
      await allDown();
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => sheetOn(page), 30000), 'E5: the pop-up opens');
      const f = P.last.in('home_error')[0];
      T.ok(f && f.kp && f.kp.own === false && !('server' in f.kp), 'E5: the frame says own false and carries NO `server` view: ' + JSON.stringify(f && Object.keys(f.kp)));
      T.ok(!/gsk_|AIza|groq|gemini|openrouter/i.test(JSON.stringify(P.last.frames.filter(x => x.dir === 'in').map(x => x.j))), 'E5: no provider name and no key anywhere in what the server sent');
      const bl = await blocks(page);
      T.ok(bl.sections === 0 && bl.rows === 0, 'E5: no key list and no owner section: ' + JSON.stringify(bl));
      T.ok(await planCard(page), 'E5: the plan card is there');
      await L.post('/__world/serverkeys', { on: false });
      await L.post('/__world/reset', { settings: { access_phase: 'growth' } });
    });

    await scenario(browser, 'P1 the plan card is a real way to the plans page (and closes the pop-up)', 'lk22', async ({ page }) => {
      await allDown();
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => sheetOn(page), 25000), 'P1: the pop-up opens');
      await page.click('#kySheet .ky-plan');
      T.ok(await until(async () => (await L.screen(page)) === 'subscribe', 6000), 'P1: the card opens the plans page');
      T.ok(!(await sheetOn(page)), 'P1: and the pop-up is closed');
    });

    // ================================================================================================ F. only chats get the pop-up; the page in Hindi; old servers
    await scenario(browser, 'F1 over HTTP the feature already says it next to what the learner was doing: no banner, no pop-up', 'lk14', async ({ page }) => {
      await page.route('**/lesson/evaluate', r => r.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ detail: 'gen_failed', kp: { state: 'transient', own: true, keys: [], now: Math.floor(Date.now() / 1000), retry_in: 6 } }) }));
      await page.evaluate(() => fetch('/lesson/evaluate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }));
      await sleep(900);
      T.ok(!(await sheetOn(page)), 'F1: no pop-up for an HTTP failure');
      T.ok(!(await bannerUp(page)), 'F1: and no banner');
      await page.evaluate(() => onMessage({ data: JSON.stringify({ type: 'practice_error', msg: 'unavailable', kp: { state: 'transient', own: true, keys: [], now: Math.floor(Date.now() / 1000), retry_in: 6 } }) }));
      await sleep(500);
      T.ok(!(await sheetOn(page)) && !(await bannerUp(page)), 'F1: nor for practice scoring (the Practice Room has its own message and Retry)');
    });

    await scenario(browser, 'F2 Hindi: the pop-up, the chip and the buttons speak Hindi (and nothing is English-only)', 'lk15', async ({ page, P }) => {
      await allDown();
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => sheetOn(page), 25000), 'F2: the pop-up opens');
      const full = (await L.txt(page, '#kySheet')) || '';
      T.ok(/जवाब आने में देर हो रही है/.test(full) && /अभी फिर कोशिश करो/.test(full) && /बाद में/.test(full), 'F2: title and both buttons in Hindi');
      T.ok(/सेकंड में अपने आप फिर कोशिश करेगी/.test((await count(page)) || ''), 'F2: the countdown in Hindi: ' + JSON.stringify(await count(page)));
      T.ok(/कोई गलती नहीं/.test(full), 'F2: "it is not your fault" in Hindi');
      T.ok(/free version/i.test(full), 'F2: the free-version tag stays (the owner asked for it on 28 Oct)');
      T.ok(/DuSu plan से और बेहतर practice/.test(full) && /Plans देखो/.test(full), 'F2: the gentle plan card, in Hindi');
      T.ok(/तुम्हारी AI keys/.test(full), 'F2: "Your AI keys" in Hindi');
      T.eq((await L.txt(page, '#hmRetry')) || '', '↻ फिर भेजो', 'F2: the chip in Hindi');
      T.eq(await feedSys(page), [], 'F2: no English system line in the Hindi chat');
      await L.shot(page, 'busy-hi-390');
    }, { lang: 'hi' });

    await scenario(browser, 'F3 an older server that still sends a busy provider as `quota` (a rollback): the same pop-up and chip, no English line', 'lk16', async ({ page, P }) => {
      await L.openHome(page, { typed: 'Hh', noWait: true });
      T.ok(await until(() => L.aiN(page).then(n => n >= 1), 15000), 'F3: Home answered the first line');
      await page.evaluate(() => { document.getElementById('feed').insertAdjacentHTML('beforeend', '<div class="msg user"><div class="av">🙂</div><div class="bubble">second line</div></div>'); });
      await page.evaluate(() => onMessage({ data: JSON.stringify({ type: 'quota', msg: 'The AI is busy right now - your keys are fine. Please try again in a minute.', kp: { state: 'transient', own: true, keys: [], now: Math.floor(Date.now() / 1000), retry_in: 6 } }) }));
      T.ok(await until(() => sheetOn(page), 4000), 'F3: the pop-up opens');
      T.eq(await feedSys(page), [], 'F3: the server\'s English sentence is NOT printed in the chat');
      T.ok(await chip(page), 'F3: the chip is there');
      T.ok(!(await bannerUp(page)), 'F3: no banner');
    });

    // ================================================================================================ G. the countdown and the details
    await scenario(browser, 'G1 the countdown pauses while the screen is locked and nothing is sent behind the learner\'s back', 'lk17', async ({ page, P }) => {
      await allDown();
      await L.openHome(page, { typed: 'Hh', noWait: true });
      await checkSheet(page, 'G1');
      const c0 = await count(page);
      await L.lock(page); await sleep(4000);
      T.eq(await count(page), c0, 'G1: the number did not move while locked');
      T.eq(userTexts(P).length, 1, 'G1: nothing was sent while locked');
      await allOk();
      await L.unlock(page);
      T.ok(await until(() => L.aiN(page).then(n => n >= 1), 15000), 'G1: after the unlock it carried on and the answer arrived');
    });

    await scenario(browser, 'G2 the numbers on the wire: a long wait has no countdown, a short one counts down; Later-only when there is nothing to resend', 'lk18', async ({ page, P }) => {
      await allDown();
      await L.openHome(page, { typed: 'a line that is never answered', noWait: true });
      // the first failure is real; after it, failure frames are delivered by hand (the page cannot tell them from the server's) with different numbers
      const frame = ra => ({ type: 'home_error', kp: Object.assign({ state: 'transient', own: true, keys: [], now: Math.floor(Date.now() / 1000) }, ra === undefined ? {} : { retry_in: ra }) });
      await until(() => sheetOn(page), 25000);
      await later(page); await sleep(300);
      await page.evaluate(f => onMessage({ data: JSON.stringify(f) }), frame(90));
      T.ok(await until(() => sheetOn(page), 3000), 'G2: a crafted failure opens the pop-up');
      T.eq(await count(page), null, 'G2: retry_in 90 -> no countdown (waiting a minute silently would look like a hang)');
      T.ok(await page.evaluate(() => document.querySelectorAll('#kySheet .ky-pop-acts .btn').length) === 2, 'G2: but the button is there');
      await later(page); await sleep(300);
      await page.evaluate(f => onMessage({ data: JSON.stringify(f) }), frame(12));
      T.ok(/(^|\D)(11|12)(\D|$)/.test((await count(page)) || ''), 'G2: retry_in 12 -> counts down from 12: ' + JSON.stringify(await count(page)));
      await later(page); await sleep(300);
      await page.evaluate(f => onMessage({ data: JSON.stringify(f) }), frame(undefined));
      T.eq(await count(page), null, 'G2: no retry_in at all (nothing can recover by itself) -> no countdown');
      await later(page);
    });

    // ================================================================================================ H. look and accessibility
    for (const vp of [{ width: 360, height: 640 }, { width: 390, height: 844 }, { width: 1280, height: 800 }]) {
      await scenario(browser, `H1 ${vp.width}px: the pop-up fits, the buttons are big enough and reachable, keyboard works`, 'lk19', async ({ page }) => {
        await allDown();
        await L.openHome(page, { typed: 'Hh', noWait: true });
        await checkSheet(page, 'H1-' + vp.width);
        const g = await page.evaluate(() => {
          const sh = document.getElementById('kySheet').getBoundingClientRect();
          const btns = [...document.querySelectorAll('#kySheet .ky-pop-acts .btn')].map(b => { const r = b.getBoundingClientRect(); return { w: r.width, h: r.height, top: r.top, bottom: r.bottom }; });
          return { sh: { top: sh.top, bottom: sh.bottom, left: sh.left, right: sh.right }, btns, vh: innerHeight, vw: innerWidth, sw: document.documentElement.scrollWidth, focus: document.activeElement && document.activeElement.id };
        });
        T.ok(g.sw <= g.vw, `H1-${vp.width}: no horizontal overflow`);
        T.ok(g.sh.top >= 0 && g.sh.bottom <= g.vh + 1 && g.sh.left >= -1 && g.sh.right <= g.vw + 1, `H1-${vp.width}: the whole pop-up is inside the screen`);
        T.ok(g.btns.length === 2 && g.btns.every(b => b.h >= 44 && b.top >= 0 && b.bottom <= g.vh + 1), `H1-${vp.width}: both buttons are >= 44 px high and on screen: ${JSON.stringify(g.btns.map(b => Math.round(b.h)))}`);
        T.eq(g.focus, 'kyTitle', `H1-${vp.width}: focus moved into the dialog`);
        await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
        T.ok(await page.evaluate(() => !!document.activeElement.closest('#kySheet')), `H1-${vp.width}: Tab stays inside the dialog`);
        await L.shot(page, `busy-en-${vp.width}`);
        await page.keyboard.press('Escape');
        T.ok(await until(async () => !(await sheetOn(page)), 3000), `H1-${vp.width}: Escape closes it`);
      }, { viewport: vp });
    }
  } finally {
    await browser.close();
  }
  const ok = T.done();
  if (L.ERRS.length) { console.log('page errors:\n  ' + L.ERRS.slice(0, 10).join('\n  ')); }
  process.exit(ok && !L.ERRS.length ? 0 : 1);
})();
