'use strict';
/*
 * Resume Interview in a REAL Chromium against the REAL app (uvicorn + scratch Postgres + the stub model; see run_real.sh and ../e2e_server.py).
 * The mock specs prove the client against the CONTRACT; this one proves client and server agree with each other: real status codes and bodies, the
 * real HTML served by the real app, real tokens, real database rows.
 *
 *   A  the whole journey as the owner (server-side speech-to-text): resume -> job -> match -> tick -> re-upload -> start -> 3 answers -> report
 *   B  a second device: the same account sees the finished interview and can CONTINUE an unfinished one (the server is the source of truth)
 *   C  isolation: another learner sees nothing and gets 404 on the first learner's ids
 *   D  a learner with her own Groq key (direct-from-the-phone speech-to-text)
 *   E  an XSS canary through every field that reaches the screen
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const fs = require('fs');

const BASE = process.env.BASE;
const TOK = JSON.parse(fs.readFileSync(process.env.TOKENS, 'utf8'));
const FX = TOK.fixtures;
const T = H.makeT('real server');
const env = { origin: BASE };

const INIT = `(() => {
  window.__events = []; window.__spoken = []; window.__errors = []; window.__rejections = [];
  window.addEventListener('error', e => window.__errors.push(String(e.message)));
  window.addEventListener('unhandledrejection', e => window.__rejections.push(String((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
  const ss = window.speechSynthesis; let cur = null;
  if (ss) { ss.speak = function (u) { window.__spoken.push(u.text); cur = u; const mine = u;
      setTimeout(() => { if (cur !== mine) return; try { mine.onstart && mine.onstart(); } catch (e) {} setTimeout(() => { if (cur !== mine) return; cur = null; try { mine.onend && mine.onend(); } catch (e) {} }, 80); }, 5); };
    ss.cancel = function () { cur = null; }; ss.getVoices = () => []; }
  try { Object.defineProperty(navigator, 'clipboard', { value: { writeText: async t => {} }, configurable: true }); } catch (e) {}
})();`;

async function realCtx(browser, who, o = {}) {
  const u = TOK[who];
  const ctx = await browser.newContext({ viewport: o.viewport || { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block', permissions: ['microphone'], acceptDownloads: true });
  await ctx.addInitScript(INIT);
  const seed = Object.assign({ dusu_token: u.token, dusu_user: u.user, dusu_onboarded: 'true', dusu_state: { onboarded: true }, dusu_rewards_intro_seen: '1', dusu_usemode: 'personal' }, o.seed || {});
  await ctx.addInitScript(`(() => { try { if (localStorage.getItem('__seeded')) return; localStorage.setItem('__seeded', '1'); const s = ${JSON.stringify(seed)};
    for (const k of Object.keys(s)) localStorage.setItem(k, typeof s[k] === 'string' ? s[k] : JSON.stringify(s[k])); } catch (e) {} })();`);
  await ctx.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.hostname === 'api.groq.com') {                                          // the learner's own key: speech-to-text straight from the phone
      const cors = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'POST, OPTIONS' };
      if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
      env.groqCalls = (env.groqCalls || 0) + 1;
      const said = env.sttText || FX.ANSWER_GOOD;
      const words = said.split(' ').map((w, i) => ({ word: w, start: 0.5 + i * 0.42, end: 0.5 + i * 0.42 + 0.32 }));
      return route.fulfill({ status: 200, headers: cors, contentType: 'application/json',
        body: JSON.stringify({ text: said, duration: words[words.length - 1].end + 1, words, segments: [{ start: 0, end: words[words.length - 1].end, avg_logprob: -0.2, no_speech_prob: 0.01 }] }) });
    }
    if (url.origin !== BASE) return route.abort();                                  // nothing leaves the box
    return route.continue();
  });
  return ctx;
}

const api = async (who, method, path, body) => {
  const r = await fetch(BASE + '/rinterview' + path, { method, headers: { Authorization: 'Bearer ' + TOK[who].token, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  let j = null; try { j = await r.json(); } catch (e) {}
  return { status: r.status, body: j };
};
const activeSid = async who => ((await api(who, 'GET', '/state')).body.active || {}).id;           // the newest unfinished interview (RI's own state is private to its closure)
const stats = async () => (await fetch(BASE + '/__e2e/stats')).json();
const url = page => page.evaluate(() => location.pathname);

(async () => {
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });

  // ------------------------------------------------------------------------------------------- A
  T.section('A - the whole journey as the owner (real server, server-side speech-to-text)');
  const ctx1 = await realCtx(browser, 'owner');
  const page = await H.boot(ctx1, env, '/');
  await H.toHub(page);
  T.eq(await url(page), '/resume-interview', 'the hub URL (served by the real app: the SPA fallback)');
  const me = await page.evaluate(() => ({ ri: userState.resume_interview, stt: userState.ri_server_stt }));
  T.eq(me, { ri: true, stt: true }, '/me from the real server carries the flags');
  await H.toMatch(page, env, { resume: FX.RESUME, jd: FX.JD, jdTitle: 'Data Analyst', jdCompany: 'Acme Corp' });
  const hero = await H.txt(page, '#riHero');
  T.has(hero, 'Data Analyst', 'the real analysis names the job');
  T.ok(/\d/.test(await H.txt(page, '#riHero .score-ring .val b')), 'a match score in the ring');
  const reqs = await page.evaluate(() => [...document.querySelectorAll('.ri-req')].map(r => r.textContent));
  T.eq(reqs.length, 6, 'six requirement cards from the real server');
  T.ok(reqs.some(t => /Strong SQL skills/.test(t) && /Matched/.test(t)), 'SQL is matched, with its evidence quote from the REAL resume');
  T.ok(reqs.some(t => /Snowflake/.test(t) && /Missing/.test(t)), 'Snowflake is missing');
  T.eq(await page.evaluate(() => document.querySelectorAll('.ri-edit').length), 2, 'two suggested edits');
  T.has(await H.txt(page, '.ri-edit'), 'Only if true for you', 'the claim-adding edit says so');
  T.has(await H.txt(page, '#riBody'), 'personal details', 'the computed note about the personal-details section the redactor removed');
  const sid = await activeSid('owner');
  await page.click('.ri-edit:nth-of-type(1) .ri-pk');
  await H.sleep(1200);
  const st1 = await api('owner', 'GET', '/sessions/' + sid);
  T.eq(st1.body.analysis.edits.filter(e => e.picked).map(e => e.id), ['e1'], 'the tick reached the database (GET /sessions/{id})');
  T.ok(await H.vis(page, '#riReupload') && await H.vis(page, '#riStart'), 'Re-upload and Start offered');

  T.section('A - re-upload an improved resume (a real file upload to the real endpoint)');
  const before = await H.txt(page, '#riHero .score-ring .val small');
  await page.click('#riReupload'); await H.waitView(page, 'resume');
  await page.setInputFiles('#riResFile', { name: 'my-private-name-v2.txt', mimeType: 'text/plain', buffer: Buffer.from(FX.RESUME2) });
  await page.waitForSelector('#riPre', { state: 'visible' });
  T.has(await H.txt(page, '#riPre'), 'Snowflake', 'the preview is the KEPT text of the new version');
  T.ok(!(await H.txt(page, '#riPre')).includes('asha.verma@example.com') && (await H.txt(page, '#riPre')).includes('[EMAIL]'), 'the real redactor replaced the email');
  await page.click('#riLooks');
  await page.waitForSelector('#riPrev', { state: 'visible', timeout: 20000 });
  const after = await H.txt(page, '#riHero .score-ring .val small');
  T.ok(before !== after, `the band moved (${before} -> ${after})`);
  T.has(await H.txt(page, '#riPrev'), 'Compared with your previous resume', 'the comparison card');
  T.ok(await page.evaluate(() => !!document.querySelector('.ri-edit.done')), 'an earlier suggestion is marked done in the new resume');
  let s = await stats();
  T.eq([s.jd, s.match], [1, 2], 'model calls so far: the job once (reused), the match twice (one per resume version)');

  T.section('A - start + three real answers (recorded with the fake microphone, transcribed by the server)');
  await H.startInterview(page);
  T.has(await H.txt(page, '#riQ'), 'Question 1', 'question 1');
  T.has(await H.txt(page, '#riQ'), 'introduce yourself', 'the first question is the introduction');
  T.has(await H.txt(page, '#riFin'), '3 more to unlock', 'Finish is locked');
  await H.answerOnce(page, { wait: 10600 });
  let fb = await H.txt(page, '#riFbCard');
  T.has(fb, 'Content:', 'band chips from the real feedback'); T.has(fb, 'What DuSu heard (from the transcript)', 'the transcript'); T.has(fb, 'A stronger answer', 'a stronger answer');
  T.ok(!/\b\d{2}\b/.test(await H.txt(page, '#riBands')), 'no raw numbers per answer');
  T.has(await H.txt(page, '#riFin'), '2 more to unlock', 'Finish: 2 more');
  const t1 = await api('owner', 'GET', '/sessions/' + sid);
  T.eq([t1.body.turns[0].status, t1.body.turns[0].feedback_state, t1.body.turns[0].engine, t1.body.turns[0].real], ['answered', 'done', 'gemini', true], 'the database holds the transcript, the feedback and the engine');
  T.ok(t1.body.turns[0].audio_device && t1.body.turns[0].answer.startsWith('In my last role'), 'with this phone\'s audio_device and the stored transcript');
  await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
  await H.answerOnce(page, { wait: 10600 });
  await page.click('#riNextQ'); await page.waitForFunction(() => /Question 3/.test(document.getElementById('riQ').textContent));
  await H.answerOnce(page, { wait: 10600 });
  T.eq(await H.txt(page, '#riFin'), 'Finish interview', 'Finish unlocked at exactly 3 real answers');
  s = await stats();
  T.eq([s.plan, s.answer], [1, 3], 'model calls: one plan, one feedback per answer');
  await page.click('#riFin');
  await H.waitView(page, 'report', 20000);
  await page.waitForSelector('#riRepHero');
  const rep = await H.txt(page, '#riBody');
  T.has(rep, 'Your five skills', 'the report: five skills'); T.eq(await page.evaluate(() => document.querySelectorAll('#riCats .ri-cat').length), 5, 'five bars');
  T.has(rep, 'Question by question', 'per-question cards'); T.ok(await H.vis(page, '#riStrip'), 'the XP strip (the real award ran)');
  const fin = await api('owner', 'GET', '/sessions/' + sid);
  T.eq([fin.body.session.status, fin.body.counts.real, typeof fin.body.report.overall], ['finished', 3, 'number'], 'the session is finished in the database with a report');
  const overall = fin.body.report.overall;

  // ------------------------------------------------------------------------------------------- B
  T.section('B - a second device: the same account sees it, and can continue an unfinished interview');
  const ctx2 = await realCtx(browser, 'owner', { viewport: { width: 360, height: 640 } });
  const page2 = await H.boot(ctx2, env, '/');
  await H.toHub(page2);
  await page2.waitForSelector('#riSessions .ri-row');
  T.has(await H.txt(page2, '#riSessions'), 'Data Analyst - Acme Corp', 'device 2 lists the finished interview (the title the server derived from the job)');
  T.eq((await H.txt(page2, '#riSessions .ri-score')).trim(), String(overall), 'with its score');
  await page2.click('#riSessions .ri-main'); await H.waitView(page2, 'report');
  await page2.waitForSelector('#riRepHero');
  T.has(await H.txt(page2, '#riBody'), 'Question by question', 'and opens its report');
  T.ok(await page2.evaluate(() => document.querySelectorAll('.ri-pq-a .btn').length) === 0, 'no ▶ Listen on the second device (the recordings are on the first phone)');
  await page.click('#riPracticeAgain');                                           // device 1 starts another interview for the same job
  await H.waitView(page, 'interview', 25000); await page.waitForSelector('#riQText');
  const q1 = await H.txt(page, '#riQText');
  await page2.click('#riBack'); await H.waitView(page2, 'hub');
  await page2.reload({ waitUntil: 'domcontentloaded' });                          // the URL is /resume-interview: the client's deep link lands on the hub, not on Home
  await H.waitView(page2, 'hub', 15000); await page2.waitForSelector('#riNew', { state: 'visible' });
  await page2.waitForSelector('#riContinue', { state: 'visible', timeout: 10000 });
  await page2.click('#riContinue'); await H.waitView(page2, 'interview', 15000);
  await page2.waitForSelector('#riQText');
  T.eq(await H.txt(page2, '#riQText'), q1, 'device 2 continues at the exact open question');
  await H.answerOnce(page2, { wait: 10600 });                                      // answered on device 2 ...
  const sid2 = await activeSid('owner');
  const turn = (await api('owner', 'GET', '/sessions/' + sid2)).body.turns[0];
  T.eq([turn.status, turn.feedback_state], ['answered', 'done'], '... and stored once, with feedback');
  await page.reload({ waitUntil: 'domcontentloaded' });                           // ... device 1 reloads (a deep link into the interview) and sees it (the other phone's answer)
  await page.waitForFunction(() => { const r = document.getElementById('ri'), on = document.querySelector('.screen.on'); return !!(r && on && on.id === 'ri' && ['hub', 'interview'].includes(r.dataset.view)); }, null, { timeout: 15000 });
  if ((await H.view(page)) === 'hub') {                                           // either landing is correct; the interview must be one tap away
    await page.waitForSelector('#riContinue', { state: 'visible', timeout: 10000 });
    await page.click('#riContinue'); await H.waitView(page, 'interview', 15000);
  }
  // the shell routes a cold deep link twice (once from the cached state, once when /me answers), so the screen is rebuilt: read both texts in ONE step
  const seen = await (await page.waitForFunction(() => {
    const c = document.getElementById('riFbCard'), l = document.getElementById('riListen');
    return c && l && /What DuSu heard/.test(c.textContent) && l.textContent.trim() ? { card: c.textContent, listen: l.textContent.trim() } : false;
  }, null, { timeout: 15000 })).jsonValue();
  T.has(seen.card, 'What DuSu heard', 'device 1 shows the feedback of the answer given on device 2');
  T.ok(/other phone|not available|on your/i.test(seen.listen), 'and says where the recording is: ' + seen.listen.slice(0, 80));

  // ------------------------------------------------------------------------------------------- C
  T.section('C - isolation: another learner');
  const ctxB = await realCtx(browser, 'bob', { seed: { dusu_office_keys: { gemini: 'stub-key', openrouter: 'stub-key-2' }, dusu_keys_ok: '1', dusu_keys_owner: 'bob@example.com', dusu_usemode: 'office' } });
  const pageB = await H.boot(ctxB, env, '/');
  await H.toHub(pageB);
  T.ok(!(await H.vis(pageB, '#riContinue')), 'Bob has no Continue card');
  T.has(await H.txt(pageB, '#riBody'), 'No interviews yet', 'and an empty list');
  for (const [m, p] of [['GET', '/sessions/' + sid], ['POST', '/sessions/' + sid + '/next'], ['POST', '/sessions/' + sid + '/finish'], ['GET', '/documents/' + 1], ['DELETE', '/sessions/' + sid]]) {
    const r = await api('bob', m, p, m === 'POST' ? { keys: { gemini: 'k' } } : undefined);
    T.eq(r.status, 404, `Bob: ${m} ${p} -> 404`);
  }
  T.eq((await api('owner', 'GET', '/sessions/' + sid)).status, 200, "and Ann's data is untouched");

  // ------------------------------------------------------------------------------------------- D
  T.section("D - a learner with her own Groq key: speech-to-text goes straight from the phone");
  const ctxA = await realCtx(browser, 'ann', { seed: { dusu_office_keys: { groq: 'gsk_e2e', gemini: 'stub-key' }, dusu_keys_ok: '1', dusu_keys_owner: 'ann@example.com', dusu_usemode: 'office' } });
  const pageA = await H.boot(ctxA, env, '/');
  await H.toHub(pageA);
  await H.toMatch(pageA, env, { resume: FX.RESUME, jd: FX.JD, jdTitle: 'Data Analyst', jdCompany: 'Acme Corp' });
  await H.startInterview(pageA);
  await H.answerOnce(pageA, { wait: 10600 });
  T.eq(env.groqCalls, 1, "one Groq call from the phone (api.groq.com), not the server proxy");
  const aTurn = (await api('ann', 'GET', '/sessions/' + (await activeSid('ann')))).body.turns[0];
  T.eq([aTurn.engine, aTurn.real, aTurn.feedback_state], ['groq', true, 'done'], 'engine groq, a real answer, feedback done (with measured pauses from the word timestamps)');
  T.eq((aTurn.feedback.delivery || {}).measured, true, 'delivery was MEASURED (word timestamps came with the Groq transcript)');

  // ------------------------------------------------------------------------------------------- E
  T.section('E - XSS canary through every field that reaches the screen');
  const ctxX = await realCtx(browser, 'bob', { seed: { dusu_office_keys: { gemini: 'stub-key', openrouter: 'stub-key-2' }, dusu_keys_ok: '1', dusu_keys_owner: 'bob@example.com', dusu_usemode: 'office' } });
  const pageX = await H.boot(ctxX, env, '/');
  await H.toHub(pageX);
  // the payload goes INTO the skills section: the fixture ends with a "Personal details / Declaration" block, which the redactor (rightly) removes to the end
  const evil = FX.RESUME.replace('SKILLS\n', '<img src=x onerror="window.__xss=1">\n<script>window.__xss=2</script>\n"><svg onload=window.__xss=3>\nSKILLS\n');
  await pageX.click('#riNew'); await H.waitView(pageX, 'resume');
  await pageX.fill('#riResName', '<img src=x onerror="window.__xss=4">');
  await pageX.fill('#riResText', evil);
  await pageX.click('#riUseText');
  await pageX.waitForSelector('#riPre', { state: 'visible' });
  T.has(await H.txt(pageX, '#riPre'), '<img src=x onerror', 'the preview shows the payload as literal TEXT');
  await pageX.click('#riLooks'); await H.waitView(pageX, 'job');
  await pageX.fill('#riJobTitle', '"><img src=x onerror=window.__xss=5>');
  await pageX.fill('#riJobCompany', '<b onmouseover=window.__xss=6>Acme</b>');
  await pageX.fill('#riJdText', FX.JD + '\n<img src=x onerror=window.__xss=7>');
  await pageX.click('#riNext');
  await pageX.waitForSelector('#riHero', { state: 'visible', timeout: 20000 });
  await H.startInterview(pageX);
  await pageX.click('#riBack').catch(() => {});
  await H.sleep(500);
  const xss = await pageX.evaluate(() => window.__xss);
  T.eq(xss, undefined, 'no payload executed (window.__xss is untouched)');
  const html = await pageX.evaluate(() => document.getElementById('ri').innerHTML);
  T.ok(!/<img[^>]+onerror/i.test(html) && !/<svg[^>]+onload/i.test(html) && !/<script>window/i.test(html), 'and the DOM contains no live payload element');

  // ------------------------------------------------------------------------------------------- F
  T.section('F - the AI is down for every answer: each answer is saved, Finish still works, the report says "not scored" (never a made-up number)');
  const ctxC = await realCtx(browser, 'cat', { seed: { dusu_office_keys: { groq: 'gsk_e2e', gemini: 'stub-key' }, dusu_keys_ok: '1', dusu_keys_owner: 'cat@example.com', dusu_usemode: 'office' } });   // a Groq key: speech-to-text from the phone
  const pageC = await H.boot(ctxC, env, '/');
  await H.toHub(pageC);
  await H.toMatch(pageC, env, { resume: FX.RESUME, jd: FX.JD, jdTitle: 'Data Analyst', jdCompany: 'Acme Corp' });
  await H.startInterview(pageC);
  await fetch(BASE + '/__e2e/fail?stage=answer', { method: 'POST' });
  for (let i = 1; i <= 3; i++) {
    await H.answerOnce(pageC, { wait: 5600, expect: 'none' });
    await pageC.waitForSelector('#riFbFail', { state: 'visible', timeout: 25000 });
    if (i === 1) T.ok(await H.vis(pageC, '#riRetryFb'), 'a failed feedback shows its card with a Retry button (the transcript is safe)');
    if (i < 3) { await pageC.click('#riNextQ'); await pageC.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i + 1); }
  }
  T.eq(await H.txt(pageC, '#riFin'), 'Finish interview', 'Finish unlocked: three REAL answers count even though no feedback could be written');
  await fetch(BASE + '/__e2e/fail?clear=true', { method: 'POST' });
  await pageC.click('#riFin');
  await H.waitView(pageC, 'report', 20000);
  await pageC.waitForSelector('#riRepHero');
  T.ok(await H.vis(pageC, '#riNoScore'), 'the report explains there is no overall score');
  T.eq((await H.txt(pageC, '#riRepHero .score-ring .val b')).trim(), '—', 'the ring shows a dash, not 0');
  T.has(await H.txt(pageC, '#riRepHero'), 'Not scored', 'with the caption "Not scored"');
  const sidC = ((await api('cat', 'GET', '/state')).body.sessions[0] || {}).id;
  const repC = (await api('cat', 'GET', '/sessions/' + sidC)).body;
  T.eq([repC.session.status, repC.report.overall, repC.report.band], ['finished', null, 'unknown'], 'in the database: finished, overall null, band unknown');

  // ------------------------------------------------------------------------------------------- G
  T.section('G - weaknesses in detail, saved focus points, "did it work?" (a weak interview, then a strong one)');
  const ctxD = await realCtx(browser, 'dan', { seed: { dusu_office_keys: { groq: 'gsk_e2e', gemini: 'stub-key' }, dusu_keys_ok: '1', dusu_keys_owner: 'dan@example.com', dusu_usemode: 'office' } });
  const pageD = await H.boot(ctxD, env, '/');
  await H.toHub(pageD);
  T.ok(!(await H.vis(pageD, '#riFocusCard')), 'a new learner has no focus card');
  env.sttText = FX.ANSWER_WEAK;
  await H.toMatch(pageD, env, { resume: FX.RESUME, jd: FX.JD, jdTitle: 'Data Analyst', jdCompany: 'Acme Corp' });
  await H.startInterview(pageD);
  for (let i = 1; i <= 3; i++) {
    await H.answerOnce(pageD, { wait: 5600 });
    if (i < 3) { await pageD.click('#riNextQ'); await pageD.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i + 1); }
  }
  await pageD.click('#riFin'); await H.waitView(pageD, 'report', 20000); await pageD.waitForSelector('#riRepHero');
  T.ok(await H.vis(pageD, '#riPlan'), 'the report has an improvement plan (the real server computed it from the real answers)');
  const plan1 = await pageD.evaluate(() => [...document.querySelectorAll('#riPlan li')].map(li => li.textContent));
  T.ok(plan1.length >= 1 && plan1.length <= 3, 'at most three focus points: ' + plan1.map(x => x.split(' — ')[0]).join(' | '));
  T.ok((await pageD.evaluate(() => document.querySelectorAll('.ri-wk').length)) >= 2, 'several weaknesses are explained in detail');
  const wk1 = await H.txt(pageD, '.ri-wk');
  for (const part of ['What happened', 'Why it matters', 'How to fix it', 'Practise this', 'Goal for next time']) T.has(wk1, part, 'a weakness card explains: ' + part);
  T.ok(!(await H.vis(pageD, '#riProgress')), 'no "since last time" on the first interview');
  T.eq(await pageD.evaluate(() => document.querySelectorAll('#riPerQ .ri-pqd').length), 3, 'every answer can be opened');
  const ans1 = await pageD.evaluate(() => { const d = document.querySelector('#riPerQ .ri-pqd'); d.open = true; return d.textContent; });
  T.has(ans1, 'What you said', 'an old answer shows what was said ...'); T.has(ans1, 'Mistakes to fix', '... and the mistakes to fix');
  const stD = (await api('dan', 'GET', '/state')).body;
  T.ok(stD.focus && stD.focus.points.length >= 1 && stD.focus.points.every(p => p.title && p.goal), 'the hub state carries the focus points');
  await pageD.click('#riBack'); await H.waitView(pageD, 'hub'); await pageD.waitForSelector('#riFocusCard');
  T.has(await H.txt(pageD, '#riFocusCard'), 'Your focus for next time', 'the hub shows the focus card');
  env.sttText = FX.ANSWER_GOOD;                                                   // the second interview is a strong one
  await pageD.click('#riFocusSee'); await H.waitView(pageD, 'report'); await pageD.waitForSelector('#riPlan');
  await pageD.click('#riPracticeAgain'); await H.waitView(pageD, 'interview', 25000); await pageD.waitForSelector('#riQText');
  T.has(await H.txt(pageD, '#riFocusBar'), 'Your focus today', 'the next interview starts with the focus bar');
  await H.answerOnce(pageD, { wait: 5600 });
  await pageD.waitForSelector('#riFocusCheck', { state: 'visible', timeout: 10000 });
  T.ok((await pageD.evaluate(() => document.querySelectorAll('#riFocusCheck li').length)) >= 1, 'every answer is checked against the focus points (tick / cross)');
  for (let i = 2; i <= 3; i++) {
    await pageD.click('#riNextQ'); await pageD.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i);
    await H.answerOnce(pageD, { wait: 5600 });
  }
  await pageD.click('#riFin'); await H.waitView(pageD, 'report', 20000); await pageD.waitForSelector('#riProgress');
  const prog = await pageD.evaluate(() => [...document.querySelectorAll('#riProgress .ri-prow')].map(r => r.textContent));
  T.ok(prog.length >= 1, '"Since your last interview" judges the saved focus points: ' + prog.map(x => x.slice(0, 60)).join(' | '));
  T.ok(prog.some(x => x.startsWith('Better')), 'strong answers after weak ones: at least one point is "Better"');
  T.ok(!prog.some(x => x.startsWith('Worse')), 'and none got worse');
  const repD = (await api('dan', 'GET', '/sessions/' + ((await api('dan', 'GET', '/state')).body.sessions[0] || {}).id)).body;
  T.ok(repD.report.progress && repD.report.progress.improved >= 1 && repD.report.v === 2, 'the comparison is saved with the interview');

  // ------------------------------------------------------------------------------------------- end
  T.section('no console errors, no unhandled rejections (the pages that ran the whole flow)');
  for (const [name, p] of [['owner device 1', page], ['owner device 2', page2], ['bob', pageB], ['ann', pageA], ['cat', pageC], ['dan', pageD]]) {
    const e = await H.collectErrors(p);
    T.eq([p.__consoleErrors, e.errors, e.rejections], [[], [], []], `${name}: no errors`);
  }
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
