'use strict';
/*
 * Stored-XSS canary. Resume Interview renders resume text, job text, titles, companies, transcripts, questions and model output - all attacker-controlled
 * in the worst case - on a page whose localStorage holds the session token and the BYOK keys. A stored XSS here would hand those over.
 *
 * Every dynamic string is hostile here:  <img src=x onerror="window.__xss=...">, <script>window.__xss=...</script>, quotes that try to break out of an attribute.
 *  - what the learner types / uploads: resume text, edited text, job title, company, job text, the (Whisper) transcript
 *  - what the server sends back: titles, role, company, requirements, evidence, verdict, edits (from / to / why), notes, strengths, questions, "why", feedback (worked,
 *    mistakes said / better / why, content notes, improvements, better answer, follow-up, resume check), report (patterns, fixes, redo, per-question text, coverage)
 * After every step window.__xss must still be undefined, no <img>/<script>/on* attribute may exist inside #ri, and the hostile text must be VISIBLE as text
 * (so the test cannot pass because nothing rendered).
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const M = require('./mock.cjs');

const IMG = '<img src=x onerror="window.__xss=(window.__xss||0)+1">';
const SCR = '<script>window.__xss=(window.__xss||0)+100</script>';
const BRK = '" onmouseover="window.__xss=(window.__xss||0)+1000" x="';
const HOSTILE = s => `${s} ${IMG} ${SCR} ${BRK}`;

(async () => {
  const T = H.makeT('xss');
  const env = await H.newEnv({ mock: { xss: true, limits: { min_answer_sec: 2 } } });
  const mock = env.mock;
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const ctx = await H.newCtx(browser, env, { viewport: { width: 390, height: 844 } });
  const page = await H.boot(ctx, env, '/');
  page.setDefaultTimeout(15000);

  async function audit(label, mustShow) {
    await page.waitForTimeout(150);
    const r = await page.evaluate(() => {
      const ri = document.getElementById('ri');
      const bad = [...ri.querySelectorAll('img, script, iframe, object, embed, svg image, [onerror], [onclick], [onmouseover], [onload], [srcdoc]')].filter(e => !(e.tagName.toLowerCase() === 'svg')).map(e => e.tagName + (e.getAttribute('onclick') ? '[onclick]' : ''));
      // attributes that no RI code path sets from a string must not exist (the h() builder only accepts functions for on*)
      const handlerAttrs = [];
      ri.querySelectorAll('*').forEach(e => { for (const a of e.attributes) if (/^on/i.test(a.name)) handlerAttrs.push(e.tagName + ':' + a.name); });
      const injectedAttr = [...document.querySelectorAll('[x], [onmouseover]')].filter(e => e.namespaceURI === 'http://www.w3.org/1999/xhtml').map(e => e.tagName);   // (SVG <rect x=...> elsewhere in the page is not an injection)
      return { xss: window.__xss, bad, handlerAttrs, injectedAttr, text: ri.textContent };
    });
    T.eq(r.xss, undefined, `${label}: window.__xss is untouched`);
    T.eq(r.bad, [], `${label}: no <img>/<script>/handler element inside #ri`);
    T.eq(r.handlerAttrs, [], `${label}: no on* attribute anywhere inside #ri`);
    T.eq(r.injectedAttr, [], `${label}: no attribute was injected through a quote`);
    for (const s of (mustShow || [])) T.ok(r.text.includes(s), `${label}: the hostile text is shown AS TEXT ("${s.slice(0, 40)}…")`);
  }

  T.section('hub: hostile titles');
  await H.toHub(page);
  await audit('hub (empty)');

  T.section('resume: hostile text typed, uploaded and edited');
  await page.click('#riNew'); await H.waitView(page, 'resume');
  const resume = HOSTILE('Asha Rao, Data Analyst') + '\n' + M.RESUME_TEXT + '\n' + HOSTILE('- Built things');
  await page.fill('#riResName', HOSTILE('My resume'));
  await page.fill('#riResText', resume);
  await page.click('#riUseText'); await page.waitForSelector('#riPre');
  await audit('resume preview', ['<img src=x onerror=', '<script>window.__xss']);
  await page.click('#riEdit'); await page.waitForSelector('#riEditText');
  await page.fill('#riEditText', (await page.inputValue('#riEditText')) + '\n' + HOSTILE('edited line'));
  await audit('resume editor', []);
  await page.click('#riSaveEdit'); await page.waitForSelector('#riPre');
  await audit('resume (edited, versions listed)', ['edited line']);
  await page.click('text=Use a different file');
  await page.setInputFiles('#riResFile', { name: '"><img src=x onerror=window.__xss=7>.txt', mimeType: 'text/plain', buffer: Buffer.from(resume + '\n- from a file') });
  await page.waitForSelector('#riPre');
  await audit('resume (uploaded; the file name is hostile too)', ['from a file']);
  await page.click('#riLooks'); await H.waitView(page, 'job');

  T.section('job: hostile title, company and text');
  await page.fill('#riJobTitle', HOSTILE('Data Analyst'));
  await page.fill('#riJobCompany', HOSTILE('Acme'));
  await page.fill('#riJdText', HOSTILE('Data Analyst - Acme Corp') + '\n' + M.JD_TEXT.split('\n').slice(1).join('\n') + '\n- ' + HOSTILE('hostile requirement'));
  await audit('job (typed)', []);
  await page.click('#riNext');
  await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });

  T.section('match: hostile requirements, evidence, edits, notes, strengths');
  await audit('match', ['<img src=x onerror=', 'Only if true for you']);
  const reqText = await page.evaluate(() => [...document.querySelectorAll('.ri-req-t')].map(e => e.textContent).join('|'));
  T.has(reqText, '<img src=x', 'requirement text is shown as text');
  await page.click('.ri-edit .btn');
  await H.sleep(200);
  T.ok((await page.evaluate(() => window.__copied)).some(x => /<img src=x/.test(x)), 'Copy puts the hostile wording on the clipboard as plain text');
  await audit('match (after copy)');
  await page.click('#riReupload'); await H.waitView(page, 'resume');
  await page.setInputFiles('#riResFile', { name: 'v2.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_IMPROVED + '\n' + HOSTILE('- v2 line')) });
  await page.waitForSelector('#riPre'); await page.click('#riLooks');
  await page.waitForSelector('#riPrev', { state: 'visible', timeout: 15000 });
  await audit('match (comparison card)', ['Compared with your previous resume']);

  T.section('interview: hostile questions, why, transcript and feedback');
  await H.startInterview(page);
  await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
  await audit('interview (question)', ['<img src=x onerror=']);
  env.groq.queue.push({ text: HOSTILE('So in my last role I make dashboard for the sales team and uh basically I used SQL to pull the weekly numbers and then I checked the duplicates before sharing with the stakeholders every Monday morning'), dur: 24 });
  await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(1300); await page.click('#riStop');
  await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
  await audit('interview (feedback)', ['<img src=x onerror=', 'What DuSu heard']);
  const heard = await H.txt(page, '#riHeard');
  T.has(heard, '<script>window.__xss', 'the hostile TRANSCRIPT is shown as text');
  await page.click('#riFbCard .ri-fix .ri-link'); await page.click('#riFbCard .ri-fix.hidden .ri-link');
  await audit('interview (after dismiss + undo)');
  for (let i = 0; i < 2; i++) {
    await page.click('#riNextQ'); await page.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i + 2);
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    await H.answerOnce(page);
  }
  await audit('interview (3 answers)');

  T.section('report: hostile patterns, fixes, redo, per-question text, coverage');
  await page.click('#riFin'); await H.waitView(page, 'report', 15000); await page.waitForSelector('#riPerQ');
  await audit('report', ['<img src=x onerror=', 'Question by question']);
  T.has(await H.txt(page, '#riPlan'), '<script>', 'the improvement plan is shown as text');
  T.has(await H.txt(page, '#riWk-no_number'), '<img src=x', 'the weakness cards are shown as text');
  await page.evaluate(() => document.querySelectorAll('#ri .ri-wk, #ri .ri-pqd').forEach(d => { d.open = true; }));
  await audit('report (every weakness and every answer opened)', ['<img src=x onerror=']);
  T.has(await H.txt(page, '#riWk-grammar'), '<img src=x', 'the learner\'s own slips inside a weakness card are shown as text');
  T.has(await H.txt(page, '#riWk-coverage'), '<img src=x', 'the job requirements inside a weakness card are shown as text');
  T.has(await H.txt(page, '#riPQ-1'), '<script>', 'an opened answer (transcript, mistakes, stronger answer) is shown as text');
  T.has(await H.txt(page, '#riRedo'), '<img src=x', 'the answer to redo is shown as text');
  T.has(await H.txt(page, '#riCov'), '<img src=x', 'coverage is shown as text');

  T.section('the next interview: hostile focus bar, per-answer check and "since last time"');
  await page.click('#riPracticeAgain'); await H.waitView(page, 'interview', 20000); await page.waitForSelector('#riQText');
  await page.click('#riFocusBar summary');
  await audit('interview (focus bar)', ['<img src=x onerror=']);
  await H.answerOnce(page);
  await page.waitForSelector('#riFocusCheck', { state: 'visible' });
  await audit('interview (focus check)', ['<img src=x onerror=']);
  T.has(await H.txt(page, '#riFocusCheck'), '<img src=x', 'the focus check shows the (hostile) focus-point titles as text');
  for (let i = 0; i < 2; i++) {
    await page.click('#riNextQ'); await page.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i + 2);
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    await H.answerOnce(page);
  }
  await page.click('#riFin'); await H.waitView(page, 'report', 15000); await page.waitForSelector('#riProgress');
  await audit('report (since last time)', ['<img src=x onerror=']);
  T.has(await H.txt(page, '#riProgress'), '<script>', 'the progress card is shown as text');

  T.section('hub + settings with hostile data');
  await page.click('#riBack'); await H.waitView(page, 'hub'); await page.waitForSelector('#riSessions .ri-row');
  T.has(await H.txt(page, '#riFocusCard'), '<img src=x', 'the hub\'s focus card shows hostile focus titles as text');
  await audit('hub (history, resumes, jobs)', ['<img src=x onerror=']);
  T.section('hub: more than one page of hostile history ("Show older interviews")');
  const mkOld = id => ({ id, title: 'Old interview ' + id, status: 'finished', settings: { type: 'mixed', level: 'fresher', feedback_lang: 'en' }, resume_id: null, jd_id: null, overall: 60,
    created_at: new Date(Date.now() - (9e5 - id) * 1000).toISOString(), started_at: new Date(Date.now() - (9e5 - id) * 1000).toISOString(), finished_at: new Date(Date.now() - (9e5 - id) * 1000 + 600e3).toISOString(),
    analysis: null, turns: [], queue: [], rev: 1, picked: [] });
  for (let i = 1; i <= 33; i++) mock.sessions.push(mkOld(7000 + i));         // the mock hostile-wraps every title it sends
  await page.reload(); await H.waitView(page, 'hub'); await page.waitForSelector('#riOlder');
  await audit('hub (first page of a long history)', ['<img src=x onerror=']);
  await page.click('#riOlder');
  await page.waitForFunction(() => document.querySelectorAll('#riSessions .ri-row').length > 30);
  await audit('hub (older interviews appended)', ['<img src=x onerror=']);
  await page.click('#riGear'); await H.waitView(page, 'settings'); await page.waitForSelector('#riExport');
  await audit('settings');

  T.section('the rest of the page is untouched');
  T.eq(await page.evaluate(() => window.__xss), undefined, 'window.__xss is STILL undefined after the whole journey');
  T.ok(await page.evaluate(() => !!localStorage.getItem('dusu_token') && !!localStorage.getItem('dusu_office_keys')), 'the token and the keys are still where they were');
  const errs = await H.collectErrors(page);
  T.eq(page.__consoleErrors.concat(errs.errors, errs.rejections), [], 'no console errors');
  await browser.close(); await env.server.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
