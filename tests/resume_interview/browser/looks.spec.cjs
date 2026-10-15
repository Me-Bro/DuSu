'use strict';
/*
 * Layout + screenshots of every Resume Interview view at 360x640, 390x844 and 1280x800.
 * For each state it asserts: no horizontal overflow, every tap target >= 44px, the action dock sits above the bottom nav (mobile) and is on screen,
 * and no text is wider than its card. Screenshots go to $OUT (default /out) as ri-<viewport>-<state>.png - open them and LOOK.
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const M = require('./mock.cjs');
const path = require('path');

const OUT = process.env.OUT || '/out';
const VPS = [{ name: '360x640', w: 360, h: 640 }, { name: '390x844', w: 390, h: 844 }, { name: '1280x800', w: 1280, h: 800 }];
const ONLY = process.env.VP ? process.env.VP.split(',') : null;

async function shot(page, vp, name) {
  await page.evaluate(() => { const w = document.querySelector('.wrap'); void w.offsetHeight; });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(OUT, `ri-${vp}-${name}.png`), animations: 'disabled' });
}
const scrollEnd = page => page.evaluate(() => { const w = document.querySelector('.wrap'); w.scrollTop = w.scrollHeight; });
const scrollTop = page => page.evaluate(() => { const w = document.querySelector('.wrap'); w.scrollTop = 0; });

(async () => {
  const T = H.makeT('looks');
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  for (const v of VPS) {
    if (ONLY && !ONLY.includes(v.name)) continue;
    T.section(v.name);
    const env = await H.newEnv({ mock: { limits: { min_answer_sec: 2 } } });
    const mock = env.mock;
    const ctx = await H.newCtx(browser, env, { viewport: { width: v.w, height: v.h }, mobile: v.w < 800 });
    const page = await H.boot(ctx, env, '/');
    const L = (label) => H.layout(page, label, T, v.name);
    await H.toHub(page); await shot(page, v.name, '01-hub-empty'); await L('hub (empty)');
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await shot(page, v.name, '02-resume-pick'); await L('resume pick');
    await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre');
    await shot(page, v.name, '03-resume-preview'); await L('resume preview');
    await page.click('#riEdit'); await page.waitForSelector('#riEditText'); await shot(page, v.name, '04-resume-edit'); await L('resume edit');
    await page.click('text=Cancel'); await page.waitForSelector('#riPre');
    await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.fill('#riJdText', M.JD_TEXT); await shot(page, v.name, '05-job'); await L('job');
    await scrollEnd(page); await shot(page, v.name, '05b-job-end'); await L('job (scrolled)');
    mock.delays.analyze = 1600;
    await page.click('#riNext'); await page.waitForSelector('#riLoad', { state: 'visible' }); await shot(page, v.name, '06-analysing'); await L('analysing'); mock.delays.analyze = 0;
    await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    await scrollTop(page); await shot(page, v.name, '07-match'); await L('match');
    await page.evaluate(() => document.querySelector('.ri-edit').scrollIntoView({ block: 'start' })); await shot(page, v.name, '08-match-edits'); await L('match (edits)');
    await page.click('.ri-edit .ri-pk'); await scrollEnd(page); await shot(page, v.name, '09-match-end'); await L('match (end)');
    // a failure note in the dock
    await H.startInterview(page);
    await page.waitForFunction(() => !document.getElementById('riMic').disabled, null, { timeout: 10000 });
    await shot(page, v.name, '10-interview-ask'); await L('interview (ask)');
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(1800);
    await shot(page, v.name, '11-interview-recording'); await L('interview (recording)');
    await page.click('#riStop'); await page.waitForSelector('#riWork', { timeout: 5000 }).catch(() => {});
    await shot(page, v.name, '12-interview-working');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    await scrollTop(page); await shot(page, v.name, '13-interview-feedback'); await L('interview (feedback)');
    await scrollEnd(page); await shot(page, v.name, '14-interview-feedback-end'); await L('interview (feedback, end)');
    for (let i = 0; i < 2; i++) { await page.click('#riNextQ'); await page.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i + 2); await H.answerOnce(page); }
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 4/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => !document.getElementById('riMic').disabled);
    await shot(page, v.name, '15-interview-q4-finish-unlocked'); await L('interview (q4, finish unlocked)');
    await page.click('#riFin'); await H.waitView(page, 'report', 15000); await page.waitForSelector('#riRepHero');
    await page.waitForTimeout(1300);
    await scrollTop(page); await shot(page, v.name, '16-report'); await L('report');
    await page.evaluate(() => document.getElementById('riCov').scrollIntoView({ block: 'start' })); await shot(page, v.name, '17-report-mid'); await L('report (middle)');
    await scrollEnd(page); await shot(page, v.name, '18-report-end'); await L('report (end)');
    await page.click('#riBack'); await H.waitView(page, 'hub'); await page.waitForSelector('#riSessions .ri-row');
    await shot(page, v.name, '19-hub-full'); await L('hub (with history)');
    await page.click('#riGear'); await H.waitView(page, 'settings'); await page.waitForSelector('#riExport');
    await shot(page, v.name, '20-settings'); await L('settings');
    T.eq(page.__consoleErrors, [], v.name + ': no console errors');
    await ctx.close(); await env.server.close();
  }
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
