'use strict';
/*
 * Failure branches and awkward paths of Resume Interview, each in a fresh browser context against the stateful contract mock:
 *   uploads (413 / 415 / 422 ...) · analysis (202 pending, 502, dropped connection, 402, 429, "still working") · start (202, 502)
 *   · answers (too short, no speech, Groq 401 / 429 / network, DuSu's own transcription, no key, mic denied, feedback failure + retry,
 *     202 pending, 409 already answered, dropped connection, 429 + retry with the SAME client_key, "did not count")
 *   · Finish (409 need_more, 500) · Next 500 · interruptions while recording (Back, tab hidden, mic taken, leaving the screen)
 *   · deep links and reload · delete / delete-all · a never-analysed draft · the daily / document / interview limits · the keys gate
 *   · history beyond the newest 30 interviews · a take rebuilt after the app died mid-recording.
 * Select scenarios with  CASES=upload,analysis  (comma list of the section names below).
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const M = require('./mock.cjs');

const WRAP = process.env.WRAP !== '0';
const CASES = process.env.CASES ? process.env.CASES.split(',') : null;
const want = n => !CASES || CASES.includes(n);

(async () => {
  const T = H.makeT('edge (wrapDetail=' + WRAP + ')');
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const errors = [];
  const closers = [];

  // a fresh world: own server + mock + context + page, signed in, on the Resume Interview hub
  async function world(o = {}) {
    const env = await H.newEnv({ mock: Object.assign({ wrapDetail: WRAP, limits: { min_answer_sec: 2 } }, o.mock || {}) });
    const ctx = await H.newCtx(browser, env, { viewport: o.viewport || { width: 390, height: 844 }, seed: o.seed });
    if (o.init) await ctx.addInitScript(o.init);
    const page = await H.boot(ctx, env, o.path || '/');
    page.setDefaultTimeout(15000);
    if (!o.path) await H.toHub(page);
    const w = { env, mock: env.mock, ctx, page, async close() { errors.push(...page.__consoleErrors.map(e => `[${w.name}] ${e}`)); const r = await H.collectErrors(page); errors.push(...r.errors.map(e => `[${w.name}] ${e}`), ...r.rejections.map(e => `[${w.name}] rejection ${e}`)); await ctx.close(); await env.server.close(); } };
    return w;
  }
  const guard = async (name, fn) => { try { await fn(); } catch (e) { const at = String(e && e.stack || '').split('\n').find(l => /edge\.spec\.cjs:\d+/.test(l)) || ''; T.ok(false, `${name}: scenario crashed: ${String(e && e.message || e).split('\n').slice(0, process.env.VERBOSE ? 14 : 1).join(' | ')} @ ${at.trim()}`); } };
  async function toInterview(w, jd) {
    await H.toMatch(w.page, w.env, { jd });
    await H.startInterview(w.page);
    await w.page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
  }
  const note = page => H.noteText(page);
  const tapRecord = async (page, ms = 1300) => { await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(ms); await page.click('#riStop'); };

  /* ------------------------------------------------------------------------------------------ uploads */
  if (want('upload')) await guard('upload', async () => {
    T.section('uploads: every failure becomes a plain sentence, nothing server-side is ever shown');
    const w = await world(); w.name = 'upload'; const { page, mock } = w;
    await page.click('#riNew'); await H.waitView(page, 'resume');
    T.eq(await page.getAttribute('#riResText', 'maxlength'), '60000', "the paste box stops at the server's 60,000 character limit (a huge paste can never turn into a confusing 'file too large')");
    const up = async (name, mime, body, expectNote, label) => {
      await page.setInputFiles('#riResFile', { name, mimeType: mime, buffer: Buffer.isBuffer(body) ? body : Buffer.from(body) });
      await H.waitNote(page);
      const n = await note(page);
      T.has(n, expectNote, label);
      T.ok(!/Traceback|detail|error"|undefined|\[object/i.test(n), label + ': no raw server text in the message');
      T.ok(!(await H.vis(page, '#riPre')), label + ': no preview was shown');
    };
    await up('a.doc', 'application/msword', 'OLEHDR....', 'old Word (.doc)', '.doc -> save as .docx or PDF');
    await up('a.png', 'image/png', 'WEIRD....', "isn't supported", 'unsupported type');
    await up('scan.pdf', 'application/pdf', '%PDF-SCAN', 'scan or a photo', 'scanned PDF -> paste the text');
    await up('locked.pdf', 'application/pdf', '%PDF-ENC', 'password-protected', 'encrypted PDF');
    await up('tiny.txt', 'text/plain', 'SHORT', 'very little text', 'too little text');
    await up('bad.pdf', 'application/pdf', 'BADFILE', "couldn't read that file", 'a corrupt file (422 bad_file) -> try another or paste');
    await up('slow.pdf', 'application/pdf', 'EXTRACT502', "can't read files right now", 'the file reader is down (502 extract_unavailable) -> paste the text');
    await page.setInputFiles('#riResFile', { name: 'empty.txt', mimeType: 'text/plain', buffer: Buffer.alloc(0) });
    await H.waitNote(page); T.has(await note(page), 'no text', 'an empty file');
    mock.faults.upload500 = 1;
    await page.setInputFiles('#riResFile', { name: 'x.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_TEXT) });
    await H.waitNote(page); T.has(await note(page), 'Something went wrong', 'a server error is a generic sentence');
    const n0 = mock.calls.length;
    await page.setInputFiles('#riResFile', { name: 'big.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(5 * 1024 * 1024 + 10, 65) });
    await H.waitNote(page); T.has(await note(page), 'larger than 5 MB', 'a file over 5 MB is refused');
    T.eq(mock.calls.length, n0, 'and is never uploaded');
    mock.faults.warn = 1;
    await page.setInputFiles('#riResFile', { name: 'ok.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_TEXT) });
    await page.waitForSelector('#riPre');
    T.has(await H.txt(page, '#riPreview'), 'wrong order', 'a server warning is shown with the preview');
    T.ok(!(await H.vis(page, '#riTopNote')), 'a successful upload clears the old message');
    await page.click('text=Use a different file');
    await page.setInputFiles('#riResFile', { name: 'ok2.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_TEXT) });
    await page.waitForSelector('#riPre');
    T.has(await H.txt(page, '#riPreview'), 'saved this exact text before', 'a duplicate upload says it reused the earlier version');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ the job */
  if (want('job')) await guard('job', async () => {
    T.section('job: upload + edit, a job text the server calls too vague, jd limits');
    const w = await world(); w.name = 'job'; const { page, mock } = w;
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.fill('#riJobTitle', 'Senior Analyst');
    await page.setInputFiles('#riJdFile', { name: 'jd.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-FAKE\n' + M.JD_TEXT) });
    await page.waitForSelector('#riPre');
    const upc = mock.calls.find(c => c.path.includes('/documents/upload') && c.query === 'kind=jd');
    T.ok(upc && decodeURIComponent(upc.headers['x-ri-name']) === 'Senior Analyst', 'a JD upload carries the typed title in X-RI-Name (kind=jd)');
    T.has(await H.txt(page, '#riPre'), 'Power BI dashboards', 'the kept job text is previewed');
    await page.click('#riEdit'); await page.waitForSelector('#riEditText');
    await page.fill('#riEditText', M.JD_TEXT + '\n- Tableau (nice)'); await page.click('#riSaveEdit'); await page.waitForSelector('#riPre');
    T.has(await H.txt(page, '#riPre'), 'Tableau', 'a JD edit becomes a new document');
    mock.faults.jdVague = 1;
    await page.click('#riNext');
    await page.waitForSelector('#riJobErr', { timeout: 15000 });
    T.has(await H.txt(page, '#riJobErr'), 'too short to compare', 'jd_too_vague -> a plain message');
    T.ok(await page.isVisible('text=Back to the job'), 'with a way back to the job step');
    await page.click('text=Back to the job'); await H.waitView(page, 'job');
    T.ok(true, 'and back we are');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ analysis */
  if (want('analysis')) await guard('analysis', async () => {
    T.section('analysis: 502 -> retry, 402, 429, 202 pending (polls), dropped connection (polls), still-working note');
    const w = await world(); w.name = 'analysis'; const { page, mock } = w;
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.fill('#riJdText', M.JD_TEXT);
    mock.faults.analyze502 = 1;
    await page.click('#riNext');
    await page.waitForSelector('#riJobErr', { timeout: 15000 });
    T.has(await H.txt(page, '#riJobErr'), "couldn't analyse this right now", '502 analysis_unavailable -> a plain message');
    T.has(await H.txt(page, '#riJobErr'), 'documents are saved', 'that says nothing is lost');
    await page.click('#riRetryJob');
    await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    T.eq(mock.calls.filter(c => c.path.endsWith('/analyze')).length, 2, 'Try again re-ran the analysis (same session)');
    T.eq(mock.sessions.length, 1, 'and did not create a second session');

    // 402 keys_required on start
    mock.faults.status402 = 1;
    await page.click('#riStart');
    await page.waitForSelector('#riJobErr', { timeout: 15000 });
    T.has(await H.txt(page, '#riJobErr'), 'Add your own AI keys', '402 -> add your keys');
    T.ok(await page.isVisible('text=Add my keys'), 'with a button for it');
    await page.click('text=Add my keys'); await page.waitForTimeout(400);
    T.eq(await H.onScreen(page), 'keys', 'which opens the keys screen');
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub');
    await page.click('#riContinue'); await H.waitView(page, 'match'); await page.waitForSelector('#riHero');

    // 202 pending on a re-analysis through swap-resume: the page polls the session
    await page.click('#riReupload'); await H.waitView(page, 'resume');
    await page.setInputFiles('#riResFile', { name: 'v2.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_IMPROVED) });
    await page.waitForSelector('#riPre');
    mock.faults.analyzePending = 1;
    const getsBefore = mock.calls.filter(c => c.method === 'GET' && /\/sessions\/\d+$/.test(c.path)).length;
    await page.click('#riLooks');
    await H.waitView(page, 'analysing');
    T.ok(await H.vis(page, '#riLoad'), '202 pending -> the loader stays up');
    await page.waitForSelector('#riPrev', { state: 'visible', timeout: 20000 });
    T.ok(mock.calls.filter(c => c.method === 'GET' && /\/sessions\/\d+$/.test(c.path)).length > getsBefore, 'it polled GET /sessions/{id} until the analysis was done');
    T.eq(mock.calls.filter(c => c.path.endsWith('/swap-resume')).length, 1, 'and did NOT re-POST while polling');

    // a dropped connection: the server finished anyway
    await page.click('#riReupload'); await H.waitView(page, 'resume');
    await page.setInputFiles('#riResFile', { name: 'v3.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_IMPROVED + '\n- Built an A/B test readout for a pricing change.') });
    await page.waitForSelector('#riPre');
    mock.faults.analyzeDrop = 1;
    await page.click('#riLooks');
    await page.waitForSelector('#riPrev', { state: 'visible', timeout: 20000 });
    T.ok(true, 'a dropped connection mid-analysis ends on the match (the page polled the session instead of giving up)');

    // 429 quota
    await page.click('#riReupload'); await H.waitView(page, 'resume');
    await page.setInputFiles('#riResFile', { name: 'v4.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_IMPROVED + '\n- Another bullet about weekly reporting.') });
    await page.waitForSelector('#riPre');
    mock.faults.analyzeQuota = 1;
    await page.click('#riLooks');
    await page.waitForSelector('#riJobErr', { timeout: 15000 });
    T.has(await H.txt(page, '#riJobErr'), 'AI keys are at their limit', '429 quota -> a plain message');
    await w.close();
  });

  if (want('slow')) await guard('slow', async () => {
    T.section('analysis: the "still working" line after 15 seconds');
    const w = await world(); w.name = 'slow'; const { page, mock } = w;
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.fill('#riJdText', M.JD_TEXT);
    mock.delays.analyze = 17500;
    await page.click('#riNext'); await H.waitView(page, 'analysing');
    T.has(await H.txt(page, '#riLWait'), 'usually takes 10 to 20 seconds', 'the honest estimate first');
    await page.waitForFunction(() => /Still working/.test(document.getElementById('riLWait').textContent), null, { timeout: 18000 });
    T.ok(true, 'after 15 s it says it is still working (and the AI is slow), nothing else changed');
    T.eq(await page.evaluate(() => document.querySelectorAll('#riLoad .ri-ls.done').length), 2, 'the first two steps read as done, the last stays active until the answer arrives');
    await page.waitForSelector('#riHero', { state: 'visible', timeout: 20000 });
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ start */
  if (want('start')) await guard('start', async () => {
    T.section('start: 502 -> retry, 202 pending -> polls until the first question exists');
    const w = await world(); w.name = 'start'; const { page, mock } = w;
    await H.toMatch(page, w.env);
    mock.faults.plan502 = 1;
    await page.click('#riStart');
    await page.waitForSelector('#riJobErr', { timeout: 15000 });
    T.has(await H.txt(page, '#riJobErr'), "couldn't prepare the questions", '502 plan_unavailable -> a plain message');
    await page.click('#riRetryJob');
    await H.waitView(page, 'interview', 15000);
    await page.waitForSelector('#riQText');
    T.ok(true, 'Try again starts the interview');
    await page.click('#riBack'); await H.waitView(page, 'hub');
    // a second job: start answers 202 (the questions are still being written)
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await page.fill('#riResText', M.RESUME_TEXT + '\n- Extra line so this is a new document.'); await page.click('#riUseText'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.fill('#riJdText', M.JD_TEXT + '\n- Documentation'); await page.click('#riNext'); await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    mock.faults.startPending = 1;
    await page.click('#riStart');
    await H.waitView(page, 'analysing');
    await H.waitView(page, 'interview', 20000);
    await page.waitForSelector('#riQText', { timeout: 15000 });
    T.has(await H.txt(page, '#riQ'), 'Question 1', '202 on start -> it polled, then showed question 1');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ answers */
  if (want('answers')) await guard('answers', async () => {
    T.section('answers: too short (server), too short (local), no speech');
    const w = await world({ mock: { limits: { min_answer_sec: 10 } } }); w.name = 'answers'; const { page, mock, env } = w;
    await toInterview(w);
    // local guard: with the real 10 s limit, a 1.3 s take is not even sent for transcription
    await tapRecord(page, 1200);
    await H.waitNote(page); await page.waitForSelector('#riAgain');
    T.has(await note(page), 'only a moment long', 'a recording under half the minimum is refused locally');
    T.eq(env.groq.calls.length, 0, 'without spending a transcription call');
    T.ok(await H.vis(page, '#riAgain') && await H.vis(page, '#riSkip'), 'the dock offers Record again and Skip');
    // server says too short (few words)
    env.groq.queue.push({ text: M.TRANSCRIPT_SHORT + ' And one more bit of detail on top.', dur: 12 });
    await page.click('#riAgain'); await page.waitForSelector('#riRec'); await H.sleep(5400); await page.click('#riStop');
    await page.waitForFunction(() => /too short/i.test(document.getElementById('riNote').textContent), null, { timeout: 15000 });
    T.has(await note(page), '25 words and 10 seconds', 'the server\'s too_short is explained with its own minimums');
    T.has(await H.txt(page, '#riFin'), '3 more to unlock', 'it did not count toward Finish');
    T.ok(await H.vis(page, '#riQText'), 'the question is still open');
    T.eq(mock.calls.filter(c => c.path.endsWith('/answer')).length, 1, 'one answer attempt reached the server (and was not stored)');
    // nothing audible
    env.groq.queue.push({ text: 'uh', dur: 6 });
    await page.click('#riAgain'); await page.waitForSelector('#riRec'); await H.sleep(5400); await page.click('#riStop');
    await page.waitForFunction(() => /couldn't hear any words/i.test(document.getElementById('riNote').textContent), null, { timeout: 15000 });
    T.ok(true, 'a transcript with no real words -> "We couldn\'t hear any words" (and no answer is sent)');
    T.eq(mock.calls.filter(c => c.path.endsWith('/answer')).length, 1, 'still just the one attempt');
    // the server decides the recording had no real speech in it (silence / noise that Whisper turned into words): the honest reason, not "too short"
    mock.faults.answerNoSpeech = 1;
    env.groq.queue.push({ text: M.TRANSCRIPT_GOOD, dur: 14 });
    await page.click('#riAgain'); await page.waitForSelector('#riRec'); await H.sleep(5400); await page.click('#riStop');
    await page.waitForFunction(() => /couldn't hear any words/i.test(document.getElementById('riNote').textContent) && document.getElementById('riAgain'), null, { timeout: 15000 });
    T.eq(mock.calls.filter(c => c.path.endsWith('/answer')).length, 2, 'a transcript that looked fine did reach the server (and came back as "no speech")');
    T.ok(!/too short/i.test(await note(page)), 'and the message does not blame the length of the answer');
    await w.close();
  });

  if (want('stt')) await guard('stt', async () => {
    T.section('transcription failures: the recording is never lost');
    const w = await world(); w.name = 'stt'; const { page, mock, env } = w;
    await toInterview(w);
    // Groq rejects the key
    env.groq.queue.push({ status: 401 });
    await tapRecord(page);
    await page.waitForFunction(() => /Groq key was rejected/.test(document.getElementById('riNote').textContent), null, { timeout: 15000 });
    T.has(await note(page), 'recording is safe on this phone', '401 -> the key was rejected, the recording is safe');
    T.ok(await H.vis(page, '#riAddKeys'), 'with a way to fix the key');
    T.eq(mock.answers ? mock.answers.length : 0, 0, 'nothing was sent to DuSu');
    // busy twice (429 429), then fine: the pipeline retries once itself, so queue 429,429 -> error -> Retry button -> OK
    env.groq.queue.push({ status: 429 }, { status: 429 });
    await page.click('#riRerecord'); await page.waitForSelector('#riRec');   // Re-record discards the old take and starts a new one straight away
    await H.sleep(1300); await page.click('#riStop');
    await page.waitForFunction(() => /transcription service is busy/.test(document.getElementById('riNote').textContent), null, { timeout: 20000 });
    T.ok(true, '429 twice -> "busy", the take is kept');
    const gc = env.groq.calls.length;
    await page.click('#riRetryAns');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.eq(env.groq.calls.length, gc + 1, 'Try again re-sent the SAME recording (no second take)');
    // network failure to Groq
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    env.groq.queue.push({ abort: 'connectionreset' }, { abort: 'connectionreset' });
    await tapRecord(page);
    await page.waitForFunction(() => /No connection/.test(document.getElementById('riNote').textContent), null, { timeout: 20000 });
    T.has(await note(page), 'saved on this phone', 'network failure -> "No connection", the recording and text are kept');
    await page.click('#riRetryAns');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.ok(true, 'and Try again works once the network is back');
    await w.close();
  });

  if (want('proxy')) await guard('proxy', async () => {
    T.section('DuSu\'s own transcription (no Groq key on this phone) and the "add a key" card');
    const seed = { dusu_office_keys: { gemini: 'AIzaOnly', openrouter: 'sk-or-test' } };   // two keys (verified), none of them Groq
    const w = await world({ seed }); w.name = 'proxy'; const { page, mock, env } = w;
    await toInterview(w);
    mock.sttQueue.push({ text: M.TRANSCRIPT_GOOD, dur: 24 });
    await tapRecord(page);
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    const tc = mock.calls.find(c => c.path === '/rinterview/transcribe');
    const tq = new URLSearchParams(tc ? tc.query : '');
    T.ok(tc && tq.get('lang') === 'en', 'POST /rinterview/transcribe?lang=en');
    T.ok(/^Um, so, uh/.test(tq.get('prompt') || '') && (tq.get('prompt') || '').length <= 200 && /Role: Data Analyst/.test(tq.get('prompt') || ''), 'with the same <= 200 character prompt as the direct call (keeps the ums, adds the role): ' + tq.get('prompt'));
    T.ok(/audio\/webm/.test(tc.headers['content-type']) && tc.rawLen > 500, 'with the raw audio and its own Content-Type');
    T.eq(env.groq.calls.length, 0, 'and Groq was not called from the phone');
    const a = mock.answers[0].body;
    T.eq(a.engine, 'gemini', 'the answer carries the server engine');
    T.eq(a.words, [], 'without word timings');
    const f = await H.txt(page, '#riFbCard');
    T.has(f, "weren't measured", 'delivery says pauses were NOT measured');
    T.ok(!/long pause/.test(f), 'and shows no pause figures it does not have');
    // 502 stt_failed from the proxy
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    mock.faults.stt502 = 2;
    await tapRecord(page);
    await page.waitForFunction(() => /turn the recording into text/.test(document.getElementById('riNote').textContent), null, { timeout: 20000 });
    T.ok(true, '502 stt_failed -> a plain message with Try again');
    await page.click('#riRetryAns');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    await w.close();

    const w2 = await world({ seed, mock: { me: { ri_server_stt: false, office: true } } }); w2.name = 'nokey';   // a BYOK account: it may open the keys screen
    await toInterview(w2);
    await tapRecord(w2.page, 600).catch(() => {});
    // with no way to transcribe, the mic button itself leads to the one "add a free Groq key" card
    await H.waitNote(w2.page);
    const n = await H.noteText(w2.page);
    T.has(n, 'One free key needed', 'no Groq key and no server transcription -> one "add a free Groq key" card');
    T.ok(await H.vis(w2.page, '#riAddKeys'), 'with a button to add it');
    T.ok(!(await w2.page.evaluate(() => !!document.getElementById('riRec'))), 'the microphone was never opened');
    await w2.page.click('#riAddKeys'); await w2.page.waitForTimeout(400);
    T.eq(await H.onScreen(w2.page), 'keys', 'the button opens the keys screen');
    await w2.close();
  });

  if (want('mic')) await guard('mic', async () => {
    T.section('microphone denied');
    const w = await world(); w.name = 'mic'; const { page } = w;
    await toInterview(w);
    await page.evaluate(() => { window.__micDenied = true; });
    await page.click('#riMic');
    await H.waitNote(page);
    T.has(await note(page), "Microphone permission is blocked", 'NotAllowedError -> how to allow it');
    await page.evaluate(() => { window.__micDenied = false; });
    await page.click('#riRetryAns');
    await page.waitForSelector('#riRec');
    T.ok(true, 'Try again opens the microphone once allowed');
    await page.click('#riStop'); await H.sleep(300);
    await w.close();
  });

  if (want('feedback')) await guard('feedback', async () => {
    T.section('feedback: 502 (answer saved) -> retry, 202 pending -> polls, "did not count"');
    const w = await world(); w.name = 'feedback'; const { page, mock } = w;
    await toInterview(w);
    mock.faults.feedback502 = 1;
    await tapRecord(page);
    await page.waitForSelector('#riFbFail', { state: 'visible', timeout: 20000 });
    const ft = await H.txt(page, '#riFbFail');
    T.has(ft, "Your answer is saved", '502 feedback_unavailable -> the answer IS saved');
    T.has(ft, 'I make dashboard', 'its transcript is shown');
    T.has(ft, 'words in', 'and the measured delivery card');
    T.ok(await H.vis(page, '#riRetryFb'), 'with Retry feedback');
    T.ok(await H.vis(page, '#riNextQ'), 'Next is still possible');
    T.has(await H.txt(page, '#riFin'), '2 more to unlock', 'a failed feedback still counts as a real answer toward Finish (the server decides "real")');
    await page.click('#riRetryFb');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 15000 });
    T.eq(mock.calls.filter(c => c.path.endsWith('/feedback')).length, 1, 'POST /turns/{id}/feedback');
    T.eq(mock.answers.length, 1, 'and the answer was NOT sent again');
    // pending
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    mock.faults.answerPending = 1;
    const getsBefore = mock.calls.filter(c => c.method === 'GET' && /\/turns\/\d+$/.test(c.path)).length;
    await tapRecord(page);
    await page.waitForFunction(() => { const w = document.getElementById('riWork'); return w && /reading your answer/.test(w.textContent); }, null, { timeout: 15000 });
    T.ok(true, '202 pending -> "DuSu is reading your answer…" stays in the dock while it polls');
    T.ok(!(await H.vis(page, '#riNextQ')), 'no Next while the feedback is being written');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.ok(mock.calls.filter(c => c.method === 'GET' && /\/turns\/\d+$/.test(c.path)).length > getsBefore, 'it polled GET /turns/{id}');
    T.eq(mock.answers.length, 2, 'and did not re-POST the answer');
    // not real
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 3/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    mock.faults.notReal = 1;
    await tapRecord(page);
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.has(await H.txt(page, '#riFbCard'), "didn't count toward the 3 needed to finish", 'an answer the server did not count says so');
    await w.close();
  });

  if (want('dup')) await guard('dup', async () => {
    T.section('409 already answered, dropped connection, 429 + retry with the same client_key');
    const w = await world(); w.name = 'dup'; const { page, mock, env } = w;
    await toInterview(w);
    mock.faults.answerAlready = 1;
    await tapRecord(page);
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.has(await H.noteText(page), 'already answered', '409 already_answered -> shows the stored feedback and says so');
    T.has(await H.txt(page, '#riHeard'), 'Answered on the other phone', 'the stored transcript is shown, not ours');
    T.eq(await page.evaluate(() => document.querySelectorAll('#riListen audio').length), 0, 'our own recording is not offered for an answer it did not produce');
    T.has(await H.txt(page, '#riListen'), 'on your other phone', 'and says where that recording is');
    // dropped connection after the server saved it
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    mock.faults.answerDrop = 1;
    const before = mock.answers.length;
    await tapRecord(page);
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 25000 });
    T.eq(mock.answers.length - before, 1, 'a dropped connection: the page asked the server (GET) instead of sending the answer twice');
    // 429 then retry: same key
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 3/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    mock.faults.answerQuota = 1;
    await tapRecord(page);
    await page.waitForFunction(() => /AI keys are at their limit/.test(document.getElementById('riNote').textContent), null, { timeout: 20000 });
    await page.click('#riRetryAns');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    const last = mock.answers.slice(-2);
    T.eq(last[0].body.client_key, last[1].body.client_key, 'Try again re-sends with the SAME client_key (so a replay can never double-count)');
    T.eq(env.groq.calls.length, 3, 'and did not transcribe the same recording a second time (only 3 transcriptions for 3 questions)');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ finish / next */
  if (want('finish')) await guard('finish', async () => {
    T.section('Finish 409 need_more / 500, Next 500');
    const w = await world(); w.name = 'finish'; const { page, mock } = w;
    await toInterview(w);
    for (let i = 0; i < 3; i++) {
      await H.answerOnce(page);
      if (i < 2) { await page.click('#riNextQ'); await page.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i + 2); await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; }); }
    }
    T.ok(!(await page.evaluate(() => document.getElementById('riFin').disabled)), 'Finish is unlocked');
    mock.faults.next500 = 1;
    await page.click('#riNextQ');
    await H.waitNote(page);
    T.has(await note(page), 'Something went wrong', 'a failing Next -> a plain message');
    T.ok(await H.vis(page, '#riNextQ') && !(await page.evaluate(() => document.getElementById('riNextQ').disabled)), 'and Next is usable again');
    mock.faults.finishNeedMore = 1;
    await page.click('#riFin');
    await page.waitForFunction(() => /Finish interview — 1 more to unlock/.test(document.getElementById('riFin').textContent), null, { timeout: 8000 });
    T.ok(await page.evaluate(() => document.getElementById('riFin').disabled), '409 need_more -> Finish re-locks with the server\'s number');
    T.has(await note(page), 'more real answers', 'and says why');
    await w.close();
    const w2 = await world(); w2.name = 'finish2';
    await toInterview(w2);
    for (let i = 0; i < 3; i++) { await H.answerOnce(w2.page); if (i < 2) { await w2.page.click('#riNextQ'); await w2.page.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i + 2); await w2.page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; }); } }
    w2.mock.faults.finish500 = 1;
    await w2.page.click('#riFin'); await H.waitNote(w2.page);
    T.has(await H.noteText(w2.page), 'Something went wrong', 'a failing Finish -> a plain message');
    await w2.page.click('#riFin'); await H.waitView(w2.page, 'report', 15000);
    T.ok(true, 'and Finish works on the next tap');
    await w2.close();
  });

  /* ------------------------------------------------------------------------------------------ interruptions */
  if (want('interrupt')) await guard('interrupt', async () => {
    T.section('interruptions while recording keep the take (Back, tab hidden, mic taken, leaving the screen)');
    const w = await world(); w.name = 'interrupt'; const { page, mock, env } = w;
    await toInterview(w);
    const hist0 = await page.evaluate(() => history.length);
    // --- Back
    await page.click('#riMic'); await page.waitForSelector('#riRec');
    T.eq(await page.evaluate(() => history.length), hist0 + 1, 'a sentinel history entry is pushed while recording');
    await H.sleep(1200);
    await page.goBack();
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 10000 });
    T.eq(await page.evaluate(() => location.pathname), '/resume-interview/interview', 'Back during a recording stays on the interview');
    T.has(await H.noteText(page), 'Recorded, but not sent yet', 'and says the take was kept, not sent');
    T.eq(await page.evaluate(() => document.querySelectorAll('#riHeld audio').length), 1, 'with the recording to listen to');
    T.ok(await H.vis(page, '#riSend') && await H.vis(page, '#riRerecord'), 'Send it / Re-record');
    T.eq(mock.answers ? mock.answers.length : 0, 0, 'nothing was sent');
    T.ok(await page.evaluate(() => !window.__streams.at(-1).getAudioTracks().some(t => t.readyState === 'live')), 'the microphone is released');
    await page.click('#riSend');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.eq(mock.answers.length, 1, 'Send it transcribes and sends the kept take');
    // --- a normal Stop pops the sentinel again
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    const h1 = await page.evaluate(() => history.length), idx1 = await page.evaluate(() => history.state);
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(1200); await page.click('#riStop');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    await page.waitForTimeout(400);
    T.eq(await page.evaluate(() => location.pathname), '/resume-interview/interview', 'after a normal Stop we are still on the interview');
    T.ok(!(await page.evaluate(() => !!(history.state && history.state.riRec))), 'and the sentinel entry is gone');
    // --- tab hidden
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 3/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(900);
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { get: () => true, configurable: true }); document.dispatchEvent(new Event('visibilitychange')); });
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 8000 });
    T.has(await H.noteText(page), 'switched away', 'a hidden tab stops and keeps the take');
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { get: () => false, configurable: true }); });
    await page.click('#riRerecord');
    // --- microphone taken by a phone call
    await page.waitForSelector('#riRec'); await H.sleep(700);
    await page.evaluate(() => { window.__streams.at(-1).getAudioTracks()[0].dispatchEvent(new Event('mute')); });
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 8000 });
    T.has(await H.noteText(page), 'interrupted', 'a muted track (call, other app) stops and keeps the take');
    // --- leaving the screen while a take is held, then coming back from the hub
    await page.click('.btab[data-tab="home"]'); await page.waitForTimeout(400);
    T.eq(await H.onScreen(page), 'home', 'left for Home');
    // (the Home card is in #moreHome, which the existing goHome() hides for the rest of the page's life - so come back through the Practice tab's entry)
    await page.click('.btab[data-tab="practice"]'); await page.click('#riEntry'); await H.waitView(page, 'hub');
    await page.click('#riContinue'); await H.waitView(page, 'interview');
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 10000 });
    T.ok(true, 'the held take is still there after leaving and coming back');
    // --- leaving WHILE recording keeps it
    await page.click('#riRerecord'); await page.waitForSelector('#riRec'); await H.sleep(800);
    await page.click('.btab[data-tab="home"]'); await page.waitForTimeout(500);
    T.ok(await page.evaluate(() => !window.__streams.at(-1).getAudioTracks().some(t => t.readyState === 'live')), 'leaving the screen releases the microphone');
    await page.click('.btab[data-tab="practice"]'); await page.click('#riEntry'); await H.waitView(page, 'hub'); await page.click('#riContinue'); await H.waitView(page, 'interview');
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 10000 });
    T.ok(true, 'and the take that was being recorded is kept (not discarded)');
    // --- reload mid-held-take: the take survives in IndexedDB
    await page.reload(); await page.waitForSelector('#home.on, #ri.on');
    await H.waitView(page, 'interview', 15000);
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 10000 });
    T.ok(true, 'a full reload: the take is recovered from IndexedDB');
    await page.click('#riSend'); await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.ok(true, 'and can still be sent');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ deep links */
  if (want('links')) await guard('links', async () => {
    T.section('deep links and reload');
    const w = await world(); w.name = 'links'; const { page, mock } = w;
    await H.toMatch(page, w.env);
    await page.reload(); await H.waitView(page, 'match', 15000); await page.waitForSelector('#riHero');
    T.ok(true, 'reload on /resume-interview/match restores the session from the server');
    await H.startInterview(page);
    await page.reload(); await H.waitView(page, 'interview', 15000); await page.waitForSelector('#riQText');
    T.has(await H.txt(page, '#riQ'), 'Question 1', 'reload on the interview restores the open question');
    T.eq(await page.evaluate(() => location.pathname), '/resume-interview/interview', 'URL unchanged');
    // direct load of a sub-path on a clean browser: restores the active session
    const ctx2 = await H.newCtx(browser, w.env, { viewport: { width: 390, height: 844 } });
    const p2 = await H.boot(ctx2, w.env, '/resume-interview/interview');
    await H.waitView(p2, 'interview', 15000); await p2.waitForSelector('#riQText');
    T.ok(true, 'a direct load of /resume-interview/interview on another browser restores the active session');
    await p2.close();
    const p3 = await H.boot(ctx2, w.env, '/resume-interview/job');
    await H.waitView(p3, 'resume', 15000);
    T.ok(true, '/resume-interview/job with no wizard state falls back to the resume step');
    await p3.close();
    // no active session at all: /match and /report fall back to the hub
    w.mock.sessions.length = 0;
    const p4 = await H.boot(ctx2, w.env, '/resume-interview/report');
    await H.waitView(p4, 'hub', 15000);
    T.ok(true, '/resume-interview/report with nothing to show falls back to the hub');
    await p4.close();
    const p5 = await H.boot(ctx2, w.env, '/resume-interview/match');
    await H.waitView(p5, 'hub', 15000);
    T.ok(true, '/resume-interview/match with no session falls back to the hub');
    await p5.close();
    await ctx2.close();
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ delete */
  if (want('delete')) await guard('delete', async () => {
    T.section('delete a session, delete everything');
    const w = await world(); w.name = 'delete'; const { page, mock } = w;
    await toInterview(w);
    await H.answerOnce(page);
    const n = await page.evaluate(async () => (await new Promise(r => { const q = indexedDB.open('dusu-interview'); q.onsuccess = () => { const t = q.result.transaction('takes'); const c = t.objectStore('takes').count(); c.onsuccess = () => r(c.result); }; })));
    T.eq(n, 1, 'one recording is on this phone');
    await page.click('#riBack'); await H.waitView(page, 'hub'); await page.waitForSelector('#riSessions .ri-row');
    await page.click('#riSessions .ri-ib.del');
    await page.waitForFunction(() => !document.querySelector('#riSessions .ri-row'));
    T.ok(page.__dialogs.some(x => /Delete this interview/.test(x)), 'deleting an interview asks first');
    const n2 = await page.evaluate(async () => (await new Promise(r => { const q = indexedDB.open('dusu-interview'); q.onsuccess = () => { const t = q.result.transaction('takes'); const c = t.objectStore('takes').count(); c.onsuccess = () => r(c.result); }; })));
    T.eq(n2, 0, 'and its recordings are removed from this phone');
    // delete everything
    await page.click('#riNew'); await H.waitView(page, 'resume'); await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre');
    await page.click('#riBack'); await H.waitView(page, 'hub');
    await page.click('#riGear'); await H.waitView(page, 'settings'); await page.waitForSelector('#riDelAll');
    await page.click('#riDelAll');
    await H.waitView(page, 'hub'); await page.waitForSelector('#riNew');
    const da = mock.calls.find(c => c.path === '/rinterview/delete-all');
    T.eq(da.body, { confirm: true }, 'POST /delete-all {confirm:true}');
    T.has(await H.noteText(page), 'All your Resume Interview data was deleted', 'a confirmation survives the navigation to the hub');
    T.has(await H.txt(page, '#riBody'), 'No saved resumes yet', 'and the hub is empty');
    T.ok(page.__dialogs.some(x => /permanently deletes/.test(x)), 'Delete all asks first');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ library + wizard */
  if (want('library')) await guard('library', async () => {
    T.section('the hub\'s saved resumes / jobs start a new interview with them; Back / Forward through the steps reuses the session');
    const w = await world(); w.name = 'library'; const { page, mock } = w;
    await H.toMatch(page, w.env);                       // creates resume #1, jd #1, session #1 (matched)
    await page.click('#riBack'); await H.waitView(page, 'job');
    T.ok(await H.vis(page, '#riPre'), 'Back from the match lands on the job step with the job text still there');
    const sessions = () => mock.calls.filter(c => c.method === 'POST' && c.path === '/rinterview/sessions').length;
    const analyses = () => mock.calls.filter(c => c.path.endsWith('/analyze')).length;
    await page.click('#riNext');
    await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    T.eq(sessions(), 1, 'Next again with the same resume, job and settings REUSES the session (no second POST /sessions)');
    T.eq(analyses(), 2, 'and analyses it again (the server caches it)');
    await page.click('#riBack'); await H.waitView(page, 'job');
    await page.click('#riType .ri-chip:nth-of-type(2)');                     // HR instead of Mixed: a new session is needed
    await page.click('#riNext'); await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    T.eq(sessions(), 2, 'a changed setting creates a new session');
    T.ok(mock.calls.some(c => c.method === 'DELETE' && /\/sessions\/\d+$/.test(c.path)), 'and the replaced draft is deleted (drafts do not pile up)');
    T.eq(mock.sessions.length, 1, 'the server holds one session');
    // browser Back / Forward through the wizard
    await page.goBack(); await H.waitView(page, 'job'); await page.waitForSelector('#riPre'); T.ok(true, 'browser Back: match -> job (the job text is still there)');
    await page.goForward(); await H.waitView(page, 'match'); await page.waitForSelector('#riHero'); T.ok(true, 'browser Forward: job -> match (the analysis is still there, no re-run)');
    T.eq(analyses(), 3, 'and Back / Forward did not trigger another analysis');
    await page.goBack(); await page.goBack(); await H.waitView(page, 'match'); T.ok(true, 'two Backs land on an earlier visit of the match, never on a blank screen');
    // hub rows
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub'); await page.waitForSelector('#riResumes .ri-main');
    await page.click('#riResumes .ri-main'); await H.waitView(page, 'resume'); await page.waitForSelector('#riPre');
    T.has(await H.txt(page, '#riPre'), '[EMAIL]', 'tapping a saved resume opens it with its kept text previewed');
    T.ok(await H.vis(page, '#riLooks'), 'ready for "Looks right"');
    await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub');
    await page.click('#riJds .ri-main'); await H.waitView(page, 'resume');
    await page.fill('#riResText', M.RESUME_TEXT + '\n- a new version'); await page.click('#riUseText'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    T.has(await H.txt(page, '#riPre'), 'Power BI dashboards', 'a saved job picked in the hub is already loaded on the job step');
    await page.click('text=Use a different file');
    await page.waitForSelector('#riJdText');
    if (process.env.VERBOSE) { await page.screenshot({ path: '/out/dbg-lib.png', animations: 'disabled' }); console.log('BODY:', (await H.bodyText(page)).replace(/\s+/g, ' ').slice(0, 500)); }
    T.ok(await page.isVisible('#ri .ri-card:has-text("Or use one you saved")'), 'the job step lists saved job descriptions');
    await page.click('#ri .ri-card:has-text("Or use one you saved") .btn');
    await page.waitForSelector('#riPre');
    T.ok(true, 'and one can be used with a tap');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ report extras */
  if (want('report')) await guard('report', async () => {
    T.section('report: an answer left without feedback -> the note; a previous interview on the same job -> the comparison');
    const w = await world(); w.name = 'report'; const { page, mock } = w;
    await toInterview(w);
    mock.sessions[0].prevFinished = 77;
    await H.answerOnce(page);
    for (let i = 0; i < 2; i++) {
      await page.click('#riNextQ'); await page.waitForFunction(n => new RegExp('Question ' + n).test(document.getElementById('riQ').textContent), i + 2);
      await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
      if (i === 1) mock.faults.feedback502 = 1;
      await tapRecord(page);
      await page.waitForSelector(i === 1 ? '#riFbFail' : '#riFbCard', { state: 'visible', timeout: 20000 });
    }
    await page.click('#riFin'); await H.waitView(page, 'report', 15000); await page.waitForSelector('#riRepHero');
    T.has(await H.txt(page, '#riPartial'), 'Some answers have no written feedback', 'partial:true -> "some answers have no written feedback"');
    T.has(await H.txt(page, '#riDelta'), 'Compared with your last interview for this job', 'delta -> the comparison card');
    T.has(await H.txt(page, '#riDelta'), 'Language: better by 7', 'a significant change is called a change');
    T.has(await H.txt(page, '#riDelta'), 'Delivery: about the same', 'a change inside the noise is called "about the same"');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ limits (fake clock) */
  if (want('limits')) await guard('limits', async () => {
    T.section('3:00 limit: the "wrap up" line at 2:30 and the automatic stop at 3:00');
    const w = await world(); w.name = 'limits'; const { page, mock } = w;
    await toInterview(w);
    await page.clock.install();
    await page.click('#riMic'); await page.waitForSelector('#riRec');
    await page.clock.runFor(60000);
    T.has(await H.txt(page, '#riRecHint'), 'Most answers run 1 to 2 minutes', 'after 10 s the guidance says how long answers usually run');
    await page.clock.runFor(91000);
    T.has(await H.txt(page, '#riTimer'), '2:31', 'the timer reads 2:31');
    T.has(await H.txt(page, '#riRecHint'), 'Time to wrap up', 'at 2:30 the line says to wrap up');
    T.ok(await page.evaluate(() => document.getElementById('riTimer').classList.contains('over')), 'and the timer changes (amber + the words, never colour only)');
    await page.clock.runFor(30000);
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.eq(mock.answers.length, 1, 'at 3:00 the recording stopped by itself and the answer was sent');
    T.ok(mock.answers[0].body.duration_sec > 0, 'with a duration');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ recorder failures */
  if (want('recorder')) await guard('recorder', async () => {
    T.section('a track that ends and a recorder that errors keep the take');
    const w = await world(); w.name = 'recorder'; const { page } = w;
    await toInterview(w);
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(900);
    await page.evaluate(() => { window.__streams.at(-1).getAudioTracks()[0].dispatchEvent(new Event('ended')); });
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 8000 });
    T.has(await H.noteText(page), 'interrupted', 'a track "ended" stops and keeps the take');
    await page.click('#riRerecord'); await page.waitForSelector('#riRec'); await H.sleep(900);
    await page.evaluate(() => { const m = window.__mrs.at(-1); m.onerror && m.onerror(new Event('error')); });
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 8000 });
    T.has(await H.noteText(page), 'hit a problem', 'a MediaRecorder error stops and keeps the take');
    await page.click('#riSend');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.ok(true, 'and the kept take can be sent');
    await w.close();
  });

  /* ------------------------------------------------------------------------------------------ storage */
  if (want('storage')) await guard('storage', async () => {
    T.section('storage: persist() is requested; without IndexedDB (private mode) the interview still works from memory');
    const w = await world({ init: () => { navigator.storage.persist = () => { window.__persist = (window.__persist || 0) + 1; return Promise.resolve(true); }; } }); w.name = 'storage'; const { page } = w;
    await toInterview(w);
    await H.answerOnce(page);
    T.ok((await page.evaluate(() => window.__persist || 0)) >= 1, 'navigator.storage.persist() was requested when recording started');
    await w.close();
    const w2 = await world({ init: () => { const real = indexedDB; Object.defineProperty(window, 'indexedDB', { value: { open() { throw new DOMException('denied', 'SecurityError'); }, deleteDatabase() { throw new Error('x'); } }, configurable: true }); } }); w2.name = 'no-idb';
    await toInterview(w2);
    await H.answerOnce(w2.page);
    T.eq(await w2.page.evaluate(() => document.querySelectorAll('#riListen audio').length), 1, 'with no IndexedDB the answer is still sent and its recording can still be played (kept in memory)');
    await w2.page.click('#riNextQ'); await w2.page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
    T.ok(true, 'and the interview carries on');
    await w2.close();
  });

  /* ------------------------------------------------------------------------------------------ draft / caps / keys gate / older / recover */
  const mkSession = (id, status) => ({ id, title: 'Role ' + id + ' · Acme', status, settings: { type: 'mixed', level: 'fresher', feedback_lang: 'en' }, resume_id: null, jd_id: null, overall: status === 'finished' ? 60 : null,
    created_at: new Date(Date.now() - (100000 - id) * 1000).toISOString(), started_at: new Date(Date.now() - (100000 - id) * 1000).toISOString(), finished_at: status === 'finished' ? new Date(Date.now() - (100000 - id) * 1000 + 600e3).toISOString() : null,
    analysis: null, turns: [], queue: [], rev: 1, picked: [] });

  if (want('draft')) await guard('draft', async () => {
    T.section('a session that was created but never analysed');
    const w = await world(); w.name = 'draft'; const { page, mock } = w;
    mock.storeDoc('resume', M.RESUME_TEXT, { title: 'My resume', source: 'paste' });
    mock.storeDoc('jd', M.JD_TEXT, { title: 'Data Analyst', source: 'paste' });
    const [r, j] = mock.docs;
    mock.handle({ method: 'POST', path: '/rinterview/sessions', query: new URLSearchParams(), headers: {}, json: { resume_id: r.id, jd_id: j.id, settings: { type: 'mixed', level: 'fresher', feedback_lang: 'en' } } });
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub');
    await page.waitForSelector('#riContinue');
    T.has(await H.txt(page, '#riBody'), 'Not started', 'a never-analysed session is labelled "Not started"');
    await page.click('#riContinue'); await H.waitView(page, 'match');
    await page.waitForSelector('#riAnalyse');
    T.has(await H.txt(page, '#riBody'), "match isn't ready yet", 'the match step says so');
    await page.click('#riAnalyse');
    await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    T.ok(true, '"Analyse now" runs the analysis and shows the match');
    await w.close();
  });

  if (want('caps')) await guard('caps', async () => {
    T.section('limits: the daily interview cap, too many documents, too many interviews, the daily limit');
    const w = await world(); w.name = 'caps'; const { page, mock } = w;
    for (let i = 0; i < 10; i++) mock.sessions.push(mkSession(3000 + i, 'finished'));
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub'); await page.waitForSelector('#riSessions .ri-row');
    await page.click('#riNew');
    await H.waitNote(page);
    T.has(await H.noteText(page), 'most interviews allowed for today', 'at the daily cap, New interview says so instead of starting');
    T.eq(await H.view(page), 'hub', 'and stays on the hub');
    await w.close();

    const w2 = await world(); w2.name = 'caps2'; const p2 = w2.page;
    for (let i = 0; i < 10; i++) w2.mock.storeDoc('resume', M.RESUME_TEXT + '\n- v' + i, { title: 'R' + i, source: 'paste' });
    await p2.evaluate(() => navTo('/resume-interview')); await H.waitView(p2, 'hub');
    await p2.click('#riNew'); await H.waitView(p2, 'resume');
    await p2.fill('#riResText', M.RESUME_TEXT + '\n- one too many'); await p2.click('#riUseText'); await H.waitNote(p2);
    T.has(await H.noteText(p2), 'too many saved documents', '409 limit_documents -> delete one first');
    await w2.close();

    const w3 = await world(); w3.name = 'caps3'; const p3 = w3.page;
    await H.toMatch(p3, w3.env);
    await p3.click('#riBack'); await H.waitView(p3, 'job');
    await p3.click('#riType .ri-chip:nth-of-type(3)');                  // a new setting -> a new session is needed
    w3.mock.faults.limitSessions = 1;
    await p3.click('#riNext'); await H.waitNote(p3);
    T.has(await H.noteText(p3), 'too many saved interviews', '409 limit_sessions -> delete one first');
    w3.mock.faults.limitSessions = 0; w3.mock.faults.dailyLimit = 1;
    await p3.click('#riNext'); await H.waitNote(p3);
    T.has(await H.noteText(p3), "today's limit", '429 daily_limit -> come back tomorrow');
    await w3.close();
  });

  if (want('keysgate')) await guard('keysgate', async () => {
    T.section('the keys gate: an account that must bring its own keys is sent to the keys screen, not to a call that will fail');
    const w = await world(); w.name = 'keysgate'; const { page, mock } = w;
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.fill('#riJdText', M.JD_TEXT);
    await page.evaluate(() => { userState.office = true; localStorage.removeItem('dusu_keys_ok'); });     // the verified keys are gone
    const before = mock.calls.length;
    await page.click('#riNext'); await page.waitForTimeout(500);
    T.eq(await H.onScreen(page), 'keys', 'Next opens the keys screen');
    T.eq(mock.calls.length, before, 'and sends nothing');
    await w.close();
  });

  if (want('older')) await guard('older', async () => {
    T.section('history beyond the newest 30 interviews');
    const w = await world(); w.name = 'older'; const { page, mock } = w;
    for (let i = 1; i <= 35; i++) mock.sessions.push(mkSession(4000 + i, 'finished'));
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub'); await page.waitForSelector('#riSessions .ri-row');
    T.eq(await page.evaluate(() => document.querySelectorAll('#riSessions .ri-row').length), 30, 'the hub lists the newest 30');
    T.ok(await H.vis(page, '#riOlder'), 'and offers "Show older interviews"');
    await page.click('#riOlder');
    await page.waitForFunction(() => document.querySelectorAll('#riSessions .ri-row').length === 35);
    T.ok(!(await H.vis(page, '#riOlder')), 'the older ones are appended, and the button goes away when there are no more');
    T.ok(await page.evaluate(() => { const r = [...document.querySelectorAll('#riSessions .ri-row .ri-main')]; return r.indexOf(document.activeElement) === 30; }), 'keyboard focus moves to the first new row (the button that was pressed is gone)');
    await page.waitForFunction(() => /Older interviews were added/.test(document.getElementById('riLive').textContent));
    T.ok(true, 'and a screen reader is told');
    const q = mock.calls.find(c => c.method === 'GET' && c.path === '/rinterview/sessions');
    T.ok(q && /before=\d+/.test(q.query) && /limit=30/.test(q.query), 'GET /sessions?before=<last id>&limit=30: ' + (q && q.query));
    await w.close();
  });

  if (want('recover')) await guard('recover', async () => {
    T.section('the app is killed in the middle of a recording: the 10-second chunks saved to disk rebuild the take');
    const w = await world(); w.name = 'recover'; const { page, mock } = w;
    await toInterview(w);
    await page.click('#riMic'); await page.waitForSelector('#riRec');
    T.ok(await page.evaluate(() => document.getElementById('riHear').disabled), '"Hear again" is disabled while recording (the question must never be in the take)');
    await H.sleep(10900);
    const chunks = await page.evaluate(() => new Promise(r => { const q = indexedDB.open('dusu-interview'); q.onsuccess = () => { const c = q.result.transaction('chunks').objectStore('chunks').count(); c.onsuccess = () => { q.result.close(); r(c.result); }; }; }));
    T.ok(chunks >= 1, 'a 10-second chunk is already on disk (' + chunks + ')');
    await page.reload();                                               // the tab dies mid-recording: no stop, no onstop
    await H.waitView(page, 'interview', 15000);
    await page.waitForSelector('#riHeld', { state: 'visible', timeout: 10000 });
    T.has(await H.noteText(page), 'closed while you were recording', 'the take is rebuilt from the chunks and the learner is told what happened');
    await page.click('#riSend');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.eq(mock.answers.length, 1, 'and the recovered take can be sent');
    await w.close();
  });

  if (want('slowans')) await guard('slowans', async () => {
    T.section('an answer that takes long to analyse: the dock says what is happening, then "Still working" after 15 seconds, then the feedback arrives');
    const w = await world(); w.name = 'slowans'; const { page, mock } = w;
    await toInterview(w);
    mock.delays.answer = 18000;
    await tapRecord(page);
    await page.waitForFunction(() => /reading your answer/.test((document.getElementById('riWork') || {}).textContent || ''), null, { timeout: 10000 });
    T.ok(true, 'while it waits, the dock (always on screen) says DuSu is reading the answer');
    await page.waitForFunction(() => /Still working/.test((document.getElementById('riWork') || {}).textContent || ''), null, { timeout: 19000 });
    T.ok(true, 'after 15 s it says it is still working');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    T.ok(true, 'and the feedback still arrives');
    await w.close();
  });

  if (want('stuck')) await guard('stuck', async () => {
    T.section('feedback the server keeps "pending" for over a minute: the page stops waiting and offers Retry (it never polls forever)');
    const w = await world(); w.name = 'stuck'; const { page, mock } = w;
    await toInterview(w);
    const s = mock.sessions.at(-1), t = s.turns.at(-1);
    // the answer was saved (say, from another phone) but its feedback is "still being written" - and never finishes
    Object.assign(t, { status: 'answered', answer: 'I led a small team and we cut the weekly reporting time in half by automating the dashboards.', answer_words: 25, answer_sec: 14, real: true,
      feedback_state: 'pending', pendingPolls: 1e9, feedback: null, answer_key: 'other-phone', answered_at: new Date().toISOString() });
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub');
    await page.clock.install();
    await page.click('#riContinue');
    await page.waitForSelector('#riPending', { state: 'visible' });
    T.ok(true, 'the saved answer with pending feedback shows the waiting card');
    const polls = () => mock.calls.filter(c => c.method === 'GET' && /\/sessions\/\d+\/turns\/\d+$/.test(c.path)).length;
    let ticks = 0;
    while (ticks < 90 && !(await page.isVisible('#riRetryFb'))) { await page.clock.runFor(2000); ticks++; await H.sleep(60); }
    T.ok(await page.isVisible('#riRetryFb'), 'after the 75 s of polling the waiting card gives way to a Retry card (' + ticks + ' ticks of 2 s)');
    T.ok(ticks >= 36 && ticks <= 60, 'and not before: it kept polling for about 75 s (' + ticks * 2 + ' s)');
    const n = polls();
    T.ok(n >= 25 && n <= 45, 'one poll every ~2 s, not a flood (' + n + ' polls)');
    await page.clock.runFor(30000); await H.sleep(300);
    T.eq(polls(), n, 'and it stopped polling once it gave up');
    T.eq(await page.isVisible('#riPending'), false, 'the spinner is gone');
    await page.click('#riRetryFb');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 15000 });
    T.ok(true, 'Retry fetches the feedback');
    await w.close();
  });

  if (want('paused')) await guard('paused', async () => {
    T.section('an account the owner has paused (403): a plain sentence of our own, never the server text');
    const w = await world(); w.name = 'paused'; const { page, mock } = w;
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.fill('#riJdText', M.JD_TEXT);
    mock.faults.status403 = 1;
    await page.click('#riNext');
    await page.waitForSelector('#riJobErr', { timeout: 15000 });
    const n = await H.txt(page, '#riJobErr');
    T.has(n, 'access is paused', '403 -> "your access is paused" and who to ask');
    T.ok(!/admin|detail|Traceback/i.test(n), 'the server\'s own sentence is not shown');
    await page.click('#riRetryJob');
    await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    T.ok(true, 'and once access is back the same button carries on');
    await w.close();
  });

  await browser.close();
  T.eq(errors, [], 'no console errors / page errors / unhandled rejections in any scenario');
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
