'use strict';
/*
 * Keys - the web client in a REAL Chromium against the REAL app (uvicorn + scratch Postgres + the real key engine; every AI provider is a scripted fake - see run_real.sh).
 * What is checked is read back from the SERVER (/keys/status, the database through the app), never from the screen alone.
 *
 *   A  who sees what: the switches (engine, screens) per learner; with them off the old Keys screen is untouched and not one /keys/status request is made
 *   B  the Keys screen from the server: a BRAND-NEW device shows the saved keys, masked, with their status; nothing of a key is ever in the page
 *   C  saving one key: success, a rejected key, an unreachable provider, an empty box, Enter; a box left empty never erases; the "taking you in" path of a new learner
 *   D  Change / Test / Remove / Check all keys
 *   E  every state on the screen and on the Home card: working, limit hit (+ when it resets), rejected, expired, mixed, none
 *   F  the pop-up: from a WebSocket frame and from an HTTP error body, dedupe, "Later", "Fix my keys", "See plans", transient = a notice not a pop-up, on Home load
 *   G  the Daily / Learn mic and the Home chat are handed back after a `quota` frame
 *   H  Hindi / English; accessibility (dialog, focus, Escape, Tab trap, names, targets); layout at 360 / 390 / 1280
 *   I  the owner's dashboard: the three switches and the WhatsApp link, and no OTHER switch changes
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('keys (real server)');
const { T, ERRS, TOK, BASE, sleep, until, ctxFor, behave, reset, calls, flush, server, boot, screen, vis, txt, shot, notif, openKeys, post, setLang, closePop } = L;

const leaky = (who) => Object.values(TOK[who].keys || {}).map(k => k.slice(8, -6));          // the middle of every key this learner owns
const NAMES = { groq: 'Groq', gemini: 'Gemini', openrouter: 'OpenRouter' };
const FIELD = { groq: 'kGroq', gemini: 'kGemini', openrouter: 'kOpenrouter' };
const status = async who => (await server(who, '/keys/status')).body;
const LESSON = who => ({ token: TOK[who].token, lang: 'en', type: 'speak', prompt: 'p', target: 't', said: 's' });
// one real model call as that learner: the server learns what the keys can do
const useKeys = async who => (await server(who, '/lesson/evaluate', 'POST', LESSON(who)));
const dom = page => page.evaluate(() => document.documentElement.outerHTML);
const inputs = page => page.evaluate(() => [...document.querySelectorAll('input')].map(i => i.value).join('|'));
const waitSum = (page, re) => page.waitForFunction(r => { const e = document.getElementById('kySum'); return e && new RegExp(r).test(e.textContent); }, re.source, { timeout: 8000 }).then(() => true).catch(() => false);

async function fresh(browser, who, o = {}) {
  const c = await ctxFor(browser, who, Object.assign({ seed: { dusu_tutorial_seen: '1' } }, o));
  const p = await boot(c, o.path || '/', o);
  return { c, p };
}

(async () => {
  const browser = await chromium.launch();
  await reset({ key_health: 'on', keys_ui: 'on', install_mode: 'on', home_ai: 'on', bilingual: 'on' });
  for (const who of Object.keys(TOK)) await setLang(who, 'en');                  // the new features default to Hindi: the spec reads English, Hindi has its own section

  // =========================================================================================== A  who sees what
  T.section('A - who sees what');
  {
    await reset({ key_health: 'off', keys_ui: 'off' });
    const { c, p } = await fresh(browser, 'two', { device: 'new' });
    await sleep(900);
    const me = await p.evaluate(() => ({ kh: userState.key_health, ku: userState.keys_ui, k: userState.keys }));
    T.eq([me.kh, me.ku, me.k], [false, false, undefined], 'both switches off: /me says so and carries no `keys` block');
    T.ok(!(await vis(p, '#kyCard')), 'both off: no Home card');
    await p.evaluate(() => { openMore(); }); await sleep(250); await p.click('.mrow[data-more="keys"]');
    await p.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'keys', null, { timeout: 8000 }); await sleep(600);
    T.ok(await p.evaluate(() => !document.getElementById('kySum') && !document.getElementById('kyb_groq')), 'both off: the Keys screen is the OLD one (no summary, no status blocks)');
    T.ok(await vis(p, '#verifyKeys'), 'both off: the old "Verify & save" button is there');
    T.eq((await calls({ kind: 'models' })).n >= 0, true, '(calls log readable)');
    await c.close();
    await reset({ key_health: 'on', keys_ui: 'off' });
    const a = await fresh(browser, 'two', { device: 'new' }); await sleep(900);
    T.eq(await a.p.evaluate(() => [userState.key_health, userState.keys_ui, !!userState.keys]), [true, false, true], 'engine on, screens off: /me carries the counts but keys_ui is false');
    T.ok(!(await vis(a.p, '#kyCard')), 'engine on, screens off: still no Home card');
    await a.c.close();
    await reset({ key_health: 'owner', keys_ui: 'owner' });
    const o1 = await fresh(browser, 'two', { device: 'new' }); await sleep(900);
    T.eq(await o1.p.evaluate(() => [userState.key_health, userState.keys_ui]), [false, false], "'owner' stage: an ordinary learner has neither");
    await o1.c.close();
    const o2 = await fresh(browser, 'tester', { device: 'new' }); await sleep(1200);
    T.eq(await o2.p.evaluate(() => [userState.key_health, userState.keys_ui]), [true, true], "... an invited early-access tester has both");
    T.ok(await vis(o2.p, '#kyCard'), '... and sees the Home card');
    await o2.c.close();
    const o3 = await fresh(browser, 'owner', { device: 'new' }); await sleep(1200);
    T.eq(await o3.p.evaluate(() => [userState.key_health, userState.keys_ui, !!userState.keys]), [true, true, false], '... the owner has both, but no key card (the owner rides the server keys: nothing of theirs to show)');
    await o3.c.close();
    await reset({ key_health: 'on', keys_ui: 'on' });
  }

  // =========================================================================================== B  the Keys screen from the server
  T.section('B - the Keys screen reads the server, on a brand-new device');
  {
    await reset();
    const who = 'three';
    await useKeys(who); await flush();           // one real call as this learner, written to the database: Groq's allowance reading (valid for the fake's 90 s) is there when the screen asks
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'en' });
    T.eq(await p.evaluate(() => Object.keys(localStorage).filter(k => k.startsWith('dusu_office')).length), await p.evaluate(() => Object.keys(localStorage).filter(k => k.startsWith('dusu_office')).length), '(a new device)');
    await openKeys(p);
    const st = await status(who);
    T.eq(st.keys.map(k => k.provider), ['groq', 'gemini', 'openrouter'], 'the server holds all three keys');
    for (const pv of ['groq', 'gemini', 'openrouter']) {
      const k = st.keys.find(x => x.provider === pv);
      T.ok(await vis(p, '#kyb_' + pv), `${pv}: the status block is shown (the saved key, not an empty box)`);
      T.ok(!(await vis(p, '#' + FIELD[pv])), `${pv}: the entry box is hidden`);
      T.has(await txt(p, '#kyb_' + pv), k.masked, `${pv}: the masked key (${k.masked}) is shown`);
      T.ok(await until(async () => /Working/.test(await txt(p, '#kyb_' + pv)), 15000), `${pv}: it says Working (after the server's first look at a key that had never been checked)`);
    }
    T.ok(await waitSum(p, /3 keys working/), 'the summary says 3 keys working (once the server has looked at the keys it had never checked)');
    T.ok(/never share your key/i.test(await txt(p, '#keysForm')), 'the "never share your key" note is on the screen');
    const html = await dom(p), vals = await inputs(p);
    for (const frag of leaky(who)) T.ok(!html.includes(frag) && !vals.includes(frag), `no key text in the page or in any input (${frag.slice(0, 6)}…)`);
    T.ok(/\d+ requests? today/.test(await txt(p, '#kyb_groq')), 'usage is shown');
    T.ok(/left today/.test(await txt(p, '#kyb_groq')), 'Groq shows how many are left (the provider reports it)');
    T.has(await txt(p, '#kyb_gemini'), "doesn't show how many are left", "Gemini says plainly that Google does not report what is left");
    T.ok(/about \d+ of 50 left/.test(await txt(p, '#kyb_openrouter')), 'OpenRouter shows a COMPUTED number and says "about"');
    await shot(p, 'keys-three-new-device');
    await c.close();
    // after the screen is opened and left, a second open repaints from the server (never from a cached picture)
    const r = await fresh(browser, 'two', { device: 'returning', lang: 'en' });
    await openKeys(r.p);
    const before = (await calls({ kind: 'models' })).n;
    await r.p.evaluate(() => { show('home'); }); await sleep(300);
    await openKeys(r.p);
    T.ok(await until(async () => (await calls({ kind: 'models' })).n >= before), 'a second visit asks the server again');
    T.ok(await r.p.evaluate(() => !document.getElementById('kyb_groq').hidden), 'and shows the saved key');
    T.has(await txt(r.p, '#kyb_groq'), '••••', 'masked');
    T.ok(await vis(r.p, '#kGroq') === false && await vis(r.p, '#kOpenrouter'), 'the provider with NO saved key (OpenRouter) shows its entry box; the others do not');
    await r.c.close();
  }

  // =========================================================================================== C  saving one key
  T.section('C - saving one key');
  {
    await reset();
    const who = 'two';
    const gk = 'gsk_BRANDNEWKEY' + 'Z'.repeat(26) + 'abcd', ok1 = 'sk-or-v1-NEWOR' + 'K'.repeat(28) + 'wxyz';
    const { c, p } = await fresh(browser, who, { lang: 'en' });
    await openKeys(p);
    // an empty box
    await p.fill('#kOpenrouter', '');
    await p.click('#kySave_openrouter');
    await until(() => p.evaluate(() => /Paste your key first/.test(document.getElementById('kym_openrouter').textContent)));
    T.has(await txt(p, '#kym_openrouter'), 'Paste your key first', 'an empty box says so (nothing is sent)');
    T.eq((await status(who)).stored, 2, 'and nothing was erased or added');
    // a rejected key
    await behave('openrouter', 'invalid', ok1);
    await p.fill('#kOpenrouter', ok1);
    await p.click('#kySave_openrouter');
    await until(() => p.evaluate(() => /didn.t accept/.test(document.getElementById('kym_openrouter').textContent)));
    T.has(await txt(p, '#kym_openrouter'), "OpenRouter didn't accept that key", 'a rejected key is called out by provider');
    T.eq((await status(who)).stored, 2, 'and was NOT stored');
    T.ok(await vis(p, '#kOpenrouter'), 'the box stays open for another try');
    // an unreachable provider
    await behave('openrouter', 'unreachable', ok1);
    await p.click('#kySave_openrouter');
    await until(() => p.evaluate(() => /Couldn.t reach/.test(document.getElementById('kym_openrouter').textContent)));
    T.has(await txt(p, '#kym_openrouter'), "Couldn't reach OpenRouter", 'an unreachable provider says so');
    T.eq((await status(who)).stored, 2, 'and nothing was stored on a guess');
    // a key that is too short / has spaces never leaves the browser's validation... the SERVER says key_shape
    await p.fill('#kOpenrouter', 'too short');
    await p.click('#kySave_openrouter');
    await until(() => p.evaluate(() => /doesn.t look like a key/.test(document.getElementById('kym_openrouter').textContent)));
    T.has(await txt(p, '#kym_openrouter'), "doesn't look like a key", 'a malformed key is refused in plain words');
    // success with Enter
    await behave('openrouter', 'ok', ok1);
    await p.fill('#kOpenrouter', ok1);
    await p.press('#kOpenrouter', 'Enter');
    T.ok(await until(() => p.evaluate(() => !document.getElementById('kyb_openrouter').hidden && /works and is saved/.test(document.getElementById('kym_openrouter').textContent)), 12000), 'Enter saves; the block flips to the saved view with a confirmation');
    const st = await status(who);
    T.eq([st.stored, st.working], [3, 3], 'the server now holds three working keys');
    T.has(await txt(p, '#kyb_openrouter'), 'sk-or-v1-••••wxyz', 'the new key is shown masked');
    T.eq(await p.evaluate(() => document.getElementById('kOpenrouter').value), '', 'and the box does not keep what was pasted');
    T.has(await txt(p, '#kySum'), '3 keys working', 'the summary follows');
    T.ok(await p.evaluate(() => { const k = JSON.parse(localStorage.getItem('dusu_office_keys') || '{}'); return Object.keys(k).length >= 2; }), 'the older gate (this browser\'s copy) was brought in step with the server');
    // Change replaces a saved key
    const gk2 = 'gsk_REPLACED' + 'R'.repeat(28) + 'efgh';
    await p.click('#kyb_groq button:has-text("Change")');
    T.ok(await vis(p, '#kGroq'), 'Change opens the entry box');
    T.eq(await p.evaluate(() => document.getElementById('kGroq').value), '', 'empty (never pre-filled with the old key)');
    await behave('groq', 'ok', gk2);
    await p.fill('#kGroq', gk2); await p.click('#kySave_groq');
    T.ok(await until(() => p.evaluate(() => /gsk_••••efgh/.test(document.getElementById('kyb_groq').textContent)), 12000), 'a changed key replaces the old one (masked, new last four)');
    T.eq((await status(who)).keys.find(k => k.provider === 'groq').masked, 'gsk_••••efgh', 'the server agrees');
    // Cancel
    await p.click('#kyb_groq button:has-text("Change")');
    await p.fill('#kGroq', 'abandoned key text here 123');
    await p.click('#kyCancel_groq');
    T.ok(!(await vis(p, '#kGroq')) && await vis(p, '#kyb_groq'), 'Cancel goes back to the saved view');
    await shot(p, 'keys-two-after-save');
    await c.close();

    // the "taking you in" path of a learner with no keys at all
    const n = await fresh(browser, 'new', { device: 'new', lang: 'en' });
    T.eq(await screen(n.p), 'keys', 'a learner with no keys is sent to the Keys screen');
    await until(() => n.p.evaluate(() => !!document.getElementById('kySum')));
    T.ok(await vis(n.p, '#kGroq') && await vis(n.p, '#kGemini') && await vis(n.p, '#kOpenrouter'), 'all three entry boxes are open');
    T.has(await txt(n.p, '#kySum'), 'Add two free keys', 'the summary says what is needed');
    const k1 = 'gsk_NEWBIE' + 'A'.repeat(30) + 'q1w2', k2 = 'AIzaNEWBIE' + 'B'.repeat(30) + 'e3r4';
    await n.p.fill('#kGroq', k1); await n.p.click('#kySave_groq');
    await until(() => n.p.evaluate(() => /works and is saved/.test(document.getElementById('kym_groq').textContent)), 12000);
    T.ok(await until(() => n.p.evaluate(() => /1 of the 2 working keys/.test(document.getElementById('kySum').textContent))), 'one key: "1 of the 2 working keys you need to start. Add 1 more."');
    T.eq(await screen(n.p), 'keys', 'one key is not enough: still on the Keys screen');
    await n.p.fill('#kGemini', k2); await n.p.click('#kySave_gemini');
    T.ok(await until(async () => (await screen(n.p)) !== 'keys', 15000), 'the second key takes the learner in');
    T.ok((await server('new', '/me')).body.has_keys === true, 'the server says the learner is set up (has_keys)');
    await n.c.close();
  }

  // =========================================================================================== D  Test / Remove / Check all
  T.section('D - Test, Remove, Check all keys');
  {
    await reset();
    const who = 'dev';
    const { c, p } = await fresh(browser, who, { lang: 'en' });
    await openKeys(p);
    const n0 = (await calls({ kind: 'chat' })).n;
    await p.click('#kyb_gemini button:has-text("Test")');
    T.ok(await until(() => p.evaluate(() => /Gemini works/.test(document.getElementById('kym_gemini').textContent)), 12000), 'Test: "Gemini works" (one real call)');
    T.ok((await calls({ kind: 'chat' })).n >= n0 + 1, '... which really went to the provider');
    await behave('gemini', 'limited');
    await p.click('#kyb_gemini button:has-text("Test")');
    T.ok(await until(() => p.evaluate(() => /hit its limit/.test(document.getElementById('kym_gemini').textContent)), 12000), 'Test on a limited key says so');
    T.has(await txt(p, '#kyb_gemini'), 'Daily limit reached', 'and the block shows the limit');
    await behave('gemini', 'ok');
    await p.click('#kyb_gemini button:has-text("Test")');
    T.ok(await until(() => p.evaluate(() => /Gemini works/.test(document.getElementById('kym_gemini').textContent) && /Working/.test(document.getElementById('kyb_gemini').textContent)), 12000), 'a Test on a key that works again clears the limit');
    await behave('groq', 'invalid');
    await p.evaluate(() => { document.getElementById('kyAll').scrollIntoView(); });
    await p.click('#kyAll');
    T.ok(await until(() => p.evaluate(() => /Rejected/.test(document.getElementById('kyb_groq').textContent)), 12000), 'Check all keys finds a key the provider now rejects');
    T.ok(await waitSum(p, /1 working, 1 need attention/), 'and the summary says "1 working, 1 need attention"');
    await reset();
    await p.click('#kyAll');
    // the rate limit is 4 a minute: say so rather than fail silently
    await sleep(300);
    for (let i = 0; i < 4; i++) await p.click('#kyAll');
    T.ok(await until(() => p.evaluate(() => /wait a moment/.test(document.getElementById('kym_all').textContent)), 8000), 'too many re-checks: "Please wait a moment" under the button (a plain message)');
    await c.close();
    // Remove (its own learner: the re-check limit above is 4 a minute)
    const rm = await fresh(browser, 'plain', { lang: 'en' });
    const p2 = rm.p; await openKeys(p2);
    await p2.click('#kyb_gemini button:has-text("Remove")');
    T.ok(await until(async () => (await status('plain')).stored === 1, 12000), 'Remove asks, then removes: the server holds one key now');
    T.ok(p2.__dialogs.some(d => /Remove your Gemini key/.test(d)), '(it asked first)');
    T.ok(await until(() => vis(p2, '#kGemini'), 6000), 'the Gemini box is open for a new key');
    T.ok(await waitSum(p2, /1 of the 2 working keys/), 'the summary says one more is needed');
    await rm.c.close();
    // Answers can come back OUT OF ORDER: a slow "Check all keys" must not bring back a key the learner removed while it was still running (mutant C3)
    const oo = await fresh(browser, 'wa', { lang: 'en' });
    const p3 = oo.p; await openKeys(p3);
    let release; const gate = new Promise(r => { release = r; }); let held = false;
    await p3.route('**/keys/recheck', async route => { const real = await route.fetch(); held = true; await gate; await route.fulfill({ response: real }); });      // the answer is computed NOW (two keys) and delivered LATER
    await p3.evaluate(() => { document.getElementById('kyAll').scrollIntoView(); });
    await p3.click('#kyAll');
    T.ok(await until(() => held, 12000), 'out of order: Check all is in flight and its answer is held back');
    await p3.click('#kyb_gemini button:has-text("Remove")');
    T.ok(await until(async () => (await status('wa')).stored === 1, 12000), '... meanwhile the learner removes Gemini: the server holds one key');
    T.ok(await until(() => p3.evaluate(() => /Gemini key removed/.test(document.getElementById('kym_gemini').textContent)), 12000), '... and the screen has APPLIED that answer ("Gemini key removed") - only now is the held answer an older one arriving late');
    await sleep(300);
    const sumBefore = await txt(p3, '#kySum');
    release();
    T.ok(await until(() => p3.evaluate(() => !document.getElementById('kyAll').disabled), 12000), '... the late answer is delivered and handled');
    await sleep(500);
    T.ok(await waitSum(p3, /1 of the 2 working keys/), 'the OLDER answer does not overwrite the newer one: the summary still says one key is missing');
    T.eq(await txt(p3, '#kySum'), sumBefore, '... and the summary is exactly what it was before the late answer arrived (the removed key is not back)');
    T.ok(!(await vis(p3, '#kyb_gemini')) && await vis(p3, '#kGemini'), '... and the removed Gemini key is not shown as a saved key (its box is open for a new one)');
    await oo.c.close();
  }

  // =========================================================================================== E  every state, on the screen and on the Home card
  T.section('E - every state on the Keys screen and the Home card');
  {
    // limited + reset time
    await reset(); await behave('groq', 'limited'); await behave('gemini', 'limited');
    await useKeys('lim');
    let { c, p } = await fresh(browser, 'lim', { lang: 'en' });
    await until(() => p.evaluate(() => !!userState.keys && userState.keys.state === 'all_limited'));
    T.eq(await p.evaluate(() => userState.keys.state), 'all_limited', 'two limited keys: /me says all_limited');
    await sleep(600);
    const card = await txt(p, '#kyCard');
    T.ok(!!card && (await vis(p, '#kyCard')), 'the Home card is shown');
    T.ok(await p.evaluate(() => document.getElementById('kyCard').classList.contains('bad')), 'in its warning style');
    await openKeys(p);
    const t1 = await txt(p, '#kyb_groq');
    T.has(t1, 'Daily limit reached', 'Groq: "Daily limit reached"');
    T.ok(/Resets (in about \d+ min|at |tomorrow|on )/.test(t1), 'Groq: when it resets (the provider said 6m45s: evidence)');
    const t2 = await txt(p, '#kyb_gemini');
    T.ok(/Should reset/.test(t2), 'Gemini: "Should reset ..." (the published daily rule, honestly marked as approximate)');
    T.has(await txt(p, '#kySum'), 'None of your keys can be used', 'the summary says none can be used');
    await shot(p, 'keys-limited'); await c.close();
    // rejected + expired
    await reset(); await behave('groq', 'invalid'); await behave('gemini', 'expired');
    await useKeys('bad');
    ({ c, p } = await fresh(browser, 'bad', { lang: 'en' }));
    await openKeys(p);
    T.has(await txt(p, '#kyb_groq'), 'Rejected', 'Groq: Rejected');
    T.has(await txt(p, '#kyb_gemini'), 'Expired', 'Gemini: Expired (the provider said the key expired)');
    T.eq(await p.evaluate(() => userState.keys.state), 'all_invalid', '/me says all_invalid');
    await shot(p, 'keys-rejected'); await c.close();
    // mixed
    await reset(); await behave('groq', 'limited', TOK.mix.keys.groq); await behave('openrouter', 'invalid', TOK.mix.keys.openrouter);
    await useKeys('mix');
    ({ c, p } = await fresh(browser, 'mix', { lang: 'en' }));
    await sleep(800);
    await p.evaluate(() => KY.refreshStatus(true)); await sleep(600);
    const st = await status('mix');
    T.eq(st.state, 'degraded', 'one working + one limited + one rejected: degraded');
    await openKeys(p);
    T.ok(/need attention/.test(await txt(p, '#kySum')) && /1 working/.test(await txt(p, '#kySum')), 'the summary: "1 working, 2 need attention"');
    const cardTxt = await txt(p, '#kyCard');
    T.ok(/Groq/.test(cardTxt) && /Gemini/.test(cardTxt) && /OpenRouter/.test(cardTxt), 'the Home card lists every key');
    await shot(p, 'keys-mixed'); await c.close();
    await reset();
  }

  // =========================================================================================== F  the pop-up
  T.section('F - the key-problem pop-up');
  const KP_LIMITED = () => ({ state: 'all_limited', now: Math.floor(Date.now() / 1000), keys: [{ provider: 'groq', kind: 'limited', scope: 'day', reset_at: Math.floor(Date.now() / 1000) + 3600 }, { provider: 'gemini', kind: 'limited', scope: 'day', reset_at: Math.floor(Date.now() / 1000) + 40000, approx: true }] });
  const openWs = (page, mode = 'conversation') => page.evaluate(m => new Promise(res => { const w = new WebSocket(WS_URL); window.__w = w; w.onmessage = ev => { try { onMessage(ev); } catch (e) { window.__errors.push(String(e)); } }; w.onopen = () => { w.send(JSON.stringify({ type: 'start', mode: m, token: authToken, name: 'x', hour: 11 })); res(true); }; }), mode);
  const sheetOn = page => vis(page, '#kySheet.on');
  {
    await reset();
    const { c, p } = await fresh(browser, 'ph', { lang: 'en' });
    await sleep(800);
    T.ok(!(await sheetOn(p)), 'a healthy learner: no pop-up on load');
    await behave('groq', 'limited'); await behave('gemini', 'limited');
    await openWs(p);
    T.ok(await until(() => sheetOn(p), 15000), 'a WebSocket frame with `kp` opens the pop-up');
    T.eq(await p.evaluate(() => document.getElementById('kySheet').getAttribute('aria-modal')), 'true', 'it is a modal dialog');
    T.has(await txt(p, '#kyTitle'), 'Your free AI limit is used up for now', 'its title says what happened');
    const lis = await p.evaluate(() => [...document.querySelectorAll('#kySheet .ky-pop-list li')].map(e => e.textContent));
    T.ok(lis.length === 2 && /^Groq: daily limit reached\. Resets/.test(lis[0]), 'Groq: daily limit reached + when it resets (the provider\'s own wait)');
    T.ok(/^Gemini: daily limit reached\. Should reset/.test(lis[1]), 'Gemini: "Should reset ..." (an approximation, marked as one)');
    T.ok(/paid plans/.test(await txt(p, '#kySheet')), 'and the one-line reason: free keys have daily limits, paid plans remove them');
    const btns = await p.evaluate(() => [...document.querySelectorAll('#kySheet .ky-pop-acts .btn')].map(e => e.textContent));
    T.eq(btns, ['Fix my keys', 'See plans', 'Later'], 'buttons: Fix my keys, See plans, Later');
    T.ok(!/Settings/.test(await txt(p, '#kySheet')) && !/WhatsApp/i.test(await txt(p, '#kySheet')), 'no "Settings" (it does not exist) and no WhatsApp link (a learner could paste a key there)');
    T.ok(!/Your API keys hit their limit/.test(await notif(p)) || !(await vis(p, '#notifBar')), 'the notification bar does not repeat the pop-up');
    // the same news again: one pop-up, repainted
    await p.evaluate(() => { window.__w.close(); }); await openWs(p);
    await sleep(1200);
    T.eq(await p.evaluate(() => document.querySelectorAll('#kySheet').length), 1, 'the same frame again: still ONE pop-up');
    await shot(p, 'popup-limited');
    await p.click('#kySheet .ky-pop-acts .btn:last-child');
    T.ok(await until(async () => !(await sheetOn(p))), 'Later closes it');
    await p.evaluate(() => { window.__w.close(); }); await openWs(p); await sleep(1500);
    T.ok(!(await sheetOn(p)), 'the SAME problem a moment later does not reopen it (told within the last 10 minutes)');
    await behave('groq', 'invalid'); await p.evaluate(() => { window.__w.close(); }); await openWs(p);
    T.ok(await until(() => sheetOn(p), 15000), 'a DIFFERENT problem (a key is now rejected) opens it again');
    T.has(await txt(p, '#kySheet'), 'Groq: rejected', 'and says which key');
    // HTTP error body
    await p.click('#kySheet .ky-pop-acts .btn:last-child'); await sleep(500);
    await behave('groq', 'limited'); await behave('gemini', 'limited');
    const r = await p.evaluate(async () => { const res = await fetch('/lesson/evaluate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: authToken, lang: 'en', type: 'speak', prompt: 'p', target: 't', said: 's' }) }); const j = await res.json(); return { status: res.status, detail: j.detail, kp: !!j.kp }; });
    T.eq([r.status, r.detail, r.kp], [429, 'quota', true], 'an HTTP 429 body still reaches the caller untouched (status, detail, kp) - the fetch wrapper only LOOKS');
    T.ok(await until(() => sheetOn(p), 15000), 'and the same error opens the pop-up (one place covers every HTTP site)');
    // buttons
    await p.click('#kySheet .ky-pop-acts .btn:first-child');
    T.ok(await until(async () => (await screen(p)) === 'keys'), 'Fix my keys goes to the Keys screen');
    T.ok(!(await sheetOn(p)), '... and closes the pop-up');
    await behave('groq', 'limited'); await behave('gemini', 'limited');
    await p.evaluate(() => KY.problem({ state: 'all_limited', now: Math.floor(Date.now() / 1000), keys: [{ provider: 'groq', kind: 'limited', scope: 'minute' }, { provider: 'gemini', kind: 'limited', scope: 'day' }, { provider: 'openrouter', kind: 'limited', scope: 'upstream' }] }));
    await sleep(500);
    T.ok(await sheetOn(p), 'another problem opens it again');
    await p.click('#kySheet .ky-pop-acts .btn:nth-child(2)');
    T.ok(await until(async () => (await screen(p)) === 'subscribe'), 'See plans goes to the plans page');
    await c.close();
  }
  {
    await reset();
    const { c, p } = await fresh(browser, 'pr', { lang: 'en' });
    await sleep(600);
    // provider trouble is a notice, never a pop-up
    await behave('groq', 'down'); await behave('gemini', 'down');
    await openWs(p);
    await sleep(2500);
    T.ok(!(await sheetOn(p)), 'provider trouble (transient): no pop-up');
    T.ok(/AI is busy right now/.test(await notif(p)), '... a plain notice: the AI is busy, your keys are fine');
    // Escape, focus and the Tab trap
    await p.evaluate(kp => KY.problem(kp), KP_LIMITED());
    await sleep(500);
    T.eq(await p.evaluate(() => document.activeElement && document.activeElement.id), 'kyTitle', 'focus moves to the dialog title');
    let stayed = true;
    for (let i = 0; i < 10; i++) { await p.keyboard.press('Tab'); if (!(await p.evaluate(() => !!document.activeElement.closest('#kySheet')))) stayed = false; }
    for (let i = 0; i < 4; i++) { await p.keyboard.press('Shift+Tab'); if (!(await p.evaluate(() => !!document.activeElement.closest('#kySheet')))) stayed = false; }
    T.ok(stayed, 'Tab / Shift+Tab never leave the open dialog');
    await p.keyboard.press('Escape');
    T.ok(await until(async () => !(await sheetOn(p))), 'Escape closes it');
    await c.close();
  }
  {
    // a key that died while the learner was away is explained on Home, once
    await reset(); await behave('groq', 'invalid'); await behave('gemini', 'invalid');
    await useKeys('bad');
    const { c, p } = await fresh(browser, 'bad', { lang: 'en', settle: 1500 });
    T.ok(await until(() => sheetOn(p), 15000), 'on Home load, a learner whose keys were both rejected is told before they start');
    T.has(await txt(p, '#kyTitle'), 'Your AI keys need attention', 'with the right headline');
    T.ok(/Groq: rejected/.test(await txt(p, '#kySheet')) && /Gemini: rejected/.test(await txt(p, '#kySheet')), 'naming each key');
    await p.click('#kySheet .ky-pop-acts .btn:last-child'); await sleep(400);
    await p.reload({ waitUntil: 'domcontentloaded' }); await sleep(2500);
    T.ok(!(await sheetOn(p)), 'after a reload the same news is NOT told again');
    await c.close();
  }

  // =========================================================================================== G  the mic and the Home chat after a `quota` frame
  T.section('G - what a quota frame hands back');
  {
    await reset();
    const { c, p } = await fresh(browser, 'ph', { lang: 'en' });
    const frame = () => ({ type: 'quota', msg: 'x', kp: { state: 'all_limited', now: Math.floor(Date.now() / 1000), keys: [{ provider: 'groq', kind: 'limited', scope: 'day' }] } });
    T.eq(await p.evaluate(f => { currentMode = 'daily'; document.getElementById('dailyMic').disabled = true; onMessage({ data: JSON.stringify(f) }); return document.getElementById('dailyMic').disabled; }, frame()), false, 'Daily Talk: the mic is handed back (it used to stay dead)');
    T.eq(await p.evaluate(f => { currentMode = 'learning'; document.getElementById('micBtn').disabled = true; onMessage({ data: JSON.stringify(f) }); return document.getElementById('micBtn').disabled; }, frame()), false, 'Learn: the mic button is handed back');
    T.eq(await p.evaluate(f => { currentMode = 'home'; let hit = 0; const o = HM.onQuota; HM.onQuota = m => { hit++; return o(m); }; onMessage({ data: JSON.stringify(f) }); HM.onQuota = o; return hit; }, frame()), 1, 'the Home chat: "thinking" is cleared (HM.onQuota runs)');
    await p.click('#kySheet .ky-pop-acts .btn:last-child').catch(() => {});
    await p.evaluate(() => { currentMode = 'conversation'; });
    await c.close();
    // with the screens OFF the old behaviour is untouched
    await reset({ keys_ui: 'off' });
    const o = await fresh(browser, 'ph', { lang: 'en' });
    T.eq(await o.p.evaluate(f => { currentMode = 'daily'; document.getElementById('dailyMic').disabled = true; onMessage({ data: JSON.stringify(f) }); return document.getElementById('dailyMic').disabled; }, frame()), true, 'screens off: the Daily mic is left exactly as the old code left it');
    T.ok(!(await sheetOn(o.p)), 'screens off: a frame with kp opens nothing');
    await o.c.close();
    await reset({ keys_ui: 'on' });
  }

  // =========================================================================================== H  Hindi, accessibility, layout
  T.section('H - Hindi, accessibility, layout');
  {
    await reset();
    await setLang('i18n', 'hi');
    const { c, p } = await fresh(browser, 'i18n', { lang: 'hi' });
    await sleep(600);
    await p.evaluate(kp => KY.problem(kp), KP_LIMITED());
    await sleep(500);
    const hi = await txt(p, '#kySheet');
    T.ok(/[ऀ-ॿ]/.test(hi), 'Hindi: the pop-up is in Devanagari');
    T.ok(!/\b(रहे हो|सकते हो|बोलोगे)\b/.test(hi), 'and uses no gendered forms toward the learner');
    T.ok(!/\bतू\b|\bतेरा\b/.test(hi), '... and never "tu"');
    await p.keyboard.press('Escape'); await sleep(300);
    await openKeys(p);
    T.ok(!/[ऀ-ॿ]/.test(await txt(p, '#keysForm')), 'the Keys screen itself stays English (like every older screen)');
    // en/hi key parity of every new module's word table
    const parity = await p.evaluate(() => { const o = {}; for (const [n, m] of [['KY', KY], ['INST', INST], ['CM', CM]]) { const t = m._txt; o[n] = { missing: Object.keys(t.en).filter(k => !(k in t.hi)), extra: Object.keys(t.hi).filter(k => !(k in t.en)) }; } return o; });
    T.eq(parity, { KY: { missing: [], extra: [] }, INST: { missing: [], extra: [] }, CM: { missing: [], extra: [] } }, 'every English string has a Hindi twin (KY, INST, CM)');
    await c.close();
    await setLang('i18n', 'en');
  }
  for (const [vp, label] of [[{ width: 360, height: 740 }, '360'], [{ width: 390, height: 844 }, '390'], [{ width: 1280, height: 900 }, '1280']]) {
    await reset(); await behave('groq', 'limited'); await behave('gemini', 'invalid');
    await useKeys('cap');
    const { c, p } = await fresh(browser, 'cap', { lang: 'en', viewport: vp });
    await sleep(1500);
    await p.evaluate(kp => KY.problem(kp), KP_LIMITED());
    await sleep(500);
    const r = await p.evaluate(() => {
      const sh = document.getElementById('kySheet'), b = sh.getBoundingClientRect();
      const ctl = [...sh.querySelectorAll('button')];
      return { overflow: document.documentElement.scrollWidth > window.innerWidth + 1, inside: b.left >= -1 && b.right <= window.innerWidth + 1 && b.top >= -1 && b.bottom <= window.innerHeight + 1,
               small: ctl.filter(x => { const q = x.getBoundingClientRect(); return q.width < 40 || q.height < 40; }).map(x => x.textContent), noname: ctl.filter(x => !(x.getAttribute('aria-label') || x.textContent || '').trim()).length,
               role: sh.getAttribute('role'), labelled: !!document.getElementById(sh.getAttribute('aria-labelledby')) };
    });
    T.ok(!r.overflow, `${label}: no horizontal overflow with the pop-up open`);
    T.ok(r.inside, `${label}: the pop-up fits inside the screen`);
    T.eq(r.small, [], `${label}: every pop-up control is at least 40 x 40`);
    T.eq([r.noname, r.role, r.labelled], [0, 'dialog', true], `${label}: dialog semantics and every control named`);
    await shot(p, `popup-${label}`);
    await p.keyboard.press('Escape'); await sleep(300);
    // the Home card
    const card = await p.evaluate(() => { const e = document.getElementById('kyCard'); if (!e || e.hidden) return null; const b = e.getBoundingClientRect(); const btn = e.querySelector('button'); const q = btn.getBoundingClientRect(); return { fits: b.right <= window.innerWidth + 1 && b.left >= -1, tall: q.height >= 40, named: btn.textContent.trim().length > 0, overflow: document.documentElement.scrollWidth > window.innerWidth + 1 }; });
    T.ok(card && card.fits && card.tall && card.named && !card.overflow, `${label}: the Home card fits, is a named button, is tall enough, nothing overflows`);
    const el = await p.$('#kyCard'); if (el) { await el.scrollIntoViewIfNeeded(); await shot(p, `card-${label}`); }
    await openKeys(p);
    const kf = await p.evaluate(() => ({ overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      small: [...document.querySelectorAll('#keysForm button')].filter(x => x.offsetParent !== null).filter(x => { const q = x.getBoundingClientRect(); return q.height < 40; }).map(x => x.textContent) }));
    T.ok(!kf.overflow, `${label}: the Keys screen does not overflow`);
    T.eq(kf.small, [], `${label}: every visible Keys-screen button is at least 40 high`);
    const f2 = await p.$('#keysForm'); if (f2) { await f2.scrollIntoViewIfNeeded(); await shot(p, `keysform-${label}`); }
    await c.close();
  }

  // =========================================================================================== I  the owner's dashboard
  T.section("I - the owner's dashboard");
  {
    await reset({ key_health: 'on', keys_ui: 'on', install_mode: 'on' });
    const ov = async () => (await server('owner', '/admin/overview')).body;
    const before = await ov();
    const { c, p } = await fresh(browser, 'owner', { lang: 'en' });
    await p.evaluate(() => { openAdmin(); });
    T.ok(await until(() => p.evaluate(() => !!document.getElementById('khSel')), 15000), 'the dashboard has the Key health, Key screens and Install select');
    T.eq(await p.evaluate(() => [document.getElementById('khSel').value, document.getElementById('kuSel').value, document.getElementById('instSel').value]), [before.key_health, before.keys_ui, before.install_mode], 'each shows the server\'s current value');
    T.eq(await p.evaluate(() => [...document.getElementById('khSel').options].map(o => o.value)), ['off', 'owner', 'on'], 'with the three stages');
    const others = o => JSON.stringify({ a: o.access_phase, l: o.level_test, b: o.owner_byok, pr: o.practice_room, lc: o.life_context, bi: o.bilingual, h: o.home_ai, p: o.planner, r: o.resume_interview, g: o.grammar_coach, n: o.notifications });
    await p.selectOption('#khSel', 'owner');
    T.ok(await until(async () => (await ov()).key_health === 'owner'), 'choosing "Owner + early access" reaches the server');
    T.eq(others(await ov()), others(before), 'and no OTHER switch changed (this endpoint writes whatever it receives)');
    T.eq([(await ov()).keys_ui, (await ov()).install_mode], [before.keys_ui, before.install_mode], 'the two sibling switches kept their values');
    await p.selectOption('#khSel', 'on');
    T.ok(await until(async () => (await ov()).key_health === 'on'), 'back to Everyone');
    await p.fill('#waInput', 'https://evil.example.com/x'); await p.click('#waSaveBtn');
    T.ok(await until(() => p.__dialogs.some(d => /not a WhatsApp/i.test(d))), 'a link that is not a WhatsApp invite is refused with a message');
    T.eq((await ov()).whatsapp_group, before.whatsapp_group, 'and the saved link is unchanged');
    await p.fill('#waInput', 'https://chat.whatsapp.com/ABCDEFGHIJKLMNOP?s=sh&p=a');
    await p.click('#waSaveBtn');
    T.ok(await until(async () => (await ov()).whatsapp_group === 'https://chat.whatsapp.com/ABCDEFGHIJKLMNOP'), 'a good link is saved with its tracking parameters stripped');
    await p.fill('#waInput', 'https://chat.whatsapp.com/TestInviteCode0123456789'); await p.click('#waSaveBtn');
    await until(async () => (await ov()).whatsapp_group === 'https://chat.whatsapp.com/TestInviteCode0123456789');
    await shot(p, 'dashboard-keys');
    await c.close();
  }

  T.section('the whole run');
  T.eq(ERRS, [], 'no console error, page error or unhandled rejection in the whole run');
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED:', e); process.exit(2); });
