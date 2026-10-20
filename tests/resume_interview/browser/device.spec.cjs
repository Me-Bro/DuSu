'use strict';
/*
 * "Full system sync": the server is the source of truth, the phone keeps only the audio.
 * Device A and device B are two separate browser contexts (own localStorage / IndexedDB / device id) signed in as the SAME learner against ONE mock server:
 *   A answers Q1 and moves to Q2 -> B opens the hub, sees "Continue", lands on the exact open question (Q2) and answers it ->
 *   A reloads: Q2 is answered, its feedback is shown, and the recording is "on your other phone" (A has no audio for it) ->
 *   A's page was stale while B answered: A's own attempt on Q2 gets 409 already_answered and shows B's feedback ->
 *   A answers Q3 and finishes; the report on A offers "Listen" only for A's own recordings; on B only for B's.
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const M = require('./mock.cjs');

(async () => {
  const T = H.makeT('device');
  const env = await H.newEnv({ mock: { limits: { min_answer_sec: 2 } } });
  const mock = env.mock;
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const errors = [];
  const open = async () => { const ctx = await H.newCtx(browser, env, { viewport: { width: 390, height: 844 } }); const page = await H.boot(ctx, env, '/'); page.setDefaultTimeout(15000); return { ctx, page }; };
  const ready = page => page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });

  const A = await open();
  await H.toHub(A.page);
  await H.toMatch(A.page, env);
  await H.startInterview(A.page);
  await ready(A.page);
  await H.answerOnce(A.page);
  await A.page.click('#riNextQ');
  await A.page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
  await ready(A.page);
  const devA = await A.page.evaluate(() => localStorage.getItem('dusu_ri_device'));
  T.ok(/^d/.test(devA), 'device A has an id: ' + devA);

  T.section('device B: hub -> Continue -> the exact open question');
  const B = await open();
  await B.page.evaluate(() => navTo('/resume-interview')); await H.waitView(B.page, 'hub');
  const devB = await B.page.evaluate(() => localStorage.getItem('dusu_ri_device') || '');
  await B.page.waitForSelector('#riContinue');
  T.has(await H.txt(B.page, '#riBody'), 'Continue where you left off', 'the hub shows the in-progress interview');
  await B.page.click('#riContinue'); await H.waitView(B.page, 'interview');
  await B.page.waitForSelector('#riQText');
  T.has(await H.txt(B.page, '#riQ'), 'Question 2', 'B lands on the exact open question');
  T.has(await H.txt(B.page, '#riQ'), 'use SQL to find a data-quality', 'with its text');
  T.has(await H.txt(B.page, '#riFin'), '2 more to unlock', 'and the real answer count from the server (1 answered)');
  T.eq(await B.page.evaluate(() => document.querySelectorAll('#riFb *').length), 0, 'no feedback is shown for a question that is still open');
  await ready(B.page);
  await H.answerOnce(B.page);
  const devB2 = await B.page.evaluate(() => localStorage.getItem('dusu_ri_device'));
  T.ok(devB2 && devB2 !== devA, 'device B sent its own device id: ' + devB2 + ' != ' + devA);
  T.eq(mock.answers.map(a => a.body.audio_device), [devA, devB2], 'each answer carries the id of the phone that recorded it');
  T.eq(await B.page.evaluate(() => document.querySelectorAll('#riListen audio').length), 1, 'B can play its own answer');

  T.section('device A (stale page): answers Q2 too -> 409 already_answered -> shows B\'s answer and feedback');
  await A.page.click('#riMic'); await A.page.waitForSelector('#riRec'); await H.sleep(1300); await A.page.click('#riStop');
  await A.page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
  T.has(await H.noteText(A.page), 'already answered', 'A is told the question was answered elsewhere');
  T.has(await H.txt(A.page, '#riListen'), 'on your other phone', 'and that the recording is on the other phone');
  T.eq(await A.page.evaluate(() => document.querySelectorAll('#riListen audio').length), 0, 'A offers no player for it');
  T.has(await H.txt(A.page, '#riFin'), '1 more to unlock', 'Finish reflects 2 real answers');

  T.section('device A reloads: the same state from the server');
  await A.page.reload(); await H.waitView(A.page, 'interview', 15000);
  await A.page.waitForSelector('#riFbCard');
  T.has(await H.txt(A.page, '#riQ'), 'Question 2', 'still Question 2');
  T.has(await H.txt(A.page, '#riListen'), 'The recording is on your other phone.', 'the recording is "on your other phone"');
  await A.page.click('#riNextQ'); await A.page.waitForFunction(() => /Question 3/.test(document.getElementById('riQ').textContent));
  await ready(A.page);
  await H.answerOnce(A.page);
  T.eq(await H.txt(A.page, '#riFin'), 'Finish interview', 'Finish unlocks at 3 real answers across the two phones');
  await A.page.click('#riFin'); await H.waitView(A.page, 'report', 15000); await A.page.waitForSelector('#riPerQ');
  T.eq(await A.page.evaluate(() => document.querySelectorAll('#riPerQ .ri-pq').length), 3, 'the report has 3 question cards');
  T.eq(await A.page.evaluate(() => document.querySelectorAll('#riPerQ .ri-pq-a .btn').length), 2, 'A can play ONLY its own two answers (Q1, Q3), not B\'s Q2');

  T.section('device B opens the finished interview from the hub');
  await B.page.evaluate(() => navTo('/resume-interview')); await H.waitView(B.page, 'hub');
  await B.page.waitForSelector('#riSessions .ri-main');
  T.has(await H.txt(B.page, '#riSessions'), 'Finished', 'B sees the interview as finished');
  await B.page.click('#riSessions .ri-main'); await H.waitView(B.page, 'report'); await B.page.waitForSelector('#riPerQ');
  T.eq(await B.page.evaluate(() => document.querySelectorAll('#riPerQ .ri-pq-a .btn').length), 1, 'B can play only its own answer (Q2)');
  T.eq(await B.page.evaluate(() => document.querySelector('#riRepHero .ri-tag').textContent), '3 of 3 answers counted', 'the same report on both phones');

  for (const p of [A.page, B.page]) { errors.push(...p.__consoleErrors); const r = await H.collectErrors(p); errors.push(...r.errors, ...r.rejections); }
  T.eq(errors, [], 'no errors on either device');
  await A.ctx.close(); await B.ctx.close(); await browser.close(); await env.server.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
