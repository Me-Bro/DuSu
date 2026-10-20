'use strict';
/*
 * The SPECIAL states, laid out and photographed at 360x640 and 1280x800 (same audit as looks.spec.cjs: no overflow, tap targets >= 44px, the dock on screen and above the nav):
 *   hub with a Continue card · saved-library rows · resume with warnings / duplicate note / upload error (inline) · job with a "too vague" error
 *   · match: unscored (fewer than 4 requirements), low match, after a re-upload (comparison)
 *   · interview: a take held after Back, "working" (transcribing / analysing), an error note with buttons, too short, Finish unlocked, the question being read aloud
 *   · report with a partial note + a comparison · owner dashboard row · feedback with a failed-feedback card
 * Screenshots: $OUT/ri2-<viewport>-<state>.png
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const M = require('./mock.cjs');
const path = require('path');

const OUT = process.env.OUT || '/out';
const VPS = [{ name: '360x640', w: 360, h: 640 }, { name: '1280x800', w: 1280, h: 800 }];
const shot = async (page, vp, name) => { await page.waitForTimeout(250); await page.screenshot({ path: path.join(OUT, `ri2-${vp}-${name}.png`), animations: 'disabled' }); };
const scrollEnd = page => page.evaluate(() => { const w = document.querySelector('.wrap'); w.scrollTop = w.scrollHeight; });
const scrollTop = page => page.evaluate(() => { const w = document.querySelector('.wrap'); w.scrollTop = 0; });
const fillJd = async (page, text) => { if (!(await page.$('#riJdText'))) await page.click('text=Use a different file'); await page.waitForSelector('#riJdText'); await page.fill('#riJdText', text); };
const ready = page => page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; }, null, { timeout: 12000 });

(async () => {
  const T = H.makeT('looks (special states)');
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  for (const v of VPS) {
    T.section(v.name);
    const env = await H.newEnv({ mock: { limits: { min_answer_sec: 2 } } });
    const mock = env.mock;
    const ctx = await H.newCtx(browser, env, { viewport: { width: v.w, height: v.h }, mobile: v.w < 800 });
    const page = await H.boot(ctx, env, '/'); page.setDefaultTimeout(15000);
    const L = label => H.layout(page, label, T, v.name);
    const S = async (name, label) => { await shot(page, v.name, name); await L(label || name); };

    await H.toHub(page);
    // --- resume step: a failed upload (inline note at the top), warnings, duplicate
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await page.setInputFiles('#riResFile', { name: 'scan.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-SCAN') });
    await H.waitNote(page); await S('01-resume-upload-error', 'resume: upload error (inline)');
    mock.faults.warn = 1;
    await page.setInputFiles('#riResFile', { name: 'ok.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_TEXT) });
    await page.waitForSelector('#riPre'); await S('02-resume-warning', 'resume: preview with a warning');
    await page.click('#riLooks'); await H.waitView(page, 'job');
    // --- job: too vague
    await page.fill('#riJdText', M.JD_TEXT); mock.faults.jdVague = 1;
    await page.click('#riNext'); await page.waitForSelector('#riJobErr', { timeout: 15000 }); await S('03-job-vague-error', 'job: "too vague" error card');
    await page.click('text=Back to the job'); await H.waitView(page, 'job');
    // --- match: unscored (3 requirements)
    await fillJd(page, 'Data Analyst - Acme Corp\nWe need an analyst who can own weekly reporting for the sales team and explain it clearly.\nRequirements\n- SQL\n- Excel\n- Communication');
    await page.click('#riNext'); try { await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 }); } catch (e) { console.log(mock.calls.slice(-9).map(c => c.method + ' ' + c.path + ' ' + JSON.stringify(c.body || '').slice(0, 60)).join('\n')); console.log('faults', JSON.stringify(mock.faults)); console.log('STUCK: view=' + await H.view(page) + ' body=' + (await H.bodyText(page)).slice(0, 300) + ' note=' + await H.noteText(page)); await page.screenshot({ path: '/out/dbg-stuck.png', animations: 'disabled' }); throw e; }
    T.has(await H.txt(page, '#riHero'), 'Not scored', 'fewer than 4 requirements -> "Not scored"');
    await S('04-match-unscored', 'match: unscored');
    // --- match: low match
    await page.click('#riBack'); await H.waitView(page, 'job');
    await fillJd(page, 'Mainframe Engineer - Initech\nWe maintain a large mainframe estate and need someone deep in legacy platforms and batch scheduling.\nRequirements\n- COBOL mainframes\n- SAP ABAP\n- Kubernetes operators\n- Rust systems programming');
    await page.click('#riNext'); await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    await page.waitForSelector('#riLow'); await S('05-match-low', 'match: low match message');
    await scrollEnd(page); await S('05b-match-low-end', 'match: low match (end)');

    // --- a fresh, normal interview for the interview states
    await page.click('#riBack'); await H.waitView(page, 'job');
    await fillJd(page, M.JD_TEXT + '\n- Documentation'); await page.click('#riNext'); await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    await H.startInterview(page);
    mock.limits.min_answer_sec = 2;
    await page.evaluate(() => { window.__ttsMs = 2600; });
    await page.click('#riHear'); await page.waitForTimeout(300); await S('06-interview-speaking', 'interview: the question is being read aloud');
    await page.evaluate(() => { window.__ttsMs = 80; });
    await ready(page);
    // held take after Back
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(1500);
    await page.goBack(); await page.waitForSelector('#riHeld'); await scrollTop(page); await S('07-interview-held', 'interview: a take kept after Back');
    await page.click('#riSend');
    env.groq.queue.push({ delay: 2500, text: M.TRANSCRIPT_GOOD, dur: 24 });
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    // working (transcribing)
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent)); await ready(page);
    env.groq.queue.push({ delay: 3500, text: M.TRANSCRIPT_GOOD, dur: 24 });
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(1500); await page.click('#riStop');
    await page.waitForSelector('#riWork'); await S('08-interview-transcribing', 'interview: transcribing');
    mock.delays.answer = 3500;
    await page.waitForFunction(() => /reading your answer/.test((document.getElementById('riWork') || { textContent: '' }).textContent), null, { timeout: 15000 });
    await S('09-interview-analysing', 'interview: analysing');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 }); mock.delays.answer = 0;
    // failed feedback card
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 3/.test(document.getElementById('riQ').textContent)); await ready(page);
    mock.faults.feedback502 = 1;
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(1500); await page.click('#riStop');
    await page.waitForSelector('#riFbFail', { state: 'visible', timeout: 20000 }); await scrollTop(page); await S('10-interview-feedback-failed', 'interview: feedback failed (answer saved)');
    await page.click('#riRetryFb'); await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    // error note with buttons: Groq rejects the key
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 4/.test(document.getElementById('riQ').textContent)); await ready(page);
    env.groq.queue.push({ status: 401 });
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(1500); await page.click('#riStop');
    await page.waitForFunction(() => /Groq key was rejected/.test(document.getElementById('riNote').textContent), null, { timeout: 15000 });
    await S('11-interview-error-note', 'interview: an error note with its buttons');
    // too short
    await page.click('#riRerecord'); await page.waitForSelector('#riRec');
    env.groq.queue.push({ text: 'I built one dashboard once and it was fine for the sales team.', dur: 12 });
    await H.sleep(1500); await page.click('#riStop');
    await page.waitForFunction(() => /too short/i.test(document.getElementById('riNote').textContent), null, { timeout: 15000 });
    await S('12-interview-too-short', 'interview: too short');
    // answer properly, 3 counted -> Finish
    await page.click('#riAgain'); await page.waitForSelector('#riRec'); await H.sleep(1500); await page.click('#riStop');
    await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
    await scrollTop(page); await S('13-interview-finish-unlocked', 'interview: Finish unlocked');
    mock.sessions[mock.sessions.length - 1].prevFinished = 41;
    await page.click('#riFin'); await H.waitView(page, 'report', 15000); await page.waitForSelector('#riPartial', { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(1300);
    await scrollTop(page); await S('14-report', 'report');
    await page.evaluate(() => { const e = document.getElementById('riDelta'); if (e) e.scrollIntoView({ block: 'start' }); }); await S('15-report-delta', 'report: delta');
    // hub with a Continue card: start another interview and leave it open
    await page.click('#riNewJob'); await H.waitView(page, 'resume'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    await fillJd(page, M.JD_TEXT + '\n- Reporting'); await page.click('#riNext'); await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
    await H.startInterview(page);
    await page.click('#riBack'); await H.waitView(page, 'hub'); await page.waitForSelector('#riContinue'); await scrollTop(page); await S('16-hub-continue', 'hub: Continue card + history');
    await scrollEnd(page); await S('16b-hub-continue-end', 'hub: Continue card (end)');
    // a history longer than one page: the newest 30 and "Show older interviews", then the rest
    const mk = id => ({ id, title: 'Role ' + id + ' - Acme', status: 'finished', settings: { type: 'mixed', level: 'fresher', feedback_lang: 'en' }, resume_id: null, jd_id: null, overall: 55 + (id % 30),
      created_at: new Date(Date.now() - (9e5 - id) * 1000).toISOString(), started_at: new Date(Date.now() - (9e5 - id) * 1000).toISOString(), finished_at: new Date(Date.now() - (9e5 - id) * 1000 + 600e3).toISOString(),
      analysis: null, turns: [], queue: [], rev: 1, picked: [] });
    for (let i = 1; i <= 34; i++) mock.sessions.push(mk(5000 + i));
    await page.reload(); await H.waitView(page, 'hub'); await page.waitForSelector('#riSessions .ri-row'); await page.waitForSelector('#riOlder');
    await page.evaluate(() => document.getElementById('riOlder').scrollIntoView({ block: 'center' })); await S('17-hub-older', 'hub: the newest 30 and "Show older interviews"');
    await page.click('#riOlder');
    await page.waitForFunction(() => document.querySelectorAll('#riSessions .ri-row').length > 30);
    await page.evaluate(() => { const r = document.querySelectorAll('#riSessions .ri-row'); r[r.length - 1].scrollIntoView({ block: 'center' }); }); await S('17b-hub-older-all', 'hub: the older interviews were added to the list');
    T.eq(page.__consoleErrors, [], v.name + ': no console errors');
    await ctx.close(); await env.server.close();
  }
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
