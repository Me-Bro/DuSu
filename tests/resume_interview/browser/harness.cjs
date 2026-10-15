'use strict';
/*
 * Shared harness for the Resume Interview browser specs (Playwright library API, no test runner needed).
 *
 *  - prepareHtml():  a COPY of backend/test_client.html with __AUTH_ENABLED__ / __GOOGLE_CLIENT_ID__ / __MAX_SESSIONS__ filled in
 *                    and the Google script tag removed (nothing off-box is ever fetched).
 *  - startServer():  a tiny static server: the HTML for every client route (SPA fallback), /logo.png, nothing else.
 *  - newCtx():       a browser context with the fake microphone, a controllable speech-synthesis stub, error collectors,
 *                    a seeded localStorage (signed in), and ONE request router: /me and /rinterview/* -> the stateful Mock,
 *                    api.groq.com -> a canned Whisper answer, any other same-origin fetch -> {} (logged), anything off-box -> aborted.
 *  - makeT():        a minimal assertion collector (pass / fail counts, exit code).
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const { Mock, TRANSCRIPT_GOOD } = require('./mock.cjs');

const REPO = process.env.REPO || path.resolve(__dirname, '../../..');
const HTML_SRC = process.env.HTML_SRC || path.join(REPO, 'backend/test_client.html');
const LOGO = path.join(REPO, 'backend/logo.png');

function prepareHtml(src, { auth = true } = {}) {
  let h = src;
  h = h.replace('<script src="https://accounts.google.com/gsi/client" async defer></script>', '');
  h = h.split('__AUTH_ENABLED__').join(auth ? 'true' : 'false');
  h = h.split('__GOOGLE_CLIENT_ID__').join('');
  h = h.split('__MAX_SESSIONS__').join('20');
  return h;
}

function startServer(html) {
  return new Promise(resolve => {
    const srv = http.createServer((req, res) => {
      const p = req.url.split('?')[0];
      if (p === '/logo.png' && fs.existsSync(LOGO)) { res.writeHead(200, { 'content-type': 'image/png' }); return res.end(fs.readFileSync(LOGO)); }
      if (p === '/manifest.webmanifest') { res.writeHead(200, { 'content-type': 'application/manifest+json' }); return res.end('{"name":"DuSu"}'); }
      if (/\.[a-z0-9]+$/i.test(p)) { res.writeHead(404); return res.end('nope'); }
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); res.end(html);
    });
    srv.listen(0, '127.0.0.1', () => resolve({ srv, origin: 'http://127.0.0.1:' + srv.address().port, close: () => new Promise(r => srv.close(r)) }));
  });
}

// in-page init script: runs before any page script, in every document
const INIT = `
(() => {
  window.__events = []; window.__spoken = []; window.__errors = []; window.__rejections = []; window.__streams = []; window.__copied = []; window.__cancels = 0; window.__ttsMs = 80;
  window.addEventListener('error', e => window.__errors.push(String(e.message)));
  window.addEventListener('unhandledrejection', e => window.__rejections.push(String((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
  // speech output: a stub the specs can slow down (__ttsMs) and inspect (__spoken / __events); the container has no audio device
  const ss = window.speechSynthesis; let cur = null;
  if (ss) {
    ss.speak = function (u) { window.__events.push('speak'); window.__spoken.push(u.text); cur = u; const mine = u;
      setTimeout(() => { if (cur !== mine) return; try { mine.onstart && mine.onstart(); } catch (e) {}
        setTimeout(() => { if (cur !== mine) return; cur = null; try { mine.onend && mine.onend(); } catch (e) {} }, window.__ttsMs); }, 5); };
    ss.cancel = function () { window.__events.push('cancel'); window.__cancels++; cur = null; };
    ss.getVoices = () => [];
  }
  // recorders created by the page, so a spec can make one fail
  if (window.MediaRecorder) { const MR = window.MediaRecorder; window.__mrs = []; window.MediaRecorder = class extends MR { constructor(...a) { super(...a); window.__mrs.push(this); } }; }
  // microphone: the browser's fake device, wrapped so a spec can see the call order and reach the tracks
  const md = navigator.mediaDevices;
  if (md && md.getUserMedia) {
    const real = md.getUserMedia.bind(md);
    md.getUserMedia = async function (c) {
      window.__events.push('gum');
      if (window.__micDenied) throw new DOMException('denied', 'NotAllowedError');
      const s = await real(c); window.__streams.push(s); return s;
    };
  }
  try { Object.defineProperty(navigator, 'clipboard', { value: { writeText: async t => { window.__copied.push(t); } }, configurable: true }); } catch (e) {}
})();`;

const seedScript = seed => `(() => { try { if (localStorage.getItem('__seeded')) return; localStorage.setItem('__seeded', '1');
  const s = ${JSON.stringify(seed)}; for (const k of Object.keys(s)) localStorage.setItem(k, typeof s[k] === 'string' ? s[k] : JSON.stringify(s[k])); } catch (e) {} })();`;

function parseMultipart(buf, ctype) {
  const m = /boundary=(.+)$/.exec(ctype || ''); if (!m) return { fields: {}, fileLen: 0 };
  const b = '--' + m[1], s = buf.toString('latin1'), fields = {}; let fileLen = 0;
  s.split(b).forEach(part => {
    const h = /name="([^"]+)"(; filename="([^"]*)")?/.exec(part); if (!h) return;
    const i = part.indexOf('\r\n\r\n'); if (i < 0) return;
    const val = part.slice(i + 4).replace(/\r\n$/, '');
    if (h[3] != null) fileLen = val.length; else (fields[h[1]] = fields[h[1]] || []).push(val);
  });
  return { fields, fileLen };
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

/**
 * env = { origin, mock, groq:{queue,calls}, unmocked:Set, userEmail }
 * o   = { viewport, seed, mobile, dsf, reducedMotion, auth }
 */
async function newCtx(browser, env, o = {}) {
  const vp = o.viewport || { width: 390, height: 844 };
  const ctx = await browser.newContext({ viewport: vp, isMobile: o.mobile != null ? o.mobile : vp.width < 800, hasTouch: vp.width < 800, serviceWorkers: 'block', permissions: ['microphone'],
    acceptDownloads: true, deviceScaleFactor: o.dsf || 1, reducedMotion: o.reducedMotion || 'no-preference' });
  await ctx.addInitScript(INIT);
  const email = (env.mock && env.mock.userEmail) || 'learner@example.com';
  const seed = Object.assign({
    dusu_token: 'tok-test', dusu_user: { sub: 'u-1', email, name: 'Asha Rao', picture: '' },
    dusu_office_keys: { groq: 'gsk_test_key_123', gemini: 'AIzaTestKey' }, dusu_keys_ok: '1', dusu_keys_owner: email, dusu_usemode: 'personal',
    dusu_rewards_intro_seen: '1', dusu_state: env.mock ? env.mock.me : {},
  }, o.seed || {});
  await ctx.addInitScript(seedScript(seed));

  await ctx.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.hostname === 'api.groq.com') {
      const cors = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'POST, OPTIONS' };
      if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
      const buf = req.postDataBuffer() || Buffer.alloc(0), mp = parseMultipart(buf, req.headers()['content-type']);
      env.groq.calls.push({ headers: req.headers(), fields: mp.fields, fileLen: mp.fileLen });
      const q = env.groq.queue.shift() || { text: TRANSCRIPT_GOOD, dur: 24 };
      if (q.delay) await sleep(q.delay);
      if (q.abort) return route.abort(q.abort);
      if (q.status) return route.fulfill({ status: q.status, headers: cors, contentType: 'application/json', body: JSON.stringify({ error: { message: q.message || 'error' } }) });
      return route.fulfill({ status: 200, headers: cors, contentType: 'application/json', body: JSON.stringify(env.mock.sttBody(q, 'groq')) });
    }
    if (url.origin !== env.origin) return route.abort();                      // fonts, analytics ...: nothing leaves the box
    const p = url.pathname;
    if (req.resourceType() === 'document' || p === '/logo.png' || p === '/manifest.webmanifest') return route.continue();
    if (p === '/me') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(env.mock.me) });
    if (p.startsWith('/rinterview')) {
      let json; const raw = req.postDataBuffer() || null;
      if (raw && /json/.test(req.headers()['content-type'] || '')) { try { json = JSON.parse(raw.toString('utf8')); } catch (e) { json = undefined; } }
      const out = env.mock.handle({ method: req.method(), path: p, query: url.searchParams, headers: req.headers(), json, raw });
      if (out.abort) return route.abort(out.abort);
      if (out.delay) await sleep(out.delay);
      return route.fulfill({ status: out.status, contentType: 'application/json', body: JSON.stringify(out.body) });
    }
    if (env.extra && env.extra(route, req, url)) return;                      // a spec's own mocks (admin overview ...)
    env.unmocked.add(req.method() + ' ' + p);                                  // an old-feature background call: answered with an empty object
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  return ctx;
}

async function newEnv(o = {}) {
  const html = prepareHtml(fs.readFileSync(o.htmlSrc || HTML_SRC, 'utf8'), { auth: o.auth !== false });
  const server = await startServer(html);
  const mock = new Mock(o.mock || {});
  return { server, origin: server.origin, mock, groq: { queue: [], calls: [] }, unmocked: new Set(), html };
}

function makeT(name) {
  let pass = 0, fail = 0; const fails = [];
  const t = {
    ok(c, msg) { if (c) { pass++; } else { fail++; fails.push(msg); console.log('  FAIL ' + msg); } return !!c; },
    eq(a, b, msg) { return t.ok(JSON.stringify(a) === JSON.stringify(b), `${msg} (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`); },
    has(s, sub, msg) { return t.ok(String(s).includes(sub), `${msg} (got ${JSON.stringify(String(s).slice(0, 160))}, wanted to contain ${JSON.stringify(sub)})`); },
    section(s) { console.log('\n# ' + s); },
    done() { console.log(`\n${name}: ${pass} passed, ${fail} failed`); return fail === 0; },
    get pass() { return pass; }, get fail() { return fail; }, fails,
  };
  return t;
}

/* ---------- page helpers shared by the specs ---------- */
const view = page => page.evaluate(() => document.getElementById('ri').dataset.view);
const onScreen = page => page.evaluate(() => (document.querySelector('.screen.on') || {}).id || '');
const vis = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return !e.closest('[hidden]') && cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0; }, sel);
const txt = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.textContent : null; }, sel);
const waitView = (page, v, timeout = 8000) => page.waitForFunction(x => document.getElementById('ri') && document.getElementById('ri').dataset.view === x && document.querySelector('.screen.on') && document.querySelector('.screen.on').id === 'ri', v, { timeout });
const waitSel = (page, sel, timeout = 8000) => page.waitForSelector(sel, { state: 'visible', timeout });
const noteText = page => page.evaluate(() => [...document.querySelectorAll('#riNote, #riTopNote')].filter(n => !n.hidden).map(n => n.textContent).join(' | '));
const waitNote = (page, timeout = 8000) => page.waitForFunction(() => [...document.querySelectorAll('#riNote, #riTopNote')].some(n => !n.hidden && n.textContent.trim()), null, { timeout });
const bodyText = page => page.evaluate(() => (document.getElementById('riBody') || {}).textContent || '');

async function collectErrors(page) {
  return page.evaluate(() => ({ errors: window.__errors || [], rejections: window.__rejections || [] }));
}

async function boot(ctx, env, urlPath = '/') {
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + String(e && e.message || e)));
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|favicon/i.test(m.text())) consoleErrors.push('console.error: ' + m.text()); });
  const dialogs = [];
  page.on('dialog', d => { dialogs.push(d.message()); d.accept(); });
  page.__consoleErrors = consoleErrors; page.__dialogs = dialogs;
  await page.goto(env.origin + urlPath, { waitUntil: 'domcontentloaded' });
  return page;
}

// Home -> hub through the real Home card
async function toHub(page) {
  await page.waitForSelector('#home.on', { timeout: 8000 });
  await page.waitForFunction(() => { const e = document.getElementById('riHomeCard'); return e && !e.hidden; }, null, { timeout: 8000 });
  await page.click('#riHomeCard');
  await waitView(page, 'hub');
  await page.waitForSelector('#riNew', { state: 'visible' });
}

// hub -> resume step with a pasted resume -> "Looks right" -> job step -> pasted JD -> Next -> match
async function toMatch(page, env, { resume, jd, jdTitle, jdCompany, viaFile } = {}) {
  const M = require('./mock.cjs');
  await page.click('#riNew'); await waitView(page, 'resume');
  if (viaFile) {
    await page.setInputFiles('#riResFile', { name: 'my-private-name.txt', mimeType: 'text/plain', buffer: Buffer.from(resume || M.RESUME_TEXT) });
  } else {
    await page.fill('#riResText', resume || M.RESUME_TEXT);
    await page.click('#riUseText');
  }
  await page.waitForSelector('#riPre', { state: 'visible' });
  await page.click('#riLooks'); await waitView(page, 'job');
  if (jdTitle) await page.fill('#riJobTitle', jdTitle);
  if (jdCompany) await page.fill('#riJobCompany', jdCompany);
  await page.fill('#riJdText', jd || M.JD_TEXT);
  await page.click('#riNext');
  await page.waitForSelector('#riHero', { state: 'visible', timeout: 15000 });
}

async function startInterview(page) {
  await page.click('#riStart');
  await waitView(page, 'interview', 15000);
  await page.waitForSelector('#riQText', { state: 'visible', timeout: 15000 });
}

// answer the open question once: wait for the mic, tap it, record ~1.4 s of the fake device, stop, wait for the feedback card
async function answerOnce(page, { wait = 1400, expect = 'feedback' } = {}) {
  await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; }, null, { timeout: 10000 });
  await page.click('#riMic');
  await page.waitForSelector('#riRec', { state: 'visible', timeout: 8000 });
  await sleep(wait);
  await page.click('#riStop');
  if (expect === 'feedback') await page.waitForSelector('#riFbCard', { state: 'visible', timeout: 20000 });
}

/* ---------- layout audit shared by the looks specs ---------- */
async function layout(page, label, T, vp) {
  await page.mouse.move(2, 2);   // the global .btn:hover lift/scale (and its 0.15s transition) must not be measured
  await page.waitForFunction(() => ![...document.querySelectorAll('#ri .btn')].some(b => { const t = getComputedStyle(b).transform; return t && t !== 'none'; }), null, { timeout: 2500 }).catch(() => {});
  const r = await page.evaluate(() => {
    const out = { overflow: [], small: [], offscreen: [], clipped: [] };
    const w = document.querySelector('.wrap');
    if (document.documentElement.scrollWidth > innerWidth + 1) out.overflow.push('document ' + document.documentElement.scrollWidth + '>' + innerWidth);
    if (w.scrollWidth > w.clientWidth + 1) out.overflow.push('wrap ' + w.scrollWidth + '>' + w.clientWidth);
    const root = document.getElementById('ri'), rr = root.getBoundingClientRect();
    for (const e of root.querySelectorAll('*')) {
      const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || e.closest('[hidden]')) continue;
      const b = e.getBoundingClientRect(); if (!b.width || !b.height) continue;
      if (b.right > rr.right + 2 || b.left < rr.left - 2) { if (e.id !== 'riBar' && !e.closest('.ri-pre') && !e.closest('.ri-file') && !e.closest('.ri-sr')) out.overflow.push(e.tagName + '.' + e.className + ' ' + Math.round(b.left) + '..' + Math.round(b.right) + ' vs ' + Math.round(rr.left) + '..' + Math.round(rr.right)); }
    }
    const tap = root.querySelectorAll('button, summary, a[href], select, textarea, input:not([type=hidden]):not([type=file]):not([type=checkbox]), label.btn, label.ri-pk');
    for (const e of tap) {
      const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || e.closest('[hidden]')) continue;
      const b = e.getBoundingClientRect(); if (!b.width || !b.height) continue;
      if (b.height < 43.5 || (!e.textContent.trim() && b.width < 43.5)) out.small.push((e.id || e.className || e.tagName) + ' ' + Math.round(b.width) + 'x' + Math.round(b.height));
    }
    // the sticky dock must be wholly on screen and (on a phone) above the bottom nav
    const bar = document.getElementById('riBar'), nav = document.getElementById('bnav');
    if (bar && !bar.hidden) {
      const b = bar.getBoundingClientRect(), n = nav.getBoundingClientRect();
      if (b.bottom > innerHeight + 1 || b.top < 0) out.offscreen.push('dock ' + Math.round(b.top) + '..' + Math.round(b.bottom) + ' of ' + innerHeight);
      if (n.height && n.top > innerHeight / 2 && b.bottom > n.top + 1) out.offscreen.push('dock overlaps the nav: dock bottom ' + Math.round(b.bottom) + ' > nav top ' + Math.round(n.top));
    }
    // buttons whose text is cut off
    for (const e of root.querySelectorAll('.btn, .ri-chip, .ri-tag, .ri-band')) {
      const cs = getComputedStyle(e); if (cs.display === 'none' || e.closest('[hidden]')) continue;
      if (e.scrollWidth > e.clientWidth + 2 && cs.overflow !== 'visible' && !/ellipsis/.test(cs.textOverflow)) out.clipped.push((e.id || e.className) + ' ' + e.scrollWidth + '>' + e.clientWidth);
    }
    return out;
  });
  T.eq(r.overflow, [], `${vp} ${label}: no horizontal overflow`);
  T.eq(r.small, [], `${vp} ${label}: every tap target is >= 44px`);
  T.eq(r.offscreen, [], `${vp} ${label}: the dock is on screen and clear of the nav`);
  T.eq(r.clipped, [], `${vp} ${label}: no clipped button text`);
}


module.exports = { layout, prepareHtml, startServer, newCtx, newEnv, makeT, sleep, parseMultipart, view, onScreen, vis, txt, waitView, waitSel, bodyText, noteText, waitNote, collectErrors, boot, toHub, toMatch, startInterview, answerOnce, REPO, HTML_SRC };
