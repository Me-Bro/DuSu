'use strict';
/*
 * Verification of the 2026-10-30 audit fixes (DUSU_AUDIT_FIX_PLAN.md): ASSERTIONS, unlike the rest of tests/audit which only photographs and measures.
 * Real Chromium against the real app on a scratch Postgres with PRODUCTION's rollout switches (tests/audit/up.sh). Every check carries the audit item it proves
 * ([P0-1] ...); the screenshots land in $OUT (~/.cache/dusu-audit-shots) so the screens can be looked at as well as measured.
 *
 *   tests/audit/spec.sh verify.cjs                  everything
 *   AUD_ENV="ONLY=K,R" tests/audit/spec.sh verify.cjs   only these sections (S smoke, K keys wizard, R deep links, P plans, F first-run overlays + short chat, O offline copy, H Home / names / hub / empty states,
 *                                                       N static facts, U UI system, W first-visit weight, V pins from the independent review, Y the fresh-eyes visual review's fixes, X XSS canary).  OLD_HTML=<page before the fixes> makes U / W / X run against it: they must FAIL there.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const A = require('./lib.cjs').create('verify');
const { sleep } = A;
const ONLY = (process.env.ONLY || '').split(',').map(s => s.trim()).filter(Boolean);
const LOG = [];
let passed = 0, failed = 0;

function check(id, name, cond, detail) {
  const ok = !!cond;
  ok ? passed++ : failed++;
  LOG.push({ id, name, ok, detail: ok ? undefined : String(detail === undefined ? '' : (typeof detail === 'string' ? detail : JSON.stringify(detail))).slice(0, 400) });
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  [${id}] ${name}${ok ? '' : '  -> ' + String(typeof detail === 'string' ? detail : JSON.stringify(detail)).slice(0, 300)}`);
}
async function section(key, title, fn, browser) {
  if (ONLY.length && !ONLY.includes(key)) return;
  console.log(`\n== ${key}: ${title}`);
  try { await fn(browser); } catch (e) { failed++; LOG.push({ id: key, name: 'section crashed', ok: false, detail: String(e && e.stack || e).slice(0, 600) }); console.log(`  FAIL  [${key}] section crashed: ${String(e && e.stack || e).slice(0, 500)}`); }
}
const sid = p => p.evaluate(() => (document.querySelector('.screen.on') || {}).id || '');
const vis = (p, sel) => p.evaluate(s => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; }, sel);
const box = (p, sel) => p.evaluate(s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), b: Math.round(r.bottom) }; }, sel);
const text = (p, sel) => p.evaluate(s => { const e = document.querySelector(s); return e ? (e.innerText || e.textContent || '').trim() : null; }, sel);
const tap = async (p, sel, o = {}) => { await p.locator(sel).first().scrollIntoViewIfNeeded().catch(() => {}); await p.locator(sel).first().click(Object.assign({ timeout: 8000 }, o)); };
const settle = async (p, ms = 700) => { await sleep(ms); };
const SEED_HOOK = 'Tell me how the project demo went.';                   // the "continue next time" promise the audit server seeds for `active`: a section that changes it puts it back
const resetKeys = async who => { for (const pr of ['groq', 'gemini', 'openrouter']) await A.api(who, '/keys/remove', 'POST', { provider: pr, token: A.TOK[who].token }); };

// ------------------------------------------------------------------------------------------------------------------------------------------------ S: the page loads without a single script error
// (a syntax check cannot see a runtime error such as a temporal-dead-zone ReferenceError at load - the whole page then dies silently)
async function S(browser) {
  const cases = [['login (signed out)', null, '/'], ['new learner', 'newbie', '/'], ['keyed learner', 'keyed', '/'], ['active learner', 'active', '/'], ['owner', 'owner', '/'], ['deep link', 'active', '/my-day'], ['plans', 'active', '/subscribe']];
  for (const [label, who, route] of cases) {
    const ctx = who ? await A.ctx(browser, who, { device: 'new', lang: 'en' }) : await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    if (!who) await ctx.route('**/*', r => { const u = new URL(r.request().url()); return u.origin === A.BASE ? r.continue() : r.abort(); });
    const page = await ctx.newPage(); const errs = [];
    page.on('pageerror', e => errs.push(String(e && e.message || e)));
    page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::ERR/.test(m.text())) errs.push('console: ' + m.text().slice(0, 160)); });
    await page.goto(A.BASE + route, { waitUntil: 'domcontentloaded' }); await sleep(2600);
    const st = await page.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id || '', hasApp: typeof show === 'function' && typeof navTo === 'function' && typeof HomeMore !== 'undefined' }));
    check('SMOKE', `${label}: the page loads with no script error and the app is alive (screen: ${st.screen || 'none'})`, errs.length === 0 && st.hasApp && !!st.screen, { errs: errs.slice(0, 3), st });
    await ctx.close();
  }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ K: the first-run Keys wizard
async function K(browser) {
  await resetKeys('newbie');
  await A.setLang('newbie', 'en');                                       // the server's saved choice wins on every /me, so it is set on the server
  const requests = [];
  const c = await A.ctx(browser, 'newbie', { device: 'new', firstRun: true, lang: 'en', viewport: { width: 390, height: 844 } });
  c.on('request', r => requests.push(r.url()));
  const p = await A.open(c, '/');
  await settle(p, 1200);
  check('P0-1', 'a brand-new account lands on the Keys screen in wizard mode', await sid(p) === 'keys' && await p.evaluate(() => document.getElementById('keys').classList.contains('ks-first')), await sid(p));
  await A.capture(p, 'wizard-start', { tag: 'K-390', full: true });
  const info = await p.evaluate(() => ({ h: (document.querySelector('.wrap') || {}).scrollHeight, view: window.innerHeight, title: (document.getElementById('keysTitle') || {}).textContent, sub: (document.getElementById('keysSub') || {}).textContent,
    step: (document.getElementById('ksStep') || {}).textContent, head: (document.getElementById('ksHead') || {}).textContent,
    help: !!(document.getElementById('ksHelp') || {}).open, formShown: !!document.getElementById('keysForm') && getComputedStyle(document.getElementById('keysForm')).display !== 'none',
    allText: (document.getElementById('keys') || {}).textContent || '' }));
  const get = await box(p, '#ksGet'), paste = await box(p, '#ksPaste'), sv = await box(p, '#ksSave');
  check('P0-1', 'the real first action - a big "Get free key" button - is above the fold (the old one was an 11px link, 1.5 screens down)', get && get.b <= info.view && get.h >= 48 && get.w >= 300, { get, view: info.view });
  check('P0-1', 'the paste box and its Save button are above the fold too', paste && sv && paste.b <= info.view && sv.b <= info.view, { paste, sv });
  check('P0-1', 'the whole first-run screen is at most ~2 phone screens (it was 4,046 px = five)', info.h <= info.view * 2.1, info);
  check('P0-1', 'progress is shown ("Key 1 of 2") and the time is honest ("about 5 minutes", not "a minute")', /Key 1 of 2/.test(info.step) && /5 minutes/.test(info.sub), info);
  check('P0-1', 'the old promises are gone: no "about a minute", no "2-minute level check" anywhere on the screen (the level check is OFF in production)', !/about a minute|2-minute|level check/i.test(info.allText), info.allText.match(/about a minute|2-minute[^.]*|level check[^.]*/gi));
  check('P0-1', 'with the level check OFF the guide does not promise it', !/level check/i.test(await text(p, '#ksStep7') || ''), await text(p, '#ksStep7'));
  check('P0-1', 'the long guide is BELOW the box and collapsed; the three identical "Save key" buttons are not shown to a first-run learner', !info.help && !info.formShown, info);
  check('P0-1', 'the guide thumbnails are not fetched while the guide is closed', !requests.some(u => /ytimg|youtube/.test(u)), requests.filter(u => /ytimg|youtube/.test(u)));
  check('P0-1', 'the primary link opens Groq (the recommended first key) in a new tab', await p.evaluate(() => { const a = document.getElementById('ksGet'); return a.href === 'https://console.groq.com/keys' && a.target === '_blank' && /noopener/.test(a.rel); }));
  check('P0-1', 'the screen speaks plainly - the word "provider" and "API key" jargon are not in the main card', !/provider|api key/i.test(await text(p, '#ksWiz') || ''), await text(p, '#ksWiz'));
  const targets = await p.evaluate(() => ['#ksGet', '#ksPaste', '#ksSave', '.ks-or a'].flatMap(s => [...document.querySelectorAll(s)].map(e => { const r = e.getBoundingClientRect(); return { s, w: Math.round(r.width), h: Math.round(r.height) }; })).filter(x => x.w < 44 || x.h < 44));
  check('UI-4', 'every wizard control is at least 44 x 44', targets.length === 0, targets);
  check('P0-1', 'no horizontal overflow at 390 px', !(await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)));

  // opening the guide
  await tap(p, '#ksHelp > summary'); await settle(p, 600);
  check('P0-1', 'opening "Need help?" reveals the video cards and the steps', await vis(p, '#keysTutorial') && await vis(p, '#keysSteps'));
  await A.capture(p, 'wizard-guide-open', { tag: 'K-390', full: false });
  await tap(p, '#ksHelp > summary'); await settle(p, 300);

  // recognising the service from the key
  const det = async v => { await p.fill('#ksPaste', v); await sleep(150); return text(p, '#ksDet'); };
  check('P0-1', 'a gsk_ key is recognised as Groq', /Groq/.test(await det('gsk_' + 'a'.repeat(40)) || ''));
  check('P0-1', 'an AIza key is recognised as Gemini', /Gemini/.test(await det('AIza' + 'b'.repeat(35)) || ''));
  check('P0-1', 'an sk-or- key is recognised as OpenRouter', /OpenRouter/.test(await det('sk-or-v1-' + 'c'.repeat(40)) || ''));
  check('P0-1', 'a pasted key with quotes and "Bearer " in front is still recognised', /Groq/.test(await det('Bearer "gsk_' + 'd'.repeat(40) + '"') || ''));
  check('P0-1', 'a short-lived AQ. token is explained instead of being saved', /AQ\./.test(await det('AQ.' + 'e'.repeat(30)) || ''));
  check('P0-1', 'nothing is shown for an empty or unrecognisable box', (await det('')) === '' );
  await p.fill('#ksPaste', 'zzzz' + 'q'.repeat(30)); await tap(p, '#ksSave'); await settle(p, 500);
  check('P0-1', 'an unrecognisable key asks which service it is from (three choices) and saves nothing', await p.evaluate(() => { const b = document.getElementById('ksPick'); return !b.hidden && b.querySelectorAll('button').length === 3; }) && !(await A.api('newbie', '/keys/status')).body.keys.length, (await A.api('newbie', '/keys/status')).body);
  await p.fill('#ksPaste', ''); await p.evaluate(() => { document.getElementById('ksPick').hidden = true; });

  // key 1
  await p.fill('#ksPaste', 'gsk_' + 'x'.repeat(48)); await tap(p, '#ksSave'); await settle(p, 2200);
  const s1 = await p.evaluate(() => ({ step: document.getElementById('ksStep').textContent, head: document.getElementById('ksHead').textContent, bar: document.getElementById('ksBarI').style.width, get: document.getElementById('ksGet').href, det: document.getElementById('ksDet').textContent, screen: (document.querySelector('.screen.on') || {}).id }));
  check('P0-1', 'after key 1 the wizard moves on to "Key 2 of 2", suggests a different service, and the bar is half full', /Key 2 of 2/.test(s1.step) && /aistudio\.google\.com/.test(s1.get) && s1.bar === '50%' && s1.screen === 'keys', s1);
  check('P0-1', 'and says plainly that the first key works', /Groq/.test(s1.det) && /works|saved/i.test(s1.det), s1.det);
  await A.capture(p, 'wizard-key2', { tag: 'K-390', full: false });
  // key 2
  await p.fill('#ksPaste', 'AIza' + 'y'.repeat(35)); await tap(p, '#ksSave'); await settle(p, 3500);
  const s2 = await sid(p);
  check('P0-1', 'after key 2 the learner is taken into the app (no level check: it is OFF)', s2 !== 'keys' && s2 !== '', s2);
  const fun = (await A.api('owner', '/admin/funnel?days=30')).body || {};
  const got = Object.fromEntries((fun.milestones || []).map(m => [m.name, m.learners]));
  check('P1-10', 'the owner\'s funnel recorded the first and the second key (server-side, nobody typed anything into it)', got.key1_saved >= 1 && got.key2_saved >= 1, got);
  await c.close();

  // Hindi default + the language pill
  await resetKeys('newbie');
  await A.setLang('newbie', 'hi');
  const c2 = await A.ctx(browser, 'newbie', { device: 'new', firstRun: true, lang: 'hi', viewport: { width: 390, height: 844 } });
  const p2 = await A.open(c2, '/');
  await settle(p2, 1200);
  const hi = await p2.evaluate(() => ({ head: document.getElementById('ksHead').textContent, step: document.getElementById('ksStep').textContent, sw: [...document.querySelectorAll('.ks-lg button')].map(b => b.textContent), lgHidden: document.querySelector('.ks-lg').hidden, htmlLang: document.documentElement.lang }));
  check('P0-1', 'the wizard speaks Hindi to a Hindi-first learner (Devanagari with everyday English words)', /[ऀ-ॿ]/.test(hi.head) && /Key 1/.test(hi.step), hi);
  check('P0-1', 'it carries the Hindi / English switch, so an English-comfortable learner can change it right there', hi.sw.length === 2 && hi.lgHidden === false, hi);
  check('P0-1', 'the document language is not rewritten (section 11)', hi.htmlLang === 'en', hi.htmlLang);
  await A.capture(p2, 'wizard-hindi', { tag: 'K-390', full: false });
  await p2.locator('.ks-lg button[data-l="en"]').click(); await settle(p2, 600);
  const en = await text(p2, '#ksHead');
  check('P0-1', 'the pill switches the wizard to English at once', /Get your free AI key/.test(en || ''), en);
  await p2.locator('.ks-lg button[data-l="hi"]').click(); await settle(p2, 300);
  await c2.close();
  await A.setLang('newbie', 'en');

  // small phone + desktop
  const c3 = await A.ctx(browser, 'newbie', { device: 'new', firstRun: true, lang: 'en', viewport: { width: 360, height: 640 } });
  const p3 = await A.open(c3, '/'); await settle(p3, 1000);
  const m3 = await p3.evaluate(() => ({ ov: document.documentElement.scrollWidth > window.innerWidth + 1, wrapOv: (document.querySelector('.wrap').scrollWidth > document.querySelector('.wrap').clientWidth + 1) }));
  check('P0-1', 'no horizontal overflow on a 360 x 640 phone', !m3.ov && !m3.wrapOv, m3);
  const g3 = await box(p3, '#ksGet');
  check('P0-1', 'on a short 640 px screen the primary button is still visible without scrolling', g3 && g3.b <= 640, g3);
  await A.capture(p3, 'wizard-360', { tag: 'K-360', full: false });
  await c3.close();
  const c4 = await A.ctx(browser, 'newbie', { device: 'new', firstRun: true, lang: 'en', viewport: { width: 1280, height: 800 } });
  const p4 = await A.open(c4, '/'); await settle(p4, 1000);
  const w4 = await box(p4, '#ksWiz');
  check('P0-1', 'desktop: the wizard is one centred column, not stretched across the screen', w4 && w4.w <= 600 && w4.w >= 360, w4);
  await A.capture(p4, 'wizard-1280', { tag: 'K-1280', full: false });
  await c4.close();

  // managing keys (a returning learner) keeps the old, complete screen
  const c5 = await A.ctx(browser, 'keyed', { viewport: { width: 390, height: 844 } });
  const p5 = await A.open(c5, '/'); await p5.evaluate(() => navTo('/keys')); await settle(p5, 1200);
  const mg = await p5.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, first: document.getElementById('keys').classList.contains('ks-first'),
    form: getComputedStyle(document.getElementById('keysForm')).display !== 'none', sum: !!document.getElementById('ksHelp') && getComputedStyle(document.querySelector('#ksHelp > summary')).display === 'none', wiz: !!document.getElementById('ksWiz') && getComputedStyle(document.getElementById('ksWiz')).display !== 'none' }));
  check('P0-1', 'a learner who already has keys sees the full manage screen (three key blocks), not the wizard', mg.screen === 'keys' && !mg.first && mg.form && !mg.wiz, mg);
  await A.capture(p5, 'manage-keys', { tag: 'K-390', full: false });
  await c5.close();
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ R: cold deep links
async function R(browser) {
  await A.setLang('keyed', 'en');                                         // the server's saved choice wins on every /me: do not inherit whatever an earlier run left
  const routes = [['/my-day', 'pl'], ['/grammar', 'gc'], ['/resume-interview', 'ri'], ['/practice-room', 'prHub'], ['/about', 'about'], ['/home-chat', 'session']];
  for (const [route, screen] of routes) {
    let ok = 0, banner = 0, last = '';
    for (let i = 0; i < 3; i++) {
      const c = await A.ctx(browser, 'keyed', { viewport: { width: 390, height: 844 } });      // a device with ONLY the sign-in: no cached state
      const p = await A.open(c, route, { waitMe: false, settle: 100 });
      await p.waitForFunction(() => { const s = document.querySelector('.screen.on'); return s && s.id !== 'login'; }, null, { timeout: 8000 }).catch(() => {});
      await sleep(900);
      const r = await p.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id || '', banner: !document.getElementById('notifBar').hidden ? document.getElementById('notifTxt').textContent : '', path: location.pathname }));
      if (r.screen === screen) ok++;
      if (r.banner) { banner++; last = r.banner; }
      await c.close();
    }
    check('P1-8', `a cold deep link to ${route} reaches ${screen} 3 of 3 times (it said "isn't available" 6 of 6 before)`, ok === 3 && banner === 0, { ok, banner, last });
  }
  // a feature that is really OFF must still be refused after /me answers (the wait must not make "off" look "on")
  await A.settings({ planner: 'off' });
  M: {
    const c = await A.ctx(browser, 'keyed', { viewport: { width: 390, height: 844 } });
    const p = await A.open(c, '/my-day', { waitMe: false, settle: 100 });
    await sleep(2500);
    const r = await p.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id || '', banner: !document.getElementById('notifBar').hidden ? document.getElementById('notifTxt').textContent : '' }));
    check('P1-8', 'with My Day really switched off, the deep link still ends on Home with the honest message (after /me, not before)', r.screen === 'home' && /available/i.test(r.banner), r);
    await c.close();
  }
  await A.settings({ planner: 'on' });
  // a hung /me must not trap the learner behind the spinner
  {
    const c = await A.ctx(browser, 'keyed', { viewport: { width: 390, height: 844 } });
    await c.route('**/me?*', r => { setTimeout(() => r.abort(), 20000); });
    const p = await A.open(c, '/my-day', { waitMe: false, settle: 100 });
    const t0 = Date.now();
    await p.waitForFunction(() => { const s = document.querySelector('.screen.on'); return s && s.id !== 'login'; }, null, { timeout: 20000 }).catch(() => {});
    const dt = Date.now() - t0;
    const sc = await sid(p);
    check('P1-8', 'if /me never answers the learner is not trapped: after the spinner\'s own 12 s ceiling they land somewhere usable', ['home', 'keys', 'pl'].includes(sc) && dt < 16000, { sc, dt });
    await c.close();
  }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ P: the plans page + "Reserve my plan"
async function P(browser) {
  await A.post('/__audit/reset', { tables: ['plan_interest', 'ev_milestones'] });
  await A.setLang('active', 'en');
  const c = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/'); await p.evaluate(() => navTo('/subscribe')); await settle(p, 900);
  const j = () => p.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, notice: (document.getElementById('subNotice') || {}).innerText, free: (document.getElementById('planFree') || {}).innerText,
    plans: [...document.querySelectorAll('.plan[data-plan]')].map(b => ({ id: b.dataset.plan, text: b.innerText.replace(/\s+/g, ' ').trim(), sel: b.classList.contains('sel'), pressed: b.getAttribute('aria-pressed'), res: !b.querySelector('.plan-res').hidden })),
    btn: { text: document.getElementById('subProceed').innerText, dis: document.getElementById('subProceed').disabled }, feel: !document.getElementById('planFeel').hidden, status: document.getElementById('subStatus').innerText,
    chips: [...document.querySelectorAll('.feel-chip')].map(b => ({ f: b.dataset.feel, on: b.getAttribute('aria-pressed') === 'true' })) }));
  let s0 = await j();
  check('P0-2', 'the plans page opens', s0.screen === 'subscribe', s0.screen);
  check('P0-2', 'it says up front that payment is not open yet and that nothing is paid now (the old page only said so AFTER "Proceed")', /isn't open yet/i.test(s0.notice) && /nothing now|pay nothing/i.test(s0.notice), s0.notice);
  check('P0-2', 'there is a Free card, so a learner can compare - and it names no number the product does not enforce', /Free/.test(s0.free) && /Your plan now/.test(s0.free) && /own free AI keys/.test(s0.free), s0.free);
  check('P0-2', 'the three plans keep their prices (299 / 599 / 899)', s0.plans.length === 3 && /299/.test(s0.plans[0].text) && /599/.test(s0.plans[1].text) && /899/.test(s0.plans[2].text), s0.plans);
  check('P0-2', 'the copy is concrete and true to the code: 50 / 150 AI replies a day and "no daily limit" (PLAN_LIMITS), no invented feature gating', /50 AI replies/.test(s0.plans[0].text) && /150 AI replies/.test(s0.plans[1].text) && /no daily limit/i.test(s0.plans[2].text) && !/interview practice|journey|learning journey/i.test(s0.plans.map(x => x.text).join(' ')), s0.plans.map(x => x.text));
  check('P0-2', 'the dead "Proceed" button is now "Reserve my plan", disabled until a plan is chosen', /Reserve my plan/.test(s0.btn.text) && s0.btn.dis && !/Proceed/.test(s0.btn.text), s0.btn);
  check('P0-2', 'the old "payment coming soon (work in progress)" line is gone', !/work in progress|payment coming soon/i.test(await text(p, '#subscribe')));
  await A.capture(p, 'plans-start', { tag: 'P-390', full: true });
  await tap(p, '.plan[data-plan="plus"]'); await settle(p, 300);
  let s1 = await j();
  check('P0-2', 'choosing a plan selects it (aria-pressed), shows the optional price question and enables the button', s1.plans[1].sel && s1.plans[1].pressed === 'true' && s1.feel && !s1.btn.dis, s1);
  await tap(p, '.feel-chip[data-feel="fair"]'); await settle(p, 200);
  check('P0-2', 'the price chips toggle (one pressed at a time)', (await j()).chips.filter(x => x.on).map(x => x.f).join() === 'fair');
  await tap(p, '#subProceed'); await settle(p, 1200);
  let s2 = await j();
  check('P0-2', 'Reserve saves: a calm confirmation, the card shows "Reserved", the button shows "Reserved" and is disabled', /Saved/.test(s2.status) && s2.plans[1].res && /Reserved/.test(s2.btn.text) && s2.btn.dis, s2);
  const mine = (await A.api('active', '/plans/interest')).body;
  check('P0-2', 'the server holds exactly that reservation (plan + price opinion)', JSON.stringify(mine.reserved) === JSON.stringify([{ plan: 'plus', price_feel: 'fair' }]), mine);
  await A.capture(p, 'plans-reserved', { tag: 'P-390', full: false });
  await tap(p, '.feel-chip[data-feel="great"]'); await settle(p, 200);
  check('P0-2', 'changing the opinion on a reserved plan offers "Update my answer"', /Update/.test((await j()).btn.text) && !(await j()).btn.dis);
  await tap(p, '#subProceed'); await settle(p, 900);
  check('P0-2', 'updating changes the opinion and does NOT create a second reservation', JSON.stringify((await A.api('active', '/plans/interest')).body.reserved) === JSON.stringify([{ plan: 'plus', price_feel: 'great' }]));
  // another device / a reload remembers
  await p.reload(); await settle(p, 1200); await p.evaluate(() => navTo('/subscribe')); await settle(p, 900);
  check('P0-2', 'after a reload the reservation is still shown (it lives on the server, not in the browser)', (await j()).plans[1].res);
  // errors
  await tap(p, '.plan[data-plan]:nth-child(3)'); await settle(p, 200);
  await c.setOffline(true); await tap(p, '#subProceed'); await settle(p, 1200); await c.setOffline(false);
  const se = await j();
  check('P0-2', 'offline: the learner is told plainly, the button comes back, nothing breaks', /Check your internet/.test(se.status) && !se.btn.dis, se);
  // the funnel
  const fun = (await A.api('owner', '/admin/funnel?days=30')).body || {};
  const got = Object.fromEntries((fun.milestones || []).map(m => [m.name, m.learners]));
  check('P1-10', 'the owner\'s funnel saw the plans being opened and a plan reserved, and counts the opinion', got.plans_seen >= 1 && got.plan_reserved >= 1 && fun.plans && fun.plans.plus.learners >= 1 && fun.plans.plus.great >= 1, { got, plans: fun.plans });
  await c.close();
  // Hindi
  await A.setLang('active', 'hi');
  const c2 = await A.ctx(browser, 'active', { lang: 'hi', viewport: { width: 390, height: 844 } });
  const p2 = await A.open(c2, '/'); await p2.evaluate(() => navTo('/subscribe')); await settle(p2, 900);
  const hi = await p2.evaluate(() => ({ title: document.getElementById('subTitle').textContent, notice: document.getElementById('subNotice').textContent, btn: document.getElementById('subProceed').textContent }));
  check('P0-2', 'the plans page follows the learner\'s Hindi choice', /[\u0900-\u097F]/.test(hi.title) && /[\u0900-\u097F]/.test(hi.notice) && /reserve/i.test(hi.btn), hi);
  await A.capture(p2, 'plans-hindi', { tag: 'P-390', full: false });
  await c2.close(); await A.setLang('active', 'en');
  // small phone + targets
  const c3 = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 360, height: 640 } });
  const p3 = await A.open(c3, '/'); await p3.evaluate(() => navTo('/subscribe')); await settle(p3, 900);
  await tap(p3, '.plan[data-plan="pro"]'); await settle(p3, 300);
  const m3 = await p3.evaluate(() => ({ ov: document.documentElement.scrollWidth > window.innerWidth + 1, small: ['.plan[data-plan]', '.feel-chip', '#subProceed'].flatMap(s => [...document.querySelectorAll(s)].filter(e => e.getBoundingClientRect().width > 0).map(e => { const r = e.getBoundingClientRect(); return { s, w: Math.round(r.width), h: Math.round(r.height) }; })).filter(x => x.w < 44 || x.h < 44) }));
  check('P0-2', 'no overflow at 360 px and every control is at least 44 px', !m3.ov && m3.small.length === 0, m3);
  await A.capture(p3, 'plans-360', { tag: 'P-360', full: false });
  await c3.close();
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ F: first-run overlays + a short chat's result
const micReady = page => page.waitForFunction(() => !!window.__srActive, null, { timeout: 20000 }).then(() => true).catch(() => false);
const say = (page, t) => page.evaluate(x => window.__say(x), t);
async function F(browser) {
  await A.post('/__audit/reset_learner', { who: 'keyed' });
  await A.setLang('keyed', 'en');
  // a brand-new learner (keys saved, never practised) on Home
  const c = await A.ctx(browser, 'keyed', { firstRun: true, lang: 'en', viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/', { settle: 1800 });
  await sleep(1800);
  const h0 = await p.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, banner: !document.getElementById('journeyBanner').hidden, rewards: document.getElementById('rgSheet').classList.contains('on'),
    seen: localStorage.getItem('dusu_rewards_intro_seen'), bannerText: document.getElementById('journeyBanner').innerText }));
  check('P1-5', 'a brand-new learner\'s Home does NOT open the four-card rewards lecture before they have spoken', h0.screen === 'home' && !h0.rewards && h0.seen !== '1', h0);
  check('P1-5', 'and does not say "Where we left off - You were doing really well." when there is nothing to continue', !h0.banner && !/doing really well/i.test(h0.bannerText) || !h0.banner, h0);
  await A.capture(p, 'home-new-learner', { tag: 'F-390', full: false });
  // a short chat: one line, then End
  await p.evaluate(() => navTo('/face-to-face')); await sleep(1500);
  if (await micReady(p)) { await say(p, 'Hello my name is Kabir.'); await sleep(2500); }
  await tap(p, '#endBtn');
  await p.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'sessionResult', null, { timeout: 30000 }).catch(() => {});
  await sleep(2500);
  const r1 = await p.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, body: document.getElementById('srBody').innerText, short: !!document.getElementById('srShort'),
    scoreRow: [...document.querySelectorAll('#srBody .sr-row')].map(r => r.innerText.replace(/\s+/g, ' ')).find(t => /Speaking Score/i.test(t)) || '', down: !!document.querySelector('#srBody .sr-row .val.down') }));
  check('P1-6', 'a few-second chat ends on the result screen', r1.screen === 'sessionResult', r1.screen);
  check('P1-6', 'it shows no red score or "(-64)": the score reads "-" and says what is needed ("too short to score ... about a minute")', r1.short && /—/.test(r1.scoreRow) && !r1.down && !/\(-\d+\)/.test(r1.body) && /about a minute/i.test(r1.body), r1);
  await A.capture(p, 'result-short', { tag: 'F-390', full: false });
  await tap(p, '#srDone'); await sleep(2600);
  const h1 = await p.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, rewards: document.getElementById('rgSheet').classList.contains('on'), seen: localStorage.getItem('dusu_rewards_intro_seen'), had: localStorage.getItem('dusu_had_session'), uid: curUid() }));
  check('P1-5', 'AFTER the first finished session the rewards guide opens once (a natural moment, not before speaking); the "had a session" flag holds THIS account\'s id', h1.screen === 'home' && h1.rewards && h1.seen === '1' && !!h1.uid && h1.had === h1.uid, h1);
  await A.capture(p, 'rewards-after-first-session', { tag: 'F-390', full: false });
  await tap(p, '#rgDone'); await sleep(600);
  const h2 = await p.evaluate(() => ({ banner: !document.getElementById('journeyBanner').hidden, text: document.getElementById('journeyBanner').innerText.replace(/\s+/g, ' ') }));
  check('P1-5', 'now that there is history, the "where we left off" card is shown - with a true line, not a generic compliment', h2.banner && !/doing really well/i.test(h2.text), h2);
  await p.reload(); await sleep(2500);
  check('P1-5', 'the rewards guide does not open again on the next visit', !(await p.evaluate(() => document.getElementById('rgSheet').classList.contains('on'))));
  await c.close();

  // a Daily Talk with no sentence at all
  await A.post('/__audit/reset_learner', { who: 'keyed' });
  const c2 = await A.ctx(browser, 'keyed', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p2 = await A.open(c2, '/daily-talk', { settle: 2500 });
  await tap(p2, '#dailyFinish').catch(() => {}); await sleep(3500);
  const d = await p2.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, body: (document.getElementById('srBody') || {}).innerText || '', ring: (document.getElementById('srDuration') || {}).textContent, kick: (document.getElementById('srKick') || {}).textContent }));
  check('P1-6', 'a Daily Talk with zero sentences no longer says "Session saved."', d.screen !== 'sessionResult' || !/Session saved/i.test(d.body), d);
  if (d.screen === 'sessionResult') check('P1-6', '... it says what to do next', /No sentences yet/i.test(d.body), d.body);
  if (d.screen === 'sessionResult') check('VR-12', '... and the ring is not stuck on the loading dots, and the title does not say "complete" over "No sentences yet"', d.ring === '—' && /nothing to score/i.test(d.kick || ''), d);
  await A.capture(p2, 'daily-zero', { tag: 'F-390', full: false });
  await c2.close();

  // the established learner is unaffected: history -> the card is there; no spurious guide
  await A.post('/__audit/hook', { who: 'active', hook: SEED_HOOK });
  const c3 = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p3 = await A.open(c3, '/', { settle: 2000 });
  const a0 = await p3.evaluate(() => ({ banner: !document.getElementById('journeyBanner').hidden, rewards: document.getElementById('rgSheet').classList.contains('on') }));
  check('P1-5', 'a learner with a month of history still sees "Where we left off"', a0.banner, a0);
  await c3.close();
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ O: offline wording + retry
async function O(browser) {
  await A.setLang('active', 'en');
  const c = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/', { settle: 1500 });
  await c.setOffline(true);
  await p.evaluate(() => navTo('/face-to-face')); await sleep(2500);
  const o1 = await p.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, orb: (document.getElementById('orbLabel') || document.getElementById('orb') || {}).innerText, all: document.getElementById('session').innerText }));
  check('P1-7', 'offline: the chat says "No internet connection" and that the chat is safe - not "Is the server running?"', /No internet connection/.test(o1.all) && /chat is safe/i.test(o1.all) && !/server/i.test(o1.all), o1);
  await A.capture(p, 'offline-f2f', { tag: 'O-390', full: false });
  await c.setOffline(false);
  await p.locator('#orb').click(); await sleep(3000);
  const o2 = await p.evaluate(() => ({ feed: document.getElementById('feed').innerText.slice(0, 300), screen: (document.querySelector('.screen.on') || {}).id }));
  check('P1-7', 'back online, a tap on DuSu opens the same chat again (it has a retry now): DuSu\'s opening line is on screen',
    o2.screen === 'session' && o2.feed.split('\n').filter(l => !/Tip:/.test(l) && l.trim().length > 15).length >= 1 && !/No internet/.test(o2.feed), o2);
  await c.close();
  // Daily Talk
  const c2 = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p2 = await A.open(c2, '/', { settle: 1500 });
  await c2.setOffline(true);
  await p2.evaluate(() => navTo('/daily-talk')); await sleep(2500);
  const d1 = await p2.evaluate(() => document.getElementById('daily').innerText);
  check('P1-7', 'offline Daily Talk: plain words, no "server"', /No internet connection/.test(d1) && !/server/i.test(d1), d1.slice(0, 300));
  await A.capture(p2, 'offline-daily', { tag: 'O-390', full: false });
  await c2.setOffline(false);
  await p2.locator('#dailyMic').click({ timeout: 5000 }).catch(() => {}); await sleep(3500);
  const d2 = await p2.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, chat: (document.getElementById('dailyChat') || document.getElementById('daily')).innerText }));
  check('P1-7', 'Daily Talk: back online, the tap on the mic the copy promises really does start the chat (DuSu\'s opening question appears, the error is gone)', d2.screen === 'daily' && !/No internet connection/.test(d2.chat) && (d2.chat.length > 60), d2);
  await c2.close();
  // Learn
  const c4 = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p4 = await A.open(c4, '/', { settle: 1500 });
  await c4.setOffline(true);
  await p4.evaluate(() => navTo('/learn')); await sleep(2500);
  const l1 = await p4.evaluate(() => document.getElementById('learning').innerText);
  check('P1-7', 'offline Learn: plain words, no "server"', /No internet connection/.test(l1) && !/server/i.test(l1), l1.slice(0, 300));
  await c4.setOffline(false);
  await p4.locator('#micBtn').click({ timeout: 5000 }).catch(() => {}); await sleep(3500);
  const l2 = await p4.evaluate(() => document.getElementById('learning').innerText);
  check('P1-7', 'Learn: back online, the tap on the mic the copy promises works (the error is gone)', !/No internet connection/.test(l2), l2.slice(0, 300));
  await c4.close();
  // Hindi
  await A.setLang('active', 'hi');
  const c3 = await A.ctx(browser, 'active', { lang: 'hi', viewport: { width: 390, height: 844 } });
  const p3 = await A.open(c3, '/', { settle: 1500 });
  await c3.setOffline(true);
  await p3.evaluate(() => navTo('/face-to-face')); await sleep(2500);
  const h1 = await p3.evaluate(() => document.getElementById('session').innerText);
  check('P1-7', 'the Hindi chat screen has the same plain wording, with no "server" and no "सर्वर"', !/सर्वर|server/i.test(h1), h1.slice(0, 300));
  await c3.close(); await A.setLang('active', 'en');
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ H: Home, names, hub, empty states, copy
async function H(browser) {
  await A.setLang('active', 'en');
  await A.post('/__audit/facts', { who: 'active', facts: { events: [] } });          // a freshly seeded learner has an upcoming-interview banner; X leaves none: count the same Home either way
  const c = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p = await A.open(c, '/', { settle: 2200 });
  await sleep(1500);
  const h = await p.evaluate(() => {
    const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
    const wrap = document.querySelector('.wrap');
    const blocks = [...document.querySelectorAll('#home .hstage > *, #home #moreHome > *')].filter(vis).filter(e => e.getBoundingClientRect().height > 24 && !e.matches('input[type=hidden],.hwords,.hchar'));
    return { footer: !!document.querySelector('footer.foot'), text: document.getElementById('home').innerText, scrollH: wrap.scrollHeight,
      tiles: [...document.querySelectorAll('#hmFeats .hm-feat')].map(b => b.getAttribute('aria-label')),
      banners: ['prHomeCard', 'plHomeCard', 'riHomeCard', 'gcHomeCard'].map(id => ({ id, shown: vis(document.getElementById(id)) })),
      progress: vis(document.getElementById('progressLabel')) || vis(document.querySelector('#home .nav-cards')), keyCard: vis(document.getElementById('kyCard')),
      blocks: blocks.map(e => (e.id || e.className.split(' ')[0] || e.tagName).slice(0, 24)), goal: vis(document.getElementById('homeGoal')), banner: vis(document.getElementById('journeyBanner')),
      beta: (document.querySelector('.beta-badge') || {}).innerText, lgNote: (document.getElementById('lgNote') || {}).innerText,
      more: { btn: vis(document.getElementById('hmMoreBtn')), label: (document.getElementById('hmMoreBtn') || {}).innerText, expanded: (document.getElementById('hmMoreBtn') || {}).getAttribute && document.getElementById('hmMoreBtn').getAttribute('aria-expanded'),
              closed: !vis(document.getElementById('homeMissions')) && !vis(document.getElementById('homeCareer')) } };
  });
  check('P1-1', 'the website footer is gone from the app (it carried "Modes (coming soon)", social icons and "Back to top")', !h.footer && !/Modes \(coming soon\)|Back to top|Rana Brothers project/i.test(h.text), { footer: h.footer });
  check('P1-1', 'Home shows the 8 practice tools - not 12 tiles', h.tiles.length === 8, h.tiles);
  check('P1-2', 'and every tile carries the feature\'s one name', JSON.stringify(h.tiles) === JSON.stringify(['Daily Talk', 'Face to Face Talk', 'Interview Prep', 'Learn', 'Practice Room', 'Job Interview Practice', 'Grammar Coach', 'My Day']), h.tiles);
  check('P1-1', 'the four banner cards that repeated a tile are hidden', h.banners.every(b => !b.shown), h.banners);
  check('P1-1', 'the two "Your progress" cards that repeated the Journey and Ranks tabs are hidden', !h.progress);
  check('P1-1', 'the technical "AI keys - 0 requests today" card is hidden while the keys are healthy', !h.keyCard);
  check('P1-1', 'Home is much shorter (it was 3,570 px = 4-5 phone screens)', h.scrollH < 2700, h.scrollH);
  check('P1-1', 'no more than 15 blocks even with every optional personal card showing (letter, timeline, one today card ...) - it was ~20 (the core of Home is 10: hero, rank, chips, league, Start Speaking, quick chips, Know About, type box, tiles, More for you)', h.blocks.length <= 15, h.blocks);
  check('P1-1', 'ONE "today" card: the generic challenge and "Where we left off" are never both shown', (h.goal ? 1 : 0) + (h.banner ? 1 : 0) === 1, { goal: h.goal, banner: h.banner });
  check('P1-1', 'the task-like cards (weekly missions, career goal) wait behind one "More for you" row, collapsed by default', h.more && h.more.btn && h.more.closed && /More for you/.test(h.more.label) && h.more.expanded === 'false', h.more);
  check('C-6', 'the Beta badge says only "Beta" (not "Testing - Unlimited")', h.beta === 'Beta', h.beta);
  check('C-8', 'the Hindi / English switch says what it changes', /Home chat, My Day/i.test(h.lgNote || ''), h.lgNote);
  await A.capture(p, 'home-active', { tag: 'H-390', full: true });
  // open the extras: they appear BELOW the row, the choice is remembered across a reload, and a second tap closes them
  await p.locator('#hmMoreBtn').click(); await sleep(400);
  const ex = await p.evaluate(() => { const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.display !== 'none'; }; const b = document.getElementById('hmMoreBtn').getBoundingClientRect();
    return { open: vis(document.getElementById('homeMissions')) || vis(document.getElementById('homeCareer')), below: [...document.querySelectorAll('#hmMoreBox > *')].filter(vis).every(e => e.getBoundingClientRect().top >= b.bottom - 1), label: document.getElementById('hmMoreBtn').innerText, exp: document.getElementById('hmMoreBtn').getAttribute('aria-expanded'),
      widths: [...document.querySelectorAll('#home #hmMoreBox > *, #home #letterCard, #home #journeyBanner, #home .sr-card, #home .hgoal')].filter(vis).map(e => Math.round(e.getBoundingClientRect().width)) }; });
  check('P1-1', 'tapping "More for you" shows the missions / goal cards below the row (and the row says "Show less")', ex.open && ex.below && /Show less/.test(ex.label) && ex.exp === 'true', ex);
  check('UI-10', 'the Home cards share one width on a phone (they were 340 / 400 px and full-width side by side)', new Set(ex.widths).size === 1, ex.widths);
  await A.capture(p, 'home-extras-open', { tag: 'H-390', full: false });
  await p.reload(); await sleep(2500);
  check('P1-1', 'the choice is remembered after a reload', await p.evaluate(() => document.getElementById('hmMoreBtn').getAttribute('aria-expanded') === 'true'));
  await p.locator('#hmMoreBtn').click(); await sleep(300);
  check('P1-1', 'a second tap closes them again', await p.evaluate(() => document.getElementById('hmMoreBtn').getAttribute('aria-expanded') === 'false' && document.getElementById('hmMoreBox').hidden));
  await c.close();
  // with a promise to continue, THAT is the one today card
  await A.post('/__audit/hook', { who: 'active', hook: 'practise your answer about your last project' });
  const cH = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const pH = await A.open(cH, '/', { settle: 2200 }); await sleep(1000);
  const th = await pH.evaluate(() => { const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.display !== 'none'; }; return { banner: vis(document.getElementById('journeyBanner')), goal: vis(document.getElementById('homeGoal')), text: document.getElementById('journeyBanner').innerText.replace(/\s+/g, ' ') }; });
  check('P1-1', 'a learner with a "continue next time" promise sees THAT as the one today card, with their own words', th.banner && !th.goal && /Last time: practise your answer/.test(th.text), th);
  await A.post('/__audit/hook', { who: 'active', hook: SEED_HOOK });
  await cH.close();

  // a brand-new learner's Home
  await A.post('/__audit/reset_learner', { who: 'keyed' });
  await A.setLang('keyed', 'en');
  const c2 = await A.ctx(browser, 'keyed', { firstRun: true, lang: 'en', viewport: { width: 390, height: 844 } });
  const p2 = await A.open(c2, '/', { settle: 2200 }); await sleep(1200);
  const n = await p2.evaluate(() => { const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
    return { goal: vis(document.getElementById('homeGoal')), career: vis(document.getElementById('homeCareer')), missions: vis(document.getElementById('homeMissions')), banner: vis(document.getElementById('journeyBanner')),
      chips: [...document.querySelectorAll('#hmChips .hm-chip')].map(b => b.innerText), start: (() => { const e = document.getElementById('startSpeak'); const r = e.getBoundingClientRect(); return { b: Math.round(r.bottom), vh: innerHeight }; })(),
      scrollH: document.querySelector('.wrap').scrollHeight };
  });
  check('P1-1', 'a brand-new learner sees no "Friday win", no "Set your goal", no weekly missions and no "where we left off" - Start Speaking is the one big action', !n.goal && !n.career && !n.missions && !n.banner, n);
  check('C-7', 'their chips are "Where do I start?" and "Interview practice" (not "my routine / my progress")', n.chips.some(x => /Where do I start/.test(x)) && n.chips.some(x => /Interview practice/.test(x)) && !n.chips.some(x => /routine|progress/i.test(x)), n.chips);
  check('P1-3', 'Start Speaking is on the first screen without scrolling', n.start.b < n.start.vh, n.start);
  await A.capture(p2, 'home-new', { tag: 'H-390', full: true });
  // chips for the established learner stay as they were
  await c2.close();

  // the More sheet
  const c3 = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p3 = await A.open(c3, '/', { settle: 1500 });
  await p3.evaluate(() => document.querySelector('.btab[data-tab="more"]').click()); await sleep(900);
  const m = await p3.evaluate(() => ({ text: document.getElementById('msheet').innerText, legal: [...document.querySelectorAll('#msheet .mlegal a')].map(a => ({ t: a.innerText, href: a.getAttribute('href'), h: Math.round(a.getBoundingClientRect().height), tg: a.target })) }));
  check('C-4', 'Privacy, Terms and Delete my data moved into More (each a 44 px target, opening in a new tab)', m.legal.length === 3 && m.legal.every(l => l.h >= 44 && l.tg === '_blank') && m.legal.map(l => l.href).join() === '/privacy,/terms,/account-deletion', m.legal);
  check('C-5', 'the internal words are gone: "My AI keys", no "DuSu keys / Mode - Personal or Office"', /My AI keys/.test(m.text) && !/Personal or Office|DuSu keys \/ Mode/.test(m.text), m.text);
  check('P0-2', 'More says "Plans", not "Subscribe"', /Plans/.test(m.text) && !/Subscribe/.test(m.text), m.text);
  await A.capture(p3, 'more-sheet', { tag: 'H-390', full: false });
  await c3.close();

  // the Practice hub
  const c4 = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p4 = await A.open(c4, '/', { settle: 1500 }); await p4.evaluate(() => navTo('/practice')); await sleep(1500);
  const pr = await p4.evaluate(() => { const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
    const cards = [...document.querySelectorAll('#practice .mode-card, #practice .pr-entry')].filter(vis);
    return { cards: cards.map(e => ({ t: (e.querySelector('h3, b') || {}).innerText, d: ((e.querySelector('p, small') || {}).innerText || '').slice(0, 60), w: Math.round(e.getBoundingClientRect().width), tag: e.querySelector('h3') ? getComputedStyle(e.querySelector('h3'), '::before').content : '' })),
      heads: [...document.querySelectorAll('#practice .prac-h')].filter(vis).length, soon: vis(document.getElementById('prSoon') || document.createElement('i')) };
  });
  check('UI-9', 'the Practice hub is one list of six doors with the same card shape (all as wide as the column)', pr.cards.length === 6 && new Set(pr.cards.map(x => x.w)).size === 1, pr.cards);
  check('P1-2', 'each door carries the feature\'s one name', pr.cards.map(x => x.t).join('|') === 'Learn|Face to Face Talk|Interview Prep|Practice Room|Job Interview Practice|Grammar Coach', pr.cards.map(x => x.t));
  check('P1-3', 'each door says what it does for you, and the recommendation tag is visible on a phone ("Start here")', pr.cards.every(x => x.d.length > 8) && pr.cards.some(x => /Start here/.test(x.tag)), pr.cards);
  check('UI-9', 'the duplicate centred headings and the "More modes coming soon" line are gone on a phone', pr.heads === 0 && !pr.soon, pr);
  await A.capture(p4, 'practice-hub', { tag: 'H-390', full: true });
  await c4.close();
  const c5 = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 1280, height: 900 } });
  const p5 = await A.open(c5, '/', { settle: 1500 }); await p5.evaluate(() => navTo('/practice')); await sleep(1500);
  const pd = await p5.evaluate(() => ({ heads: [...document.querySelectorAll('#practice .prac-h')].filter(e => e.getBoundingClientRect().width > 0).map(e => e.innerText), badges: [...document.querySelectorAll('#practice .mc-badge')].filter(e => e.getBoundingClientRect().width > 0).map(e => e.innerText) }));
  check('UI-10', 'desktop keeps its own three-column hub with its headings and badges, with the new names and outcomes', pd.heads.length === 3 && /Say it in Hindi/.test(pd.heads[0]) && pd.badges.length === 3, pd);
  await A.capture(p5, 'practice-hub', { tag: 'H-1280', full: false });
  await c5.close();

  // empty states
  const c6 = await A.ctx(browser, 'keyed', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p6 = await A.open(c6, '/', { settle: 1500 });
  await p6.evaluate(() => navTo('/interview-reports')); await sleep(1800);
  const e1 = await p6.evaluate(() => ({ es: !!document.querySelector('#interviewReports .es, #irList .es'), btn: (document.querySelector('#irList .es-b') || {}).innerText, title: (document.querySelector('#irList .es-t') || {}).innerText }));
  check('P1-4', 'Interview Reports with no reports: an icon, one sentence and a button ("Start an interview")', e1.es && /Start an interview/.test(e1.btn || ''), e1);
  await A.capture(p6, 'empty-interview-reports', { tag: 'H-390', full: false });
  await p6.locator('#irList .es-b').click(); await sleep(1200);
  check('P1-4', '... and the button takes the learner to the interview setup', (await sid(p6)) === 'setup', await sid(p6));
  await p6.evaluate(() => navTo('/grammar/mistakes')); await sleep(1800);
  const e2 = await p6.evaluate(() => ({ es: !!document.querySelector('#gc .es'), btn: (document.querySelector('#gc .es-b') || {}).innerText }));
  check('P1-4', 'Grammar Coach - Mistakes with nothing recorded: icon + sentence + a button to the thing that fills it', e2.es && /Face to Face Talk/.test(e2.btn || ''), e2);
  await A.capture(p6, 'empty-grammar-mistakes', { tag: 'H-390', full: false });
  for (const [tab, label] of [['/grammar/sentences', 'Sentences'], ['/grammar/practice', 'Practice'], ['/grammar', 'Overview']]) {
    await p6.evaluate(x => navTo(x), tab); await sleep(1500);
    check('P1-4', `Grammar Coach - ${label} with nothing yet has the same empty state`, await p6.evaluate(() => !!document.querySelector('#gc .es .es-b')));
  }
  await p6.evaluate(() => navTo('/practice-room')); await sleep(1800);
  const e3 = await p6.evaluate(() => ({ es: !!document.querySelector('#prList .es'), btn: (document.querySelector('#prList .es-b') || {}).innerText }));
  check('P1-4', 'Practice Room history with no attempts: icon + sentence + "Start a presentation"', e3.es && /Start a presentation/.test(e3.btn || ''), e3);
  await p6.locator('#prList .es-b').click(); await sleep(1500);
  check('P1-4', '... which opens the presentation setup', (await sid(p6)) === 'prSetup', await sid(p6));
  await p6.evaluate(() => navTo('/career-path')); await sleep(1200);
  check('P1-4', 'Career Path with no goal has its own "Set your goal" button (verified - it already did)', await p6.evaluate(() => !!document.querySelector('#careerBody [data-career-setgoal]')));
  await c6.close();

  // copy
  const c7 = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 } });
  const p7 = await A.open(c7, '/', { settle: 1500 });
  await p7.evaluate(() => navTo('/interview')); await sleep(900);
  const r = await p7.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, value: document.getElementById('role').value, ph: document.getElementById('role').placeholder, labelFor: (document.querySelector('label[for=role]') || {}).innerText }));
  check('C-1', 'the interview role is empty with a placeholder (it was pre-filled "Frontend Developer" for everyone) and its label is attached', r.value === '' && /Frontend Developer/.test(r.ph) && /interview role/i.test(r.labelFor || ''), r);
  const lb = await p7.evaluate(async () => { navTo('/league'); await new Promise(r => setTimeout(r, 2200)); return document.getElementById('league').innerText; });
  check('C-3', 'no "1 sessions" in the weekly league rows (one "1 session", the others plural)', !/\b1 sessions\b/.test(lb) && /\b1 session\b/.test(lb) && /\b[2-9] sessions\b/.test(lb), lb.slice(0, 500));
  const fn = await p7.evaluate(() => ({ a: normTime('8:30 pm'), b: normTime('7:00\u202Fam'), c: normTime('Tue, 5 Nov, 8:30\u202Fpm'), d: plural(1, 'session'), e: plural(2, 'session'), f: plural(0, 'session') }));
  check('C-3', 'one time style: 8:30 PM everywhere (lower-case and narrow-space variants are normalised)', fn.a === '8:30 PM' && fn.b === '7:00 AM' && fn.c === 'Tue, 5 Nov, 8:30 PM', fn);
  check('C-3', 'plural() says "1 session", "2 sessions", "0 sessions"', fn.d === '1 session' && fn.e === '2 sessions' && fn.f === '0 sessions', fn);
  const hi = await p7.evaluate(() => JSON.stringify(HINDI) + JSON.stringify(LEARN_SAY.hi));
  check('C-2', 'the spoken Hindi of Learn / Daily uses one register ("tum"), like the server\'s replies - no "aap" forms left in those lines', !/आप|बोलिए|दोहराइए|कृपया/.test(hi), hi);
  await c7.close();
  // ... and the Hindi the HOME CHAT shows around DuSu's own tum replies (orb hints, the headphones tip, thinking steps, limit lines): it was "aap" (बोलिए, लगाइए, आपके)
  await A.setLang('active', 'hi');
  const c8 = await A.ctx(browser, 'active', { lang: 'hi', viewport: { width: 390, height: 844 } });
  const p8 = await A.open(c8, '/home-chat', { settle: 3800 });
  const AAP = /आप(?:का|की|के|ने|को)?(?![\u0900-\u097F])|बोलिए|रुकिए|सुनिए|लगाइए|कीजिए|दीजिए|जाँचिए|आइए|दबाइए|कृपया/;
  const hc = await p8.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, text: document.getElementById('session').innerText,
    keys: ['tipPhones', 'orbReady', 'orbReadyHint', 'orbReady2', 'orbReady2Hint', 'orbListen', 'orbListenHint', 'orbThink', 'orbSpeak', 'orbSpeakHint', 'orbMicBlocked', 'orbMicBlockedHint', 'orbMicTrouble', 'orbMicTroubleHint',
           'orbPaused', 'orbPausedHint', 'orbWrap', 'keysLimit', 'limitReached', 'th_think', 'th_start', 'th_wrap', 'connErr', 'connErrHint', 'connLost', 'connLostHint'].map(k => k + '=' + JSON.stringify(lgt(k, { n: 20 }))).join(' ') }));
  check('C-2', 'the Hindi on the Home chat screen is one register - tum, like DuSu\'s own replies - in what is on screen AND in every orb / tip / thinking / limit line it can show (no बोलिए, लगाइए, आपके, कीजिए ...)', hc.screen === 'session' && !AAP.test(hc.text) && !AAP.test(hc.keys) && /बोलो/.test(hc.keys), { screen: hc.screen, onScreen: (hc.text.match(AAP) || [])[0], inTable: (hc.keys.match(new RegExp('.{12}(' + AAP.source + ').{6}', 'u')) || [])[0] });
  await c8.close(); await A.setLang('active', 'en');
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ N: retired names (static, over the shipped source)
async function N(browser) {
  const src = fs.readFileSync(process.env.HTML_OVERRIDE || '/repo/backend/test_client.html', 'utf8');       // a planted-bug copy (mutants.sh) is checked instead of the real file
  const code = src.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '').split('\n').filter(l => !/^\s*\/\//.test(l)).map(l => l.replace(/\s\/\/ .*$/, '')).join('\n');
  for (const retired of ['Confidence Talk', 'Learning Mode', 'Convey your thoughts', 'Face to Face English Talk', 'Modes (coming soon)', 'Face-to-Face']) {
    const hits = code.split('\n').filter(l => l.includes(retired)).map(l => l.trim().slice(0, 140));
    check('P1-2', `the retired name "${retired}" no longer appears in anything a learner can see`, hits.length === 0, hits.slice(0, 4));
  }
  check('UI-7', 'the old brand-gold glow values (rgba 212,175,55) are gone from the page - every one is an accent tint now', !/rgba\(\s*212\s*,\s*175\s*,\s*55/.test(src), (src.match(/rgba\(\s*212\s*,\s*175\s*,\s*55[^)]*\)/g) || []).length);
  const css = (src.match(/<style[^>]*>[\s\S]*?<\/style>/g) || []).join('\n');
  const smallDecl = [...src.matchAll(/font-size:\s*(\d*\.?\d+)px/g)].filter(m => +m[1] > 0 && +m[1] < 12).map(m => m[0]);
  check('UI-2', 'no font-size under 12 px is declared anywhere in the page (CSS, inline styles or script)', smallDecl.length === 0, smallDecl.slice(0, 6));
  check('UI-1', 'no rule says only "tabular-nums" (it must keep lining figures)', ![...css.matchAll(/font-variant-numeric:\s*([^;}]*)/g)].some(m => !/lining-nums/.test(m[1])), [...css.matchAll(/font-variant-numeric:\s*([^;}]*)/g)].map(m => m[1]));
  check('P0-3a', 'the page does not reference /logo.png (login card, header, icons, manifest all use the small versioned files)', !/["'(=]\/logo\.png/.test(src.replace(/<link[^>]*rel="manifest"[^>]*>/, '')), (src.match(/.{30}\/logo\.png.{10}/g) || []).slice(0, 3));
  { // Cloudflare's "Email Address Obfuscation" rewrites any address it finds in the page markup, injects a blocking decoder script ahead of the app's script and drops the page's ETag
    const markup = src.replace(/<!--[\s\S]*?-->/g, '').replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<style[\s\S]*?<\/style>/gi, '');
    const mails = markup.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}|mailto:/gi) || [];
    check('P0-3b', 'no email address or mailto: link is written into the page markup: Cloudflare rewrites it, injects a blocking decoder script before the app script and, because it changed the body, drops the page ETag (measured on the live site 2026-10-31: no repeat open could be a 304)', mails.length === 0, mails.slice(0, 4));
    const c = await A.ctx(browser, 'keyed', { lang: 'en', viewport: { width: 390, height: 844 }, html: OLD_PAGE() });
    const p = await A.open(c, '/', { settle: 1500 });
    const m = await p.evaluate(() => { openHelp(); const a = document.getElementById('helpMail'); return a ? { href: a.getAttribute('href'), text: a.textContent } : null; });
    check('P0-3b', 'the Help & Feedback screen still shows the support address as a working mailto: link (assembled in script, not written in the page)', !!m && m.href === 'mailto:support@ranabrothers.online' && m.text === 'support@ranabrothers.online', m);
    await c.close();
  }
  check('V-9', 'the card-border token `--glass-brd` is a plain rgba: a custom property built with color-mix() is invalid on a browser without it, and then EVERY border using it vanishes', /--glass-brd:\s*rgba\(/.test(src), (src.match(/--glass-brd:[^;]*;/) || [''])[0]);
  const nullCalls = [...code.matchAll(/renderSessionResult\(null[^)]*\)/g)].map(m => m[0]);
  check('V-3', 'every call that shows an empty session result says whether the learner spoke (3 call sites)', nullCalls.length === 3 && nullCalls.every(c => /dailyInputs > 0/.test(c)), nullCalls);
  const mainPy = fs.readFileSync('/repo/backend/app/main.py', 'utf8');
  check('C-5', 'no message anywhere still points a learner to "DuSu keys": the More row is called "My AI keys" (the page and the server\'s fallback texts)', !/DuSu keys/.test(src) && !/DuSu keys/.test(mainPy), [(src.match(/.{30}DuSu keys.{10}/g) || []).slice(0, 2), (mainPy.match(/.{30}DuSu keys.{10}/g) || []).slice(0, 2)]);
  const reg = fs.readFileSync('/repo/backend/app/home_content.py', 'utf8');
  check('P1-2', 'the server\'s own registry (Know About, the tiles) uses the same six names', ['Daily Talk', 'Face to Face Talk', 'Interview Prep', 'Learn', 'Practice Room', 'Job Interview Practice', 'Grammar Coach', 'My Day'].every(n => reg.includes('"title": "' + n + '"')));
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ in-page helpers for the UI-system checks
const INSTALL = () => {
  const vis = e => { const r = e.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return false; for (let n = e; n && n !== document.body; n = n.parentElement) { const s = getComputedStyle(n); if (s.display === 'none' || s.visibility === 'hidden') return false; if (n.hasAttribute && n.hasAttribute('hidden')) return false; } return true; };
  const lab = e => (e.id ? '#' + e.id : e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '')) + ' "' + ((e.getAttribute('aria-label') || e.innerText || e.value || '').trim().replace(/\s+/g, ' ').slice(0, 26)) + '"';
  const ownText = e => [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').trim();
  const parse = s => { const m = s && s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const mix = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const bgOf = e => { const layers = []; for (let n = e; n && n.nodeType === 1; n = n.parentElement) { const cs = getComputedStyle(n); if (cs.backgroundImage !== 'none' && n !== document.body) return null; const b = parse(cs.backgroundColor); if (b && b.a > 0) { layers.push(b); if (b.a >= 0.99) break; } } let base = { r: 11, g: 16, b: 32, a: 1 }; for (let i = layers.length - 1; i >= 0; i--) base = mix(layers[i], base); return base; };
  window.__aud = {
    vis, lab,
    tiny: () => [...document.querySelectorAll('body *')].filter(vis).filter(e => ownText(e).length > 1).map(e => ({ l: lab(e), px: parseFloat(getComputedStyle(e).fontSize) })).filter(x => x.px > 0 && x.px < 12),
    small: () => [...document.querySelectorAll('a,button,input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select,textarea,summary,[role=button],[role=tab],[onclick]')].filter(vis)
      .map(e => { const r = e.getBoundingClientRect(); return { l: lab(e), w: Math.round(r.width), h: Math.round(r.height) }; }).filter(x => (x.w < 44 || x.h < 44) && !(x.w <= 2 && x.h <= 2)),   // a 1 x 1 input is a visually hidden file input; its label is the real button
    lowContrast: () => { const out = []; for (const e of [...document.querySelectorAll('body *')].filter(vis)) { const t = ownText(e); if (t.length < 2 || !/[\p{L}\p{N}]/u.test(t)) continue; const cs = getComputedStyle(e); const fg = parse(cs.color), bg = bgOf(e); if (!fg || !bg) continue;
        const f = mix(fg, bg); const L1 = lum(f), L2 = lum(bg); const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05); const px = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700; const need = (px >= 24 || (px >= 18.66 && bold)) ? 3 : 4.5;
        if (ratio < need) out.push({ l: lab(e), ratio: Math.round(ratio * 100) / 100, need, text: t.slice(0, 24) }); } return out; },
  };
};
// all ten digits, drawn in the serif display font with whatever numeral style the page gives its text, photographed and measured IN THE BROWSER: does each digit reach the same height and stand on the same baseline?
async function digitInk(page, family) {
  await page.evaluate(fam => { const old = document.getElementById('__dg'); if (old) old.remove(); const d = document.createElement('div'); d.id = '__dg';
    d.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;padding:24px;background:#000;color:#fff;font-family:' + fam + ';font-weight:600;font-size:110px;line-height:1.5;white-space:nowrap;letter-spacing:0';
    d.innerHTML = [...'0123456789'].map(c => '<span>' + c + '</span>').join('<i style="display:inline-block;width:.5em"></i>'); document.body.appendChild(d); }, family);
  await page.evaluate(() => document.fonts.ready); await sleep(250);
  const buf = await page.locator('#__dg').screenshot();
  const r = await page.evaluate(async b64 => {
    const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
    const cv = document.createElement('canvas'); cv.width = img.width; cv.height = img.height; const cx = cv.getContext('2d'); cx.drawImage(img, 0, 0);
    const { data, width, height } = cx.getImageData(0, 0, img.width, img.height); const top = new Array(width).fill(1e9), bot = new Array(width).fill(-1);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) { if (data[(y * width + x) * 4] > 110) { if (y < top[x]) top[x] = y; if (y > bot[x]) bot[x] = y; } }
    const groups = []; let cur = null;
    for (let x = 0; x < width; x++) { if (bot[x] >= 0) { if (!cur) cur = { top: top[x], bot: bot[x] }; else { cur.top = Math.min(cur.top, top[x]); cur.bot = Math.max(cur.bot, bot[x]); } } else if (cur) { groups.push(cur); cur = null; } }
    if (cur) groups.push(cur);
    const hs = groups.map(g => g.bot - g.top), H = Math.max(...hs, 1);
    return { groups: groups.length, h: H, topSpread: +((Math.max(...groups.map(g => g.top)) - Math.min(...groups.map(g => g.top))) / H).toFixed(3), botSpread: +((Math.max(...groups.map(g => g.bot)) - Math.min(...groups.map(g => g.bot))) / H).toFixed(3), heights: hs };
  }, buf.toString('base64'));
  await page.evaluate(() => document.getElementById('__dg').remove());
  return r;
}
const OLD_PAGE = () => { const f = process.env.OLD_HTML || process.env.HTML_OVERRIDE; return f && fs.existsSync(f) ? fs.readFileSync(f, 'utf8') : null; };   // OLD_HTML=<the page before the fixes> (or HTML_OVERRIDE=<a planted-bug copy>): the same checks must FAIL there

// ------------------------------------------------------------------------------------------------------------------------------------------------ U: the UI system (numerals, type, header, targets, My Day, icons, tabs, badges, ranks, journey, dashboard, contrast, moods)
async function U(browser) {
  const OLD = OLD_PAGE();
  const mk = (who, vp, extra = {}) => A.ctx(browser, who, Object.assign({ lang: 'en', viewport: vp, html: OLD }, extra));
  const open = async (c, route = '/') => { const p = await A.open(c, route, { settle: 2000 }); await p.evaluate(INSTALL); return p; };
  const go = async (p, route, ms = 1500) => { await p.evaluate(r => navTo(r), route); await sleep(ms); await p.evaluate(INSTALL); };
  await A.setLang('active', 'en');
  // some real rows for My Day (idempotent by client_key)
  const ymd = (d = 0) => new Date(Date.now() + d * 864e5).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
  await A.api('active', '/planner/tasks', 'POST', { client_key: 'u-t1', title: 'Revise tenses for 20 minutes', priority: 1, remind: 'none', due_date: ymd(0) });
  await A.api('active', '/planner/tasks', 'POST', { client_key: 'u-t2', title: 'Finish slides for the project demo', priority: 2, remind: 'none', due_date: ymd(1) });
  await A.api('active', '/planner/habits', 'POST', { client_key: 'u-h1', title: 'Speak English for 10 minutes', target: 10, unit: 'min', partial_ok: true, schedule: { days: 'daily', times: [] } });
  await A.api('active', '/planner/goals', 'POST', { client_key: 'u-g1', title: 'Crack my first campus interview', why: 'A software job.', target_date: ymd(30), daily_minutes: 20, milestones: ['Finish my resume', 'Do 5 mock interviews'] });
  await A.api('active', '/planner/reminders', 'POST', { client_key: 'u-r1', title: 'Call Papa about the fee form', date: ymd(0), time: '23:30' });

  // ---- UI-1 numerals
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c);
    const body = await p.evaluate(() => getComputedStyle(document.body).fontVariantNumeric);
    check('UI-1', 'the whole app asks for lining numerals (font-variant-numeric on the body)', /lining-nums/.test(body), body);
    const decls = await p.evaluate(() => { const out = []; const walk = rules => { for (const r of rules) { if (r.cssRules && !r.style) walk(r.cssRules); if (r.style && r.style.fontVariantNumeric) out.push(r.selectorText + ' {' + r.style.fontVariantNumeric + '}'); } }; for (const ss of document.styleSheets) { try { walk(ss.cssRules); } catch (e) {} } return out; });
    check('UI-1', 'no stylesheet rule switches them off again (a rule that says only "tabular-nums" would bring old-style digits back in the serif font - the two big timers did; `font: inherit` resets are fine, they inherit the body)', decls.every(d => /lining-nums|\{inherit\}/.test(d)), decls.filter(d => !/lining-nums|\{inherit\}/.test(d)));
    const ink = await digitInk(p, 'var(--font-d)');
    check('UI-1', 'in the serif display font all ten digits reach the same height and stand on the same baseline - "0" is not a small "o", "1" is not an "I" (top spread ' + ink.topSpread + ', baseline spread ' + ink.botSpread + ' of the digit height)', ink.groups === 10 && ink.topSpread <= 0.08 && ink.botSpread <= 0.08, ink);
    await go(p, '/leaderboard');
    const lb = await p.evaluate(() => [...document.querySelectorAll('#leaderboard *')].filter(e => window.__aud.vis(e) && /\d/.test([...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('')) ).map(e => getComputedStyle(e).fontVariantNumeric));
    check('UI-1', 'the numbers on Ranks (XP, ranks) are drawn with lining figures', lb.length > 0 && lb.every(v => /lining-nums/.test(v)), lb.slice(0, 4));
    await c.close();
  }

  // ---- UI-2 / UI-4 / A-1: type floor, tap targets, contrast on the main screens (phone)
  const MAIN = ['/', '/practice', '/learning-journey', '/leaderboard', '/league', '/achievements', '/profile', '/my-day', '/my-day/tasks', '/my-day/goals', '/my-day/habits', '/my-day/reminders', '/my-day/settings',
    '/grammar', '/grammar/mistakes', '/grammar/sentences', '/grammar/practice', '/grammar/rules', '/grammar/settings', '/subscribe', '/interview-reports', '/career-path', '/keys', '/resume-interview',
    '/resume-interview/resume', '/resume-interview/job', '/resume-interview/settings', '/practice-room', '/about', '/interview', '/learn', '/daily-talk', '/face-to-face', '/home-chat'];
  for (const [w, h] of [[390, 844], [360, 740]]) {
    const c = await mk('active', { width: w, height: h }); const p = await open(c);
    const tinyAll = [], smallAll = [], lowAll = [], overflow = [];
    for (const r of MAIN) {
      await go(p, r, 1300);
      const m = await p.evaluate(() => ({ tiny: window.__aud.tiny(), small: window.__aud.small(), low: window.__aud.lowContrast(), ov: document.documentElement.scrollWidth > window.innerWidth + 1 || (document.querySelector('.wrap').scrollWidth > document.querySelector('.wrap').clientWidth + 1), screen: (document.querySelector('.screen.on') || {}).id }));
      tinyAll.push(...m.tiny.map(x => r + ' ' + x.l + ' ' + x.px)); smallAll.push(...m.small.map(x => r + ' ' + x.l + ' ' + x.w + 'x' + x.h)); lowAll.push(...m.low.map(x => r + ' ' + x.l + ' ' + x.ratio + ':1'));
      if (m.ov) overflow.push(r + ' (' + m.screen + ')');
    }
    check('UI-2', `${w} px: no text on any of ${MAIN.length} screens is smaller than 12 px (the audit: bottom-nav labels 10.5, chips 10-11, tiles 11.5)`, tinyAll.length === 0, tinyAll.slice(0, 8));
    check('UI-4', `${w} px: every tap target on those screens is at least 44 x 44`, smallAll.length === 0, [...new Set(smallAll)].slice(0, 6));
    check('A-1', `${w} px: no text on those screens misses WCAG AA contrast (4.5:1; 3:1 for large text) - the secondary text was 4.46:1`, lowAll.length === 0, lowAll.slice(0, 8));
    check('UI-2', `${w} px: none of those screens scrolls sideways after the larger type`, overflow.length === 0, overflow);
    await c.close();
  }
  { // the type scale exists
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c);
    const tok = await p.evaluate(() => { const cs = getComputedStyle(document.documentElement); return ['--fs-xs', '--fs-sm', '--fs-md', '--fs-base', '--fs-lg', '--fs-xl'].map(k => cs.getPropertyValue(k).trim()); });
    check('UI-2', 'the six-step type scale is defined as variables (12 / 13 / 14 / 16 / 20 / 26 px) so new rules have one place to look', tok.join() === '12px,13px,14px,16px,20px,26px', tok);
    await c.close();
  }

  // ---- UI-3 header: logo + one avatar button on phones and tablets; the richer desktop header is unchanged
  for (const [w, h] of [[360, 740], [390, 844], [768, 1000], [1024, 900]]) {
    const c = await mk('active', { width: w, height: h }); const p = await open(c);
    const hd = await p.evaluate(() => { const vis = window.__aud.vis; const bx = e => { if (!e) return null; const r = e.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; };
      const hdr = document.querySelector('header'); const av = document.getElementById('uAvBtn'); const u = document.getElementById('uInit'); const img = document.getElementById('uAvatar');
      const shown = [...hdr.querySelectorAll('*')].filter(vis).filter(e => e.children.length === 0 || /^(BUTTON|A|IMG)$/.test(e.tagName)).map(e => (e.id || e.className || e.tagName).toString().split(' ')[0]);
      return { shown, beta: vis(hdr.querySelector('.beta-badge')), day: vis(document.getElementById('dayChip')), who: vis(hdr.querySelector('.uwho')), alias: vis(document.getElementById('uAlias')), female: /♀/.test(hdr.innerText) || !!document.querySelector('.voicebar'),
        av: bx(av), name: av.getAttribute('aria-label'), isButton: av.tagName === 'BUTTON', faceBox: bx(vis(img) ? img : u), docOv: document.documentElement.scrollWidth > innerWidth + 1, hdrOv: hdr.scrollWidth > hdr.clientWidth + 1 }; });
    check('UI-3', `${w} px: the header is the logo and ONE avatar button - no "Beta", no "Day N", no alias, no name, no dead ♀ button`, !hd.beta && !hd.day && !hd.who && !hd.alias && !hd.female && hd.shown.length <= 4, hd);
    check('UI-3', `${w} px: the avatar is a real button named "Your profile", at least 44 x 44, and the picture inside is a circle (it was squashed into an oval at 360 px)`, hd.isButton && /profile/i.test(hd.name) && hd.av.w >= 44 && hd.av.h >= 44 && hd.faceBox.w === hd.faceBox.h, hd);
    check('UI-3', `${w} px: nothing in the header overflows`, !hd.docOv && !hd.hdrOv, hd);
    if (w === 390) {
      await p.locator('#uAvBtn').click(); await sleep(1000);
      check('UI-3', 'the avatar opens Profile - where the name, the leaderboard alias and Sign out (in More) now live', await sid(p) === 'profile' && /BoldSparrow/.test(await text(p, '#profile') || '') && /Asha Kumari/.test(await text(p, '#profile') || ''), await sid(p));
      await A.capture(p, 'header-390', { tag: 'U-390', full: false });
    }
    await c.close();
  }
  { // desktop keeps its own header
    const c = await mk('active', { width: 1280, height: 900 }); const p = await open(c);
    const d = await p.evaluate(() => { const vis = window.__aud.vis; return { beta: vis(document.querySelector('.beta-badge')), day: vis(document.getElementById('dayChip')), alias: vis(document.getElementById('uAlias')), name: vis(document.getElementById('uName')) }; });
    check('UI-3', 'desktop (>= 1200 px) keeps its richer header: Beta, Day N, name and alias', d.beta && d.day && d.alias && d.name, d);
    await c.close();
  }

  { // the Home cards share one width on desktop (the career card was 560 px beside four 420 px cards)
    const c = await mk('active', { width: 1280, height: 900 }); const p = await open(c);
    await p.locator('#hmMoreBtn').click().catch(() => {}); await sleep(400);                    // the missions / career cards live behind "More for you"
    const w = await p.evaluate(() => Object.fromEntries(['speakerRank', 'leagueChip', 'homeGoal', 'homeMissions', 'homeCareer'].map(id => { const e = document.getElementById(id); const was = e.hidden; e.hidden = false; const x = Math.round(e.getBoundingClientRect().width); e.hidden = was; return [id, x]; })));
    check('UI-10', 'desktop: the five Home cards (rank, league, goal, missions, career) are one width - 420 px (the career card was 560)', Object.values(w).every(x => x === 420), w);
    await c.close();
  }
  { // with the Install switch ON the phone header still fits: logo + install pill + avatar, every one a 44 px target
    await A.settings({ install_mode: 'on' });
    for (const [w, h] of [[360, 740], [320, 640]]) {
      const c = await mk('active', { width: w, height: h }); const p = await open(c); await sleep(900);
      const hd = await p.evaluate(() => { const vis = window.__aud.vis; const hdr = document.querySelector('header'); const pill = document.getElementById('instPill'); const av = document.getElementById('uAvBtn'); const r = e => { const b = e.getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; };
        return { pillShown: !!pill && vis(pill), pill: pill && r(pill), av: r(av), ov: hdr.scrollWidth > hdr.clientWidth + 1, docOv: document.documentElement.scrollWidth > innerWidth + 1, overlap: pill && vis(pill) ? pill.getBoundingClientRect().right > av.getBoundingClientRect().left : false }; });
      check('UI-3', `${w} px with the Install switch on: the header holds the logo, the install pill and the avatar - no overflow, no overlap, both buttons 44 x 44`, hd.pillShown && hd.pill[0] >= 44 && hd.pill[1] >= 44 && hd.av[0] >= 44 && !hd.ov && !hd.docOv && !hd.overlap, hd);
      await c.close();
    }
    await A.settings({ install_mode: 'off' });
  }

  // ---- UI-8 the Home language pill is the first thing in the stack (it sat at the bottom of the first screen, cut by the nav) + Grammar Coach tabs
  for (const [w, h] of [[360, 740], [390, 800], [768, 1000]]) {
    const c = await mk('active', { width: w, height: h }); const p = await open(c); await sleep(700);
    const lg = await p.evaluate(() => { const b = e => { if (!e) return null; const r = e.getBoundingClientRect(); return { t: Math.round(r.top), b: Math.round(r.bottom), l: Math.round(r.left), r: Math.round(r.right), w: Math.round(r.width), h: Math.round(r.height) }; };
      const pill = document.querySelector('#home .lg-row .lg-sw'); const nav = document.getElementById('bnav'); const start = document.getElementById('startSpeak');
      return { pill: b(pill), nav: b(nav), start: b(start), shown: !!pill && window.__aud.vis(pill), btns: pill ? [...pill.querySelectorAll('button')].map(x => { const r = x.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }) : [], note: (document.getElementById('lgNote') || {}).innerText || '', vw: innerWidth }; });
    check('UI-8', `${w}x${h}: the Hindi / English pill is fully visible on the first screen (above the bottom nav), not cut in half`, lg.shown && lg.pill.b <= lg.nav.t && lg.pill.r <= lg.vw && lg.btns.every(([bw, bh]) => bw >= 44 && bh >= 44), lg);
    check('UI-8', `${w}x${h}: Start Speaking is still on the first screen, above the nav`, lg.start.b <= lg.nav.t, lg);
    if (w === 390) { check('C-8', 'the one-line note that says what the switch changes is still on Home (now at the end of the page)', /Home chat, My Day and Know About DuSu/.test(lg.note) && /Hindi \/ English/.test(lg.note), lg.note); await A.capture(p, 'home-pill', { tag: 'U-390', full: false }); }
    await c.close();
  }
  {
    const c = await mk('active', { width: 1280, height: 900 }); const p = await open(c);
    const d = await p.evaluate(() => { const pill = document.querySelector('#home .lg-row .lg-sw'); const start = document.getElementById('startSpeak'); return { pillTop: Math.round(pill.getBoundingClientRect().top), startTop: Math.round(start.getBoundingClientRect().top), shown: window.__aud.vis(pill) }; });
    check('UI-8', 'desktop keeps the pill row under the type box, below Start Speaking (unchanged)', d.shown && d.pillTop > d.startTop, d);
    await c.close();
  }
  for (const [w, h] of [[390, 844], [360, 740], [320, 640]]) {
    const c = await mk('active', { width: w, height: h }); const p = await open(c); await go(p, '/grammar', 1600);
    const t = await p.evaluate(() => [...document.querySelectorAll('#gcTabs [role=tab]')].map(x => ({ t: x.innerText.trim(), cut: x.scrollWidth > x.clientWidth + 1 && getComputedStyle(x).overflow !== 'visible' && getComputedStyle(x).textOverflow === 'ellipsis', h: Math.round(x.getBoundingClientRect().height) })));
    check('UI-8', `${w} px: all five Grammar Coach tabs show their whole word (no "Senten...") and are 44 px high`, t.length === 5 && t.every(x => !x.cut && x.h >= 44), t);
    if (w === 360) await A.capture(p, 'gc-tabs', { tag: 'U-360', full: false });
    await c.close();
  }

  // ---- UI-5 My Day: one header row, one add button, the labels in one language
  for (const [w, h] of [[360, 740], [390, 844]]) {
    const c = await mk('active', { width: w, height: h }); const p = await open(c); await go(p, '/my-day', 1800);
    const m = await p.evaluate(() => { const b = id => { const e = document.getElementById(id); if (!e) return null; const r = e.getBoundingClientRect(); return { t: Math.round(r.top), h: Math.round(r.height), w: Math.round(r.width) }; };
      return { back: b('plBack'), bell: b('plBell'), gear: b('plGear'), title: b('plTitle'), tabs: [...document.querySelectorAll('#plTabs [role=tab]')].map(t => t.innerText.trim()), fab: [...document.querySelectorAll('.pl-fab')].some(window.__aud.vis),
        add: [...document.querySelectorAll('.pl-addbtn')].filter(window.__aud.vis).map(e => e.innerText.trim()), chk: [...document.querySelectorAll('#plBody .pl-chk')].map(e => (e.innerText || '').trim()), ov: document.documentElement.scrollWidth > innerWidth + 1 }; });
    check('UI-5', `${w} px: Back, the title, the bell and the gear sit on ONE row (the gear used to wrap onto a row of its own)`, m.back && m.bell && m.gear && Math.abs(m.bell.t - m.back.t) <= 6 && Math.abs(m.gear.t - m.back.t) <= 6, m);
    check('UI-5', `${w} px: ONE add button, labelled - the round "+" that covered the row icons is gone`, !m.fab && m.add.length === 1 && /Add/.test(m.add[0]), { fab: m.fab, add: m.add });
    check('UI-5', `${w} px: the tabs are all in the learner's language (English here - no lone Hindi "आज")`, m.tabs.length === 5 && !m.tabs.some(t => /[ऀ-ॿ]/.test(t)), m.tabs);
    check('UI-6', `${w} px: My Day's check circles are drawn shapes, not emoji glyphs (no ⬜ / ☐ text inside)`, m.chk.length > 0 && m.chk.every(t => t === ''), m.chk);
    check('UI-5', `${w} px: nothing overflows sideways`, !m.ov, m);
    const tabs = await p.evaluate(() => { const t = document.getElementById('plTabs'); return { sw: t.scrollWidth, cw: t.clientWidth, n: t.querySelectorAll('[role=tab]').length }; });
    check('UI-8', `${w} px: all five My Day tabs fit in the row, none is cut off at the edge`, tabs.n === 5 && tabs.sw <= tabs.cw + 1, tabs);
    if (w === 360) await A.capture(p, 'myday-360', { tag: 'U-360', full: false });
    await c.close();
  }

  // ---- UI-6 icons: the More sheet and the Practice entries use the one SVG set
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c);
    await p.evaluate(() => document.querySelector('.btab[data-tab="more"]').click()); await sleep(800);
    const m = await p.evaluate(() => [...document.querySelectorAll('#msheet .mrow[data-more]')].filter(window.__aud.vis).map(r => ({ id: r.dataset.more, svg: !!r.querySelector('.mi svg'), emoji: /\p{Extended_Pictographic}/u.test((r.querySelector('.mi') || {}).innerText || '') })));
    check('UI-6', 'every row of the More sheet has a line icon from the one SVG set - no emoji left in the icon slots', m.length >= 10 && m.every(x => x.svg && !x.emoji), m.filter(x => !x.svg || x.emoji));
    await A.capture(p, 'more-sheet', { tag: 'U-390', full: false });
    await p.keyboard.press('Escape'); await sleep(300);
    await go(p, '/practice');
    const pr = await p.evaluate(() => ['prEntry', 'riEntry', 'gcEntry'].map(id => { const e = document.getElementById(id); const ic = e && e.querySelector('.pr-ic'); return { id, shown: !!e && window.__aud.vis(e), svg: !!ic && !!ic.querySelector('svg'), emoji: !!ic && /\p{Extended_Pictographic}/u.test(ic.innerText || '') }; }));
    check('UI-6', 'the Practice Room, Job Interview Practice and Grammar Coach entries use the SVG icons too', pr.every(x => x.shown && x.svg && !x.emoji), pr);
    await c.close();
  }
  // ---- UI-7 one accent
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c);
    const t = await p.evaluate(() => { const cs = getComputedStyle(document.documentElement); const stops = [...document.querySelectorAll('#g stop')].map(s => s.getAttribute('stop-color')); return { gold: cs.getPropertyValue('--gold').trim(), accent: cs.getPropertyValue('--accent').trim(), glass: cs.getPropertyValue('--glass-brd').trim(), stops }; });
    check('UI-7', '`--gold` is honestly an alias of `--accent` (it held indigo under a gold name)', t.accent !== '' && t.gold === t.accent, t);
    const hue = hex => { const n = parseInt(hex.slice(1), 16), r = (n >> 16 & 255) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255, mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; if (!d) return 0; let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h = Math.round(h * 60); return h < 0 ? h + 360 : h; };
    check('UI-7', 'the interview-report score ring is in the brand indigo / violet, not gold (it was #f5d97a to #b8860b)', t.stops.length >= 2 && t.stops.every(s => { const h = hue(s); return h >= 200 && h <= 290; }), t.stops);
    check('UI-7', 'the card hairline (`--glass-brd`) is an accent tint now, not the old brand gold', /var\(--accent\)|111, ?140, ?255|rgb\(111/.test(t.glass) || /color-mix/.test(t.glass), t.glass);
    await c.close();
  }

  // ---- UI-11 badges, UI-12 ranks, UI-13 journey
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c);
    await go(p, '/achievements', 1800);
    const a = await p.evaluate(() => ({ locked: [...document.querySelectorAll('#achievements .ach-card.locked')].map(e => e.innerText.replace(/\s+/g, ' ').trim()), all: Object.keys(BADGE_LABELS).length, how: Object.keys(BADGE_LABELS).filter(k => !BADGE_HOW[k]) }));
    check('UI-11', 'every locked badge says HOW to earn it (24 of them said just "Locked")', a.locked.length >= 10 && a.locked.every(t => /Locked\.\s+\S.{8,}/.test(t)), a.locked.filter(t => !/Locked\.\s+\S.{8,}/.test(t)));
    check('UI-11', 'every badge the app can award has a requirement text (no badge is missing from BADGE_HOW)', a.how.length === 0, a.how);
    await A.capture(p, 'badges', { tag: 'U-390', full: false });
    await go(p, '/leaderboard', 1800);
    const lbTxt = await text(p, '#leaderboard');
    check('UI-12', 'Ranks shows no "0 XP" row', !/\b0 XP\b/.test(lbTxt || ''), lbTxt);
    const nb = (await A.api('newbie', '/leaderboard')).body || {};
    check('UI-12', 'the server lists only learners with XP above zero - a brand-new 0-XP learner is not on the board, and the podium cannot show 0 XP (the board is `top`; the learner\'s own row is pinned separately)', Array.isArray(nb.top) && nb.top.length > 0 && nb.top.every(r => r.xp > 0), nb.top);
    await go(p, '/learning-journey', 2000);
    const j = (await text(p, '#journey') || '');
    check('UI-13', 'the goal reads as a sentence ("Your goal: Get a job"), not the raw value ("Goal: job")', /Your goal: Get a job/.test(j) && !/Goal: job\b/.test(j), j.slice(0, 160));
    check('UI-13', 'the counters say what they count ("WORLDS CLEARED", "SESSIONS TODAY") - not "CONFIDENCE STARS 1/7" - and today\'s sessions are today\'s: a learner who practised YESTERDAY starts at 0/5 (it showed yesterday\'s 8 as "8/5"; visual review 9)', /WORLDS CLEARED/i.test(j) && /0\s*\/\s*5\s*SESSIONS TODAY/i.test(j) && !/\b8\s*\/\s*5/.test(j) && !/CONFIDENCE STARS/i.test(j), j.slice(0, 400));
    const metTxt = await p.evaluate(() => { const was = userState.progress.sessions_today; userState.progress.sessions_today = 8; renderJourney(); const t = document.getElementById('jrnyStats').innerText.replace(/\s+/g, ' '); userState.progress.sessions_today = was; renderJourney(); return t; });
    check('UI-13', 'past the daily goal the chip says "8 ✓ DAILY GOAL MET" - not "TODAY 8/5"', /8\s*✓\s*DAILY GOAL MET/i.test(metTxt) && !/TODAY\s*8\s*\/\s*5/i.test(metTxt) && !/\b8\s*\/\s*5/.test(metTxt), metTxt);
    check('UI-13', 'the skills chart is labelled (a heading and a name beside every bar)', /Your skills/.test(j) && ['Confidence', 'Pronunciation', 'Listening', 'Vocabulary', 'Grammar', 'Thinking in English'].every(k => j.includes(k)), j.slice(0, 500));
    check('UI-13', 'no lone "💪 78%" chip', !/💪/.test(j));
    const q = 'In one month I will answer interview questions without fear.';
    check('UI-13', '"YOU TODAY" no longer repeats the Day-1 quote (it appears once, under "YOU ON DAY 1")', j.split(q).length - 1 === 1 && /YOU TODAY/i.test(j), j.split(q).length - 1);
    await A.capture(p, 'journey', { tag: 'U-390', full: true });
    await c.close();
  }
  // ---- UI-14 the owner's dashboard stacks each setting under its text on a phone
  {
    const c = await mk('owner', { width: 390, height: 844 }); const p = await open(c);
    await p.evaluate(() => openAdmin()); await sleep(2800);
    const d = await p.evaluate(() => { const rows = [...document.querySelectorAll('#adminBody .swrow')].filter(r => r.querySelector('select')).map(r => { const s = r.querySelector('select').getBoundingClientRect(), t = r.firstElementChild.getBoundingClientRect(), rr = r.getBoundingClientRect(); return { below: s.top >= t.bottom - 2, wide: s.width >= rr.width - 40, h: Math.round(s.height) }; });
      return { screen: (document.querySelector('.screen.on') || {}).id, rows, ov: document.documentElement.scrollWidth > innerWidth + 1 }; });
    check('UI-14', 'on a phone each dashboard setting puts its select UNDER its explanation, full width, 44 px high (it was squeezed into a 9-word column)', d.screen === 'admin' && d.rows.length >= 4 && d.rows.every(x => x.below && x.wide && x.h >= 44) && !d.ov, d);
    const fnb = await p.evaluate(() => { const b = document.getElementById('fnBox'); return b ? { rows: b.querySelectorAll('.fn-row').length, text: b.innerText, days: [...b.querySelectorAll('.fn-days button')].map(x => x.innerText), bars: [...b.querySelectorAll('.fn-track i')].every(i => /^\d+(\.\d+)?%$/.test(i.style.width)) } : null; });
    const fapi = (await A.api('owner', '/admin/funnel?days=30')).body || {};
    check('P1-10', 'the owner can SEE the first-run funnel on the dashboard (not just call an endpoint): one row per step, in the API\'s order, with its numbers, Day-1 / Day-7 return and plan interest', !!fnb && fnb.rows === (fapi.milestones || []).length && fnb.rows >= 6 && (fapi.milestones || []).every(m => fnb.text.includes(m.label)) && /Came back on day 1/.test(fnb.text) && /Reserved a plan: Starter/.test(fnb.text) && fnb.bars, { fnb, steps: (fapi.milestones || []).length });
    await p.locator('.fn-days button:nth-child(1)').click(); await sleep(1200);
    const f7 = await text(p, '#fnBox');
    check('P1-10', 'its 7 / 30 / 90-day buttons re-count the window (and say which is pressed)', fnb && fnb.days.join() === '7 days,30 days,90 days' && /last 7 days/.test(f7 || '') && await p.evaluate(() => document.querySelector('.fn-days button:nth-child(1)').getAttribute('aria-pressed') === 'true'), f7 && f7.slice(0, 200));
    await A.capture(p, 'dashboard', { tag: 'U-390', full: false });
    await c.close();
  }
  // ---- A-2 the mood buttons are named (and say it in words)
  {
    await A.post('/__audit/reset_learner', { who: 'keyed' });
    const c = await mk('keyed', { width: 390, height: 844 }, { firstRun: true }); const p = await open(c); await sleep(800);
    const m = await p.evaluate(() => { const row = document.getElementById('moodRow'); const btns = row ? [...row.querySelectorAll('button')] : []; return { shown: !!row && window.__aud.vis(row), n: btns.length, named: btns.every(b => (b.getAttribute('aria-label') || '').trim().length > 2), words: btns.every(b => { const l = b.querySelector('.mood-l'); return l && window.__aud.vis(l) && l.innerText.trim().length > 2; }), sizes: btns.map(b => { const r = b.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }) }; });
    check('A-2', 'the five mood buttons carry an accessible name AND a visible word under the emoji (they were emoji-only)', m.shown && m.n === 5 && m.named && m.words && m.sizes.every(([w, h]) => w >= 44 && h >= 44), m);
    await c.close();
  }
  // ---- Hindi: the new placement and the type floor hold in the other language too
  {
    await A.setLang('active', 'hi');
    const c = await mk('active', { width: 360, height: 740 }, { lang: 'hi' }); const p = await open(c); await sleep(800);
    const h = await p.evaluate(() => { const pill = document.querySelector('#home .lg-row .lg-sw'); const nav = document.getElementById('bnav').getBoundingClientRect(); return { shown: !!pill && window.__aud.vis(pill), labels: pill ? [...pill.querySelectorAll('button')].map(b => b.innerText) : [], bottom: pill ? Math.round(pill.getBoundingClientRect().bottom) : 0, navTop: Math.round(nav.top), tiny: window.__aud.tiny().length, small: window.__aud.small().map(x => x.l), ov: document.documentElement.scrollWidth > innerWidth + 1, hdrOv: document.querySelector('header').scrollWidth > document.querySelector('header').clientWidth + 1 }; });
    check('UI-8', 'Hindi, 360 px: the pill is at the top, visible, and the header, type floor and tap targets hold', h.shown && h.bottom <= h.navTop && h.tiny === 0 && h.small.length === 0 && !h.ov && !h.hdrOv, h);
    await A.capture(p, 'home-hindi-360', { tag: 'U-hi-360', full: false });
    await c.close(); await A.setLang('active', 'en');
  }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ W: the weight of the first visit (the live numbers can only be re-measured after a deploy; this proves what the page ASKS for)
async function W(browser) {
  const OLD = OLD_PAGE();
  const reqs = [];
  const watch = (p, bag) => { p.on('request', r => bag.push(r.url())); };
  { // signed out: the login screen
    const c = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block', userAgent: A.PHONE_UA || undefined });
    await c.route('**/*', r => { const u = new URL(r.request().url()); if (u.origin === A.BASE) { if (OLD && u.pathname === '/') return r.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: OLD }); return r.continue(); } if (u.hostname === 'accounts.google.com') return r.fulfill({ status: 200, contentType: 'application/javascript', body: '/* stub */' }); return r.abort(); });
    const p = await c.newPage(); const bag = []; watch(p, bag); let bytes = 0;
    p.on('requestfinished', async r => { try { const s = await r.sizes(); bytes += s.responseBodySize + s.responseHeadersSize; } catch (e) {} });
    await p.goto(A.BASE + '/', { waitUntil: 'load' }); await sleep(2500);
    const rel = bag.map(u => u.replace(A.BASE, ''));
    check('P0-3a', 'the login screen never asks for the 1.7 MB /logo.png (it was 74% of the first visit)', !rel.some(u => /^\/logo\.png/.test(u)), rel);
    check('P0-3d', 'fonts come from the app\'s own origin - no request to Google Fonts (two extra origins before)', !bag.some(u => /fonts\.(googleapis|gstatic)\.com/.test(u)) && rel.some(u => /^\/assets\/fonts\//.test(u)), rel.filter(u => /font/.test(u)));
    check('P0-3e', 'the Google sign-in script IS loaded on the login screen (sign-in still works) ...', bag.some(u => /accounts\.google\.com\/gsi\/client/.test(u)), bag.filter(u => /google/.test(u)));
    check('P0-3', `the whole first visit is ${Math.round(bytes / 1024)} KB over ${rel.length} requests (it was 2,873 KB over 7 requests in the same lab measurement)`, bytes < 700 * 1024 || !!OLD, { kb: Math.round(bytes / 1024), rel, note: OLD ? 'a replaced page is served uncompressed by the test, so its size is not judged' : '' });
    await c.close();
  }
  { // the sign-in delay note: a merely SLOW connection is not reported as a fault (the first version said "check your internet" after 2 s); offline is reported at once; a long wait after ~8 s
    const mkc = async () => { const c = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
      await c.route('**/*', r => { const u = new URL(r.request().url()); if (u.origin === A.BASE) return r.continue(); if (u.hostname === 'accounts.google.com') return r.fulfill({ status: 200, contentType: 'application/javascript', body: '/* a loader that never finishes */' }); return r.abort(); }); return c; };
    const c = await mkc(); const p = await c.newPage();
    await p.goto(A.BASE + '/', { waitUntil: 'load' }); await sleep(4000);
    const early = await text(p, '#loginNote');
    check('P0-3e', 'a slow sign-in script is NOT reported as a fault in the first 4 s (a 3G phone is still downloading it)', !early, early);
    await sleep(5500);
    const late = await text(p, '#loginNote');
    check('P0-3e', '... after ~9 s without a button a note says sign-in is taking a while', /taking a while/.test(late || ''), late);
    await c.close();
    const c2 = await mkc(); const p2 = await c2.newPage();
    await p2.goto(A.BASE + '/', { waitUntil: 'load' }); await sleep(800); await c2.setOffline(true); await sleep(2600);
    const off = await text(p2, '#loginNote');
    check('P0-3e', 'offline, the note appears at once (within ~2 s), not after the long wait', /taking a while/.test(off || ''), off);
    await c2.close();
  }
  { // signed in: no sign-in script at all
    const c = await A.ctx(browser, 'keyed', { lang: 'en', viewport: { width: 390, height: 844 }, html: OLD }); const bag = [];
    const p = await c.newPage(); watch(p, bag);
    await p.goto(A.BASE + '/', { waitUntil: 'load' }); await sleep(3000);
    check('P0-3e', '... but a learner who is already signed in never downloads it', !bag.some(u => /accounts\.google\.com/.test(u)), bag.filter(u => /google/.test(u)));
    await c.close();
  }
  { // validators + caching, straight from the server
    const r1 = await fetch(A.BASE + '/'); const et = r1.headers.get('etag'); const body = await r1.text();
    check('P0-3b', 'GET / carries an ETag and "no-cache" (always revalidate - a deploy shows at once)', !!et && /no-cache/.test(r1.headers.get('cache-control') || ''), { et, cc: r1.headers.get('cache-control') });
    const r2 = await fetch(A.BASE + '/', { headers: { 'If-None-Match': et } });
    check('P0-3b', 'a repeat open with that ETag is answered 304 with NO body (1.1 MB not re-sent)', r2.status === 304 && (await r2.text()).length === 0, r2.status);
    check('P0-3b', 'the ETag is WEAK: Cloudflare drops a strong one when it re-encodes the page (measured on the live site 2026-10-31 - the origin sent one, no browser received it, so no repeat open could be a 304)', /^W\/"[0-9a-f]{24}"$/.test(et || ''), et);
    const f = await fetch(A.BASE + '/assets/fonts/inter-latin-v1.woff2');
    check('P0-3d', 'a self-hosted font is cached for a year, immutable', f.status === 200 && /max-age=31536000/.test(f.headers.get('cache-control') || '') && /immutable/.test(f.headers.get('cache-control') || ''), f.headers.get('cache-control'));
    check('P0-3d', 'the font says what it is: font/woff2 (the slim image has no mime table - Starlette would say text/plain, seen on the live site)', f.headers.get('content-type') === 'font/woff2', f.headers.get('content-type'));
    const wp = await fetch(A.BASE + '/assets/icons/dusu-logo-160-v1.webp');
    check('P0-3a', 'the small WebP logo is served as image/webp, not text/plain', wp.status === 200 && wp.headers.get('content-type') === 'image/webp', wp.headers.get('content-type'));
    const lg = await fetch(A.BASE + '/logo.png');
    check('P0-3a', '/logo.png is still served (external references: the Play listing) but the page no longer points at it', lg.status === 200 && !/["'(]\/logo\.png/.test(body), lg.status);
    const sw = await (await fetch(A.BASE + '/sw.js')).text();
    check('P0-3c', 'the service worker does not pre-download the big logo', !/SHELL\s*=\s*\[[^\]]*logo\.png/.test(sw), sw.match(/SHELL\s*=\s*\[[^\]]*\]/));
  }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ V: pins from the independent review (2026-10-30)
// A fresh agent read the diff cold and reported nine findings; each was reproduced (or rejected) and the real ones got a check here (the service-worker ones are in tests/keys/browser/sw.spec.cjs).
async function V(browser) {
  const OLD = OLD_PAGE();
  const mk = (who, vp, extra = {}) => A.ctx(browser, who, Object.assign({ lang: 'en', viewport: vp, html: OLD }, extra));
  const P390 = { width: 390, height: 844 };

  { // finding 1 (High): a failing GET /keys/status was retried in a tight loop
    const c = await mk('keyed', P390); let n = 0;
    await c.route('**/keys/status*', r => { n++; r.abort(); });
    const p = await A.open(c, '/', { settle: 2500 }); await sleep(3500);
    const n0 = n;
    check('V-1', `a failing /keys/status is asked ${n0} time(s) in ~6 s - not in a tight loop (paintCard -> refreshStatus -> fail -> paintAll -> paintCard used to make dozens a second)`, n0 >= 1 && n0 <= 3, n0);
    await p.evaluate(() => navTo('/keys')); await sleep(1500);
    check('V-1', '... and the learner\'s own tap (opening the Keys screen) still asks again, once', n >= n0 + 1 && n <= n0 + 3, { n0, n });
    await c.close();
  }
  { // finding 3: "No sentences yet" only when nothing was said
    const c = await mk('keyed', P390); const p = await A.open(c, '/', { settle: 1800 });
    const r = await p.evaluate(() => { renderSessionResult(null, true); const a = document.getElementById('srBody').innerText; renderSessionResult(null, false); const b = document.getElementById('srBody').innerText; renderSessionResult(null); const d = document.getElementById('srBody').innerText; return { a, b, d }; });
    check('V-3', 'a Daily session the learner spoke in, whose result did not arrive in time, says "Session saved." - not "No sentences yet"', /Session saved/i.test(r.a) && !/No sentences/i.test(r.a), r.a);
    check('V-3', '... and a session with nothing said still says "No sentences yet"', /No sentences yet/i.test(r.b) && /No sentences yet/i.test(r.d), r);
    await c.close();
  }
  { // finding 6: a second key pasted while the first one is saving survives
    await resetKeys('newbie'); await A.setLang('newbie', 'en');
    const c = await A.ctx(browser, 'newbie', { device: 'new', firstRun: true, lang: 'en', viewport: P390, html: OLD });
    await c.route('**/keys/save', async r => { await sleep(1800); r.continue(); });
    const p = await A.open(c, '/'); await settle(p, 1200);
    const k1 = 'gsk_' + 'x'.repeat(48), k2 = 'AIza' + 'y'.repeat(35);
    await p.fill('#ksPaste', k1); await tap(p, '#ksSave'); await sleep(300);
    await p.fill('#ksPaste', k2);                                    // typed while the first key is still being checked
    await sleep(4200);
    const st = await p.evaluate(() => ({ v: document.getElementById('ksPaste').value, step: document.getElementById('ksStep').textContent }));
    check('V-6', 'a second key pasted while the first was saving is still in the box afterwards (the wizard used to wipe it)', st.v === k2 && /Key 2 of 2/.test(st.step), { v: st.v.slice(0, 8), step: st.step });
    await resetKeys('newbie'); await c.close();
  }
  { // finding 7: a saved price opinion can be changed but not un-pressed (the server never erases one)
    await A.post('/__audit/reset', { tables: ['plan_interest'] }); await A.setLang('active', 'en');
    const c = await mk('active', P390); const p = await A.open(c, '/'); await p.evaluate(() => navTo('/subscribe')); await settle(p, 900);
    const pressed = () => p.evaluate(() => [...document.querySelectorAll('.feel-chip')].filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.dataset.feel).join());
    await tap(p, '.plan[data-plan="plus"]'); await tap(p, '.feel-chip[data-feel="fair"]'); await tap(p, '#subProceed'); await settle(p, 1200);
    await tap(p, '.feel-chip[data-feel="fair"]'); await settle(p, 300);
    check('V-7', 'after "fair" was saved, tapping it again does NOT un-press it (the UI used to say "Saved" while the server kept the old answer)', (await pressed()) === 'fair' && /Reserved/.test(await text(p, '#subProceed') || ''), { pressed: await pressed(), btn: await text(p, '#subProceed') });
    await tap(p, '.plan[data-plan="pro"]'); await tap(p, '.feel-chip[data-feel="great"]'); await tap(p, '.feel-chip[data-feel="great"]'); await settle(p, 300);
    check('V-7', 'before anything is saved a chip can still be un-pressed (no opinion is a valid answer)', (await pressed()) === '', await pressed());
    await A.post('/__audit/reset', { tables: ['plan_interest'] }); await c.close();
  }
  { // finding 8: a second account on a shared phone does not inherit "history"
    await A.post('/__audit/reset_learner', { who: 'keyed' });
    const c = await mk('keyed', P390, { firstRun: true, seed: { dusu_had_session: 'aud-someone-else' } }); const p = await A.open(c, '/', { settle: 2000 });
    const r = await p.evaluate(() => ({ hist: hasHistory(), banner: !document.getElementById('journeyBanner').hidden }));
    check('V-8', 'a "had a session" flag left by ANOTHER account on this phone is not history for this one (no "where we left off")', r.hist === false && !r.banner, r);
    await p.evaluate(() => markSession());
    const r2 = await p.evaluate(() => ({ hist: hasHistory(), flag: localStorage.getItem('dusu_had_session'), uid: curUid() }));
    check('V-8', '... and finishing a session marks THIS account (the flag holds its id)', r2.hist === true && !!r2.uid && r2.flag === r2.uid, r2);
    await c.close();
  }
  { // finding 2: Journey XP alone is not the test of "has done something" (Face to Face / Interview add SPEAKER xp and sentences), and the Ranks copy says how to get on that board
    for (const [label, facts, progress, expect] of [['only speaker XP', {}, { speaker_xp: 120 }, true], ['only spoken sentences on record', { total_sentences: 14 }, null, true], ['nothing at all', {}, null, false]]) {
      await A.post('/__audit/reset_learner', { who: 'keyed' });
      await A.post('/__audit/facts', { who: 'keyed', facts, progress: progress || undefined });
      const c = await mk('keyed', P390, { firstRun: true }); const p = await A.open(c, '/', { settle: 1800 });
      const h = await p.evaluate(() => hasHistory());
      check('V-2', `a learner with ${label} ${expect ? 'HAS' : 'has NO'} history (Journey XP alone called everyone who only talks in Face to Face "brand new" on a new phone)`, h === expect, h);
      await c.close();
    }
    await A.post('/__audit/reset_learner', { who: 'keyed' });
    const c = await mk('newbie', P390); const p = await A.open(c, '/'); await p.evaluate(() => navTo('/leaderboard')); await settle(p, 1800);
    const t = await text(p, '#lbYou');
    check('V-2', 'the Ranks row of a learner with no XP says how to earn it - Daily Talk or a Journey lesson (not "speak once": Face to Face adds speaker XP, which this board does not count)', /Daily Talk or a Journey lesson/.test(t || ''), t);
    await c.close();
  }
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ X: the XSS canary (audit E-1)
// Hostile markup is planted in every learner-controlled / model-written field the server stores, the screens that show them are walked, and nothing may execute: no handler fires, no element
// carrying onerror / onload / a script appears, and the payload is visible as plain TEXT where the field is displayed (so the check cannot pass by showing nothing).
async function X(browser) {
  const OLD = process.env.OLD_HTML && fs.existsSync(process.env.OLD_HTML) ? fs.readFileSync(process.env.OLD_HTML, 'utf8') : null;   // OLD_HTML=<the page before the fixes>: the same canary must FAIL there
  const P1 = '<img src=x onerror="window.__xss=(window.__xss||0)+1">', P2 = '"><svg onload="window.__xss=(window.__xss||0)+1">', P3 = "'\"><script>window.__xss=(window.__xss||0)+1</script>";
  await A.post('/__audit/facts', { who: 'active', facts: {
    nickname: P1.slice(0, 40), dream: P2, career_goal: P1, next_hook: P3, last_letter: { date: '2026-10-29', text: P1 + ' ' + P3 },
    future_me: { day1_text: P1, latest_text: P2, latest_date: '2026-10-29' }, baseline: { intro_text: P1, date: '2026-10-01' },
    moments: [{ text: P1, emotion: P2, created: '2026-10-29', expires: '2099-01-01' }], achievements: [{ text: P3, date: '2026-10-29' }],
    events: [{ type: P1, date: '2099-01-01', note: P2 }],
    career_roadmap: { goal: P1, stages: [{ phase: P2, steps: [{ title: P1, status: 'todo', why: P3 }] }] } },
    profile: { goal: P1 } });
  const cleanHostile = async () => {                                         // the planter's own rows must not pile up in the scratch database (they did, run after run)
    for (const [list, del] of [['/planner/tasks?view=all', '/planner/tasks/'], ['/planner/goals', '/planner/goals/'], ['/planner/habits', '/planner/habits/'], ['/planner/reminders?view=all', '/planner/reminders/']]) {
      const b = (await A.api('active', list)).body || {};
      const arr = Object.values(b).find(v => Array.isArray(v) && v.length && v[0] && v[0].id !== undefined && 'title' in v[0]) || [];
      for (const it of arr) if (/^[<'"]/.test(String(it.title || ''))) await A.api('active', del + it.id, 'DELETE');
    }
  };
  await cleanHostile();
  await A.api('active', '/planner/tasks', 'POST', { client_key: 'x1' + Date.now(), title: P1, priority: 1, remind: 'none' });
  await A.api('active', '/planner/goals', 'POST', { client_key: 'x2' + Date.now(), title: P2, why: P3, milestones: [P1] });
  await A.api('active', '/planner/habits', 'POST', { client_key: 'x3' + Date.now(), title: P3, target: 1, unit: P1, schedule: { days: 'daily', times: [] } });
  await A.api('active', '/planner/reminders', 'POST', { client_key: 'x4' + Date.now(), title: P1, date: new Date(Date.now() + 864e5).toISOString().slice(0, 10), time: '10:00' });
  const c = await A.ctx(browser, 'active', { lang: 'en', viewport: { width: 390, height: 844 }, html: OLD });
  const p = await A.open(c, '/', { settle: 2500 });
  const screens = [['/', 'Home'], ['/profile', 'Profile'], ['/learning-journey', 'Journey'], ['/career-path', 'Career Path'], ['/achievements', 'Achievements'], ['/leaderboard', 'Ranks'], ['/league', 'League'],
    ['/interview-reports', 'Interview Reports'], ['/about', 'Know About'], ['/my-day', 'My Day: Today'], ['/my-day/tasks', 'My Day: Tasks'], ['/my-day/goals', 'My Day: Goals'], ['/my-day/habits', 'My Day: Habits'],
    ['/my-day/reminders', 'My Day: Reminders'], ['/grammar', 'Grammar Coach'], ['/resume-interview', 'Job Interview Practice'], ['/practice-room', 'Practice Room'], ['/subscribe', 'Plans']];
  let shown = 0;
  for (const [route, label] of screens) {
    await p.evaluate(r => navTo(r), route); await sleep(1700);
    const r = await p.evaluate(() => ({ xss: window.__xss || 0, handlers: document.querySelectorAll('[onerror],[onload]').length, scripts: [...document.querySelectorAll('script')].filter(s => /__xss/.test(s.textContent)).length,
      injected: document.querySelectorAll('img[src="x"], svg[onload]').length, text: document.body.innerText.includes('<img src=x') || document.body.innerText.includes('onerror=') || document.body.innerText.includes('<svg onload') }));
    if (r.text) shown++;
    check('E-1', `${label}: hostile markup in the learner's own data runs nothing (no handler fired, no injected element or script)`, r.xss === 0 && r.handlers === 0 && r.scripts === 0 && r.injected === 0, r);
  }
  check('E-1', 'and the canary is real: on the screens that show those fields the payload is visible as plain text (not silently dropped)', shown >= 4, { shown });
  // a hostile line typed into the Home chat
  await p.evaluate(() => navTo('/')); await sleep(1200);
  await p.fill('#hmTypeIn', P1); await p.press('#hmTypeIn', 'Enter'); await sleep(4000);
  const ch = await p.evaluate(() => ({ xss: window.__xss || 0, bubble: (document.querySelector('#feed .msg.user .bubble, #feed .bubble') || {}).textContent || '', handlers: document.querySelectorAll('[onerror],[onload]').length }));
  check('E-1', 'a hostile line typed into the Home chat is shown as text and runs nothing', ch.xss === 0 && ch.handlers === 0, ch);
  // model-written text: an interview report whose strengths / fixes the model filled with markup
  await A.post('/__audit/hostile', { on: true });
  await p.evaluate(() => navTo('/interview')); await sleep(900);
  await p.fill('#role', 'Analyst'); await p.click('#startInterview');
  for (const line of ['I am a final year student and I like data.', 'Last year I built a small dashboard for my class.', 'My dream is to become a data analyst.']) {
    if (!await micReady(p)) break;
    await say(p, line); await sleep(2600);
  }
  await p.click('#endBtn');
  await p.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'report', null, { timeout: 40000 }).catch(() => {});
  await sleep(1800);
  const rep = await p.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id, xss: window.__xss || 0, handlers: document.querySelectorAll('[onerror],[onload]').length,
    strengths: (document.getElementById('repStrengths') || {}).innerText || '', fixes: (document.getElementById('repFixes') || {}).innerText || '' }));
  check('E-1', 'an interview report whose strengths / fixes the MODEL filled with markup runs nothing and shows the text', rep.screen === 'report' && rep.xss === 0 && rep.handlers === 0 && /<img src=x/.test(rep.strengths) && /<img src=x/.test(rep.fixes), rep);
  await A.post('/__audit/hostile', { on: false });
  await cleanHostile();
  await A.post('/__audit/facts', { who: 'active', facts: { nickname: 'Asha', dream: 'A software engineer job', career_goal: '', next_hook: SEED_HOOK, last_letter: { date: '2026-10-29', text: 'Hi Asha, This week you spoke on four days.' }, moments: [], achievements: [], events: [],
    future_me: { day1_text: 'In one month I will answer interview questions without fear.', latest_text: 'In one month I will answer interview questions without fear.', latest_date: '2026-10-29' }, baseline: { intro_text: 'In one month I will answer interview questions without fear.', date: '2026-10-01' }, career_roadmap: null }, profile: { goal: 'job' } });
  await c.close();
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ Y: the fresh-eyes visual review's fixes (2026-10-31)
// A reviewer who had not seen the earlier work looked at ~80 final screenshots and found defects the other sections cannot see (a word cut in the middle, a dim button with no reason, five equal bars, ...).
// Each check below is one of those findings, measured in the browser; OLD_HTML=<the page before these fixes> (tests/audit/.out/pre-vr.html) must FAIL them.
async function Y(browser) {
  const OLD = OLD_PAGE();
  const mk = (who, vp, extra = {}) => A.ctx(browser, who, Object.assign({ lang: 'en', viewport: vp, html: OLD }, extra));
  const open = async (c, route = '/') => { const p = await A.open(c, route, { settle: 2000 }); await p.evaluate(INSTALL); return p; };
  const go = async (p, route, ms = 1500) => { await p.evaluate(r => navTo(r), route); await sleep(ms); await p.evaluate(INSTALL); };
  const lumOf = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (a, b) => { const x = lumOf(a), y = lumOf(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const rgb = s => (String(s).match(/[\d.]+/g) || []).slice(0, 3).map(Number);
  const ymd = (d = 0) => new Date(Date.now() + d * 864e5).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
  await A.setLang('active', 'en');

  // ---- VR-1 plans: a ring that shows the choice, and a line that says why the button waits
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c); await go(p, '/subscribe', 1200);
    const s0 = await p.evaluate(() => { const h = document.getElementById('planHint'), b = document.getElementById('subProceed'), r = document.querySelector('.plan[data-plan="plus"] .plan-top b'); const ring = getComputedStyle(r, '::before');
      return { hint: !!h && !h.hidden && h.getBoundingClientRect().height > 0, hintText: h ? h.textContent : '', dis: b.disabled, ringBg: ring.backgroundImage, ringW: ring.width }; });
    check('VR-1', 'plans: "Tap a plan above to choose it" is shown above the dim "Reserve my plan" (the button said nothing about why it waited)', s0.hint && /choose it/i.test(s0.hintText) && s0.dis, s0);
    check('VR-1', 'plans: every plan card starts with an empty 18 px radio ring', s0.ringBg === 'none' && s0.ringW === '18px', s0);
    await p.locator('.plan[data-plan="plus"]').click(); await sleep(300);
    const s1 = await p.evaluate(() => { const h = document.getElementById('planHint'); const ring = n => getComputedStyle(document.querySelector('.plan[data-plan="' + n + '"] .plan-top b'), '::before').backgroundImage;
      return { hintGone: !h || h.hidden || h.getBoundingClientRect().height === 0, plus: ring('plus'), pro: ring('pro'), starter: ring('starter'), dis: document.getElementById('subProceed').disabled }; });
    check('VR-1', 'plans: choosing a plan fills ITS ring only, the hint goes away and the button comes alive', s1.hintGone && /radial-gradient/.test(s1.plus) && s1.pro === 'none' && s1.starter === 'none' && !s1.dis, s1);
    await A.capture(p, 'plans-picked', { tag: 'Y-390', full: false });
    await c.close();
    await A.setLang('active', 'hi');
    const c2 = await mk('active', { width: 390, height: 844 }, { lang: 'hi' }); const p2 = await open(c2); await go(p2, '/subscribe', 1200);
    const hi = await p2.evaluate(() => { const h = document.getElementById('planHint'); return { text: h ? h.textContent : '', shown: !!h && !h.hidden }; });
    check('VR-1', 'plans in Hindi: the same hint, in Devanagari', hi.shown && /[ऀ-ॿ]/.test(hi.text), hi);
    await A.capture(p2, 'plans-hindi-hint', { tag: 'Y-390', full: false });
    await c2.close();
    await A.setLang('active', 'en');
  }

  // ---- VR-4 My Day: the summary line is read in full, and the header stays one row
  for (const [w, h, lang] of [[360, 740, 'en'], [390, 844, 'hi'], [360, 740, 'hi']]) {
    await A.setLang('active', lang);
    const c = await mk('active', { width: w, height: h }, { lang }); const p = await open(c); await go(p, '/my-day', 1500);
    const m = await p.evaluate(() => { const sub = document.getElementById('plSub'), cs = getComputedStyle(sub), lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.3; const top = document.querySelector('#pl .pl-top');
      const tops = [...top.querySelectorAll('button')].filter(b => b.getBoundingClientRect().width > 0).map(b => Math.round(b.getBoundingClientRect().top));
      return { text: sub.textContent, clipped: sub.scrollHeight > sub.clientHeight + 1 || sub.scrollWidth > sub.clientWidth + 1, lines: Math.round(sub.getBoundingClientRect().height / lh), spread: Math.max(...tops) - Math.min(...tops), ov: document.documentElement.scrollWidth > innerWidth + 1 }; });
    check('VR-4', `${w} px ${lang}: the My Day summary is shown in full (it read "Tasks, habits, goals & re…") in at most two lines`, !m.clipped && m.lines >= 1 && m.lines <= 2 && m.text.length > 20, m);
    check('VR-4', `${w} px ${lang}: back, bell and settings still sit on one row, and nothing scrolls sideways`, m.spread <= 14 && !m.ov, m);
    if (w === 360 && lang === 'en') await A.capture(p, 'myday-header-360', { tag: 'Y-360', full: false });
    await c.close();
  }
  await A.setLang('active', 'en');

  // ---- VR-5 profile: the alias is one word and stays whole
  for (const w of [390, 360, 320]) {
    const c = await mk('active', { width: w, height: 800 }); const p = await open(c); await go(p, '/profile', 1300);
    const r = await p.evaluate(() => { const el = document.getElementById('pfAlias'); const tn = [...el.childNodes].find(n => n.nodeType === 3); const alias = (el.textContent.match(/(\w+)\s*$/) || [])[1] || ''; const i = tn.textContent.lastIndexOf(alias);
      const rg = document.createRange(); rg.setStart(tn, i); rg.setEnd(tn, i + alias.length); const rects = [...rg.getClientRects()].filter(x => x.width > 0); return { alias, lines: new Set(rects.map(x => Math.round(x.top))).size, text: el.textContent }; });
    check('VR-5', `${w} px: the leaderboard alias on Profile is never cut in the middle of the word ("BoldSparr / ow")`, r.alias.length > 6 && r.lines === 1, r);
    if (w === 360) await A.capture(p, 'profile-alias-360', { tag: 'Y-360', full: false });
    await c.close();
  }

  // ---- VR-6 Journey: "Who you're becoming"
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c); await go(p, '/learning-journey', 1600);
    const a = await p.evaluate(() => { const root = document.getElementById('becoming'); const row = root.querySelector('.sr-trend') || root.querySelector('.sr-row'); const val = row && row.querySelector('.val');
      return { has: !!row, valH: val ? Math.round(val.getBoundingClientRect().height) : 0, valText: val ? val.textContent.trim() : '', chart: !!root.querySelector('[role=img]'), iso: /\d{4}-\d{2}-\d{2}/.test(root.innerText) }; });
    check('VR-6', 'Journey: the "62 → 64 (+2)" score stays on one line (the label wraps, the number does not)', a.has && a.valH > 0 && a.valH < 28, a);
    check('VR-6', 'Journey: sessions from ONE day draw no "over time" chart (five equal bars) and show no ISO date', !a.chart && !a.iso, a);
    const b = await p.evaluate(() => { userState.speaking_trend = { baseline: 50, recent: 70, delta: 20, day1_fallback: false, timeline: [{ date: '2026-10-01', avg: 50 }, { date: '2026-10-08', avg: 60 }, { date: '2026-10-15', avg: 70 }, { date: '2026-10-30', avg: 72 }] };
      renderBecoming(); const root = document.getElementById('becoming'); const img = root.querySelector('[role=img]'); const cap = [...root.querySelectorAll('.trend-cap span')].map(e => ({ t: e.textContent, h: Math.round(e.getBoundingClientRect().height) }));
      return { bars: img ? img.children.length : 0, label: img ? img.getAttribute('aria-label') : '', cap, iso: /\d{4}-\d{2}-\d{2}/.test(root.innerText) }; });
    check('VR-6', 'Journey: with three or more distinct days the chart appears; its captions read "1 Oct" and "30 Oct" on one line each, and its label carries the numbers', b.bars === 4 && b.cap.length === 2 && b.cap[0].t === '1 Oct' && b.cap[1].t === '30 Oct' && b.cap.every(x => x.h < 22) && /50 on 1 Oct/.test(b.label) && !b.iso, b);
    await A.capture(p, 'journey-trend', { tag: 'Y-390', full: false });
    await c.close();
  }

  // ---- VR-9 the counters are today's: a streak that died is 0, yesterday's sessions are not "today's"
  {
    const L = (await A.api('lapsed', '/me')).body, Ac = (await A.api('active', '/me')).body;
    check('VR-9', '/me: a learner who last practised 8 days ago has streak 0 and 0 sessions today (the stored 4 and 2 were shown as live)', L.progress.streak_days === 0 && L.progress.sessions_today === 0 && L.growth && L.growth.streak === 0, { p: L.progress, g: L.growth && L.growth.streak });
    check('VR-9', '/me: a learner who practised YESTERDAY keeps the streak (6) and starts today at 0 sessions', Ac.progress.streak_days === 6 && Ac.progress.sessions_today === 0 && Ac.growth && Ac.growth.streak === 6, { p: Ac.progress, g: Ac.growth && Ac.growth.streak });
    const c = await mk('lapsed', { width: 390, height: 844 }); const p = await open(c); await go(p, '/learning-journey', 1600);
    const j = await p.evaluate(() => ({ chips: [...document.querySelectorAll('#jrnyStats .stat-chip')].map(e => e.innerText.replace(/\s+/g, ' ').trim()) }));
    check('VR-9', 'Journey for that learner: "0🔥 Day streak" and "0/5 Sessions today" - no "4 DAY STREAK", no "2/5"', j.chips.some(t => /^0\s*🔥\s*Day streak/i.test(t)) && j.chips.some(t => /^0\/5\s*Sessions today/i.test(t)), j);
    await go(p, '/', 1500);
    const hm = await p.evaluate(() => ({ text: document.getElementById('home').innerText, chip: /-day streak/i.test((document.getElementById('heroGrowth') || {}).innerText || '') }));
    check('VR-9', 'Home for that learner shows no "N-day streak" chip', !hm.chip, hm.chip);
    await c.close();
  }

  // ---- VR-12 the result of a session with nothing to score
  {
    const c = await mk('keyed', { width: 390, height: 844 }); const p = await open(c);
    const e = await p.evaluate(() => { const g = id => document.getElementById(id); const k = g('srKick');
      showSessionResult(); const loading = { ring: g('srDuration').textContent, kick: k && k.textContent };
      renderSessionResult(null, false); const none = { ring: g('srDuration').textContent, kick: k && k.textContent, body: g('srBody').innerText };
      showSessionResult(); const reset = { ring: g('srDuration').textContent, kick: k && k.textContent };
      renderSessionResult(null, true); const saved = { ring: g('srDuration').textContent, kick: k && k.textContent, body: g('srBody').innerText };
      return { loading, none, reset, saved }; });
    check('VR-12', 'a session with nothing to score: the ring shows a dash (not the loading dots), the title says "Nothing to score yet", the body says what to do', e.loading.ring === '…' && e.none.ring === '—' && /nothing to score/i.test(e.none.kick || '') && /No sentences yet/.test(e.none.body), e);
    check('VR-12', 'opening the screen again returns to "Session complete" with the loading ring (the dash is not sticky)', e.reset.ring === '…' && /Session complete/i.test(e.reset.kick || ''), e.reset);
    check('VR-12', 'a session where the learner spoke but nothing could be scored keeps "Session complete", shows a dash, and says it was saved', e.saved.ring === '—' && /Session complete/i.test(e.saved.kick || '') && /saved/i.test(e.saved.body), e.saved);
    await c.close();
  }

  // ---- VR-13 Grammar settings: the data buttons
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c); await go(p, '/grammar/settings', 1700);
    const g = await p.evaluate(() => { const ex = document.getElementById('gcExport'), del = document.getElementById('gcDelAll'); if (!ex || !del) return null; const card = ex.closest('.gc-card'), cs = getComputedStyle(card); const inner = card.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight); const eb = ex.getBoundingClientRect(), db = del.getBoundingClientRect();
      return { ex: ex.innerText.trim(), del: del.innerText.trim(), exW: +(eb.width / inner).toFixed(2), delW: +(db.width / inner).toFixed(2), stacked: db.top >= eb.bottom - 1, delH: Math.round(db.height) }; });
    check('VR-13', 'Grammar settings: "Download my data" and "Delete all my Grammar Coach data" are stacked full-width (the delete label wrapped to five lines in a half-width button), in the words My Day and Job Interview Practice already use', g && g.stacked && g.exW > 0.9 && g.delW > 0.9 && g.delH < 70 && g.ex === 'Download my data', g);
    const hp = await p.evaluate(() => document.querySelector('#gcSetChoice-counts') ? document.querySelector('#gcSetChoice-counts').closest('.gc-card').innerText : '');
    check('VR-13', 'Grammar settings: the "Counts only" explanation says what happens to the learner\'s sentences', /If you pick Counts only/i.test(hp), hp.slice(0, 160));
    await A.capture(p, 'grammar-settings-data', { tag: 'Y-390', full: true });
    await c.close();
  }

  // ---- VR-14 / VR-20 My AI keys and the first-run wizard
  {
    const ks = (await A.api('keyed', '/keys/status')).body;
    const c = await mk('keyed', { width: 390, height: 844 }); const p = await open(c); await go(p, '/keys', 1900);
    const k = await p.evaluate(() => { const a = document.querySelector('.keyblk-get'); const cs = a ? getComputedStyle(a) : null; const del = document.querySelector('.ky-del'); const chg = document.querySelector('.ky-acts .btn:not(.ky-del)');
      return { has: !!a, under: cs && cs.textDecorationLine, borderB: cs && cs.borderBottomWidth, delColor: del ? getComputedStyle(del).color : null, chgColor: chg ? getComputedStyle(chg).color : null, cards: document.querySelectorAll('.ky-acts').length }; });
    check('VR-14', 'My AI keys: the dotted underline belongs to the words "Get free key" (a text decoration), not to the bottom edge of a 44 px box 20 px below them', k.has && /underline/.test(k.under) && parseFloat(k.borderB) === 0, { k, keys: (ks.keys || []).length });
    check('VR-14', 'My AI keys: Remove is tinted like what it does - not the same colour as Change and Test', !!k.delColor && !!k.chgColor && k.delColor !== k.chgColor, k);
    await c.close();
    await resetKeys('newbie'); await A.setLang('newbie', 'en');
    const c2 = await mk('newbie', { width: 390, height: 844 }, { device: 'new', firstRun: true }); const p2 = await open(c2); await sleep(1200);
    const before = await p2.evaluate(() => ({ open: !!document.getElementById('ksHelp').open, sc: document.querySelector('.wrap').scrollTop }));
    await tap(p2, '#ksHelp > summary'); await sleep(900);
    const after = await p2.evaluate(() => { const r = document.getElementById('keysSteps') && document.getElementById('keysSteps').getBoundingClientRect(); const t = document.getElementById('keysTutorial') && document.getElementById('keysTutorial').getBoundingClientRect(); const s = document.getElementById('ksHelpSum').getBoundingClientRect();
      return { open: document.getElementById('ksHelp').open, sc: document.querySelector('.wrap').scrollTop, bodyTop: Math.round(Math.min(r ? r.top : 1e9, t ? t.top : 1e9)), sumTop: Math.round(s.top), view: innerHeight }; });
    check('VR-20', 'the wizard\'s "Need help?" guide opens INTO VIEW: the tap scrolls it up so the learner sees the steps (it opened below the fold and looked like only an arrow flipped)', before.open === false && after.open && after.sc > before.sc && after.bodyTop < after.view - 120, { before, after });
    await A.capture(p2, 'wizard-guide-scrolled', { tag: 'Y-390', full: false });
    await c2.close();
  }

  // ---- VR-15 the header avatar's initial
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c);
    const a = await p.evaluate(() => { const u = document.getElementById('uInit'); const cs = getComputedStyle(u); return { shown: window.__aud.vis(u), color: cs.color, size: cs.fontSize, text: u.textContent }; });
    const fg = rgb(a.color);
    const mid = ratio(fg, [0x6f, 0x8c, 0xff]);
    check('VR-15', 'the avatar initial is dark on the periwinkle circle: at least 4.5:1 at the centre of the gradient (it was the dim tan text colour, about 1.6:1)', a.shown && a.text.length === 1 && mid >= 4.5, { a, ratio: +mid.toFixed(2) });
    await c.close();
  }

  // ---- VR-16 the mood row: five across; the weekly missions can be seen
  {
    await A.post('/__audit/reset_learner', { who: 'keyed' });
    for (const w of [390, 360]) {
      const c = await mk('keyed', { width: w, height: 800 }); const p = await open(c); await sleep(800);
      if (await vis(p, '#hmMoreBtn')) { await p.locator('#hmMoreBtn').click().catch(() => {}); await sleep(500); }
      const m = await p.evaluate(() => { const bs = [...document.querySelectorAll('#moodRow .mood-btn')].filter(b => b.getBoundingClientRect().width > 0); const r = bs.map(b => b.getBoundingClientRect());
        return { n: bs.length, tops: [...new Set(r.map(x => Math.round(x.top)))], minW: r.length ? Math.round(Math.min(...r.map(x => x.width))) : 0, minH: r.length ? Math.round(Math.min(...r.map(x => x.height))) : 0 }; });
      check('VR-16', `${w} px: the five mood buttons share one row (it wrapped 4 + 1 and left "Tired" alone) and are at least 44 px wide and tall`, m.n === 5 && m.tops.length === 1 && m.minW >= 44 && m.minH >= 44, m);
      if (w === 390) await A.capture(p, 'mood-row', { tag: 'Y-390', full: false });
      await c.close();
    }
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c); await sleep(900);
    const css = await p.evaluate(() => { const probe = document.createElement('div'); probe.className = 'sr-mission-row'; probe.innerHTML = '<span class="sr-check">✓</span><span class="bar"><i></i></span>'; document.body.appendChild(probe);
      const out = { ring: getComputedStyle(probe.querySelector('.sr-check')).borderTopColor, track: getComputedStyle(probe.querySelector('.bar')).backgroundColor }; probe.remove(); return out; });
    const ringA = (css.ring.match(/[\d.]+/g) || []).map(Number), trackA = (css.track.match(/[\d.]+/g) || []).map(Number);
    check('VR-16', 'weekly missions: the empty check circle and the progress track are visible (the circle at least as bright as 55 % periwinkle, the track at least 16 % white)', ringA[3] >= 0.55 && trackA[3] >= 0.16, css);
    await c.close();
  }

  // ---- VR-8 Ranks: what the learner is called, and a place for a learner who is not on the weekly board yet
  {
    await A.post('/__audit/reset_learner', { who: 'keyed' });
    const c = await mk('keyed', { width: 390, height: 844 }); const p = await open(c); await go(p, '/league', 1800);
    const l = await p.evaluate(() => ({ sub: (document.getElementById('leagueSub') || {}).innerText, you: document.getElementById('leagueYou') ? { shown: !document.getElementById('leagueYou').hidden, text: document.getElementById('leagueYou').innerText.replace(/\s+/g, ' ') } : null }));
    check('VR-8', 'Weekly League: a learner with no practice this week is told "You\'re not on this week\'s board yet" and what puts them there (the list alone looked like they had been left out)', l.you && l.you.shown && /not on this week's board yet/i.test(l.you.text) && /Practise once/i.test(l.you.text), l);
    check('VR-8', 'Weekly League: the subtitle says "Others see you as <alias>" (the real name sits on the learner\'s own row: "You are X" read as a contradiction)', /^Others see you as \S+/.test(l.sub || ''), l.sub);
    await A.capture(p, 'league-not-on-board', { tag: 'Y-390', full: true });
    await go(p, '/leaderboard', 1500);
    const b = await p.evaluate(() => (document.getElementById('lbSub') || {}).innerText);
    check('VR-8', 'Leaderboard: the same wording', /^Others see you as \S+/.test(b || ''), b);
    await c.close();
  }

  // ---- VR-11 the Practice hub's Interview Prep icon is the briefcase Home uses (a "sliders" icon reads as Settings)
  {
    const c = await mk('active', { width: 390, height: 844 }); const p = await open(c); await go(p, '/practice', 1300);
    const ic = await p.evaluate(() => { const svg = document.querySelector('.mode-card.interview .mc-orb svg'); return svg ? { rects: svg.querySelectorAll('rect').length, circles: svg.querySelectorAll('circle').length } : null; });
    check('VR-11', 'Practice hub: Interview Prep draws the briefcase (a rectangle with a handle, no sliders\' circles)', ic && ic.rects === 1 && ic.circles === 0, ic);
    await c.close();
  }

  // ---- VR-17 / VR-18 copy: the garbled " - ＋", an unclear Hindi priority label, badge names
  {
    await A.post('/__audit/reset_learner', { who: 'keyed' });
    const g = await A.api('keyed', '/planner/goals'); const gl = (g.body && (g.body.goals || g.body)) || [];
    for (const lang of ['en', 'hi']) {
      await A.setLang('keyed', lang);
      const c = await mk('keyed', { width: 390, height: 844 }, { lang }); const p = await open(c); await go(p, '/my-day/goals', 1700);
      const t = await p.evaluate(() => (document.getElementById('plBody') || document.getElementById('pl')).innerText.replace(/\s+/g, ' '));
      if (!Array.isArray(gl) || !gl.length) check('VR-17', `goals empty state (${lang}): the sentence is complete without a dash before the plus ("... bigger. Tap ＋ ...")`, /No goals yet\. A goal is something bigger\. Tap ＋/.test(t) || (lang === 'hi' && /Goal कुछ बड़ा होता है। ＋ दबाओ/.test(t)) , t.slice(0, 200));
      await c.close();
    }
    await A.setLang('keyed', 'en');
    const hiPrio = await (async () => {
      const mkT = await A.api('active', '/planner/tasks', 'POST', { client_key: 'y-t-high-' + Date.now(), title: 'Call the bank about the card', priority: 3, remind: 'none', due_date: ymd(0) });
      await A.setLang('active', 'hi');
      const c = await mk('active', { width: 390, height: 844 }, { lang: 'hi' }); const p = await open(c); await go(p, '/my-day/tasks', 1800);
      const chips = await p.evaluate(() => [...document.querySelectorAll('#pl .pl-chip.hi')].map(e => e.textContent.trim()));
      await c.close(); await A.setLang('active', 'en');
      if (mkT.body && mkT.body.id) await A.api('active', '/planner/tasks/' + mkT.body.id, 'DELETE');
      return chips;
    })();
    check('VR-17', 'My Day in Hindi: a high-priority task carries "ज़रूरी" (important), not "ज़्यादा" (more)', hiPrio.length > 0 && hiPrio.every(t => /ज़रूरी|ज़रूरी/.test(t) && !/ज़्यादा/.test(t)), hiPrio);
    const c2 = await mk('active', { width: 390, height: 844 }); const p2 = await open(c2); await go(p2, '/achievements', 1600);
    const ach = await p2.evaluate(() => ({ names: [...document.querySelectorAll('.ach-card .name')].map(e => e.innerText.replace(/\s+/g, ' ').trim()), text: document.getElementById('achievements').innerText }));
    const base = n => n.replace(/\([^)]*\)/g, '').replace(/[^\p{L}\p{N} ]/gu, '').trim();
    const dup = ach.names.map(base).filter((n, i, a) => a.indexOf(n) !== i);
    check('VR-18', 'Achievements: no two badges carry the same name (there were two "Consistent Speaker"), and the brand is spelled DuSu, not DUSU', ach.names.length > 10 && dup.length === 0 && !/DUSU/.test(ach.text), { dup, upper: /DUSU/.test(ach.text) });
    await go(p2, '/', 800); await p2.evaluate(() => { const b = document.querySelector('.btab[data-tab="more"]'); b && b.click(); }); await sleep(600);
    const ms = await p2.evaluate(() => (document.getElementById('msheet') || {}).innerText || '');
    check('VR-18', 'More sheet: "Your DuSu badge collection"', /Your DuSu badge collection/.test(ms) && !/DUSU/.test(ms), ms.slice(0, 120));
    await c2.close();
  }

  await A.setLang('active', 'en');
}

// ------------------------------------------------------------------------------------------------------------------------------------------------ main
(async () => {
  const browser = await chromium.launch();
  await section('S', 'smoke: the page loads without a script error', S, browser);
  await section('K', 'the first-run Keys wizard', K, browser);
  await section('R', 'cold deep links', R, browser);
  await section('P', 'the plans page and Reserve my plan', P, browser);
  await section('F', 'first-run overlays and a short chat\'s result', F, browser);
  await section('O', 'offline wording and retry', O, browser);
  await section('H', 'Home, names, Practice hub, empty states, copy', H, browser);
  await section('N', 'retired names and static facts about the shipped page', N, browser);
  await section('U', 'the UI system: numerals, type, header, targets, My Day, icons, tabs, badges, ranks, journey, dashboard, contrast', U, browser);
  await section('W', 'the weight of the first visit', W, browser);
  await section('V', 'pins from the independent review', V, browser);
  await section('Y', 'the fresh-eyes visual review: a word cut in half, a dim button with no reason, equal bars, stale counters ...', Y, browser);
  await section('X', 'the XSS canary', X, browser);
  await browser.close();
  console.log(`\n${passed} passed, ${failed} failed`);
  fs.writeFileSync(path.join(A.OUT, 'verify-results.json'), JSON.stringify(LOG, null, 1));
  process.exit(failed ? 1 : 0);
})();
