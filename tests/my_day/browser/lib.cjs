'use strict';
/*
 * Shared helpers for the My Day browser specs (Playwright library API, no test runner): a signed-in browser context for a seeded learner, the real
 * HTTP API as that learner, page helpers that WAIT for an outcome instead of racing the server, and the learner's own clock (India: no daylight saving).
 *
 *   const L = require('./lib.cjs').create('my day: something');   // reads BASE / TOKENS / OUT from the environment run_real.sh sets
 */
const fs = require('fs');
const path = require('path');
const { makeT, sleep } = require('../../resume_interview/browser/harness.cjs');

function create(name) {
  const BASE = process.env.BASE;
  const OUT = process.env.OUT || '/tmp';
  const TOK = JSON.parse(fs.readFileSync(process.env.TOKENS, 'utf8'));
  const T = makeT(name);
  const ERRS = [];                                                          // every page error / console error of every page in the run

  // ----------------------------------------------------------------------- the learner's clock
  const IST_OFF = 5.5 * 3600 * 1000;
  const ist = d => new Date(d.getTime() + IST_OFF);                         // read with getUTC*
  const hhmm = d => String(ist(d).getUTCHours()).padStart(2, '0') + ':' + String(ist(d).getUTCMinutes()).padStart(2, '0');
  const isoDay = d => ist(d).toISOString().slice(0, 10);
  const wd = d => (ist(d).getUTCDay() + 6) % 7;                              // Mon = 0
  const DAY = 86400000;
  const SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  const INIT = `(() => {
    window.__errors = []; window.__rejections = []; window.__xss = 0;
    window.addEventListener('error', e => window.__errors.push(String(e.message)));
    window.addEventListener('unhandledrejection', e => window.__rejections.push(String((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
  })();`;

  async function ctxFor(browser, who, o = {}) {
    const u = TOK[who];
    const vp = o.viewport || { width: 390, height: 844 };
    const ctx = await browser.newContext({ viewport: vp, isMobile: vp.width < 800, hasTouch: vp.width < 800, serviceWorkers: 'block', reducedMotion: 'reduce' });
    await ctx.addInitScript(INIT);
    // the app's own-keys wall (every normal learner must bring two free keys) is passed the way a real learner passes it: two keys, verified, for THIS account
    const seed = Object.assign({ dusu_token: u.token, dusu_user: u.user, dusu_onboarded: 'true', dusu_state: { onboarded: true, planner: true, bilingual: true }, dusu_rewards_intro_seen: '1',   // a returning learner's cached /me
      dusu_usemode: 'office', dusu_office_keys: { groq: 'gsk_test_key_123', gemini: 'AIzaTestKey' }, dusu_keys_ok: '1', dusu_keys_owner: u.user.email,
      dusu_lang: o.lang || 'en', dusu_pl_pushhint: '1' }, o.seed || {});
    await ctx.addInitScript(`(() => { try { if (localStorage.getItem('__seeded')) return; localStorage.setItem('__seeded', '1'); const s = ${JSON.stringify(seed)};
      for (const k of Object.keys(s)) localStorage.setItem(k, typeof s[k] === 'string' ? s[k] : JSON.stringify(s[k])); } catch (e) {} })();`);
    await ctx.route('**/*', route => new URL(route.request().url()).origin !== BASE ? route.abort() : route.continue());   // nothing leaves the box
    return ctx;
  }

  // the real HTTP API, as that learner
  const api = async (who, method, p, body) => {
    const r = await fetch(BASE + '/planner' + p, { method, headers: { Authorization: 'Bearer ' + TOK[who].token, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, body: j };
  };
  // the learner's language lives on the server (it wins over the device cache on every /me)
  async function setLang(who, lang) {
    const r = await fetch(BASE + '/lang', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: TOK[who].token, lang }) });
    if (!r.ok) throw new Error('could not save the language for ' + who + ': ' + r.status);
  }

  // ----------------------------------------------------------------------- the page
  async function boot(ctx, urlPath, o = {}) {
    const page = await ctx.newPage();
    page.on('pageerror', e => ERRS.push('pageerror: ' + String((e && e.message) || e)));
    page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|favicon/i.test(m.text())) ERRS.push('console.error: ' + m.text()); });
    page.__dialogs = [];
    page.on('dialog', d => { page.__dialogs.push(d.message()); d.accept(); });
    // the app paints from the learner's cached state at once and /me answers a moment later: let it settle, like a person who looks before tapping
    const meDone = o.waitMe === false ? null : page.waitForResponse(r => new URL(r.url()).pathname === '/me' && r.request().method() === 'GET', { timeout: 30000 });
    await page.goto(BASE + urlPath, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#pl.on', { timeout: 15000 });
    if (meDone) { await meDone; await sleep(400); }
    await page.waitForFunction(() => { const b = document.getElementById('plBody'); return b && !b.querySelector('.spin') && b.textContent.trim().length > 0; }, null, { timeout: 15000 });
    return page;
  }
  const txt = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.textContent : null; }, sel);
  const body = page => page.evaluate(() => document.getElementById('plBody').innerText);
  const vis = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return !e.closest('[hidden]') && cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0; }, sel);
  const settle = async page => { await page.waitForFunction(() => { const b = document.getElementById('plBody'); return b && !b.querySelector('.spin'); }, null, { timeout: 15000 }); await sleep(150); };
  const notif = page => page.evaluate(() => { const e = document.getElementById('notifTxt'); return e ? e.textContent : ''; });
  const sheetOpen = page => vis(page, '#plSheet');
  const shot = (page, n) => page.screenshot({ path: path.join(OUT, n + '.png'), fullPage: false }).catch(() => {});
  // poll a (sync or async) predicate; true as soon as it holds, false after `ms` - never throws, so a failing check is a failed ASSERTION, not a crashed run
  async function until(fn, ms = 8000, every = 80) {
    const end = Date.now() + ms;
    for (;;) { try { if (await fn()) return true; } catch (e) { /* not yet */ } if (Date.now() > end) return false; await sleep(every); }
  }
  const bodyHas = (page, re) => page.waitForFunction(r => new RegExp(r.src, r.flags).test(document.getElementById('plBody').innerText), { src: re.source, flags: re.flags }, { timeout: 8000 }).then(() => true).catch(() => false);
  const bodyLacks = (page, text) => page.waitForFunction(t => !document.getElementById('plBody').innerText.includes(t), text, { timeout: 8000 }).then(() => true).catch(() => false);

  async function openAdd(page) {
    await page.click('#plAddRow [data-act="addnew"]');
    await page.waitForSelector('#plSheet:not([hidden]) #plTitle2', { timeout: 5000 });
  }
  // a save waits for its OUTCOME (the sheet closes, or the refusal shows) instead of racing the request
  async function save(page) {
    await page.click('#plSheet [data-act="save"]');
    await page.waitForFunction(() => { const s = document.getElementById('plSheet'), e = document.getElementById('plErr'); return s.hidden || (e && !e.hidden); }, null, { timeout: 15000 });
  }
  // move between My Day's tabs the way a person does (a real click on the tab), and wait for the new tab to finish loading
  async function goTab(page, tab) {
    await page.click(`.pl-tab[data-tab="${tab}"]`);
    await page.waitForFunction(t => { const b = document.querySelector(`.pl-tab[data-tab="${t}"]`); return b && b.classList.contains('on'); }, tab, { timeout: 8000 });
    await settle(page);
  }

  return { BASE, OUT, TOK, T, ERRS, sleep, until, ist, hhmm, isoDay, wd, DAY, SHORT, ctxFor, api, setLang, boot, txt, body, vis, settle, notif, sheetOpen, shot,
           bodyHas, bodyLacks, openAdd, save, goTab };
}

module.exports = { create };
