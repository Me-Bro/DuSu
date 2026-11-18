'use strict';
/*
 * Talk (milestone M5) - real Chromium -> a WebSocket proxy -> the REAL app (scratch MongoDB, the real topic bank, a scripted Talk model, scripted fake providers).
 *
 *   A  the Talk screen: today's topic, starters (a hint, never a send), useful words, the grammar-focus chip, the level switch (remembered), another topic, an empty bank, Hindi to
 *      English really opening Daily Talk with today's frames, the screen's own language, the entry points, the switch off
 *   B  the chat on #session: the start frame, the opener (one bubble), the Hindi subtitle as a SIBLING of the bubble, the correction card under the learner's own line - drawn only when
 *      DuSu has finished speaking, Hear it / Try again - the mic stays en-US, a locked screen re-opens the SAME topic with a replay that holds no Hindi and no correction, the subtitle
 *      toggle, the end-of-chat list of fixes, one reward
 *   C  a failed turn: the retry pop-up and the SAME words once; a key-limit frame; the turn cap
 *   D  the global Hindi / English switch changes not one word of the chat
 *   E  hostile text from the model or the topic bank is text, never markup
 *   F  layout at 360 / 390 / 1280 (screenshots), tab order and focus
 *
 *   tests/talk/browser/run_real.sh real.spec.cjs        ONLY=B3,C1 runs just those scenarios; SECTIONS=A,B just those sections
 */
const { chromium } = require('/pw/node_modules/playwright');
const L = require('./lib.cjs').create('talk (real browser, real server)');
const { T, sleep, until } = L;

const ONLY = (process.env.ONLY || '').split(',').filter(Boolean), SECS = (process.env.SECTIONS || '').split(',').filter(Boolean);
const DEV = s => /[ऀ-ॿ]/.test(String(s));
// replies the scripted model gives. The two fixes are the ones the server-side tests already prove verifiable for these learner lines.
const SAY_HE = 'he go to office every day', FIX_HE = { q: 'he go', f: 'he goes', r: 'He needs goes.' };
const SAY_PAST = 'yesterday i go to the market', FIX_PAST = { q: 'i go', f: 'I went', r: 'Yesterday means past: use went.', w: 'Yesterday के साथ past आता है, इसलिए went।' };
const HI1 = 'अच्छा! तुमने वहाँ क्या खरीदा?', HI2 = 'अच्छा लगा! फिर आगे क्या हुआ?';
const rep = (reply, hi, fix) => ({ reply, hi: hi === undefined ? HI2 : hi, fix: fix || null });
const userTexts = P => P.conns.flatMap(c => c.out('user_text')).map(j => j.text);
const aiFrames = P => P.conns.flatMap(c => c.in('ai_text'));
const bubbleTexts = page => page.evaluate(() => [...document.querySelectorAll('#feed .msg:not(.thinking)')].map(m => ({ role: m.classList.contains('ai') ? 'assistant' : 'user', content: m.querySelector('.bubble').textContent.trim() })));
const feedText = page => page.evaluate(() => document.getElementById('feed').innerText);
const fixCount = page => page.evaluate(() => document.querySelectorAll('#feed .tk-fix').length);
const aiN = page => L.aiN(page);
const wait = (fn, ms) => until(fn, ms || 10000);
const stateOf = async who => (await L.tk(who, '/state')).body;
const dailyKeys = ['day', 'hour', 'keys', 'lang', 'mode', 'mood', 'resume', 'token', 'type'];

let browser;
async function scenario(id, title, who, fn, o = {}) {
  if (ONLY.length && ONLY.indexOf(id) < 0) return;
  if (SECS.length && SECS.indexOf(id[0]) < 0) return;
  T.section(id + ' ' + title);
  let ctx;
  try {
    await L.reset();
    if (o.pre) await o.pre();
    ctx = await L.ctxFor(browser, who, o);
    const P = await L.proxy(ctx);
    const page = o.noBoot ? null : await (o.boot ? o.boot(ctx) : L.bootTalk(ctx));
    await fn({ page, P, who, ctx });
    if (page) {
      const e = await page.evaluate(() => ({ errors: window.__errors, rejections: window.__rejections }));
      T.eq(e.errors, [], id + ': no script error'); T.eq(e.rejections, [], id + ': no unhandled rejection');
    }
    T.eq(L.ERRS.splice(0), [], id + ': no console or page error');
  } catch (e) {
    T.ok(false, id + ': the scenario threw: ' + String((e && e.stack) || e).slice(0, 400));
  } finally {
    try { await ctx.close(); } catch (e) { /* closed */ }
    await L.reset();
  }
}

(async () => {
  browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    // ==================================================================================================================== A. the Talk screen
    await scenario('A1', 'the topic card: today\'s topic in English and Hindi, three starters, useful words with Hindi, the grammar focus, the level choice', 'tk1', async ({ page, P }) => {
      const st = await stateOf('tk1'), tp = st.topic;
      T.ok(st.enabled && tp && st.levels.length === 3 && st.alternatives.length === 3, 'A1: the server answered with a topic, three levels and three alternatives');
      T.eq(await L.screen(page), 'tk', 'A1: the Talk screen is open');
      T.eq(await page.evaluate(() => location.pathname), '/talk', 'A1: the URL is /talk');
      T.eq(await L.tc(page, '#tkTopicEn'), tp.title.en, 'A1: the topic title in English');
      T.eq(await L.tc(page, '#tkTopicHi'), tp.title.hi, 'A1: ...and in Hindi (the learner\'s own screen language does not change either)');
      T.eq(await page.$$eval('#tkStarters .tk-chip', e => e.map(x => x.textContent)), tp.starters.map(s => s.en), 'A1: three starter chips, in English');
      const vocab = await page.$$eval('#tkVocab .tk-w', e => e.map(x => x.innerText.replace(/\s+/g, ' ').trim()));
      T.ok(vocab.length >= 6 && vocab.length <= 8 && vocab.every((v, i) => v === tp.vocab[i].en + ' ' + tp.vocab[i].hi), 'A1: 6-8 useful words, each with its Hindi: ' + JSON.stringify(vocab));
      T.eq(await L.tc(page, '#tkFocus'), 'Grammar focus: ' + tp.focus.split('_').map(w => w[0].toUpperCase() + w.slice(1)).join(' ') + ' →', 'A1: the grammar focus chip names the Lab unit');
      T.eq(await page.getAttribute('#tkFocus', 'data-unit'), tp.focus, 'A1: ...and carries the unit id');
      T.eq(await page.$$eval('#tkLv .tk-lvopt', e => e.map(x => x.dataset.level)), ['hi', 'en_sub', 'en'], 'A1: the three levels, in order');
      T.eq(await page.$$eval('#tkLv .tk-lvopt', e => e.map(x => x.getAttribute('aria-checked'))), ['false', 'true', 'false'], 'A1: the level of an A2 learner is preselected (English + Hindi subtitles)');
      T.eq(await page.getAttribute('#tkLv', 'role'), 'radiogroup', 'A1: the level switch is a radio group');
      const lv = await page.$$eval('#tkLv .tk-lvopt', e => e.map(x => x.querySelector('b').textContent + ' | ' + x.querySelector('small').textContent));
      T.eq(lv, st.levels.map(l => l.label.hi + ' | ' + l.hint.hi), 'A1: each level shows the server\'s label and hint (Hindi is the screen\'s default)');
      T.has(await L.tc(page, '#tkStart'), 'बात शुरू करो', 'A1: the primary button starts the talk');
      T.eq(P.conns.length, 0, 'A1: just opening the screen opens no chat connection');
      T.ok(/lining-nums/.test(await page.evaluate(() => getComputedStyle(document.getElementById('tkVocab')).fontVariantNumeric)), 'A1: lining numerals');
      // the focus chip is a real link into the Grammar Lab
      await page.click('#tkFocus'); await page.waitForSelector('#gl.on');
      T.eq(await page.evaluate(() => location.pathname), '/grammar-lab/' + tp.focus, 'A1: the focus chip opens that Grammar Lab unit');
    });

    await scenario('A2', 'a starter is a hint, never a send: tap shows it with its Hindi and a Hear button, tap again or Escape closes it', 'tk2', async ({ page, P }) => {
      const tp = (await stateOf('tk2')).topic;
      const reqs = []; page.on('request', r => { if (r.method() !== 'GET') reqs.push(r.method() + ' ' + new URL(r.url()).pathname); });
      T.ok(!(await L.vis(page, '#tkHint')), 'A2: no hint before a tap');
      await page.click('#tkS1');
      T.ok(await L.vis(page, '#tkHint'), 'A2: a tap shows the hint');
      T.eq(await L.tc(page, '#tkHint .tk-hint-en'), tp.starters[1].en, 'A2: the English of that starter');
      T.eq(await L.tc(page, '#tkHint .tk-hint-hi'), tp.starters[1].hi, 'A2: ...and its Hindi');
      T.eq(await page.getAttribute('#tkS1', 'aria-pressed'), 'true', 'A2: the chip is pressed');
      T.eq(await page.getAttribute('#tkS0', 'aria-pressed'), 'false', 'A2: the others are not');
      await page.click('#tkS2');
      T.eq(await L.tc(page, '#tkHint .tk-hint-en'), tp.starters[2].en, 'A2: another starter replaces the hint');
      await page.click('#tkHintHear'); await sleep(250);
      T.ok((await L.spoken(page)).includes(tp.starters[2].en), 'A2: Hear speaks the English starter');
      const sp = await page.evaluate(() => window.__spoken.slice());
      T.ok(sp.every(x => !DEVf(x)), 'A2: nothing Hindi is spoken: ' + JSON.stringify(sp));
      await page.click('#tkS2');
      T.ok(!(await L.vis(page, '#tkHint')), 'A2: tapping the same chip again closes it');
      await page.click('#tkS0'); await page.keyboard.press('Escape');
      T.ok(!(await L.vis(page, '#tkHint')), 'A2: Escape closes the hint');
      T.eq(await page.evaluate(() => document.activeElement && document.activeElement.id), 'tkS0', 'A2: ...and the focus goes back to the chip that opened it');
      T.eq(P.conns.length, 0, 'A2: no chat connection was opened by any of it');
      T.eq(reqs, [], 'A2: nothing was POSTed (a starter is not sent anywhere)');
      T.eq((await L.log()).talk_calls, 0, 'A2: and the model was never called');
    });

    await scenario('A3', 'the level switch is remembered on the server (and again after a reload)', 'tk3', async ({ page, ctx }) => {
      T.eq((await stateOf('tk3')).support_chosen, false, 'A3: nothing chosen yet');
      await L.selectLevel(page, 'en');
      T.ok(await wait(async () => (await stateOf('tk3')).support === 'en', 5000), 'A3: choosing English only is saved (POST /tk/prefs)');
      T.eq((await stateOf('tk3')).support_chosen, true, 'A3: ...as the learner\'s own choice');
      T.eq(await page.$$eval('#tkLv .tk-lvopt', e => e.map(x => x.getAttribute('aria-checked'))), ['false', 'false', 'true'], 'A3: the radio moved');
      await page.reload(); await page.waitForSelector('#tk.on'); await L.settled(page);
      T.eq(await page.$$eval('#tkLv .tk-lvopt', e => e.map(x => x.getAttribute('aria-checked'))), ['false', 'false', 'true'], 'A3: after a reload English only is still the preselected level');
      await L.selectLevel(page, 'hi');
      T.has(await L.tc(page, '#tkStart'), 'Daily Talk', 'A3: Hindi to English: the primary button says it starts Daily Talk');
      T.ok(await wait(async () => (await stateOf('tk3')).support === 'hi', 5000), 'A3: Hindi to English is remembered too');
      await L.selectLevel(page, 'en_sub');
      T.has(await L.tc(page, '#tkStart'), 'बात शुरू करो', 'A3: and back to a Talk level the button is the Talk one again');
      T.ok(await wait(async () => (await stateOf('tk3')).support === 'en_sub', 5000), 'A3: English + Hindi subtitles is remembered');
    });

    await scenario('A4', 'choose another topic: three alternatives, the card changes, a way back to today\'s, and the chat opens THAT topic', 'tk4', async ({ page, P }) => {
      const st = await stateOf('tk4'), today = st.topic, alts = st.alternatives;
      T.ok(!(await L.vis(page, '#tkAlts')), 'A4: the list is closed at first');
      await page.click('#tkAnother');
      T.eq(await page.$$eval('#tkAlts .tk-alt', e => e.map(x => x.dataset.id)), alts.map(a => a.id), 'A4: the three alternatives the server named');
      T.eq(await page.getAttribute('#tkAnother', 'aria-expanded'), 'true', 'A4: the button says the list is open');
      await page.keyboard.press('Escape');
      T.ok(!(await L.vis(page, '#tkAlts')), 'A4: Escape closes the list'); T.eq(await page.evaluate(() => document.activeElement.id), 'tkAnother', 'A4: ...and the focus returns to the button');
      await page.click('#tkAnother');
      const pick = alts[1], full = (await L.tk('tk4', '/topic/' + pick.id)).body;
      await page.click('#tkAlts .tk-alt[data-id="' + pick.id + '"]');
      T.ok(await wait(async () => (await L.tc(page, '#tkTopicEn')) === full.title.en, 5000), 'A4: the card now shows the chosen topic');
      T.eq(await L.tc(page, '#tkTopicHi'), full.title.hi, 'A4: ...in Hindi too');
      T.eq(await page.$$eval('#tkStarters .tk-chip', e => e.map(x => x.textContent)), full.starters.map(s => s.en), 'A4: with its own starters');
      T.has(await L.tc(page, '#tkCard .tk-lab'), 'चुना हुआ', 'A4: the label says it is the learner\'s choice, not today\'s topic');
      await page.click('#tkAnother');
      T.has(await L.tc(page, '#tkAlts .tk-alt'), 'आज के topic पर वापस', 'A4: the first row is the way back to today\'s topic');
      await L.selectLevel(page, 'en_sub');
      await page.evaluate(() => { window.__hold = true; });
      await page.click('#tkStart'); await L.onSession(page); await L.sessReady(page);
      T.eq(P.starts()[0].topic_id, full.id, 'A4: the chat\'s start frame names the CHOSEN topic, not today\'s');
      T.eq((await bubbleTexts(page))[0].content, full.opener.en, 'A4: and the opener is that topic\'s');
      // the way back: go to the card again
      await page.evaluate(() => navTo('/talk')); await page.waitForSelector('#tk.on'); await L.settled(page);
      T.eq(await L.tc(page, '#tkTopicEn'), today.title.en, 'A4: coming back to the screen shows today\'s topic again');
      await page.click('#tkAnother'); await page.click('#tkAlts .tk-alt[data-id="' + pick.id + '"]');
      await wait(async () => (await L.tc(page, '#tkTopicEn')) === full.title.en);
      await page.click('#tkAnother'); await page.click('#tkAlts .tk-alt:first-child');
      T.ok(await wait(async () => (await L.tc(page, '#tkTopicEn')) === today.title.en, 5000), 'A4: "back to today\'s topic" restores it without asking the server');
      T.has(await L.tc(page, '#tkCard .tk-lab'), 'आज का topic', 'A4: ...and the label');
    });

    await scenario('A5', 'with the Grammar Lab off the focus is a plain label, not a link', 'tk5', async ({ page }) => {
      T.eq(await page.evaluate(() => document.getElementById('tkFocus').tagName), 'BUTTON', 'A5: with the Lab on the focus is a button');
      await L.setting('grammar_lab', 'off');
      await page.evaluate(() => refreshMe());                                       // /me lands again: the Lab is gone for this account
      T.ok(await wait(async () => (await page.evaluate(() => document.getElementById('tkFocus').tagName)) === 'SPAN', 6000), 'A5: a span (no button, no link) once the Lab is not available for this account - the card follows /me');
      T.has(await L.tc(page, '#tkFocus'), 'Grammar focus:', 'A5: it still tells what the topic practises');
    });

    await scenario('A6', 'an empty topic bank is a friendly message, never an error', 'tk6', async ({ page }) => {
      const st = await stateOf('tk6');
      T.ok(st.empty === true && st.topic === null, 'A6: the server says empty with no topic');
      T.has(await L.tc(page, '#tkEmpty'), 'Topics जल्दी आ रहे हैं', 'A6: "topics are coming soon", in Hindi (the default)');
      T.ok(!(await L.vis(page, '#tkNote')) && !(await L.vis(page, '#tkRetry')), 'A6: no error banner and no retry button');
      T.ok(!(await L.vis(page, '#tkLv')) && !(await L.vis(page, '#tkStart')), 'A6: no level switch and no Start (there is nothing to talk about)');
      await page.click('#tkEmptyGo'); await page.waitForSelector('#daily.on');
      T.eq(await page.evaluate(() => location.pathname), '/daily-talk', 'A6: Daily Talk is one tap away');
    }, { pre: () => L.e2e('/bank', { mode: 'empty' }) });

    await scenario('A7', 'the screen\'s own language: Hindi by default, English one tap away, remembered, no request, the topic\'s own words never translated', 'tk7', async ({ page }) => {
      const tp = (await stateOf('tk7')).topic;
      const reqs = []; page.on('request', r => reqs.push(new URL(r.url()).pathname));
      T.has(await L.tc(page, '#tkCard .tk-lab'), 'आज का topic', 'A7: Hindi by default');
      T.eq(await page.getAttribute('#tkLangHi', 'aria-pressed'), 'true', 'A7: the Hindi button is pressed');
      await page.click('#tkLangEn');
      T.has(await L.tc(page, '#tkCard .tk-lab'), "Today's topic", 'A7: English on a tap');
      T.eq(await L.tc(page, '#tkStart'), 'Start talking', 'A7: the button too');
      T.eq(await L.tc(page, '#tkTopicHi'), tp.title.hi, 'A7: the topic\'s Hindi title is still Hindi');
      T.eq(await L.tc(page, '#tkTopicEn'), tp.title.en, 'A7: ...and its English title is still English');
      T.eq(await page.evaluate(() => localStorage.getItem('dusu_tk_lang')), 'en', 'A7: remembered on this device');
      T.eq(reqs.filter(p => p.startsWith('/tk')), [], 'A7: flipping it asked the server for nothing');
      await page.reload(); await page.waitForSelector('#tk.on'); await L.settled(page);
      T.has(await L.tc(page, '#tkCard .tk-lab'), "Today's topic", 'A7: after a reload it is still English');
      T.eq(await page.evaluate(() => document.getElementById('tkLangEn').getAttribute('aria-pressed')), 'true', 'A7: ...with the English button pressed');
    });

    await scenario('A8', 'Hindi to English is Daily Talk: its own route and socket, today\'s frames untouched, nothing sent to the talk mode', 'tk8', async ({ page, P, ctx }) => {
      await L.selectLevel(page, 'hi');
      await page.evaluate(() => { window.__hold = true; });
      await page.click('#tkStart'); await page.waitForSelector('#daily.on');
      T.eq(await page.evaluate(() => location.pathname), '/daily-talk', 'A8: the URL is Daily Talk\'s');
      T.ok(await wait(async () => P.conns.length >= 1 && P.conns[0].out('start').length === 1, 8000), 'A8: one socket with a start frame was opened');
      const f = P.starts()[0];
      T.eq(f.mode, 'daily', 'A8: the mode is daily');
      T.eq(Object.keys(f).sort(), dailyKeys, 'A8: the frame has exactly the keys Daily Talk always sent: ' + Object.keys(f).sort().join(','));
      T.ok(!('topic_id' in f) && !('support' in f), 'A8: no topic and no support level in it');
      T.ok(P.starts().every(s => s.mode === 'daily') && P.conns.flatMap(c => c.out('user_text')).length === 0, 'A8: and no frame at all went to the talk mode');
      T.ok(await wait(async () => P.conns[0].in('daily_question').length === 1, 10000), 'A8: the server answered with Daily Talk\'s own opener');
      // the same frame the Daily tab sends
      const ctx2 = await L.ctxFor(browser, 'tk9'); const P2 = await L.proxy(ctx2); const p2 = await L.boot(ctx2, '/');
      await p2.click('.btab[data-tab="daily"]'); await p2.waitForSelector('#daily.on'); await wait(async () => P2.starts().length === 1, 8000);
      T.eq(Object.keys(P2.starts()[0]).sort(), Object.keys(f).sort(), 'A8: it is the very frame the Daily tab sends (same keys)');
      await ctx2.close();
    });

    await scenario('A9', 'the default level follows the learner\'s level: A1 Hindi to English, A2 subtitles, B1 English only', 'tk1', async ({ ctx }) => {
      const want = { a1: 'hi', tk1: 'en_sub', b1: 'en' };
      for (const who of ['a1', 'tk1', 'b1']) {
        const c = await L.ctxFor(browser, who); const p = await L.bootTalk(c);
        const on = await p.$$eval('#tkLv .tk-lvopt', e => e.filter(x => x.getAttribute('aria-checked') === 'true').map(x => x.dataset.level));
        T.eq(on, [want[who]], 'A9: ' + who + ' starts on ' + want[who]);
        await c.close();
      }
    });

    await scenario('A10', 'entry points: the Practice hub, the More sheet and (with Home AI on) a Home tile all open /talk', 'tk10', async ({ page }) => {
      await page.evaluate(() => { show('practice'); });
      T.ok(await wait(() => L.vis(page, '#tkEntry'), 5000), 'A10: the Practice hub has the Talk entry');
      await page.click('#tkEntry'); await page.waitForSelector('#tk.on');
      T.eq(await page.evaluate(() => location.pathname), '/talk', 'A10: the hub entry opens /talk');
      T.eq(await page.evaluate(() => document.querySelector('.btab.active').dataset.tab), 'practice', 'A10: the Practice tab is lit');
      await page.evaluate(() => { show('home'); openMore(); });
      T.ok(await L.vis(page, '#mrowTK'), 'A10: the More sheet has the Talk row'); T.has(await L.tc(page, '#mrowTK'), 'Hindi subtitles', 'A10: it says what Talk is');
      await page.click('#mrowTK'); await page.waitForSelector('#tk.on'); await L.settled(page);
      T.eq(await page.evaluate(() => location.pathname), '/talk', 'A10: the More row opens /talk');
      await L.setting('home_ai', 'on');
      const c2 = await L.ctxFor(browser, 'tk11'); const p2 = await L.boot(c2, '/'); await p2.waitForSelector('#home.on');
      T.ok(await wait(() => L.vis(p2, '#hmFeats .hm-feat[data-id="talk"]'), 15000), 'A10: with Home AI on, Home has a Talk tile');
      T.eq(await p2.getAttribute('#hmFeats .hm-feat[data-id="talk"]', 'data-route'), '/talk', 'A10: it goes to /talk');
      T.eq((await p2.$$('#hmFeats .hm-feat[data-id="talk"] svg')).length, 1, 'A10: with a drawn icon, not the fallback glyph');
      await p2.click('#hmFeats .hm-feat[data-id="talk"]'); await p2.waitForSelector('#tk.on');
      T.eq(await p2.evaluate(() => location.pathname), '/talk', 'A10: a tap opens it');
      await c2.close();
    });

    await scenario('A11', 'the switch off: no entry point, /talk goes Home, the API says 404 - cold or from a stale cache', 'off', async ({ ctx }) => {
      await L.setting('talk_v3', 'owner');
      T.eq((await L.tk('off', '/state')).status, 404, 'A11: /tk/state answers 404 for an ordinary account');
      const cold = await L.ctxFor(browser, 'off', { cachedOn: false });
      const coldReqs = []; cold.on('request', r => { const q = new URL(r.url()).pathname; if (q.startsWith('/tk/')) coldReqs.push(q); });
      const p = await L.boot(cold, '/talk');
      await sleep(800);
      T.eq(coldReqs, [], 'A11: with the switch off the page never even asks /tk (the route is guarded by /me.talk_v3, not by a 404)');
      T.eq(await L.screen(p), 'home', 'A11: a cold /talk deep link ends on Home');
      await p.evaluate(() => { show('practice'); });
      T.ok(await wait(() => L.vis(p, '#glEntry'), 5000), 'A11: (control) the same Practice hub does show the Grammar Lab entry, so the Talk entry\'s absence below is real');
      T.ok(!(await L.vis(p, '#tkEntry')), 'A11: there is no Talk entry in the Practice hub');
      T.eq(await p.evaluate(() => document.getElementById('tkEntry').hidden), true, 'A11: the entry carries the hidden attribute');
      await p.evaluate(() => { show('home'); openMore(); });
      T.ok(!(await L.vis(p, '#mrowTK')), 'A11: ...and no Talk row in the More sheet');
      T.eq(await p.evaluate(() => document.getElementById('mrowTK').hidden), true, 'A11: the row carries the hidden attribute');
      T.eq(await p.evaluate(() => userState.talk_v3), false, 'A11: /me says talk_v3 false');
      await cold.close();
      const stale = await L.ctxFor(browser, 'off'); const p2 = await L.boot(stale, '/talk');   // the cached state still says "on"
      T.ok(await wait(async () => (await L.screen(p2)) === 'home', 8000), 'A11: with a stale cache saying "on" the page asks, hears 404 and goes Home');
      await stale.close();
      for (const who of ['owner', 'early']) { T.eq((await L.tk(who, '/state')).status, 200, 'A11: ' + who + ' still has it under "owner + early access"'); }
      await L.setting('talk_v3', 'off');
      T.eq((await L.tk('owner', '/state')).status, 404, 'A11: "off" is off for everyone');
    }, { noBoot: true });

    await scenario('A12', 'a cold /talk deep link (nothing cached) waits for the first /me and then opens - it does not bounce a learner who HAS Talk to Home', 'tk12', async ({ ctx }) => {
      const cold = await L.ctxFor(browser, 'tk12', { cachedOn: false, seed: { dusu_state: { onboarded: true } } });
      await cold.addInitScript(() => { window.__screens = []; const note = () => { const e = document.querySelector('.screen.on'); const id = e ? e.id : ''; if (id && window.__screens[window.__screens.length - 1] !== id) window.__screens.push(id); };
        new MutationObserver(note).observe(document, { subtree: true, attributes: true, attributeFilter: ['class'] }); document.addEventListener('DOMContentLoaded', note); });
      const p = await L.boot(cold, '/talk');
      T.ok(await wait(async () => (await L.screen(p)) === 'tk', 12000), 'A12: the Talk screen opens once /me has answered');
      const seen = await p.evaluate(() => window.__screens);
      T.ok(seen.indexOf('tk') >= 0 && seen.slice(0, seen.indexOf('tk')).indexOf('home') < 0, 'A12: and the learner was never shown Home on the way (the flag was not judged before /me answered): ' + JSON.stringify(seen));
      await L.settled(p);
      T.eq(await p.evaluate(() => location.pathname), '/talk', 'A12: on /talk');
      T.eq(await p.evaluate(() => userState.talk_v3), true, 'A12: /me said talk_v3');
      await cold.close();
    }, { noBoot: true });

    await scenario('A13', 'a second routing pass (a cold start routes twice) does not wipe a card that was just drawn, and asks the server nothing more', 'tk13', async ({ page }) => {
      const reqs = []; page.on('request', r => { const p = new URL(r.url()).pathname; if (p.startsWith('/tk/')) reqs.push(p); });
      await page.click('#tkS1');
      T.ok(await L.vis(page, '#tkHint'), 'A13: a starter hint is open');
      await page.evaluate(() => navTo('/talk')); await sleep(600);
      T.ok(await L.vis(page, '#tkHint'), 'A13: after the second pass the hint is still open (the card was not rebuilt)');
      T.eq(reqs, [], 'A13: and /tk/state was not asked again');
    });

    // ==================================================================================================================== B. the chat
    await scenario('B1', 'a chat at English + Hindi subtitles: the start frame, one opener bubble, the subtitle as a sibling, English spoken, en-US mic', 'tk20', async ({ page, P }) => {
      const tp = (await stateOf('tk20')).topic;
      await L.spyUsage(page);
      await L.startChat(page);
      const st = P.starts();
      T.eq(st.length, 1, 'B1: one start frame');
      const f = st[0];
      T.eq(Object.keys(f).sort(), ['day', 'hour', 'keys', 'mode', 'name', 'support', 'token', 'topic_id', 'type', 'tzmin'], 'B1: its keys: ' + Object.keys(f).sort().join(','));
      T.ok(f.mode === 'talk' && f.support === 'en_sub' && f.topic_id === tp.id && typeof f.tzmin === 'number' && typeof f.hour === 'number', 'B1: mode talk, the level, the topic id, the clock: ' + JSON.stringify({ ...f, token: '…', keys: '…' }));
      T.ok(!('lang' in f) && !('seed' in f) && !('gref' in f) && !('opening' in f), 'B1: no `lang`, no seed, no Grammar Coach reference (Talk is English, and v1 has no second analysis)');
      T.eq(await page.evaluate(() => currentMode), 'talk', 'B1: the page is in Talk mode');
      T.eq(await page.evaluate(() => document.getElementById('session').classList.contains('tk-chat')), true, 'B1: the session screen is the Talk chat');
      T.eq(await L.tc(page, '#sessTitle'), 'Talk', 'B1: the title says Talk'); T.eq(await L.tc(page, '#sessSub'), tp.title.en, 'B1: ...and the sub-line the topic');
      T.eq(await L.tc(page, '#endBtn'), 'End', 'B1: End');
      T.eq(await page.evaluate(() => location.pathname), '/talk', 'B1: the URL stays /talk');
      T.eq(await aiN(page), 1, 'B1: the opener is ONE bubble from DuSu');
      T.eq((await bubbleTexts(page))[0].content, tp.opener.en, 'B1: its text is the topic\'s English opener');
      const subs = await L.subs(page);
      T.eq(subs.length, 1, 'B1: one Hindi subtitle');
      T.ok(subs[0].text === tp.opener.hi && subs[0].inBubble === false && subs[0].parentIsMsg === true, 'B1: it is the Hindi opener, a child of the message but NOT inside the bubble: ' + JSON.stringify(subs[0]));
      T.eq(await page.evaluate(() => document.querySelector('#feed .msg.ai .bubble').textContent.trim()), tp.opener.en, 'B1: the bubble holds the English only');
      await sleep(400);
      const spoken = await page.evaluate(() => window.__spoken.slice());
      T.eq(spoken, [tp.opener.en], 'B1: the learner hears the English opener and nothing else - nobody reads the subtitle aloud');
      const langs = await page.evaluate(() => window.__srLangs);
      T.ok(langs.length >= 1 && langs.every(l => l === 'en-US'), 'B1: the mic listens in en-US: ' + JSON.stringify(langs));
      T.eq(await L.usageCalls(page), 1, 'B1: the chat counted as ONE session');
      T.eq((await L.log()).talk_calls, 0, 'B1: the opener made no model call');
      T.ok(await L.vis(page, '#tkSubBtn'), 'B1: the subtitle toggle is there at this level');
      T.ok(await wait(async () => (await L.tc(page, '#stateLabel')) === 'Listening', 5000), 'B1: and DuSu is listening');
    });

    await scenario('B2', 'English only: no subtitle button, no subtitle even when a stray one arrives', 'tk21', async ({ page, P }) => {
      await L.startChat(page, { level: 'en' });
      T.eq(P.starts()[0].support, 'en', 'B2: the start frame says English only');
      T.eq((await L.subs(page)).length, 0, 'B2: the opener has no subtitle');
      T.ok(!(await L.vis(page, '#tkSubBtn')), 'B2: and there is no subtitle button');
      P.rewrite = j => j.type === 'ai_text' ? Object.assign({}, j, { hi: 'यह कभी नहीं दिखना चाहिए।' }) : j;
      await L.script([rep('Nice. What do you do there?', undefined)]);
      T.ok(await L.saySess(page, 'i like my city'), 'B2: a turn is answered');
      await sleep(300);
      T.eq((await L.subs(page)).length, 0, 'B2: a stray `hi` from the server is NOT drawn at English only');
      T.eq((await bubbleTexts(page)).map(b => b.role), ['assistant', 'user', 'assistant'], 'B2: three bubbles');
    });

    await scenario('B3', 'a turn with a subtitle and NO fix: no card; then a verified fix: the card sits under the learner\'s own line - after DuSu has finished speaking', 'tk22', async ({ page, P }) => {
      await L.startChat(page);
      await L.script([rep('Lovely. Who do you go with?', HI2), rep('Good! What did you buy there?', HI1, FIX_PAST)]);
      T.ok(await L.saySess(page, 'i like the market'), 'B3: the first turn is answered');
      await sleep(400);
      T.eq(await fixCount(page), 0, 'B3: a turn without a fix draws no card');
      T.eq((await L.subs(page)).length, 2, 'B3: but both of DuSu\'s lines have their subtitle');
      T.eq((await L.subs(page))[1].text, HI2, 'B3: the second subtitle is the turn\'s `hi`');
      await page.evaluate(() => { window.__ttsMs = 1600; });                         // DuSu speaks for 1.6 s
      T.ok(await wait(() => L.listening(page), 6000), 'B3: the mic is listening again');
      await page.evaluate(t => window.__say(t), SAY_PAST);
      T.ok(await wait(async () => (await aiN(page)) === 3, 8000), 'B3: DuSu\'s answer to the second turn is on screen');
      const a = aiFrames(P).pop();
      T.ok(a.fix && a.fix.q === 'i go' && a.fix.f === 'I went' && a.fix.full === 'yesterday I went to the market' && (a.fix.c === 'sure' || a.fix.c === 'likely') && a.fix.w, 'B3: the server verified the fix: ' + JSON.stringify(a.fix));
      T.eq(await fixCount(page), 0, 'B3: while DuSu is still speaking the correction is NOT drawn');
      T.eq(await page.evaluate(() => aiSpeaking), true, 'B3: (and she really is speaking)');
      T.ok(await wait(async () => (await fixCount(page)) === 1, 6000), 'B3: when she has finished, the card appears');
      T.eq(await page.evaluate(() => aiSpeaking), false, 'B3: after her speech');
      const fx = (await L.fixes(page))[0];
      T.ok(fx.prevIsUser && /yesterday i go to the market/.test(fx.prevText), 'B3: it sits right under the learner\'s own bubble: ' + fx.prevText);
      T.ok(!fx.inMsg && !fx.inBubble, 'B3: it is outside every message and every bubble (the replay reads only bubbles)');
      T.eq(await L.order(page).then(o => o.join(',')), 'sysmsg,ai,user,ai,user,fix,ai', 'B3: the feed order: ... learner, correction, DuSu\'s answer');
      T.has(fx.text, 'i go', 'B3: the card shows what was said'); T.has(fx.text, 'I went', 'B3: ...the better wording'); T.has(fx.text, 'Yesterday means past: use went.', 'B3: ...the reason in English');
      T.has(fx.text, 'Yesterday के साथ past आता है', 'B3: ...and in Hindi (it came with the fix)');
      T.has(fx.text, a.fix.c === 'sure' ? 'Better' : 'You could say', 'B3: the wording follows the server\'s confidence (' + a.fix.c + ')');
      T.ok(a.fix.c === 'sure' ? !/You could say/.test(fx.text) : !/Better/.test(fx.text), 'B3: and only that wording');
      T.eq(await page.evaluate(() => document.querySelector('#feed .tk-fix').dataset.c), a.fix.c, 'B3: the card carries the confidence');
      T.eq((await L.subs(page)).map(s => s.inBubble), [false, false, false], 'B3: no subtitle is inside a bubble');
      // Hear it speaks the whole corrected line, in English
      await page.evaluate(() => { window.__ttsMs = 60; });
      await page.click('#feed .tk-fix [data-act="hear"]'); await sleep(300);
      const sp = await page.evaluate(() => window.__spoken.slice());
      T.eq(sp[sp.length - 1], 'yesterday I went to the market', 'B3: Hear it speaks the whole corrected sentence');
      T.ok(sp.every(x => !DEVf(x)), 'B3: and nothing spoken is Hindi');
      // Try again hands the learner the mic
      await wait(async () => (await page.evaluate(() => aiSpeaking)) === false, 4000);
      await page.evaluate(() => { window.__hold = true; });
      const s0 = await page.evaluate(() => window.__srStarts);
      await page.click('#feed .tk-fix [data-act="again"]');
      T.ok(await wait(async () => (await page.evaluate(() => window.__srStarts)) > s0, 4000), 'B3: Try again starts the recogniser');
      T.ok((await page.evaluate(() => window.__srLangs)).every(l => l === 'en-US'), 'B3: in en-US');
      T.has(await L.tc(page, '#feed .tk-fix .tk-fix-st'), 'सुन रही हूँ', 'B3: and says it is listening (in Hindi at the subtitle level)');
      await L.script([rep('That is right! What else?', HI2)]);
      T.ok(await wait(() => L.listening(page), 4000), 'B3: the recogniser is listening');
      await page.evaluate(() => window.__say('yesterday I went to the market'));
      T.ok(await wait(async () => (await aiN(page)) === 4, 8000), 'B3: saying the corrected line is an ordinary turn - DuSu answers');
      T.eq(userTexts(P).slice(-1)[0], 'yesterday I went to the market', 'B3: sent as that turn\'s words');
      for (const b of await page.$$('#feed .tk-fix [data-act]')) { const bb = await b.boundingBox(); T.ok(bb.height >= 43.5 && bb.width >= 43.5, 'B3: the card\'s buttons are 44 px targets: ' + JSON.stringify(bb)); }
    });

    await scenario('B4', 'a fix the server cannot verify is dropped (no card); a "likely" is worded softly, a "sure" firmly; at most one card per turn', 'tk23', async ({ page, P }) => {
      await L.startChat(page, { level: 'en' });
      await L.script([rep('Good! Tell me more about that.', undefined, { q: 'he go', f: 'he goes', r: 'He needs goes.' })]);
      T.ok(await L.saySess(page, 'yesterday i went to the market'), 'B4: a turn whose fix quotes words the learner never said is answered');
      await sleep(400);
      T.eq(await fixCount(page), 0, 'B4: ...with NO card (the server dropped the fix)');
      T.eq(aiFrames(P).pop().fix, undefined, 'B4: and the frame had no `fix` key');
      // wording: the frame's `c` decides - one of each, forced through the proxy
      let n = 0; P.rewrite = j => { if (j.type !== 'ai_text' || !j.fix) return j; n++; return Object.assign({}, j, { fix: Object.assign({}, j.fix, { c: n === 1 ? 'sure' : 'likely' }) }); };
      for (const i of [1, 2]) {
        await L.script([rep('Good! Tell me more about that.', undefined, FIX_HE)]);
        T.ok(await L.saySess(page, SAY_HE), 'B4: turn ' + i + ' answered');
        T.ok(await wait(async () => (await fixCount(page)) === i, 5000), 'B4: a card for turn ' + i);
      }
      const cards = await L.fixes(page);
      T.eq(cards.map(c => c.c), ['sure', 'likely'], 'B4: the cards carry their confidence');
      T.ok(/Better/.test(cards[0].text) && !/You could say/.test(cards[0].text), 'B4: "sure" is worded firmly ("Better")');
      T.ok(/You could say/.test(cards[1].text) && !/Better/.test(cards[1].text), 'B4: "likely" is worded softly ("You could say")');
      T.ok(!/तुमने कहा|सुनो/.test(cards[0].text) && !DEVf(cards[0].text), 'B4: at English only the card has no Hindi at all');
      // never two cards for one turn, even if a (rogue) frame carried a list
      P.rewrite = j => j.type === 'ai_text' ? Object.assign({}, j, { fix: [j.fix, j.fix].filter(Boolean) }) : j;
      await L.script([rep('Nice.', undefined, FIX_HE)]);
      T.ok(await L.saySess(page, SAY_HE), 'B4: a turn with a rogue list of fixes is answered');
      await sleep(500);
      T.eq(await fixCount(page), 2, 'B4: a list instead of ONE fix object draws nothing (still two cards)');
    });

    await scenario('B5', 'a locked screen re-opens the SAME topic at the SAME level; the replay holds no Hindi and no correction', 'tk24', async ({ page, P }) => {
      const tp = (await stateOf('tk24')).topic;
      await L.startChat(page);
      await L.script([rep('Lovely. Who do you go with?', HI2), rep('Good! What did you buy there?', HI1, FIX_PAST)]);
      T.ok(await L.saySess(page, 'i like the market'), 'B5: turn 1');
      T.ok(await L.saySess(page, SAY_PAST), 'B5: turn 2');
      T.ok(await wait(async () => (await fixCount(page)) === 1, 6000), 'B5: the card is on screen');
      const before = await bubbleTexts(page), a0 = await aiN(page);
      await L.lock(page); await sleep(300);
      P.last.kill(); await sleep(400);
      await L.script([rep('Welcome back! Where were we?', HI2)]);
      await L.unlock(page);
      T.ok(await wait(async () => P.conns.length === 2 && P.conns[1].out('start').length === 1, 10000), 'B5: on unlock a second connection sends a start frame');
      const f2 = P.conns[1].out('start')[0];
      T.ok(f2.reconnect === true && f2.mode === 'talk', 'B5: it is a quiet reconnect for the talk mode');
      T.eq(f2.topic_id, tp.id, 'B5: the SAME topic (a revive that loses it would be refused by the server)');
      T.eq(f2.support, 'en_sub', 'B5: the SAME level');
      T.ok(!('lang' in f2) && !('gref' in f2), 'B5: still no `lang` and no Grammar Coach reference');
      T.eq(f2.resume, before, 'B5: the replay is exactly the bubbles on screen, in order');
      const blob = JSON.stringify(f2.resume);
      T.ok(!DEVf(blob), 'B5: it holds NO Hindi (the subtitles stayed out)');
      T.ok(!/Yesterday means past|Yesterday के साथ|You said|Better|You could say|Try again|Hear it/.test(blob) && !/I went/.test(blob.replace('yesterday i go to the market', '')), 'B5: and no correction text (the card stayed out)');
      T.ok(await wait(async () => P.conns[1].in('session_resumed').length === 1, 8000), 'B5: the server took it: session_resumed');
      T.eq(P.conns[1].in('session_resumed')[0].mode, 'talk', 'B5: for mode talk');
      T.eq(P.conns[1].in('ai_text').length, 0, 'B5: no second opener');
      T.eq(await aiN(page), a0, 'B5: and no new bubble from DuSu');
      T.eq((await L.subs(page)).length, 3, 'B5: the subtitles on screen are still there'); T.eq(await fixCount(page), 1, 'B5: ...and so is the card');
      T.ok(await wait(() => L.listening(page), 8000), 'B5: the mic is back');
      T.eq((await L.log()).talk_calls, 2, 'B5: the reconnect made no model call');
      // the chat goes on: a further turn is answered, with a subtitle
      T.ok(await L.saySess(page, 'i buy vegetables'), 'B5: a turn after the revive is answered');
      T.eq((await L.subs(page)).length, 4, 'B5: with its subtitle');
      T.ok((await page.evaluate(() => window.__srLangs)).every(l => l === 'en-US'), 'B5: the mic is en-US throughout');
    });

    await scenario('B6', 'the subtitle toggle hides and shows the Hindi, and is remembered for the next chat', 'tk25', async ({ page, P }) => {
      await L.startChat(page);
      T.eq(await page.getAttribute('#tkSubBtn', 'aria-pressed'), 'true', 'B6: subtitles are on by default at this level');
      T.ok(await L.vis(page, '#feed .tk-sub'), 'B6: the opener\'s subtitle is visible');
      await page.click('#tkSubBtn');
      T.ok(!(await L.vis(page, '#feed .tk-sub')), 'B6: one tap hides every subtitle');
      T.eq(await page.getAttribute('#tkSubBtn', 'aria-pressed'), 'false', 'B6: the button says they are off');
      T.has(await L.tc(page, '#tkSubBtn'), 'दिखाओ', 'B6: and offers to show them');
      T.eq(await page.evaluate(() => localStorage.getItem('dusu_tk_sub')), '0', 'B6: remembered');
      T.eq((await L.subs(page)).length, 1, 'B6: (the subtitle is still in the page, only hidden)');
      await L.script([rep('Nice. What do you do there?', HI2, FIX_PAST)]);
      T.ok(await L.saySess(page, SAY_PAST), 'B6: a turn while hidden is answered');
      T.ok(await wait(async () => (await fixCount(page)) === 1, 5000), 'B6: the card is drawn');
      T.ok(!(await L.vis(page, '#feed .tk-fix-w')), 'B6: but its Hindi reason is hidden as well - the learner turned the Hindi off');
      await page.evaluate(() => navTo('/talk')); await page.waitForSelector('#tk.on'); await L.settled(page);
      await L.startChat(page);
      T.eq(await page.getAttribute('#tkSubBtn', 'aria-pressed'), 'false', 'B6: the next chat remembers it: subtitles stay off');
      T.ok(!(await L.vis(page, '#feed .tk-sub')), 'B6: ...and are hidden');
      await page.click('#tkSubBtn');
      T.ok(await L.vis(page, '#feed .tk-sub'), 'B6: a tap shows them again');
    });

    await scenario('B7', 'the end of a chat lists the top three fixes on the session-result screen; one reward; Back and a chat with no turn return to the card', 'tk26', async ({ page, P }) => {
      await L.spyUsage(page);
      await L.startChat(page);
      // four fixes: two real ones, two the proxy adds (so the list has to choose three, "sure" ones first)
      let k = 0; P.rewrite = j => { if (j.type !== 'ai_text' || !j.fix) return j; k++; return Object.assign({}, j, { fix: Object.assign({}, j.fix, { c: k === 3 ? 'sure' : 'likely', f: j.fix.f + (k > 2 ? ' ' + k : '') }) }); };
      for (const [say, fix] of [[SAY_PAST, FIX_PAST], [SAY_HE, FIX_HE], [SAY_HE, FIX_HE], [SAY_PAST, FIX_PAST]]) {
        await L.script([rep('Good. And then?', HI2, fix)]);
        T.ok(await L.saySess(page, say), 'B7: a turn answered');
      }
      T.ok(await wait(async () => (await fixCount(page)) === 4, 6000), 'B7: four cards');
      await page.click('#endBtn');
      T.ok(await wait(async () => (await L.screen(page)) === 'sessionResult', 15000), 'B7: End shows the session-result screen');
      await sleep(700);
      T.eq(await L.screen(page), 'sessionResult', 'B7: and `ended` does not move the learner off it (a Talk chat keeps its result like Face-to-Face)');
      T.ok(await L.vis(page, '#tkSum'), 'B7: the list of fixes is on that screen');
      const rows = await page.$$eval('#tkSum .tk-fix-row', e => e.map(x => x.innerText.replace(/\s+/g, ' ').trim()));
      T.eq(rows.length, 3, 'B7: three fixes, not four: ' + JSON.stringify(rows));
      T.has(rows[0], 'he goes 3', 'B7: the one verified "sure" fix comes first');
      T.ok(new Set(rows.map(r => r.split('→')[1].trim().split(' ')[0] + r.split('→')[1].split(' ')[1])).size >= 2, 'B7: they are not all the same fix');
      T.has(await L.tc(page, '#tkSum'), 'Your top fixes', 'B7: titled');
      T.ok(await wait(async () => (await L.awards('tk26')).length === 1, 8000), 'B7: exactly one reward was paid');
      const aw = (await L.awards('tk26'))[0];
      T.ok(aw.mode === 'talk' && aw.turns === 4, 'B7: as mode "talk" for the 4 turns: ' + JSON.stringify(aw));
      T.eq(await L.usageCalls(page), 1, 'B7: and the chat counted as one session');
      T.eq((await L.log()).sessions.filter(m => m === 'talk').length, 1, 'B7: the server built one Talk session');
      // Back from a fresh chat returns to the Talk screen
      await page.click('#srDone'); await page.waitForSelector('#home.on');
      await page.evaluate(() => navTo('/talk')); await page.waitForSelector('#tk.on'); await L.settled(page);
      await L.startChat(page);
      await page.click('#backBtn'); await page.waitForSelector('#tk.on');
      T.eq(await page.evaluate(() => location.pathname), '/talk', 'B7: Back from a chat returns to the Talk screen (not Home)');
      T.eq((await L.awards('tk26')).length, 1, 'B7: and a chat with no turn paid nothing');
    });

    await scenario('B8', 'End with no turn: back on the card, nothing saved', 'tk27', async ({ page }) => {
      await L.startChat(page);
      await page.click('#endBtn');
      T.ok(await wait(async () => (await L.screen(page)) === 'tk', 12000), 'B8: ended with nothing said -> the Talk screen');
      T.eq((await L.awards('tk27')).length, 0, 'B8: no reward');
    });

    await scenario('B9', 'the free daily session limit is honoured like in every chat: no socket, the plan pop-up opens', 'tk28', async ({ page, P }) => {
      await page.evaluate(() => { window.isUnlimited = () => false; localStorage.setItem('dusu_usage', JSON.stringify({ d: new Date().toISOString().slice(0, 10), n: 99 })); });
      T.eq(await page.evaluate(() => overLimit()), true, 'B9: the page thinks this learner has used up today\'s sessions');
      await page.click('#tkStart');
      T.ok(await wait(() => L.vis(page, '#kySheet.on'), 6000), 'B9: the limit pop-up opens');
      await sleep(400);
      T.eq(P.conns.length, 0, 'B9: and no chat connection was opened');
      T.eq(await L.screen(page), 'tk', 'B9: the learner stays on the Talk screen');
      T.eq(await page.evaluate(() => currentMode === 'talk'), false, 'B9: the page did not enter Talk mode');
    });

    // ==================================================================================================================== C. failures
    await scenario('C1', 'a failed turn: the retry pop-up, no banner, and the SAME words go out once more', 'tk30', async ({ page, P }) => {
      await L.startChat(page);
      await L.fail(1);
      await L.script([rep('Nice to hear that! Tell me more.', HI2)]);
      const a0 = await aiN(page);
      await page.evaluate(t => window.__say(t), 'i like cricket');
      T.ok(await wait(() => L.vis(page, '#kySheet.on'), 20000), 'C1: the pop-up opens');
      const f = P.last.in('error')[0];
      T.ok(f && f.kp && f.kp.state === 'transient' && f.kp.own === true, 'C1: the server frame is `error` with kp (transient, own): ' + JSON.stringify(f && f.kp));
      T.eq(P.last.in('quota').length, 0, 'C1: never a quota frame');
      T.ok(!(await page.evaluate(() => { const b = document.getElementById('notifBar'); return !!b && !b.hidden && getComputedStyle(b).display !== 'none'; })), 'C1: no banner at the top');
      T.eq(await L.userN(page), 1, 'C1: the learner\'s line is on screen once');
      T.eq(await aiN(page), a0, 'C1: nothing new from DuSu yet');
      T.eq((await L.log()).talk_calls, 1, 'C1: one model call so far (the failed one)');
      T.eq(await page.evaluate(() => retryTurnInfo()).then(r => r.can), true, 'C1: the page knows there is a line to send again');
      await page.click('#kySheet .ky-pop-acts .btn.primary');                  // "Try again now"
      T.ok(await wait(async () => (await aiN(page)) > a0, 15000), 'C1: after the button DuSu answers');
      T.eq(userTexts(P), ['i like cricket', 'i like cricket'], 'C1: exactly two user_text frames, the SAME words');
      T.eq(await L.userN(page), 1, 'C1: still ONE bubble for the learner');
      T.eq((await L.log()).talk_calls, 2, 'C1: the retry made exactly one more model call');
      T.ok(await wait(async () => !(await L.vis(page, '#kySheet.on')), 5000), 'C1: the pop-up closed');
      T.eq((await L.subs(page)).length, 2, 'C1: the answer has its subtitle');
      T.eq(await L.fixes(page).then(f => f.length), 0, 'C1: and no card');
    });

    await scenario('C2', 'a key-limit frame and the turn cap are handled like Face-to-Face (the mic rests, the orb says why)', 'tk31', async ({ page, P }) => {
      await L.startChat(page);
      P.last.inject({ type: 'quota', msg: 'Your keys hit their limit.' });
      T.ok(await wait(async () => (await L.tc(page, '#stateLabel')) === 'Paused', 4000), 'C2: a quota frame -> the orb says Paused');
      T.eq(await page.evaluate(() => running), false, 'C2: the mic is off');
      P.last.inject({ type: 'limit', msg: 'That is enough for today.' });
      T.ok(await wait(async () => (await L.tc(page, '#stateLabel')) === 'Session limit', 4000), 'C2: a limit frame -> "Session limit"');
      T.has(await feedText(page), 'That is enough for today.', 'C2: and the message is in the chat');
    });

    // ==================================================================================================================== D. the global language switch
    await scenario('D1', 'the Hindi / English switch changes not one word of the Talk chat', 'tk35', async ({ page, P }) => {
      T.eq(await page.evaluate(() => [LG.lang('talk'), LG.switchable('talk')]), ['en', false], 'D1: Talk is English and not switchable');
      await L.startChat(page);
      await L.script([rep('Lovely. Who do you go with?', HI2, FIX_PAST)]);
      T.ok(await L.saySess(page, SAY_PAST), 'D1: a turn'); T.ok(await wait(async () => (await fixCount(page)) === 1, 5000), 'D1: with a card');
      const snap = () => page.evaluate(() => ({ feed: document.getElementById('feed').innerText, title: document.getElementById('sessTitle').textContent, sub: document.getElementById('sessSub').textContent, end: document.getElementById('endBtn').textContent, btn: document.getElementById('tkSubBtn').textContent }));
      const s0 = await snap();
      await page.evaluate(() => LG.set('en')); await sleep(400);
      const s1 = await snap();
      await page.evaluate(() => LG.set('hi')); await sleep(400);
      const s2 = await snap();
      T.eq(s1, s0, 'D1: switching to English changed nothing on the chat screen');
      T.eq(s2, s0, 'D1: switching to Hindi changed nothing either');
      T.ok(/^(Listening|DuSu is speaking|DuSu is thinking)$/.test(await L.tc(page, '#stateLabel')), 'D1: the orb\'s words are still the English ones: ' + await L.tc(page, '#stateLabel'));
      T.eq(P.conns.flatMap(c => c.out('lang')).length, 0, 'D1: no `lang` frame was sent');
      T.eq(await page.evaluate(() => currentMode), 'talk', 'D1: still in the Talk mode');
      T.ok((await page.evaluate(() => window.__srLangs)).every(l => l === 'en-US'), 'D1: the mic is en-US whatever the switch says');
      await L.script([rep('That is right! What else?', HI2)]);
      T.ok(await L.saySess(page, 'yesterday I went to the market'), 'D1: a turn after the switch');
      T.eq((await L.subs(page)).length, 3, 'D1: still gets its subtitle');
      const sp = await page.evaluate(() => window.__spoken.slice()); T.ok(sp.every(x => !DEVf(x)), 'D1: nothing Hindi was spoken: ' + JSON.stringify(sp));
      T.ok(await wait(async () => (await page.evaluate(() => window.__srStarts)) >= 3, 6000), 'D1: the mic restarted after the switch');
      const langs = await page.evaluate(() => window.__srLangs); T.ok(langs.length >= 3 && langs.every(l => l === 'en-US'), 'D1: every recogniser start - before AND after the switch - was en-US: ' + JSON.stringify(langs));
    });

    // ==================================================================================================================== E. hostile text
    await scenario('E1', 'markup from the model (reply, subtitle, every part of a fix) is text, never HTML', 'tk40', async ({ page, P }) => {
      await L.startChat(page);
      const H = k => '<img src=x onerror="window.__xss=(window.__xss||0)+1"><script>window.__xss=99<\/script>' + k;
      P.rewrite = j => j.type === 'ai_text' && j.text !== undefined && P.last.in('ai_text').length > 1
        ? { type: 'ai_text', text: H('reply'), lang: 'en', hi: H('hi'), fix: { q: H('q'), f: H('f'), r: H('r'), w: H('w'), c: 'sure', full: H('full') } } : j;
      await L.script([rep('ok', HI2)]);
      T.ok(await L.saySess(page, 'i like my city'), 'E1: a hostile turn arrived and was drawn');
      T.ok(await wait(async () => (await fixCount(page)) === 1, 5000), 'E1: with its card');
      await sleep(600);
      T.eq(await page.evaluate(() => window.__xss), 0, 'E1: no script ran');
      T.eq(await page.evaluate(() => document.querySelectorAll('#feed img, #feed script, #feed iframe, #feed [onerror]').length), 0, 'E1: no element was injected into the chat');
      T.has(await feedText(page), '<img src=x', 'E1: the markup is shown as plain text');
      T.has(await page.evaluate(() => { const s = document.querySelectorAll('#feed .tk-sub'); return s[s.length - 1].textContent; }), '<img', 'E1: the subtitle too');
      await page.click('#endBtn'); await wait(async () => (await L.screen(page)) === 'sessionResult', 15000);
      await sleep(400);
      T.eq(await page.evaluate(() => window.__xss), 0, 'E1: nothing ran on the result screen either');
      T.eq(await page.evaluate(() => document.querySelectorAll('#tkSum img, #tkSum script, #srBody img, #srBody script').length), 0, 'E1: no element injected into the list of fixes');
    });

    await scenario('E2', 'markup in the topic card (title, starters, words, alternatives, focus) is text', 'tk41', async ({ ctx }) => {
      const bad = k => '<img src=x onerror="window.__xss=(window.__xss||0)+1">' + k;
      const topic = { id: 'a2-bad', band: 'A2', cat: 'daily', title: { en: bad('t'), hi: bad('h') }, opener: { en: bad('o'), hi: bad('oh') }, starters: [0, 1, 2].map(i => ({ en: bad('s' + i), hi: bad('sh' + i) })),
        vocab: [0, 1, 2, 3, 4, 5].map(i => ({ en: bad('w' + i), hi: bad('wh' + i) })), focus: 'x" onclick="window.__xss=7" y="' };
      const c2 = await L.ctxFor(browser, 'tk41');
      await c2.route('**/tk/state', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ enabled: true, date: '2026-11-17', level: 'A2', band: 'A2', support: 'en_sub', support_chosen: false, support_default: 'en_sub', topic,
        alternatives: [{ id: 'a2-alt', title: { en: bad('alt'), hi: bad('alth') }, band: 'A2', cat: 'daily', focus: 'past_simple' }], levels: [{ id: 'hi', ws_mode: 'daily', label: { en: bad('l'), hi: bad('l') }, hint: { en: bad('x'), hi: bad('x') } }, { id: 'en_sub', ws_mode: 'talk', label: { en: 'x', hi: 'x' }, hint: { en: 'x', hi: 'x' } }, { id: 'en', ws_mode: 'talk', label: { en: 'x', hi: 'x' }, hint: { en: 'x', hi: 'x' } }], empty: false, reviewed: false }) }));
      const page = await L.bootTalk(c2);
      await page.click('#tkS0'); await page.click('#tkAnother'); await sleep(500);
      T.eq(await page.evaluate(() => window.__xss), 0, 'E2: no script ran');
      T.eq(await page.evaluate(() => document.querySelectorAll('#tk img, #tk script, #tk iframe, #tk [onerror], #tk [onclick]').length), 0, 'E2: no element or handler was injected');
      T.has(await L.tc(page, '#tkTopicEn'), '<img src=x', 'E2: the title is shown as text');
      T.eq(await page.evaluate(() => document.getElementById('tkFocus')), null, 'E2: a focus value that is not a unit id draws no chip at all');
      await c2.close();
    }, { noBoot: true });

    // ==================================================================================================================== F. layout, keys
    for (const [name, vw, vh] of [['360', 360, 740], ['390', 390, 844], ['1280', 1280, 800]]) {
      await scenario('F' + name, 'layout at ' + vw + ' px: the card, the level switch, the chat with a subtitle and a card, the end list - nothing overflows, 44 px targets, 12 px text', 'tk4' + (vw === 360 ? 2 : vw === 390 ? 3 : 4), async ({ page, P }) => {
        for (const lg of ['hi', 'en']) {
          await page.evaluate(l => { document.getElementById(l === 'hi' ? 'tkLangHi' : 'tkLangEn').click(); }, lg);
          await page.evaluate(() => { document.querySelector('.wrap').scrollTop = 0; });
          await page.click('#tkS0'); await L.shot(page, `tk-card-${name}-${lg}`);
          L.clean(await L.audit(page, '#tk'), `F${name} card (${lg})`);
          await page.evaluate(() => { document.getElementById('tkLevelCard').scrollIntoView(); }); await L.shot(page, `tk-level-${name}-${lg}`);
          await page.click('#tkAnother'); L.clean(await L.audit(page, '#tk'), `F${name} card with the other topics (${lg})`); await page.click('#tkAnother');
        }
        await page.evaluate(() => { document.getElementById('tkLangHi').click(); });
        await L.startChat(page);
        await L.script([rep('Good! What did you buy there?', HI1, FIX_PAST)]);
        await L.saySess(page, SAY_PAST); await wait(async () => (await fixCount(page)) === 1, 6000); await sleep(300);
        await L.shot(page, `tk-chat-${name}`);
        L.clean(await L.audit(page, '#session'), `F${name} chat`);
        await page.evaluate(() => { const f = document.getElementById('feed'); f.scrollTop = 0; }); await L.shot(page, `tk-chat-top-${name}`);
        await page.click('#endBtn'); await wait(async () => (await L.screen(page)) === 'sessionResult', 15000); await sleep(1500);
        await L.shot(page, `tk-result-${name}`);
        L.clean(await L.audit(page, '#sessionResult'), `F${name} result`);
      }, { viewport: { width: vw, height: vh } });
    }

    await scenario('F2', 'keyboard: Tab goes through the card in order and every stop shows a focus ring', 'tk45', async ({ page }) => {
      await page.evaluate(() => { document.getElementById('tkBack').focus(); });
      const seen = [];
      for (let i = 0; i < 16; i++) {
        await page.keyboard.press('Tab');
        const r = await page.evaluate(() => { const e = document.activeElement; const cs = getComputedStyle(e); return { id: e.id || e.className, inTk: !!e.closest('#tk'), ring: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2 }; });
        if (!r.inTk) break;                                                          // past the last control of the card the Tab walks into the page's own nav
        seen.push(r);
      }
      const ids = seen.map(s => s.id);
      T.eq(ids.slice(0, 5), ['tkLangHi', 'tkLangEn', 'tkFocus', 'tkS0', 'tkS1'], 'F2: header toggle, then the focus chip, then the starters');
      T.ok(ids.indexOf('tkLv-hi') > ids.indexOf('tkS2') && ids.indexOf('tkStart') > ids.indexOf('tkLv-en') && ids[ids.length - 1] === 'tkAnother', 'F2: then the levels, then Start, then "another topic": ' + ids.join(' > '));
      T.ok(seen.every(s => s.ring), 'F2: every stop has a visible focus ring: ' + JSON.stringify(seen.filter(s => !s.ring)));
      await page.focus('#tkLv-en'); await page.keyboard.press('Space');
      T.eq(await page.getAttribute('#tkLv-en', 'aria-checked'), 'true', 'F2: Space picks a level');
      await page.keyboard.press('ArrowUp');
      T.eq(await page.evaluate(() => [document.activeElement.id, document.getElementById('tkLv-en_sub').getAttribute('aria-checked')]), ['tkLv-en_sub', 'true'], 'F2: ArrowUp moves to the previous level, picks it and keeps the focus on it');
      await page.keyboard.press('ArrowDown'); await page.keyboard.press('ArrowDown');
      T.eq(await page.evaluate(() => [document.activeElement.id, document.getElementById('tkLv-hi').getAttribute('aria-checked')]), ['tkLv-hi', 'true'], 'F2: ArrowDown wraps round from the last level to the first');
      await page.keyboard.press('ArrowUp');
      T.eq(await page.getAttribute('#tkLv-en', 'aria-checked'), 'true', 'F2: and ArrowUp wraps back to the last');
      await page.focus('#tkStart'); await page.evaluate(() => { window.__hold = true; }); await page.keyboard.press('Enter');
      await L.onSession(page); await L.sessReady(page);
      T.eq((await page.evaluate(() => document.querySelector('.screen.on').id)), 'session', 'F2: Enter on Start opens the chat');
    });
  } finally {
    await browser.close();
  }
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
function DEVf(s) { return /[ऀ-ॿ]/.test(String(s)); }
