'use strict';
/*
 * Shared helpers for the Keys / Install browser specs (Playwright library API, no test runner): a signed-in browser context for a seeded learner - optionally a
 * BRAND-NEW device with nothing in localStorage - the control routes of the e2e server (tests/keys/e2e_server.py), and page helpers that WAIT for an outcome.
 *
 *   const L = require('./lib.cjs').create('keys: something');   // reads BASE / TOKENS / OUT from the environment run_real.sh sets
 */
const fs = require('fs');
const path = require('path');
const { makeT, sleep } = require('../../resume_interview/browser/harness.cjs');

function create(name) {
  const BASE = process.env.BASE;
  const OUT = process.env.OUT || '/tmp';
  const TOK = JSON.parse(fs.readFileSync(process.env.TOKENS, 'utf8'));
  const T = makeT(name);
  const ERRS = [];

  const INIT = `(() => {
    window.__errors = []; window.__rejections = [];
    window.addEventListener('error', e => window.__errors.push(String(e.message)));
    window.addEventListener('unhandledrejection', e => window.__rejections.push(String((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
  })();`;

  /** A signed-in browser context. `device`: 'returning' (the learner's own phone: cached state + the keys this browser holds) or 'new' (nothing but the login). */
  async function ctxFor(browser, who, o = {}) {
    const u = TOK[who];
    const vp = o.viewport || { width: 390, height: 844 };
    const ctx = await browser.newContext({ viewport: vp, isMobile: vp.width < 800, hasTouch: vp.width < 800, serviceWorkers: o.sw ? 'allow' : 'block', reducedMotion: o.motion ? 'no-preference' : 'reduce',
                                           userAgent: o.ua, permissions: o.permissions });
    await ctx.addInitScript(INIT);
    const base = { dusu_token: u.token, dusu_user: u.user, dusu_onboarded: 'true', dusu_rewards_intro_seen: '1', dusu_lang: o.lang || 'en', dusu_pl_pushhint: '1' };
    const returning = o.device !== 'new';
    const seed = Object.assign({}, base, returning ? { dusu_state: { onboarded: true, key_health: true, keys_ui: true, install_app: true, bilingual: true }, dusu_usemode: 'office',
      dusu_office_keys: u.keys ? Object.fromEntries(Object.entries(u.keys).slice(0, 2)) : { groq: 'gsk_test_key_123', gemini: 'AIzaTestKey' }, dusu_keys_ok: '1', dusu_keys_owner: u.user.email } : {}, o.seed || {});
    await ctx.addInitScript(`(() => { try { if (localStorage.getItem('__seeded')) return; localStorage.setItem('__seeded', '1'); const s = ${JSON.stringify(seed)};
      for (const k of Object.keys(s)) localStorage.setItem(k, typeof s[k] === 'string' ? s[k] : JSON.stringify(s[k])); } catch (e) {} })();`);
    if (o.init) await ctx.addInitScript(o.init);
    await ctx.route('**/*', route => new URL(route.request().url()).origin !== BASE ? route.abort() : route.continue());          // nothing leaves the box
    return ctx;
  }

  // ---------------------------------------------------------------------- the e2e server's control routes
  const post = async (p, body) => { const r = await fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); let j = null; try { j = await r.json(); } catch (e) {} return { status: r.status, body: j }; };
  const behave = (provider, mode, key) => post('/__world/behave', { provider, mode, key, clear_gate: true });
  const reset = settings => post('/__world/reset', { settings });
  const calls = (o = {}) => post('/__world/calls', o).then(r => r.body);
  const flush = () => post('/__world/flush');
  // what the SERVER says about this learner (the truth the screen is checked against - never the screen itself)
  async function server(who, p, method = 'GET', body) {
    const r = await fetch(BASE + p, { method, headers: { Authorization: 'Bearer ' + TOK[who].token, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, body: j };
  }

  // ---------------------------------------------------------------------- the page
  async function boot(ctx, urlPath = '/', o = {}) {
    const page = await ctx.newPage();
    page.on('pageerror', e => ERRS.push('pageerror: ' + String((e && e.message) || e)));
    page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|favicon/i.test(m.text())) ERRS.push('console.error: ' + m.text()); });
    page.__dialogs = [];
    page.on('dialog', d => { page.__dialogs.push(d.message()); d.accept(); });
    const meDone = o.waitMe === false ? null : page.waitForResponse(r => new URL(r.url()).pathname === '/me' && r.request().method() === 'GET', { timeout: 30000 });
    await page.goto(BASE + urlPath, { waitUntil: 'domcontentloaded' });
    if (meDone) { await meDone; await sleep(o.settle || 700); }
    return page;
  }
  const screen = page => page.evaluate(() => (document.querySelector('.screen.on') || {}).id || '');
  const vis = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return !e.closest('[hidden]') && cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0; }, sel);
  const txt = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.innerText : null; }, sel);
  const shot = (page, n) => page.screenshot({ path: path.join(OUT, n + '.png'), fullPage: false }).catch(() => {});
  async function until(fn, ms = 8000, every = 80) {
    const end = Date.now() + ms;
    for (;;) { try { if (await fn()) return true; } catch (e) { /* not yet */ } if (Date.now() > end) return false; await sleep(every); }
  }
  const notif = page => page.evaluate(() => { const e = document.getElementById('notifTxt'); return e ? e.textContent : ''; });
  // the learner's language lives on the server (it wins over the device cache on every /me)
  async function setLang(who, lang) {
    const r = await fetch(BASE + '/lang', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: TOK[who].token, lang }) });
    if (!r.ok) throw new Error('could not save the language for ' + who + ': ' + r.status);
  }
  /** The key pop-up may be open (it opens by itself when a key died): dismiss it with "Later", the way a learner would. */
  async function closePop(page) {
    if (await vis(page, '#kySheet.on')) { await page.click('#kySheet .ky-pop-acts .btn:last-child'); await sleep(400); }
  }
  /** Open the Keys screen the way a learner does: the More sheet row. */
  async function openKeys(page) {
    await closePop(page);
    await page.evaluate(() => { openMore(); });
    await sleep(250);
    await page.click('.mrow[data-more="keys"]');
    await page.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'keys', null, { timeout: 8000 });
    await until(() => page.evaluate(() => !!document.querySelector('#kySum') && !/Checking/.test(document.querySelector('#kySum').textContent)), 8000);
    await sleep(150);
  }
  return { BASE, OUT, TOK, T, ERRS, sleep, until, ctxFor, post, behave, reset, calls, flush, server, boot, screen, vis, txt, shot, notif, openKeys, setLang, closePop };
}

module.exports = { create };
