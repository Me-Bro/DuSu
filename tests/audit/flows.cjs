'use strict';
/*
 * Flows: what a learner DOES, not just what a screen looks like. Real clicks, real server, a fake model and fake speech. Every step is timed and every tap counted, and the
 * key moments are photographed.     AUD_ENV="FLOWS=A,B" tests/audit/spec.sh flows.cjs
 *   A  first run of a brand-new account (keys wall -> Home -> first conversation)
 *   B  Face-to-Face conversation -> result screen            C  Daily Talk            D  Learn           E  Interview -> report
 *   F  My Day: the add menu and the forms                    G  the More sheet, the rewards guide, the owner's dashboard
 *   H  features about to go live: Install + WhatsApp group + notification prompt
 */
const { chromium } = require('playwright');
const A = require('./lib.cjs').create('flows');
const { sleep } = A;

const FLOWS = (process.env.FLOWS || 'A,B,C,D,E,F,G,H').split(',');
const LOG = [];
let taps = 0, t0 = Date.now();
const mark = (flow, step, extra = '') => { const r = { flow, step, sec: +((Date.now() - t0) / 1000).toFixed(1), taps, extra }; LOG.push(r); console.log(`[${flow}] ${step.padEnd(34)} +${String(r.sec).padStart(5)}s  taps:${String(taps).padStart(2)} ${extra}`); };
const tap = async (page, sel, o = {}) => { taps++; await page.click(sel, Object.assign({ timeout: 8000 }, o)); };
const micReady = page => page.waitForFunction(() => !!window.__srActive, null, { timeout: 20000 }).then(() => true).catch(() => false);
const say = (page, t) => page.evaluate(x => window.__say(x), t);
const sid = page => A.screenId(page);
const guard = async (flow, fn) => { try { await fn(); } catch (e) { console.log(`[${flow}] !! ${String(e.message || e).split('\n')[0]}`); LOG.push({ flow, step: 'FAILED', extra: String(e.message || e).split('\n')[0] }); } };

async function flowA(browser) {                                         // ------------------------------------------------ first run, brand-new account
  t0 = Date.now(); taps = 0;
  const c = await A.ctx(browser, 'newbie', { device: 'new', firstRun: true, viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/');
  mark('A', 'signed in -> first screen', 'lands on: ' + await sid(p));
  await tap(p, '#kGroq', { force: true }).catch(() => {});
  await p.fill('#kGroq', 'gsk_' + 'x'.repeat(48)); mark('A', 'pasted key 1');
  await tap(p, '#kySave_groq'); await sleep(1800);
  await A.capture(p, 'keys-one-saved', { tag: 'flowA', full: false }); mark('A', 'key 1 saved', 'screen: ' + await sid(p));
  await p.fill('#kGemini', 'AIza' + 'y'.repeat(35)); mark('A', 'pasted key 2');
  await tap(p, '#kySave_gemini'); await sleep(2500);
  mark('A', 'key 2 saved', 'screen: ' + await sid(p));
  await sleep(1500);
  await A.capture(p, 'after-keys', { tag: 'flowA', full: false });
  mark('A', 'first Home (rewards pop-up?)', 'screen: ' + await sid(p) + ' | rewards sheet on: ' + await p.evaluate(() => !!(document.getElementById('rgSheet') || {}).classList && document.getElementById('rgSheet').classList.contains('on')));
  if (await p.evaluate(() => document.getElementById('rgSheet') && document.getElementById('rgSheet').classList.contains('on'))) { await tap(p, '#rgDone'); await sleep(500); }
  await A.capture(p, 'home-new-learner', { tag: 'flowA' });
  mark('A', 'Home of a new learner');
  await tap(p, '#startSpeak'); await sleep(2500);
  mark('A', 'Start Speaking tapped', 'screen: ' + await sid(p));
  await A.capture(p, 'first-chat-open', { tag: 'flowA', full: false });
  const mic = await micReady(p);
  mark('A', 'mic ready', String(mic));
  if (mic) { await say(p, 'Hello, my name is Neha and I want a job.'); await sleep(3500); await A.capture(p, 'first-chat-reply', { tag: 'flowA', full: false }); mark('A', 'first reply on screen'); }
  await c.close();
}

async function flowB(browser) {                                         // ------------------------------------------------ Face-to-Face -> result
  t0 = Date.now(); taps = 0;
  const c = await A.ctx(browser, 'active', { viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/face-to-face', { settle: 1500 });
  mark('B', 'Face-to-Face opened');
  for (const line of ['I am a final year student and I like computers.', 'Last week I made a small app for my class.', 'My dream is to become a software engineer.']) {
    if (!await micReady(p)) { mark('B', 'mic never became ready'); break; }
    await say(p, line); await sleep(2800);
  }
  await A.capture(p, 'f2f-midchat', { tag: 'flowB', full: false });
  await tap(p, '#endBtn'); mark('B', 'End tapped');
  await p.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'sessionResult', null, { timeout: 30000 }).catch(() => {});
  await sleep(2500);
  mark('B', 'result screen', 'screen: ' + await sid(p));
  await A.capture(p, 'f2f-result', { tag: 'flowB' });
  if (await sid(p) === 'sessionResult') { await tap(p, '#srDone'); await sleep(1200); mark('B', 'Continue tapped', 'lands on: ' + await sid(p)); await A.capture(p, 'after-result', { tag: 'flowB', full: false }); }
  await c.close();
}

async function flowC(browser) {                                         // ------------------------------------------------ Daily Talk
  t0 = Date.now(); taps = 0;
  const c = await A.ctx(browser, 'active', { viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/daily-talk', { settle: 2500 });
  mark('C', 'Daily Talk opened');
  await A.capture(p, 'daily-open', { tag: 'flowC', full: false });
  await tap(p, '#dailyMic').catch(() => {});
  if (await micReady(p)) {
    await say(p, 'Aaj main market gaya tha aur sabzi kharidi.'); await sleep(5500);
    await A.capture(p, 'daily-after-answer', { tag: 'flowC' });
    mark('C', 'answered once');
    await tap(p, '#dcNext').catch(() => {}); await sleep(800);
    await tap(p, '#dailyMic').catch(() => {});
    if (await micReady(p)) { await say(p, 'Kal mera interview hai.'); await sleep(5500); await A.capture(p, 'daily-after-answer-2', { tag: 'flowC', full: false }); mark('C', 'answered twice'); }
  }
  if (await p.evaluate(() => !!document.getElementById('dailyFinish') && document.getElementById('dailyFinish').offsetParent !== null)) {
    await tap(p, '#dailyFinish'); await sleep(3500); mark('C', 'Finish tapped', 'lands on: ' + await sid(p));
    await A.capture(p, 'daily-finish', { tag: 'flowC' });
  }
  await c.close();
}

async function flowD(browser) {                                         // ------------------------------------------------ Learn
  t0 = Date.now(); taps = 0;
  const c = await A.ctx(browser, 'active', { viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/learn', { settle: 2000 });
  mark('D', 'Learn opened');
  await tap(p, '#micBtn').catch(() => {});
  if (await micReady(p)) { await say(p, 'Mujhe kal doctor ke paas jaana hai.'); await sleep(3500); }
  await A.capture(p, 'learn-translation', { tag: 'flowD' });
  mark('D', 'translation shown');
  await c.close();
}

async function flowE(browser) {                                         // ------------------------------------------------ Interview -> report
  t0 = Date.now(); taps = 0;
  const c = await A.ctx(browser, 'active', { viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/interview', { settle: 1500 });
  await tap(p, '#startInterview'); await sleep(2500);
  mark('E', 'interview started');
  await A.capture(p, 'interview-live', { tag: 'flowE', full: false });
  for (const line of ['Hello, I am Asha. I study computer science and I like building web apps.', 'I want this role because I enjoy solving problems with code.', 'In my project I made a timetable app and about two hundred classmates used it.']) {
    if (!await micReady(p)) { mark('E', 'mic not ready'); break; }
    await say(p, line); await sleep(2800);
  }
  await tap(p, '#endBtn'); mark('E', 'End tapped (report)');
  await p.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'report', null, { timeout: 30000 }).catch(() => {});
  await sleep(3000);
  mark('E', 'report screen', 'screen: ' + await sid(p));
  await A.capture(p, 'interview-report', { tag: 'flowE' });
  await c.close();
}

async function flowF(browser) {                                         // ------------------------------------------------ My Day add menu + forms
  t0 = Date.now(); taps = 0;
  const c = await A.ctx(browser, 'keyed', { viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/', { settle: 1200 });                      // open Home first: /me has answered, so the feature flags are known (a cold deep link races it - see race.cjs)
  await p.evaluate(() => navTo('/my-day')); await sleep(2000);
  await A.capture(p, 'empty-today', { tag: 'flowF' });
  mark('F', 'My Day, a new learner');
  await tap(p, '.pl-addbtn'); await sleep(800);
  await A.capture(p, 'add-menu', { tag: 'flowF', full: false }); mark('F', 'add menu open');
  const kinds = await p.evaluate(() => [...document.querySelectorAll('#plSheet button, #plSheet .pl-opt, .pl-sheet button')].filter(b => b.offsetParent !== null).map(b => b.innerText.trim().replace(/\s+/g, ' ')).filter(Boolean).slice(0, 14));
  console.log('   add-menu buttons:', kinds.join(' | '));
  for (const [needle, name] of [['Task', 'task-form'], ['Reminder', 'reminder-form'], ['Habit', 'habit-form'], ['Goal', 'goal-form']]) {
    const btn = await p.$(`#plSheet button:has-text("${needle}"), .pl-sheet button:has-text("${needle}")`);
    if (!btn) { console.log('   (no "' + needle + '" button in the add menu)'); continue; }
    await btn.click(); taps++; await sleep(800);
    await A.capture(p, name, { tag: 'flowF', full: false }); mark('F', name);
    await p.keyboard.press('Escape').catch(() => {}); await sleep(400);
    if (!await p.evaluate(() => !!document.querySelector('#plSheet.on, .pl-sheet.on'))) { await tap(p, '.pl-addbtn').catch(() => {}); await sleep(600); }
  }
  await c.close();
}

async function flowG(browser) {                                         // ------------------------------------------------ More sheet, rewards guide, owner's dashboard
  t0 = Date.now(); taps = 0;
  for (const [vp, tag] of [[{ width: 390, height: 844 }, '390'], [{ width: 1280, height: 900 }, '1280']]) {
    const c = await A.ctx(browser, 'owner', { viewport: vp });
    const p = await A.open(c, '/', { settle: 1500 });
    await tap(p, '.btab[data-tab="more"]'); await sleep(700);
    await A.capture(p, 'more-sheet', { tag: 'flowG-' + tag, full: false });
    mark('G', 'More sheet ' + tag);
    const rows = await p.evaluate(() => [...document.querySelectorAll('#msheet .mrow')].filter(r => r.offsetParent !== null).map(r => (r.querySelector('b,span') || r).innerText.trim().replace(/\s+/g, ' ')));
    console.log('   More rows (' + tag + '):', rows.join(' | '));
    if (tag === '390') {
      const adm = await p.$('#mrowAdmin');
      if (adm) { await adm.click(); taps++; await sleep(2500); await A.capture(p, 'owner-dashboard', { tag: 'flowG-' + tag }); mark('G', 'owner dashboard', 'screen: ' + await sid(p)); }
    } else {
      const adm = await p.$('#mrowAdmin');
      if (adm) { await adm.click(); taps++; await sleep(2500); await A.capture(p, 'owner-dashboard', { tag: 'flowG-' + tag }); }
    }
    await c.close();
  }
}

async function flowH(browser) {                                         // ------------------------------------------------ features about to go live
  t0 = Date.now(); taps = 0;
  await A.settings({ install_mode: 'on', notifications: 'on', whatsapp_group: 'https://chat.whatsapp.com/TestInviteCode0123456789' });
  try { await flowH2(browser); } finally { await A.settings({ install_mode: 'off', notifications: 'off' }); }
}
async function flowH2(browser) {
  const c = await A.ctx(browser, 'active', { viewport: { width: 390, height: 844 }, seed: { dusu_inst_visits: '3' } });
  const p = await A.open(c, '/', { settle: 2500 });
  await A.capture(p, 'home-with-install-and-community', { tag: 'flowH' });
  mark('H', 'Home with install / WhatsApp / notifications on');
  await p.keyboard.press('Escape').catch(() => {}); await sleep(600);
  const gotIt = await p.$('button:has-text("Got it")'); if (gotIt && await gotIt.isVisible().catch(() => false)) { await gotIt.click(); taps++; await sleep(600); }
  await A.capture(p, 'home-after-sheet', { tag: 'flowH' });
  await tap(p, '.btab[data-tab="more"]'); await sleep(700);
  await A.capture(p, 'more-sheet', { tag: 'flowH', full: false });
  const rows = await p.evaluate(() => [...document.querySelectorAll('#msheet .mrow')].filter(r => r.offsetParent !== null).map(r => (r.querySelector('b,span') || r).innerText.trim().replace(/\s+/g, ' ')));
  console.log('   More rows:', rows.join(' | '));
  for (const [data, name] of [['install', 'install-sheet'], ['whatsapp', 'whatsapp-sheet'], ['notifications', 'notifications-sheet']]) {
    const row = await p.$(`#msheet .mrow[data-more="${data}"]`);
    if (!row) { console.log('   (no More row for ' + data + ')'); continue; }
    await row.click(); taps++; await sleep(1200);
    await A.capture(p, name, { tag: 'flowH', full: false });
    mark('H', name);
    await p.keyboard.press('Escape').catch(() => {}); await sleep(500);
    await p.evaluate(() => { try { if (window.INST && INST.close) INST.close(); } catch (e) {} });
    await tap(p, '.btab[data-tab="more"]').catch(() => {}); await sleep(600);
  }
  await c.close();
}

(async () => {
  const browser = await chromium.launch();
  const map = { A: flowA, B: flowB, C: flowC, D: flowD, E: flowE, F: flowF, G: flowG, H: flowH };
  for (const k of FLOWS) await guard(k, () => map[k](browser));
  A.save('flows');
  require('fs').writeFileSync(require('path').join(A.OUT, 'flows-log.json'), JSON.stringify(LOG, null, 1));
  await browser.close();
})();
