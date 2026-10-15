'use strict';
/*
 * The build the project's visual-verification recipe uses: __AUTH_ENABLED__ -> false (no Google sign-in; initAuth() just shows Home), a FAKE userState seeded by
 * the test (resume_interview + ri_server_stt + onboarded), and every /rinterview call mocked. Proves the module also runs without /me ever being fetched.
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');

(async () => {
  const T = H.makeT('smoke (AUTH_ENABLED=false, seeded userState)');
  const env = await H.newEnv({ auth: false, mock: { limits: { min_answer_sec: 2 } } });
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const ctx = await H.newCtx(browser, env, { viewport: { width: 390, height: 844 } });
  const page = await H.boot(ctx, env, '/'); page.setDefaultTimeout(15000);
  await page.waitForSelector('#home.on'); await page.waitForTimeout(500);
  T.ok(await page.evaluate(() => typeof userState === 'object' && (userState === null || !userState.resume_interview)), 'no /me was fetched: userState starts empty');
  T.ok(await page.evaluate(() => document.getElementById('riHomeCard').hidden), 'so the Home card is hidden');
  await page.evaluate(() => { userState = { onboarded: true, resume_interview: true, ri_server_stt: true, office: false, role: 'user', progress: { journey: {} } }; RI.syncEntries(); });
  await H.toHub(page);
  T.eq(await page.evaluate(() => location.pathname), '/resume-interview', 'hub');
  await H.toMatch(page, env, { viaFile: true });
  T.ok(await H.vis(page, '#riHero'), 'match');
  await H.startInterview(page);
  await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
  await H.answerOnce(page);
  T.has(await H.txt(page, '#riFbCard'), 'What DuSu heard', 'feedback');
  T.eq(env.groq.calls.length, 1, 'transcribed with the key from localStorage');
  const r = await H.collectErrors(page);
  T.eq(page.__consoleErrors.concat(r.errors, r.rejections), [], 'no errors');
  await browser.close(); await env.server.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
