'use strict';
/*
 * A locked screen must not kill Daily Talk / Learn - real Chromium -> a WebSocket proxy -> the REAL server (scratch Postgres, scripted fake providers).
 *
 * The bug: lock the phone in Daily Talk, unlock, and the mic and Reply are dead until the chat ends (the page closed its socket on "hidden" and nothing handled the return).
 * Every scenario below is a state the learner can be in when the screen locks. Sections tagged [pin] describe behaviour that must be the SAME before and after the fix.
 *
 *   tests/daily_voice/browser/run_real.sh lock.spec.cjs
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('daily voice: lock / unlock');
const { T, sleep, until } = L;

const MINUTE = 60 * 1000;

async function scenario(browser, title, who, fn, o = {}) {
  if (process.env.ONLY && !process.env.ONLY.split(',').some(k => title.startsWith(k + ' '))) return;     // mutants.sh runs only the scenarios that should catch a planted bug
  T.section(title);
  let ctx;
  try {
    ctx = await L.ctxFor(browser, who, o);
    if (o.clock) await ctx.clock.install();
    const P = await L.proxy(ctx);
    if (o.holdNew) P.holdNew = true;
    const page = await L.boot(ctx, '/');
    await fn({ page, P, who, ctx });
    const e = await page.evaluate(() => ({ errors: window.__errors, rejections: window.__rejections }));
    T.eq(e.errors, [], title + ': no script error');
    T.eq(e.rejections, [], title + ': no unhandled rejection');
  } catch (e) {
    T.ok(false, title + ': the scenario threw: ' + String((e && e.message) || e).slice(0, 300));
  } finally {
    try { await ctx.close(); } catch (e) { /* closed */ }
  }
}

const listening = page => page.evaluate(() => document.getElementById('dailyMic').classList.contains('listening'));
const cardUp = page => L.vis(page, '#dailyCard');

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    // ================================================================================================ A. the reported bug, in every state the learner can be in
    await scenario(browser, 'A1 lock while the mic is idle', 'lk1', async ({ page, P }) => {
      await L.openDaily(page);
      T.eq(P.conns.length, 1, 'one socket after opening Daily');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(400);
      T.ok(await L.micOn(page), 'after the unlock the mic is enabled');
      T.ok(await L.sayTurn(page, 'mera naam Asha hai'), 'the mic works: DuSu answers');
      T.ok(await L.sayTurn(page, 'main kaam par jaa rahi hoon', { reply: true }), 'Reply works too');
      T.eq(P.conns.length, 1, 'still the SAME socket (one session)');
      T.eq(P.starts().length, 1, 'no second start frame');
      T.eq(P.last.out('user_text').length, 2, 'both turns went over that one socket');
    });

    await scenario(browser, 'A2 lock while the mic is listening', 'lk1', async ({ page, P }) => {
      await L.openDaily(page);
      await page.evaluate(() => { window.__hold = true; });
      await page.click('#dailyMic');
      T.ok(await until(() => page.evaluate(() => !!window.__srActive)), 'the recogniser is listening');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(500);
      T.ok(await L.micOn(page), 'the mic is enabled again after the unlock');
      T.ok(!(await listening(page)), 'and it no longer claims to be listening');
      await page.evaluate(() => { window.__hold = false; });
      T.ok(await L.sayTurn(page, 'aaj mausam accha hai'), 'a turn works after the lock');
      T.eq(P.conns.length, 1, 'same socket');
    });

    await scenario(browser, 'A3 lock while DuSu is speaking her reply', 'lk1', async ({ page, P }) => {
      await L.openDaily(page);
      await page.evaluate(() => { window.__ttsMs = 2500; window.__utter.push('mujhe office jaana hai'); });
      const n0 = await page.evaluate(() => window.__spoken.length);
      await page.click('#dailyMic');
      T.ok(await until(() => page.evaluate(n => window.__spoken.length > n && !document.getElementById('dailyCard').hidden, n0), 12000), 'DuSu started speaking and the reply card is up');
      await L.lock(page); await sleep(5000);                                       // longer than the utterance AND the speech watchdog: nothing may start talking meanwhile
      T.eq(await L.spokenHidden(page), [], 'a locked phone is never spoken to (the reply chain stopped at the lock)');
      await L.unlock(page); await sleep(500);
      await page.evaluate(() => { window.__ttsMs = 60; });
      T.ok(await L.micOn(page), 'the mic is enabled');
      T.ok(await cardUp(page), 'the reply card is still there');
      T.ok(await L.sayTurn(page, 'phir milte hain', { reply: true }), 'Reply works after the lock');
      T.eq(P.conns.length, 1, 'same socket');
    });

    await scenario(browser, 'A4 lock while DuSu is thinking - her answer lands while the screen is off', 'lk2', async ({ page, P }) => {
      await L.openDaily(page);
      P.last.hold = true;                                                           // the server's answer waits at the door
      await page.evaluate(() => { window.__utter.push('main bahut khush hoon'); });
      await page.click('#dailyMic');
      T.ok(await until(() => P.last.out('user_text').length === 1), 'the learner\'s line reached the server');
      await L.lock(page); await sleep(200);
      P.last.release();                                                             // the answer arrives while hidden
      await sleep(700);
      T.eq(await L.spokenHidden(page), [], 'nothing is spoken while the page is hidden');
      await L.unlock(page); await sleep(500);
      T.ok(await cardUp(page), 'the answer is on screen after the unlock');
      const b = await L.bubbles(page);
      T.eq(b, { me: 1, ai: 2 }, 'one bubble for the learner, DuSu\'s greeting + her answer, no duplicates');
      T.ok(await L.micOn(page), 'the mic is enabled');
      T.ok(await L.sayTurn(page, 'chalo aage badhte hain', { reply: true }), 'Reply works');
    });

    await scenario(browser, 'A4b lock while thinking - the answer lands AFTER the unlock', 'lk2', async ({ page, P }) => {
      await L.openDaily(page);
      P.last.hold = true;
      await page.evaluate(() => { window.__utter.push('mera din accha tha'); });
      await page.click('#dailyMic');
      T.ok(await until(() => P.last.out('user_text').length === 1), 'line sent');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(300);
      T.ok(!(await cardUp(page)), 'still waiting for the answer');
      const s0 = (await L.spoken(page)).length;
      P.last.release();
      T.ok(await until(() => cardUp(page), 8000), 'the answer shows when it arrives');
      T.ok(await until(async () => (await L.spoken(page)).length > s0, 5000), 'and it is spoken (the page is visible)');
      T.eq(await L.bubbles(page), { me: 1, ai: 2 }, 'no duplicate bubbles');
    });

    await scenario(browser, 'A5 lock while DuSu is speaking her greeting', 'lk3', async ({ page, P }) => {
      await page.evaluate(() => { window.__ttsMs = 2500; });
      await L.openDaily(page, { noWait: true });
      T.ok(await until(() => page.evaluate(() => window.__spoken.length >= 1), 12000), 'the greeting started');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(500);
      await page.evaluate(() => { window.__ttsMs = 60; });
      T.ok(await until(() => L.micOn(page), 5000), 'the mic is handed over even though the greeting was cut');
      T.eq((await L.bubbles(page)).ai, 1, 'the greeting is on screen once');
      T.ok(await L.sayTurn(page, 'namaste'), 'a turn works');
    });

    await scenario(browser, 'A5b the opening greeting arrives while the screen is off', 'lk3', async ({ page, P }) => {
      P.holdNew = true;                                                             // the opener waits at the door
      await L.openDaily(page, { noWait: true });
      T.ok(await until(() => P.conns.length === 1), 'connected');
      await L.lock(page); await sleep(200);
      P.last.release();
      await sleep(700);
      T.eq(await L.spokenHidden(page), [], 'the greeting is not spoken to a locked phone');
      await L.unlock(page);
      T.ok(await until(() => L.micOn(page), 5000), 'the mic is handed over after the unlock');
      T.eq((await L.bubbles(page)).ai, 1, 'the greeting is on screen');
    });

    // ================================================================================================ B. the socket did not survive the lock
    await scenario(browser, 'B1 the connection dies while locked -> a quiet reconnect, the same chat', 'lk4', async ({ page, P, who }) => {
      await L.spyUsage(page);
      await L.openDaily(page);
      T.eq(await L.usageCalls(page), 1, 'opening Daily counts one session');
      T.ok(await L.sayTurn(page, 'mera naam Ravi hai'), 'a first turn');
      const xp0 = await L.xp(who), spoken0 = (await L.spoken(page)).length;
      await L.lock(page); await sleep(200);
      P.last.kill();
      T.ok(await until(async () => (await L.xp(who)) > xp0, 20000), 'the server saved the first part when its socket closed (that save is itself a model call)');
      await sleep(500);
      const calls0 = await L.calls();
      await L.unlock(page);
      T.ok(await until(() => P.conns.length === 2, 8000), 'the page opened a second socket by itself');
      T.ok(await until(() => P.conns[1] && P.conns[1].out('start').length === 1, 5000), 'and started it');
      const s = P.conns[1] && P.conns[1].out('start')[0];
      T.ok(s && s.reconnect === true, 'it told the server this is a quiet reconnect');
      T.ok(s && Array.isArray(s.resume) && s.resume.length >= 2, 'with the conversation so far');
      T.ok(await until(() => P.conns[1] && P.conns[1].in('daily_resumed').length === 1, 8000), 'the server answered daily_resumed');
      T.eq(P.conns[1].in('daily_question').length, 0, 'no new greeting');
      await sleep(500);
      T.eq(await L.calls(), calls0, 'no model call for the reconnect');
      T.eq((await L.spoken(page)).length, spoken0, 'DuSu did not speak');
      T.eq(await L.usageCalls(page), 1, 'it was not counted as a new session');
      T.ok(await L.micOn(page), 'the mic is enabled');
      T.ok(await L.sayTurn(page, 'main ghar jaa raha hoon'), 'the next turn works over the new socket');
      T.eq(P.conns[1].out('user_text').length, 1, 'that turn went over socket 2');
      T.eq((await L.bubbles(page)).me, 2, 'the whole chat is still on screen');
    });

    await scenario(browser, 'B2 a tap on a dead socket reconnects (no lock involved)', 'lk4', async ({ page, P }) => {
      await L.openDaily(page);
      T.ok(await L.sayTurn(page, 'main theek hoon'), 'a first turn');
      P.last.kill(); await sleep(600);
      T.ok(await L.micOn(page), 'the mic is not left dead when the connection drops');
      await page.click('#dailyMic');
      T.ok(await until(() => P.conns.length === 2, 8000), 'the tap reconnected');
      T.ok(await until(() => P.conns[1] && P.conns[1].in('daily_resumed').length === 1, 8000), 'quietly');
      T.ok(await until(() => L.micOn(page), 5000), 'and the mic is back');
      T.ok(await L.sayTurn(page, 'ab sab theek hai'), 'then it works');
    });

    await scenario(browser, 'B3 the learner\'s line was in flight when the connection died -> it is answered once', 'lk5', async ({ page, P }) => {
      await L.openDaily(page);
      P.last.hold = true;
      await page.evaluate(() => { window.__utter.push('kal meri exam hai'); });
      await page.click('#dailyMic');
      T.ok(await until(() => P.last.out('user_text').length === 1), 'line sent');
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(400);                                              // the answer never arrives
      await L.unlock(page);
      T.ok(await until(() => P.conns.length === 2, 8000), 'reconnected');
      T.ok(await until(() => P.conns[1] && P.conns[1].out('user_text').length === 1, 8000), 'the line was sent again, once');
      T.eq(P.conns[1].out('user_text')[0].text, 'kal meri exam hai', 'the same words');
      T.ok(await until(() => cardUp(page), 12000), 'DuSu answered');
      T.eq(await L.bubbles(page), { me: 1, ai: 2 }, 'one bubble for the learner, no duplicate');
    });

    await scenario(browser, 'B4 a half-open socket (looks open, answers nothing) after a long lock', 'lk6', async ({ page, P }) => {
      await L.openDaily(page);
      T.ok(await L.sayTurn(page, 'main office me hoon'), 'a first turn');
      await L.lock(page); await sleep(200);
      P.last.frozen = true;                                                         // the phone's network went away; the page does not know
      await page.clock.fastForward(30 * 1000);
      await L.unlock(page); await sleep(300);
      T.ok(P.conns[0].out('ping').length >= 1, 'the page checked the connection (ping)');
      await page.clock.fastForward(3500);
      T.ok(await until(() => P.conns.length === 2, 8000), 'no answer -> it reconnected');
      T.ok(await until(() => P.conns[1] && P.conns[1].out('start').length === 1, 5000), 'and started it');
      T.ok(P.conns[1].out('start')[0].reconnect === true, 'quietly');
      T.ok(await until(() => L.micOn(page), 5000), 'the mic is enabled');
      T.ok(await L.sayTurn(page, 'sab theek hai'), 'a turn works over the new socket');
    }, { clock: true });

    await scenario(browser, 'B5 a long lock on a HEALTHY socket -> a ping, no reconnect', 'lk6', async ({ page, P }) => {
      await L.openDaily(page);
      T.ok(await L.sayTurn(page, 'main khush hoon'), 'a first turn');
      await L.lock(page); await sleep(200);
      await page.clock.fastForward(30 * 1000);
      await L.unlock(page);
      T.ok(await until(() => P.conns[0].in('pong').length >= 1, 5000), 'the server answered the ping');
      await sleep(400);
      T.eq(P.conns.length, 1, 'no reconnect');
      T.ok(await until(() => L.micOn(page), 5000), 'the mic is enabled');
      T.ok(await L.sayTurn(page, 'aur batao'), 'a turn works on the same socket');
    }, { clock: true });

    await scenario(browser, 'B6 away longer than 10 minutes -> the page ends the session itself, and reconnects on return', 'lk6', async ({ page, P }) => {
      await L.openDaily(page);
      T.ok(await L.sayTurn(page, 'main bazaar jaa rahi hoon'), 'a first turn');
      await L.lock(page); await sleep(200);
      await page.clock.fastForward(11 * MINUTE);
      T.ok(await until(() => P.conns[0].pageClosed, 5000), 'after 10 minutes the page closed the socket (the server saves the chat, as before)');
      await L.unlock(page);
      T.ok(await until(() => P.conns.length === 2, 8000), 'on return it reconnected');
      T.ok(await until(() => P.conns[1] && P.conns[1].out('start').length === 1, 5000), 'and started it');
      T.ok(P.conns[1].out('start')[0].reconnect === true, 'quietly');
      T.ok(await until(() => L.micOn(page), 5000), 'the mic is enabled');
    }, { clock: true });

    // ================================================================================================ C. rewards are never paid twice
    await scenario(browser, 'C1 reconnect, then Finish with nothing new said -> no second reward', 'lk7', async ({ page, P, who }) => {
      await L.openDaily(page);
      T.ok(await L.sayTurn(page, 'mera naam Ravi hai'), 'turn 1');
      T.ok(await L.sayTurn(page, 'main engineer hoon', { reply: true }), 'turn 2');
      const xp0 = await L.xp(who);
      await L.lock(page); await sleep(200);
      P.last.kill();
      T.ok(await until(async () => (await L.xp(who)) > xp0, 20000), 'the first part was saved and rewarded when its socket closed');
      const xp1 = await L.xp(who);
      await L.unlock(page);
      T.ok(await until(() => P.conns.length === 2 && P.conns[1].in('daily_resumed').length === 1, 8000), 'reconnected quietly');
      await page.click('#dailyFinish');
      T.ok(await until(() => P.conns[1].out('end').length === 1, 5000), 'Finish told the server');
      T.ok(await until(() => L.screen(page).then(s => s === 'sessionResult'), 5000), 'the result screen opened');
      T.ok(await until(() => page.evaluate(() => !document.querySelector('#srBody .spin')), 8000), 'and it does not spin for 20 seconds when there is nothing new to show');
      await sleep(1500);
      T.eq(await L.xp(who), xp1, 'no second reward for turns that were already rewarded');
    });

    await scenario(browser, 'C2 reconnect, one new turn, Finish -> rewarded once for the new turn', 'lk8', async ({ page, P, who }) => {
      await L.openDaily(page);
      T.ok(await L.sayTurn(page, 'mera naam Ravi hai'), 'turn 1');
      const xp0 = await L.xp(who);
      await L.lock(page); await sleep(200);
      P.last.kill();
      T.ok(await until(async () => (await L.xp(who)) > xp0, 20000), 'part 1 rewarded');
      const xp1 = await L.xp(who);
      await L.unlock(page);
      T.ok(await until(() => P.conns.length === 2 && P.conns[1].in('daily_resumed').length === 1, 8000), 'reconnected quietly');
      T.ok(await until(() => L.micOn(page), 5000), 'mic enabled');
      T.ok(await L.sayTurn(page, 'main kal bhi aaungi'), 'one new turn');
      await page.click('#dailyFinish');
      T.ok(await until(() => L.screen(page).then(s => s === 'sessionResult'), 8000), 'the result screen opened');
      T.ok(await until(async () => (await L.xp(who)) > xp1, 20000), 'the new turn is rewarded');
      await sleep(1500);
      T.eq((await L.xp(who)) - xp1, 20, 'exactly once (+20), not twice');
    });

    // ================================================================================================ D. adjacent dead mic: after a "your keys hit their limit" frame
    await scenario(browser, 'D1 the mic works again after a key-limit pop-up was dismissed', 'lk9', async ({ page, P }) => {
      await L.openDaily(page);
      T.ok(await L.sayTurn(page, 'pehli baat'), 'a first turn');
      await L.behave('groq', 'limited'); await L.behave('gemini', 'limited');
      await page.evaluate(() => { window.__utter.push('doosri baat'); });
      await page.click('#dcNext');
      T.ok(await until(() => P.last.in('quota').length === 1, 15000), 'the server said the keys are limited');
      await sleep(500);
      if (await L.vis(page, '#kySheet.on')) { await page.click('#kySheet .ky-pop-acts .btn:last-child'); await sleep(400); }
      await L.behave('groq', 'ok'); await L.behave('gemini', 'ok');
      T.ok(await L.micOn(page), 'the mic was handed back');
      T.ok(await L.sayTurn(page, 'teesri baat'), 'and tapping it works (it used to do nothing)');
    });

    // ================================================================================================ E. Learn
    await scenario(browser, 'E1 Learn: lock while the mic is idle', 'lk10', async ({ page, P }) => {
      await page.evaluate(() => startLearning());
      T.ok(await until(() => page.evaluate(() => !document.getElementById('micBtn').disabled), 15000), 'Learn handed the mic over');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(500);
      T.ok(await page.evaluate(() => !document.getElementById('micBtn').disabled), 'the mic is enabled after the unlock');
      await page.evaluate(() => { window.__utter.push('mujhe market jaana hai'); });
      await page.click('#micBtn');
      T.ok(await until(() => page.evaluate(() => !document.getElementById('transCard').hidden), 12000), 'the translation card appears');
      T.eq(P.conns.length, 1, 'same socket');
    });

    await scenario(browser, 'E2 Learn: the connection dies while locked -> quiet reconnect, no new greeting', 'lk10', async ({ page, P }) => {
      await L.spyUsage(page);
      await page.evaluate(() => startLearning());
      T.ok(await until(() => page.evaluate(() => !document.getElementById('micBtn').disabled), 15000), 'mic handed over');
      T.eq(await L.usageCalls(page), 1, 'starting Learn counts one session');
      const spoken0 = (await L.spoken(page)).length;
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(400);
      await L.unlock(page);
      T.ok(await until(() => P.conns.length === 2, 8000), 'reconnected by itself');
      T.ok(await until(() => P.conns[1].in('ready').length === 1, 8000), 'the server said ready');
      await sleep(600);
      T.eq((await L.spoken(page)).length, spoken0, 'DuSu did not greet again');
      T.eq(await L.usageCalls(page), 1, 'not counted as a new session');
      T.ok(await until(() => page.evaluate(() => !document.getElementById('micBtn').disabled), 5000), 'the mic is enabled');
      await page.evaluate(() => { window.__utter.push('main ghar jaa raha hoon'); });
      await page.click('#micBtn');
      T.ok(await until(() => page.evaluate(() => !document.getElementById('transCard').hidden), 12000), 'a translation works over the new socket');
    });

    // ================================================================================================ F. [pin] what must NOT change
    await scenario(browser, 'F1 [pin] Face-to-Face still stops everything when the screen locks', 'lk9', async ({ page, P }) => {
      await page.evaluate(() => startSession('conversation'));
      T.ok(await until(() => P.conns.length === 1 && P.conns[0].in('ai_text').length >= 1, 15000), 'the chat opened');
      await L.lock(page);
      T.ok(await until(() => P.conns[0].pageClosed, 3000), 'the page closed the socket on lock (unchanged)');
      T.eq(await page.evaluate(() => running), false, 'and stopped the loop (unchanged)');
      await L.unlock(page); await sleep(500);
      T.eq(P.conns.length, 1, 'nothing reconnects (unchanged)');
    });

    await scenario(browser, 'F2 [pin] a Daily session that is never locked sends exactly the frames it always did', 'lk9', async ({ page, P }) => {
      await L.openDaily(page);
      T.ok(await L.sayTurn(page, 'mera naam Sita hai'), 'a turn');
      const st = P.last.out('start')[0];
      T.eq(Object.keys(st).sort(), ['day', 'hour', 'keys', 'lang', 'mode', 'mood', 'resume', 'token', 'type'], 'the start frame has exactly the old keys (no reconnect key)');
      T.eq(P.last.out('user_text'), [{ type: 'user_text', text: 'mera naam Sita hai' }], 'the user_text frame is unchanged');
      T.eq(P.last.out('ping').length, 0, 'no ping is ever sent while the page is visible');
      T.eq(P.conns.length, 1, 'one socket');
      await page.click('#dailyFinish');
      T.ok(await until(() => P.last.out('end').length === 1, 5000), 'Finish sends end');
      T.eq(P.last.out('end'), [{ type: 'end' }], 'the end frame is unchanged');
    });
  } finally {
    await browser.close();
  }
  const ok = T.done();
  if (L.ERRS.length) { console.log('page errors:\n  ' + L.ERRS.slice(0, 10).join('\n  ')); }
  process.exit(ok && !L.ERRS.length ? 0 : 1);
})();
