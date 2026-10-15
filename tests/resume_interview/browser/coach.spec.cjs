'use strict';
/*
 * The coaching layer of Job Interview Practice, in a real Chromium against the contract mock:
 *   1  the first interview's report: an improvement plan, EVERY weakness explained (what happened, why, how to fix it, a drill, the learner's own
 *      stronger answer, the questions it happened in), every answer re-readable with its full feedback, the old "patterns / fixes" cards gone
 *   2  the hub's "Your focus for next time" card -> opens that report
 *   3  the second interview: the focus bar before the first question, a tick / cross for each focus point on every answer, and at the end
 *      "Since your last interview" (better / same / worse, with the real numbers)
 *   4  an OLD-format report (no coaching fields) still renders, answers still expandable
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const M = require('./mock.cjs');

const MIC = ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'];

async function interview(page, n) {              // answer n questions (the fake microphone, ~1.4 s each), staying on the feedback card of the last one
  for (let i = 1; i <= n; i++) {
    await H.answerOnce(page);
    if (i < n) { await page.click('#riNextQ'); await page.waitForFunction(k => new RegExp('Question ' + k).test(document.getElementById('riQ').textContent), i + 1); }
  }
}

(async () => {
  const T = H.makeT('coach');
  const browser = await chromium.launch({ args: MIC });

  // ------------------------------------------------------------------------------------------------ 1. the first interview
  const env = await H.newEnv({ mock: { limits: { min_answer_sec: 2 } } });
  const mock = env.mock;
  const ctx = await H.newCtx(browser, env, { viewport: { width: 390, height: 844 } });
  const page = await H.boot(ctx, env, '/');
  await H.toHub(page);
  T.section('before any interview: nothing to remind');
  T.ok(!(await H.vis(page, '#riFocusCard')), 'no "focus for next time" card on the hub');
  await H.toMatch(page, env, { resume: M.RESUME_TEXT, jd: M.JD_TEXT, jdTitle: 'Data Analyst', jdCompany: 'Acme Corp' });
  T.ok(!(await H.vis(page, '#riFocusCard')), 'no reminder on the match screen');
  await H.startInterview(page);
  T.eq(await page.evaluate(() => document.querySelectorAll('#riFocusBar details').length), 0, 'no focus bar in the first interview');
  await interview(page, 3);
  T.ok(!(await H.vis(page, '#riFocusCheck')), 'no per-answer focus check without earlier focus points');
  await page.click('#riFin');
  await H.waitView(page, 'report', 15000);
  await page.waitForSelector('#riRepHero');

  T.section('the report: improvement plan, weaknesses in detail, answers you can re-read');
  T.ok(!(await H.vis(page, '#riProgress')), 'no "since your last interview" card on a first interview');
  T.ok(await H.vis(page, '#riPlan'), 'the improvement plan is shown');
  T.eq(await page.evaluate(() => document.querySelectorAll('#riPlan li').length), 2, 'two focus points');
  T.has(await H.txt(page, '#riPlan'), 'Add numbers to your stories', 'a focus point by name');
  T.has(await H.txt(page, '#riPlan'), 'DuSu will check them in your next interview', 'it says the next interview will check them');
  T.eq(await page.evaluate(() => !!document.getElementById('riPatterns') || !!document.getElementById('riFixes')), false, 'the old "patterns" and "fixes" cards are replaced by the detailed weaknesses');
  T.eq(await page.evaluate(() => document.querySelectorAll('.ri-wk').length), 3, 'three weakness cards');
  T.eq(await page.evaluate(() => [...document.querySelectorAll('.ri-wk')].map(d => d.open)), [true, false, false], 'the first one is open, the others are one tap away');
  const wk = await H.txt(page, '#riWk-no_number');
  for (const part of ['Work on first', 'What happened', 'Why it matters', 'How to fix it', 'Practise this (3 to 5 minutes)', 'Goal for next time', 'Happened in', 'written stronger'])
    T.has(wk, part, `the first weakness explains: ${part}`);
  T.eq(await page.evaluate(() => document.querySelectorAll('#riWk-no_number ol.ri-ol li').length), 3, 'three concrete steps');
  T.ok(await H.vis(page, '#riWk-no_number .btn'), 'the learner\'s own stronger answer can be heard');
  await page.click('#riWk-grammar summary');
  T.has(await H.txt(page, '#riWk-grammar'), 'I make dashboard', 'the grammar card shows the learner\'s own slip ...');
  T.has(await H.txt(page, '#riWk-grammar'), 'I made a dashboard', '... and the fix');
  await page.click('#riWk-coverage summary');
  T.has(await H.txt(page, '#riWk-coverage'), 'Power BI dashboards', 'the job requirements no answer showed are named');
  T.eq(await page.evaluate(() => [...document.querySelectorAll('#riWk-no_number .ri-chip')].map(b => b.getAttribute('aria-label'))), ['Open your answer to question 1', 'Open your answer to question 2', 'Open your answer to question 3'], 'the "Happened in" buttons have full accessible names');
  await page.click('#riWk-no_number .ri-chip:nth-of-type(2)');
  T.eq(await page.evaluate(() => document.getElementById('riPQ-2').open), true, '"Happened in Q2" opens the answer to question 2');
  T.eq(await page.evaluate(() => document.querySelectorAll('#riPerQ .ri-pqd').length), 3, 'every answered question is expandable');
  const body1 = await page.evaluate(() => { const d = document.getElementById('riPQ-1'); d.open = true; return d.textContent; });
  for (const part of ['What you said', 'What worked', 'Mistakes to fix', 'Fix next time', 'I make dashboard', 'I made a dashboard', 'A stronger answer'])
    T.has(body1, part, `an answer can be re-read in full: ${part}`);
  T.eq(await page.evaluate(() => document.querySelectorAll('.ri-pq-a .btn').length), 3, '▶ Listen stays outside the collapsed answers (3 local recordings)');

  T.section('the hub: your focus for next time');
  await page.click('#riBack'); await H.waitView(page, 'hub');
  await page.waitForSelector('#riFocusCard');
  T.has(await H.txt(page, '#riFocusCard'), 'Your focus for next time', 'the card');
  T.eq(await page.evaluate(() => document.querySelectorAll('#riFocusCard li').length), 2, 'with the two focus points');
  T.has(await H.txt(page, '#riFocusCard'), 'DuSu will check these in your next interview', 'and the promise');
  await page.click('#riFocusSee'); await H.waitView(page, 'report'); await page.waitForSelector('#riPlan');
  T.ok(true, '"Read the full report" opens that interview\'s report');

  // ------------------------------------------------------------------------------------------------ 3. the second interview
  T.section('the next interview: focus bar, a check on every answer, "since last time"');
  await page.click('#riPracticeAgain');
  await H.waitView(page, 'interview', 20000);
  await page.waitForSelector('#riQText');
  T.has(await H.txt(page, '#riFocusBar'), 'Your focus today (2)', 'the focus bar is above the first question');
  await page.click('#riFocusBar summary');
  T.eq(await page.evaluate(() => document.querySelectorAll('#riFocusBar li').length), 2, 'it lists the two points with their goals');
  T.has(await H.txt(page, '#riFocusBar'), 'A number in every project answer', 'including the goal');
  await H.answerOnce(page);
  await page.waitForSelector('#riFocusCheck', { state: 'visible' });
  const fcheck = await H.txt(page, '#riFocusCheck');
  T.has(fcheck, 'Your focus points', 'each answer carries a check');
  T.eq(await page.evaluate(() => document.querySelectorAll('#riFocusCheck li').length), 2, 'one row per focus point');
  T.ok(/[✓✗]/.test(fcheck) && /done in this answer|not in this answer yet/.test(fcheck), 'each row is a tick or a cross with words (not colour alone)');
  await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
  await H.answerOnce(page);                                                   // question 2
  await page.click('#riNextQ'); await page.waitForFunction(() => /Question 3/.test(document.getElementById('riQ').textContent));
  await H.answerOnce(page);                                                   // question 3
  await page.click('#riFin');
  await H.waitView(page, 'report', 15000);
  await page.waitForSelector('#riRepHero');
  T.ok(await H.vis(page, '#riProgress'), '"Since your last interview" is on the new report');
  const pg = await H.txt(page, '#riProgress');
  T.has(pg, 'Since your last interview', 'its heading');
  T.has(pg, 'Compared with', 'it says which interview it compares with');
  T.has(pg, 'Better', 'an improved point is called Better');
  T.has(pg, 'Same', 'an unchanged one is called Same');
  T.has(pg, '3 of 3 answers  →  Now: 1 of 3 answers', 'with the real numbers, then and now');
  T.has(pg, '1 of 2 focus points improved.', 'and a one-line summary');
  T.eq(await page.evaluate(() => document.querySelectorAll('#riProgress .ri-st').length), 2, 'a status chip per point');
  const errs = await H.collectErrors(page);
  T.eq(page.__consoleErrors, [], 'no console errors / page errors');
  T.eq([errs.errors, errs.rejections], [[], []], 'no window errors, no unhandled rejections');
  await ctx.close(); await env.server.close();

  // ------------------------------------------------------------------------------------------------ 4. an old-format report
  T.section('an OLD-format report (written before the coaching fields) still renders');
  const env2 = await H.newEnv({ mock: { limits: { min_answer_sec: 2 }, reportV1: true } });
  const ctx2 = await H.newCtx(browser, env2, { viewport: { width: 390, height: 844 } });
  const p2 = await H.boot(ctx2, env2, '/');
  await H.toHub(p2);
  await H.toMatch(p2, env2, { resume: M.RESUME_TEXT, jd: M.JD_TEXT, jdTitle: 'Data Analyst', jdCompany: 'Acme Corp' });
  await H.startInterview(p2);
  await interview(p2, 3);
  await p2.click('#riFin'); await H.waitView(p2, 'report', 15000); await p2.waitForSelector('#riRepHero');
  T.ok(await H.vis(p2, '#riPatterns') && await H.vis(p2, '#riFixes'), 'the old "patterns" and "fixes" cards are shown');
  T.ok(!(await H.vis(p2, '#riPlan')) && (await p2.evaluate(() => document.querySelectorAll('.ri-wk').length)) === 0, 'and no plan / weakness cards (there is nothing to show)');
  T.eq(await p2.evaluate(() => document.querySelectorAll('#riPerQ .ri-pqd').length), 3, 'the answers are still expandable');
  await p2.click('#riBack'); await H.waitView(p2, 'hub');
  T.ok(!(await H.vis(p2, '#riFocusCard')), 'no focus card for an interview with no saved focus points');
  const errs2 = await H.collectErrors(p2);
  T.eq([p2.__consoleErrors, errs2.errors, errs2.rejections], [[], [], []], 'no errors on the old-format path either');

  await ctx2.close(); await env2.server.close();

  // ------------------------------------------------------------------------------------------------ 5. an interview with nothing to fix
  T.section('an interview with no weak spot says so (and sets no focus points)');
  const env3 = await H.newEnv({ mock: { limits: { min_answer_sec: 2 }, strong: true } });
  const ctx3 = await H.newCtx(browser, env3, { viewport: { width: 390, height: 844 } });
  const p3 = await H.boot(ctx3, env3, '/');
  await H.toHub(p3);
  await H.toMatch(p3, env3, { resume: M.RESUME_TEXT, jd: M.JD_TEXT, jdTitle: 'Data Analyst', jdCompany: 'Acme Corp' });
  await H.startInterview(p3);
  await interview(p3, 3);
  await p3.click('#riFin'); await H.waitView(p3, 'report', 15000); await p3.waitForSelector('#riRepHero');
  T.ok(await H.vis(p3, '#riNoWeak'), 'a friendly "nothing stands out" note');
  T.ok(!(await H.vis(p3, '#riPlan')) && (await p3.evaluate(() => document.querySelectorAll('.ri-wk').length)) === 0, 'no plan and no weakness cards');
  T.eq(await p3.evaluate(() => document.querySelectorAll('#riPerQ .ri-pqd').length), 3, 'the answers can still be re-read');
  await p3.click('#riBack'); await H.waitView(p3, 'hub');
  T.ok(!(await H.vis(p3, '#riFocusCard')), 'and no focus card on the hub');
  await browser.close(); await env3.server.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
