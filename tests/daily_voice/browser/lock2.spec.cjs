'use strict';
/*
 * A locked screen must not kill the OTHER chats either: Face-to-Face (Talk), Interview, a Practice Room conversation (viva) and the Home chat - the screens that share #session.
 * Real Chromium -> a WebSocket proxy -> the REAL server (scratch Postgres, scripted fake providers). The Daily Talk / Learn half is lock.spec.cjs.
 *
 * Before the fix a lock ran stopAllVoice() on these screens too: the recogniser was dropped, `running` went false and the socket was closed AND nulled - so after the unlock the
 * mic never came back, End showed "wrapping up" forever and an interview in progress was lost. Now the page PAUSES the chat (mic and voice off, socket kept) and, if the socket did
 * not survive, re-opens the SAME chat quietly: `start {reconnect: true, resume: [the lines on screen]}` -> `session_resumed` (no greeting, no model call, only new turns count).
 * Sections tagged [pin] describe behaviour that must be the SAME before and after.
 *
 *   tests/daily_voice/browser/run_real.sh lock2.spec.cjs        ONLY=T1,H3 runs just those scenarios
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('session chats: lock / unlock');
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

const label = page => page.evaluate(() => document.getElementById('stateLabel').textContent);
const startOf = (P, n) => P.conns[n] && P.conns[n].out('start')[0];

/** The page opened a second socket, started it as a quiet reconnect and the server took it. */
async function reconnected(P, n = 1) {
  const a = await until(() => P.conns.length === n + 1, 8000);
  const b = a && await until(() => P.conns[n] && P.conns[n].out('start').length === 1, 5000);
  const c = b && await until(() => P.conns[n].in('session_resumed').length === 1, 8000);
  return !!c;
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    // the Home chat and the Practice Room are staged per learner in production: switch them on for this scratch server
    await L.post('/__world/reset', { settings: { home_ai: 'on', practice_room: 'on' } });

    // ================================================================================================ T. Face-to-Face (Talk)
    await scenario(browser, 'T1 Face-to-Face: lock while the mic is listening', 'lk11', async ({ page, P }) => {
      await L.openTalk(page);
      T.eq(P.conns.length, 1, 'one socket after opening');
      const starts0 = await page.evaluate(() => window.__srStarts);
      await L.lock(page); await sleep(900);                                          // longer than the recogniser's own retry back-off (250 ms)
      T.ok(!(await L.listening(page)), 'nothing listens on a locked phone');
      T.eq(await page.evaluate(() => window.__srStarts), starts0, 'and nothing tries to START a recogniser on a hidden page either');
      T.eq(P.last.pageClosed, false, 'the page keeps the socket (it used to close it)');
      await L.unlock(page);
      T.ok(await until(() => L.listening(page), 5000), 'after the unlock the mic listens again');
      T.ok(await L.saySess(page, 'I like cricket a lot'), 'a turn works');
      T.eq(P.conns.length, 1, 'still the SAME socket (one session)');
      T.eq(P.starts().length, 1, 'no second start frame');
      T.eq(P.last.out('user_text').length, 1, 'the turn went over that socket');
    });

    await scenario(browser, 'T2 Face-to-Face: lock while DuSu is speaking', 'lk12', async ({ page, P }) => {
      await page.evaluate(() => { window.__ttsMs = 2500; });
      await L.openTalk(page, { noWait: true });
      T.ok(await until(() => page.evaluate(() => window.__spoken.length >= 1), 15000), 'DuSu started speaking her opening');
      await L.lock(page); await sleep(5000);                                       // longer than the utterance AND the speech watchdog: nothing may start talking or listening meanwhile
      T.eq(await L.spokenHidden(page), [], 'a locked phone is never spoken to');
      T.ok(!(await L.listening(page)), 'and nothing listens');
      await L.unlock(page);
      await page.evaluate(() => { window.__ttsMs = 60; });
      T.ok(await until(() => L.listening(page), 6000), 'after the unlock the mic opens');
      T.eq(await L.aiN(page), 1, 'the opening is on screen once');
      T.ok(await L.saySess(page, 'my favourite food is biryani'), 'a turn works');
      T.eq(P.conns.length, 1, 'same socket');
    });

    await scenario(browser, 'T3 Face-to-Face: lock while DuSu is thinking - her answer lands while the screen is off', 'lk13', async ({ page, P }) => {
      await L.openTalk(page);
      P.last.hold = true;                                                           // the server's answer waits at the door
      await page.evaluate(() => window.__say('I went to the market today'));
      T.ok(await until(() => P.last.out('user_text').length === 1), 'the learner\'s line reached the server');
      await L.lock(page); await sleep(200);
      P.last.release();                                                             // the answer arrives while hidden
      await sleep(800);
      T.eq(await L.spokenHidden(page), [], 'nothing is spoken while the page is hidden');
      await L.unlock(page);
      T.ok(await until(() => L.listening(page), 6000), 'the mic opens after the unlock');
      T.eq({ ai: await L.aiN(page), me: await L.userN(page) }, { ai: 2, me: 1 }, 'the greeting + the answer are on screen, no duplicates');
    });

    await scenario(browser, 'T3b Face-to-Face: lock while thinking - the answer lands AFTER the unlock', 'lk14', async ({ page, P }) => {
      await L.openTalk(page);
      P.last.hold = true;
      await page.evaluate(() => window.__say('I like music'));
      T.ok(await until(() => P.last.out('user_text').length === 1), 'line sent');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(300);
      T.ok(!(await L.listening(page)), 'the mic stays off while the answer is still on its way');
      const s0 = (await L.spoken(page)).length;
      P.last.release();
      T.ok(await until(async () => (await L.aiN(page)) === 2, 8000), 'the answer shows when it arrives');
      T.ok(await until(async () => (await L.spoken(page)).length > s0, 5000), 'and it is spoken (the page is visible)');
      T.ok(await until(() => L.listening(page), 6000), 'then the mic opens');
    });

    await scenario(browser, 'T4 Face-to-Face: the opening line arrives while the screen is off', 'lk15', async ({ page, P }) => {
      P.holdNew = true;                                                             // the opener waits at the door
      await L.openTalk(page, { noWait: true });
      T.ok(await until(() => P.conns.length === 1 && P.last.out('start').length === 1), 'connected and started');
      await L.lock(page); await sleep(200);
      P.last.release();
      await sleep(800);
      T.eq(await L.spokenHidden(page), [], 'the opening is not spoken to a locked phone');
      await L.unlock(page);
      T.ok(await until(() => L.listening(page), 6000), 'the mic opens after the unlock');
      T.eq(await L.aiN(page), 1, 'the opening is on screen');
    });

    await scenario(browser, 'T5 Face-to-Face: the connection dies while locked -> a quiet reconnect, the same chat', 'lk16', async ({ page, P }) => {
      await L.spyUsage(page);
      await L.openTalk(page);
      T.eq(await L.usageCalls(page), 1, 'opening the chat counts one session');
      T.ok(await L.saySess(page, 'My name is Ravi and I am a student'), 'a first turn');
      const before = await L.lines(page);
      T.eq(before.map(m => m.role), ['assistant', 'user', 'assistant'], 'the chat so far: DuSu, the learner, DuSu');
      await L.lock(page); await sleep(200);
      P.last.kill();
      await L.settled();                                                            // the server saved the first part when its socket closed (that save is itself a model call)
      const calls0 = await L.calls(), spoken0 = (await L.spoken(page)).length;
      await L.unlock(page);
      T.ok(await reconnected(P), 'the page opened a second socket by itself and the server said session_resumed');
      const s = startOf(P, 1);
      T.eq(s.reconnect, true, 'the start frame says this is a quiet reconnect');
      T.eq(s.mode, 'conversation', 'in the same mode');
      T.eq(s.resume, before, 'carrying exactly the lines that are on screen');
      T.eq(s.seed, '', 'with no one-shot seed');
      T.eq(P.conns[1].in('ai_text').length, 0, 'no new greeting');
      await sleep(800);
      T.eq(await L.calls(), calls0, 'no model call for the reconnect');
      T.eq((await L.spoken(page)).length, spoken0, 'DuSu did not speak');
      T.eq(await L.usageCalls(page), 1, 'it was not counted as a new session');
      T.eq(await L.aiN(page), 2, 'no extra greeting bubble');
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens');
      T.ok(await L.saySess(page, 'I live in Delhi'), 'the next turn works over the new socket');
      T.eq(P.conns[1].out('user_text').length, 1, 'that turn went over socket 2');
      T.eq(await L.userN(page), 2, 'the whole chat is still on screen');
    });

    await scenario(browser, 'T6 Face-to-Face: the learner\'s line was in flight when the connection died -> answered once', 'lk17', async ({ page, P }) => {
      await L.openTalk(page);
      P.last.hold = true;
      await page.evaluate(() => window.__say('Tomorrow I have an exam'));
      T.ok(await until(() => P.last.out('user_text').length === 1), 'line sent');
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(400);                                              // the answer never arrives
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      T.eq(startOf(P, 1).resume.map(m => m.role), ['assistant'], 'the replay holds only what DuSu had said (the unanswered line is not history)');
      T.ok(await until(() => P.conns[1].out('user_text').length === 1, 8000), 'the line was sent again, once');
      T.eq(P.conns[1].out('user_text')[0].text, 'Tomorrow I have an exam', 'the same words');
      T.ok(await until(async () => (await L.aiN(page)) === 2, 12000), 'DuSu answered');
      T.eq({ ai: await L.aiN(page), me: await L.userN(page) }, { ai: 2, me: 1 }, 'one bubble for the learner, no duplicate');
    });

    await scenario(browser, 'T7 Face-to-Face: a half-open socket (looks open, answers nothing) after a long lock', 'lk18', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I am at the office'), 'a first turn');
      await L.lock(page); await sleep(200);
      P.last.frozen = true;                                                         // the phone's network went away; the page does not know
      await page.clock.fastForward(30 * 1000);
      await L.unlock(page); await sleep(300);
      T.ok(P.conns[0].out('ping').length >= 1, 'the page checked the connection (ping)');
      await page.clock.fastForward(3500);
      T.ok(await reconnected(P), 'no answer -> it reconnected quietly');
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens');
      T.ok(await L.saySess(page, 'everything is fine'), 'a turn works over the new socket');
    }, { clock: true });

    await scenario(browser, 'T8 Face-to-Face: a long lock on a HEALTHY socket -> a ping, no reconnect', 'lk18', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I am happy today'), 'a first turn');
      await L.lock(page); await sleep(200);
      await page.clock.fastForward(30 * 1000);
      await L.unlock(page);
      T.ok(await until(() => P.conns[0].in('pong').length >= 1, 5000), 'the server answered the ping');
      await sleep(400);
      T.eq(P.conns.length, 1, 'no reconnect');
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens');
      T.ok(await L.saySess(page, 'tell me more'), 'a turn works on the same socket');
    }, { clock: true });

    await scenario(browser, 'T9 Face-to-Face: away longer than 10 minutes -> the page ends the session itself, and reconnects on return', 'lk18', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I am going to the bazaar'), 'a first turn');
      await L.lock(page); await sleep(200);
      await page.clock.fastForward(11 * MINUTE);
      T.ok(await until(() => P.conns[0].pageClosed, 5000), 'after 10 minutes the page closed the socket (the server saves the chat, as before)');
      await L.unlock(page);
      T.ok(await reconnected(P), 'on return it reconnected quietly');
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens');
    }, { clock: true });

    await scenario(browser, 'T10 Face-to-Face: End on a dead connection reconnects and finishes (no "wrapping up" forever), nothing is rewarded twice', 'lk19', async ({ page, P, who }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I work in a bank'), 'a first turn');
      P.last.kill();
      await L.settled();
      const xp1 = await L.xp(who);
      await page.click('#endBtn');
      T.ok(await reconnected(P), 'End reconnected quietly');
      T.ok(await until(() => P.conns[1].out('end').length === 1, 5000), 'and then told the server to finish');
      T.ok(await until(() => L.screen(page).then(s => s === 'home'), 8000), 'the chat ended (home), not an endless "wrapping up"');
      await sleep(1500);
      T.eq(await L.xp(who), xp1, 'no second reward for turns that were already rewarded');
      T.eq(P.conns[1].in('speaker_progress').length, 0, 'and no result for a chat with nothing new in it');
    });

    await scenario(browser, 'T11 Face-to-Face: reconnect, one new turn, End -> a result for the new turn', 'lk20', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I like football'), 'turn 1');
      await L.lock(page); await sleep(200);
      P.last.kill();
      await L.settled();
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      T.ok(await until(() => L.listening(page), 6000), 'mic listens');
      T.ok(await L.saySess(page, 'I play every Sunday'), 'one new turn');
      await page.click('#endBtn');
      T.ok(await until(() => P.conns[1].in('speaker_progress').length === 1, 20000), 'the server sent a result for the new turn');
      T.ok(await until(() => L.screen(page).then(s => s === 'sessionResult'), 8000), 'the result screen opened');
    });

    await scenario(browser, 'T12 Face-to-Face: the server cannot be reached on return -> a clear message, a tap on DuSu tries again', 'lk19', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I am at home'), 'a first turn');
      await L.lock(page); await sleep(200);
      P.last.kill(); P.refuse = true; await sleep(300);
      await L.unlock(page);
      T.ok(await until(() => (P.refused || 0) >= 1, 8000), 'the page tried to reconnect');
      T.ok(await until(async () => /tap DuSu/.test(await label(page)), 6000), 'and says what to do (tap DuSu) instead of leaving a dead screen: ' + (await label(page)));
      P.refuse = false;
      await page.click('#orb');
      T.ok(await reconnected(P), 'the tap reconnected quietly');
      T.ok(await until(() => L.listening(page), 6000), 'and the mic is back');
      T.ok(await L.saySess(page, 'now it works'), 'a turn works');
    });

    await L.post('/__world/reset', { settings: { grammar_coach: 'on' } });          // Grammar Coach on for this one scenario (every chat's start frame then carries a reference)
    await scenario(browser, 'T13 Face-to-Face with Grammar Coach on: the reconnect has its own Grammar Coach reference', 'lk37', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I am learning english every day'), 'a first turn');
      const g1 = startOf(P, 0).gref;
      T.ok(typeof g1 === 'string' && g1.length >= 8 && g1.length <= 40, 'the first start carries a Grammar Coach reference (' + g1 + ')');
      await L.lock(page); await sleep(200);
      P.last.kill();
      await L.settled();
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      const g2 = startOf(P, 1).gref;
      T.ok(typeof g2 === 'string' && g2.length >= 8 && g2.length <= 40 && g2 !== g1, 'the second socket has its OWN reference (' + g2 + '), so its part is analysed on its own');
    });
    await L.post('/__world/reset', { settings: { grammar_coach: 'off' } });

    await scenario(browser, 'T14 Face-to-Face: the lock and the dead connection came BEFORE the opener -> a fresh opener, and the mic still opens', 'lk39', async ({ page, P }) => {
      P.holdNew = true;                                                             // the opener waits at the door
      await L.openTalk(page, { noWait: true });
      T.ok(await until(() => P.conns.length === 1 && P.last.out('start').length === 1), 'connected and started');
      P.holdNew = false;
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(300);
      await L.unlock(page);
      T.ok(await until(() => P.conns.length === 2 && P.conns[1].in('ai_text').length === 1, 12000), 'the server opened a fresh chat (nothing had been said, so there was nothing to resume)');
      T.eq(P.conns[1].in('session_resumed').length, 0, 'it was not a resume');
      T.eq(startOf(P, 1).resume, [], 'the replay was empty');
      T.ok(await until(() => L.listening(page), 8000), 'and the mic opens (it used to stay dead: `running` was only restored by a resume)');
      T.eq(await L.aiN(page), 1, 'one opening line on screen');
      T.ok(await L.saySess(page, 'hello there'), 'a turn works');
    });

    await scenario(browser, 'T15 Face-to-Face: End tapped while the reconnect is under way -> sent once, after the chat is back', 'lk40', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I live in Pune'), 'a first turn');
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(300);
      P.holdNew = true;                                                             // the server's answer to the reconnect waits at the door
      await L.unlock(page);
      T.ok(await until(() => P.conns.length === 2 && P.conns[1].out('start').length === 1, 8000), 'the page reconnected and started');
      P.holdNew = false;
      await page.click('#endBtn');
      await sleep(700);
      T.eq(P.conns[1].out('end').length, 0, 'End did not run ahead of the resume');
      P.conns[1].release();
      T.ok(await until(() => P.conns[1].in('session_resumed').length === 1, 5000), 'the resume arrived');
      T.ok(await until(() => P.conns[1].out('end').length === 1, 5000), 'and End was sent right after it');
      T.ok(await until(() => L.screen(page).then(s => s === 'home'), 8000), 'the chat ended');
      T.eq(P.conns[1].out('end').length, 1, 'exactly once');
    });

    await scenario(browser, 'T16 Face-to-Face: a long lock while the server is still working on her answer -> the socket is NOT declared dead', 'lk39', async ({ page, P }) => {
      await L.openTalk(page);
      P.last.hold = true;                                                           // the server is busy: nothing it says (the answer, the pong) comes through yet
      await page.evaluate(() => window.__say('I am at the station'));
      T.ok(await until(() => P.last.out('user_text').length === 1), 'the line was sent');
      await L.lock(page); await sleep(200);
      await page.clock.fastForward(30 * 1000);
      await L.unlock(page); await sleep(300);
      T.ok(P.conns[0].out('ping').length >= 1, 'the page asked whether the connection is alive');
      await page.clock.fastForward(10 * 1000);                                      // far longer than the idle 3 s window
      T.eq(P.conns.length, 1, 'no reconnect while the answer is still being worked on (a reconnect would answer it twice)');
      P.last.release();
      T.ok(await until(async () => (await L.aiN(page)) === 2, 10000), 'the answer arrives on the SAME socket');
      T.eq(P.conns.length, 1, 'still one socket');
      T.ok(await until(() => L.listening(page), 6000), 'and the mic opens');
    }, { clock: true });

    await scenario(browser, 'T17 Face-to-Face: End forced while the screen is off and the connection is dead -> nothing reconnects until the learner is back', 'lk39', async ({ page, P }) => {
      await L.openTalk(page);
      T.ok(await L.saySess(page, 'I am on the train'), 'a first turn');
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(300);
      await page.evaluate(() => document.getElementById('endBtn').click());         // what a timed Confidence Check does at its 2 minutes, locked or not
      await sleep(900);
      T.eq(P.conns.length, 1, 'no socket is opened while the page is hidden');
      await L.unlock(page);
      T.ok(await reconnected(P), 'on return the page reconnected quietly');
      T.ok(await until(() => P.conns[1].out('end').length === 1, 5000), 'and finished the chat');
      T.ok(await until(() => L.screen(page).then(s => s === 'home'), 8000), 'the chat ended');
    });

    // ================================================================================================ I. Interview
    await scenario(browser, 'I1 Interview: lock mid-interview on a live socket, then carry on and finish', 'lk21', async ({ page, P }) => {
      await L.openInterview(page);
      T.ok(await L.saySess(page, 'I am a software engineer with three years of experience'), 'a first answer');
      await L.lock(page); await sleep(400); await L.unlock(page);
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens again');
      T.ok(await L.saySess(page, 'my biggest strength is problem solving'), 'a second answer');
      T.eq(P.conns.length, 1, 'the same socket the whole time');
      await page.click('#endBtn');
      T.ok(await until(() => L.screen(page).then(s => s === 'report'), 20000), 'End shows the report');
      T.eq(P.conns.length, 1, 'still one socket');
    });

    await scenario(browser, 'I2 Interview: the connection dies while locked -> the SAME interview carries on (role and answers kept), then the report', 'lk22', async ({ page, P }) => {
      await L.openInterview(page, { role: 'Data Analyst' });
      T.ok(await L.saySess(page, 'I analyse sales data for a retail company'), 'a first answer');
      const before = await L.lines(page);
      await L.lock(page); await sleep(200);
      P.last.kill();
      await L.settled();
      const calls0 = await L.calls();
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      const s = startOf(P, 1);
      T.eq([s.mode, s.role, s.reconnect], ['interview', 'Data Analyst', true], 'same mode, same role, a quiet reconnect');
      T.eq(s.resume, before, 'with the questions and answers so far');
      await sleep(800);
      T.eq(await L.calls(), calls0, 'no model call for the reconnect (no new first question)');
      T.eq(await L.aiN(page), 2, 'no new first question on screen');
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens');
      T.ok(await L.saySess(page, 'I use SQL and Python every day'), 'the interview continues over the new socket');
      await page.click('#endBtn');
      T.ok(await until(() => P.conns[1].in('report').length === 1, 20000), 'the report is built on the new socket');
      T.ok(await until(() => L.screen(page).then(s => s === 'report'), 8000), 'and shown');
    });

    await scenario(browser, 'I3 Interview: End on a dead connection reconnects and gives the report', 'lk23', async ({ page, P }) => {
      await L.openInterview(page);
      T.ok(await L.saySess(page, 'I have worked on three projects'), 'a first answer');
      P.last.kill(); await sleep(500);
      await page.click('#endBtn');
      T.ok(await reconnected(P), 'End reconnected quietly');
      T.ok(await until(() => P.conns[1].in('report').length === 1, 20000), 'the report arrived');
      T.ok(await until(() => L.screen(page).then(s => s === 'report'), 8000), 'and is on screen');
    });

    await scenario(browser, 'I4 Interview: DuSu wrapped up and the connection died before the report -> it is finished on the new socket', 'lk24', async ({ page, P }) => {
      await L.openInterview(page);
      P.last.holdIf = j => j && j.type === 'report';                                // the report is built but never reaches the phone
      await L.post('/__world/chatdone', { on: true });                              // the interviewer's next line is her closing one
      T.ok(await L.saySess(page, 'I think I am a good fit for this role'), 'the last answer');
      T.ok(await until(() => P.last.in('interview_done').length === 1, 8000), 'DuSu wrapped up (interview_done)');
      await L.post('/__world/chatdone', { on: false });
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(400);
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      T.ok(await until(() => P.conns[1].out('end').length === 1, 5000), 'the page finished the interview on the new socket');
      T.ok(await until(() => P.conns[1].in('report').length === 1, 20000), 'the report arrived');
      T.ok(await until(() => L.screen(page).then(s => s === 'report'), 8000), 'and is on screen');
    });

    // ================================================================================================ P. a Practice Room conversation (viva)
    await scenario(browser, 'P1 Practice (viva): lock on a live socket, then carry on and finish', 'lk25', async ({ page, P }) => {
      await L.openViva(page);
      T.ok(await L.saySess(page, 'a database is an organised collection of data stored electronically'), 'a first answer');
      await L.lock(page); await sleep(400); await L.unlock(page);
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens again');
      T.ok(await L.saySess(page, 'normalisation reduces redundancy by splitting tables'), 'a second answer');
      T.eq(P.conns.length, 1, 'the same socket');
      await page.click('#endBtn');
      T.ok(await until(() => P.last.in('practice_report').length + P.last.in('practice_error').length >= 1, 25000), 'the server scored (or honestly could not score) the practice');
      if (P.last.in('practice_error').length) T.eq(await page.evaluate(() => sessEnding), false, 'a failed scoring leaves End to the learner (a later reconnect must not tap it for them)');
    });

    await scenario(browser, 'P2 Practice (viva): the connection dies while locked -> the SAME practice carries on', 'lk26', async ({ page, P }) => {
      await L.openViva(page, { topic: 'Operating systems' });
      T.ok(await L.saySess(page, 'an operating system manages hardware and software resources'), 'a first answer');
      const before = await L.lines(page);
      await L.lock(page); await sleep(200);
      P.last.kill();
      await sleep(600);
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      const s = startOf(P, 1);
      T.eq([s.mode, s.kind, s.topic, s.reconnect], ['practice', 'viva', 'Operating systems', true], 'same practice, same topic, a quiet reconnect');
      T.eq(s.resume, before, 'with the questions and answers so far');
      T.ok(Number.isInteger(s.elapsed) && s.elapsed >= 0, 'and how long it had been going (' + s.elapsed + ' s)');
      T.eq(await L.aiN(page), 2, 'no new first question');
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens');
      T.ok(await L.saySess(page, 'a process is a program in execution'), 'the practice continues over the new socket');
      await page.click('#endBtn');
      T.ok(await until(() => P.conns[1].in('practice_report').length + P.conns[1].in('practice_error').length >= 1, 25000), 'the practice is scored on the new socket');
    });

    await scenario(browser, 'P3 Practice (viva): the time the phone was locked is not counted as practice time', 'lk26', async ({ page, P }) => {
      await L.openViva(page, { topic: 'Computer networks' });
      T.ok(await L.saySess(page, 'a network connects computers so they can share data'), 'a first answer');
      await L.lock(page); await sleep(200);
      await page.clock.fastForward(5 * MINUTE);                                     // five minutes locked
      P.last.kill(); await sleep(300);
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      const e = startOf(P, 1).elapsed;
      T.ok(Number.isInteger(e) && e >= 0 && e < 90, 'the practice has been going for seconds, not for the 5 minutes the phone was locked (elapsed = ' + e + ' s)');
    }, { clock: true });

    // ================================================================================================ H. the Home chat
    await scenario(browser, 'H1 Home chat: lock while the mic is listening', 'lk27', async ({ page, P }) => {
      await L.openHome(page);
      T.eq(P.conns.length, 1, 'one socket');
      await L.lock(page); await sleep(400);
      T.ok(!(await L.listening(page)), 'nothing listens on a locked phone');
      T.eq(P.last.pageClosed, false, 'the socket is kept');
      await L.unlock(page);
      T.ok(await until(() => L.listening(page), 6000), 'after the unlock the mic listens again');
      T.ok(await L.saySess(page, 'what is the time now'), 'a turn works');
      T.eq(P.conns.length, 1, 'the same socket');
      T.eq(P.starts().length, 1, 'no second start frame');
    });

    await scenario(browser, 'H2 Home chat: lock while she is speaking her greeting', 'lk28', async ({ page, P }) => {
      await page.evaluate(() => { window.__ttsMs = 2500; });
      await L.openHome(page, { noWait: true });
      T.ok(await until(() => page.evaluate(() => window.__spoken.length >= 1), 10000), 'the greeting started');
      await L.lock(page); await sleep(4500);
      T.eq(await L.spokenHidden(page), [], 'a locked phone is never spoken to');
      await L.unlock(page);
      await page.evaluate(() => { window.__ttsMs = 60; });
      T.ok(await until(() => L.listening(page), 8000), 'the mic opens even though the greeting was cut short');
      T.eq(await L.aiN(page), 1, 'the greeting is on screen once');
      T.ok(await L.saySess(page, 'tell me about my day'), 'a turn works');
    });

    await scenario(browser, 'H3 Home chat: the connection dies while locked -> a quiet reconnect, the same chat', 'lk29', async ({ page, P }) => {
      await L.spyUsage(page);
      await L.openHome(page);
      T.eq(await L.usageCalls(page), 1, 'opening the chat counts one session');
      T.ok(await L.saySess(page, 'how are you today'), 'a first turn');
      const before = await L.lines(page);
      await L.lock(page); await sleep(200);
      P.last.kill();
      await L.settled();
      const calls0 = await L.calls();
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      const s = startOf(P, 1);
      T.eq([s.mode, s.reconnect, s.opening, s.plan], ['home', true, '', false], 'a quiet reconnect: no opening line, no plan line');
      T.eq(s.resume, before, 'carrying exactly the lines that are on screen (her greeting too)');
      await sleep(800);
      T.eq(await L.calls(), calls0, 'no model call for the reconnect');
      T.eq(await L.usageCalls(page), 1, 'not counted as a new session');
      T.eq(await L.aiN(page), before.filter(m => m.role === 'assistant').length, 'no new greeting');
      T.ok(await until(() => L.listening(page), 6000), 'the mic listens');
      T.ok(await L.saySess(page, 'and what about tomorrow'), 'the chat carries on over the new socket');
      T.eq(P.conns[1].out('user_text').length, 1, 'that turn went over socket 2');
    });

    await scenario(browser, 'H4 Home chat (typing): a line typed on a dead connection is shown, the chat reconnects, and it is answered once', 'lk30', async ({ page, P }) => {
      await L.openHome(page, { typed: 'hello there' });
      T.ok(await until(async () => (await L.aiN(page)) >= 2, 15000), 'the first typed line was answered');
      P.last.kill(); await sleep(500);
      const ai0 = await L.aiN(page);
      await page.fill('#hmInput', 'what is the date today'); await page.press('#hmInput', 'Enter');
      T.ok(await reconnected(P), 'typing reconnected quietly');
      T.ok(await until(() => P.conns[1].out('user_text').length === 1, 8000), 'the line was sent once, on the new socket');
      T.eq(P.conns[1].out('user_text')[0].text, 'what is the date today', 'with the same words');
      T.ok(await until(async () => (await L.aiN(page)) > ai0, 15000), 'and answered');
      T.eq(await L.userN(page), 2, 'two learner bubbles in all, no duplicate');
    });

    await scenario(browser, 'H5 Home chat: the line was in flight when the connection died -> answered once', 'lk31', async ({ page, P }) => {
      await L.openHome(page);
      P.last.hold = true;
      await page.evaluate(() => window.__say('remind me what I told you'));
      T.ok(await until(() => P.last.out('user_text').length === 1), 'line sent');
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(400);
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      T.ok(await until(() => P.conns[1].out('user_text').length === 1, 8000), 'the line was sent again, once');
      T.eq(P.conns[1].out('user_text')[0].text, 'remind me what I told you', 'the same words');
      T.ok(await until(async () => (await L.aiN(page)) === 2, 15000), 'DuSu answered');
      T.eq(await L.userN(page), 1, 'one learner bubble');
    });

    await scenario(browser, 'H6 Home chat (typing): lock and unlock keep the mic OFF and the chat working', 'lk32', async ({ page, P }) => {
      await L.openHome(page, { typed: 'good evening' });
      T.ok(await until(async () => (await L.aiN(page)) >= 2, 15000), 'answered');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(800);
      T.ok(!(await L.listening(page)), 'the mic did not switch itself on in text mode');
      await page.fill('#hmInput', 'thank you'); await page.press('#hmInput', 'Enter');
      T.ok(await until(async () => (await L.aiN(page)) >= 3, 15000), 'typing still works');
      T.eq(P.conns.length, 1, 'the same socket');
    });

    await scenario(browser, 'H8 Home chat: DuSu\'s "ready" lands while the screen is off -> the mic does NOT start on a hidden page, and opens after the unlock', 'lk38', async ({ page, P }) => {
      P.holdNew = true;                                                             // her "ready" waits at the door
      await L.openHome(page, { noWait: true });
      T.ok(await until(() => P.conns.length === 1 && P.last.out('start').length === 1), 'connected and started');
      T.ok(await until(() => page.evaluate(() => window.__spoken.length >= 1), 8000), 'the greeting was spoken');
      await sleep(500);
      await L.lock(page); await sleep(200);
      P.last.release();                                                             // "ready" arrives while hidden
      await sleep(1500);
      T.eq(await page.evaluate(() => window.__srStarts), 0, 'the recogniser was never started on a hidden page');
      await L.unlock(page);
      T.ok(await until(() => L.listening(page), 8000), 'after the unlock the mic opens');
      T.ok(await L.saySess(page, 'good morning'), 'a turn works');
    });

    await scenario(browser, 'H9 Home chat (typing): a second line typed while the reconnect is under way is sent once, after the chat is back', 'lk40', async ({ page, P }) => {
      await L.openHome(page, { typed: 'hello there' });
      T.ok(await until(async () => (await L.aiN(page)) >= 2, 15000), 'the first line was answered');
      P.last.kill(); await sleep(400);
      P.holdNew = true;                                                             // the server's answer to the reconnect waits at the door
      await page.fill('#hmInput', 'first line'); await page.press('#hmInput', 'Enter');   // a dead connection: shown, the chat reconnects
      T.ok(await until(() => P.conns.length === 2 && P.conns[1].out('start').length === 1, 8000), 'reconnecting');
      P.holdNew = false;
      await page.fill('#hmInput', 'second line'); await page.press('#hmInput', 'Enter');  // typed while the resume is still on its way
      await sleep(700);
      T.eq(P.conns[1].out('user_text').length, 0, 'nothing is sent before the chat is back');
      P.conns[1].release();
      T.ok(await until(() => P.conns[1].out('user_text').length >= 1, 8000), 'the line is sent once the chat is back');
      await sleep(1500);
      T.eq(P.conns[1].out('user_text').map(f => f.text), ['second line'], 'exactly once (it used to be sent twice: directly, and again by the resume)');
      T.eq(await L.userN(page), 3, 'three learner bubbles in all');
    });

    await scenario(browser, 'H10 Home chat: a Hindi / English switch made mid-chat survives a reconnect', 'lk39', async ({ page, P }) => {
      await L.openHome(page);
      T.ok(await L.saySess(page, 'how are you today'), 'a turn');
      const l1 = startOf(P, 0).lang, other = l1 === 'hi' ? 'en' : 'hi';
      await page.evaluate(l => LG.set(l), other);
      T.ok(await until(() => P.last.out('lang').length >= 1, 5000), 'the switch went to the server (' + l1 + ' -> ' + other + ')');
      await sleep(600);
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(300);
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      T.eq(startOf(P, 1).lang, other, 'the reconnected chat is in the language the learner switched to, not the one it opened with');
    });

    await scenario(browser, 'H7 Home chat (typing): the first line was typed and the connection died before DuSu was ready -> it is sent after the reconnect', 'lk36', async ({ page, P }) => {
      P.holdNew = true;                                                             // DuSu's ready frame waits at the door
      await L.openHome(page, { typed: 'hello DuSu', noWait: true });
      T.ok(await until(() => P.conns.length === 1 && P.last.out('start').length === 1), 'connected and started');
      P.holdNew = false;                                                            // only the first socket is held
      await L.lock(page); await sleep(200);
      P.last.kill(); await sleep(300);
      await L.unlock(page);
      T.ok(await reconnected(P), 'reconnected quietly');
      T.ok(await until(() => P.conns[1].out('user_text').length === 1, 8000), 'the typed line was sent once, on the new socket');
      T.eq(P.conns[1].out('user_text')[0].text, 'hello DuSu', 'with the same words');
      T.ok(await until(async () => (await L.aiN(page)) >= 2, 15000), 'and answered');
      T.eq(await L.userN(page), 1, 'one learner bubble');
    });

    // ================================================================================================ F. [pin] what must NOT change
    const OLD_START = {
      conversation: ['day', 'hour', 'keys', 'lang', 'mode', 'mood', 'name', 'role', 'seed', 'token', 'type'],
      interview: ['day', 'hour', 'keys', 'lang', 'mode', 'mood', 'name', 'role', 'seed', 'token', 'type'],
      practice: ['day', 'feedback_lang', 'hour', 'keys', 'kind', 'level', 'mode', 'mood', 'plang', 'rounds', 'token', 'topic', 'type'],
      home: ['day', 'hour', 'keys', 'lang', 'mode', 'mood', 'name', 'opening', 'plan', 'token', 'type', 'tzmin'],
    };
    for (const [mode, open] of [['conversation', p => L.openTalk(p)], ['interview', p => L.openInterview(p)], ['practice', p => L.openViva(p)], ['home', p => L.openHome(p)]]) {
      await scenario(browser, `F1-${mode} [pin] a ${mode} chat that is never locked sends exactly the frames it always did`, 'lk33', async ({ page, P }) => {
        await open(page);
        T.ok(await L.saySess(page, 'I am learning english every day'), 'a turn');
        const st = P.last.out('start')[0];
        T.eq(Object.keys(st).sort(), OLD_START[mode], 'the start frame has exactly the old keys (no reconnect / resume / elapsed)');
        T.eq(P.last.out('user_text'), [{ type: 'user_text', text: 'I am learning english every day' }], 'the user_text frame is unchanged');
        T.eq(P.last.out('ping').length, 0, 'no ping is ever sent while the page is visible');
        T.eq(P.conns.length, 1, 'one socket');
        await page.click('#endBtn');
        T.ok(await until(() => P.last.out('end').length === 1, 5000), 'End sends end');
        T.eq(P.last.out('end'), [{ type: 'end' }], 'the end frame is unchanged');
      });
    }

    await scenario(browser, 'F2 [pin] a lock on a screen that is not a chat does nothing', 'lk34', async ({ page, P }) => {
      T.eq(await L.screen(page), 'home', 'on Home');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(300);
      T.eq(await L.screen(page), 'home', 'still Home');
      T.eq(P.conns.length, 0, 'no socket was opened by a lock');
    });

    await scenario(browser, 'F3 [pin] leaving the chat with Back still closes its socket and stops the voice', 'lk35', async ({ page, P }) => {
      await L.openTalk(page);
      await page.click('#backBtn');
      T.ok(await until(() => P.last.pageClosed, 3000), 'Back closed the socket');
      T.eq(await L.screen(page), 'home', 'and went home');
      T.ok(!(await L.listening(page)), 'nothing listens');
      await L.lock(page); await sleep(300); await L.unlock(page); await sleep(600);
      T.eq(P.conns.length, 1, 'a lock afterwards reconnects nothing');
    });
  } finally {
    await browser.close();
  }
  const ok = T.done();
  if (L.ERRS.length) { console.log('page errors:\n  ' + L.ERRS.slice(0, 10).join('\n  ')); }
  process.exit(ok && !L.ERRS.length ? 0 : 1);
})();
