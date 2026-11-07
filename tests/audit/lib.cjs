'use strict';
/*
 * Audit helpers (Playwright library API, no runner). A product / UI review is not a test: nothing here asserts. Every screen is photographed and MEASURED, and the numbers
 * go to a JSON file next to the screenshots for a human to read.
 *
 *   const A = require('./lib.cjs').create('walk');
 *   const ctx = await A.ctx(browser, 'active', { viewport: { width: 390, height: 844 }, lang: 'en' });
 *   const page = await A.open(ctx, '/');
 *   await A.capture(page, 'home', { tag: 'active-390' });
 *   A.save();
 */
const fs = require('fs');
const path = require('path');

const PHONE_UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function create(name) {
  const BASE = process.env.BASE;
  const OUT = process.env.OUT || '/tmp';
  const FONTS = process.env.FONTS || '';
  const TOK = JSON.parse(fs.readFileSync(process.env.TOKENS, 'utf8'));
  const RESULTS = [];
  const fontCss = FONTS && fs.existsSync(path.join(FONTS, 'fonts.css')) ? fs.readFileSync(path.join(FONTS, 'fonts.css'), 'utf8') : '';
  const OVERRIDE = process.env.HTML_OVERRIDE && fs.existsSync(process.env.HTML_OVERRIDE) ? fs.readFileSync(process.env.HTML_OVERRIDE, 'utf8') : null;

  const INIT = `(() => {
    window.__errors = []; window.__rejections = [];
    window.addEventListener('error', e => window.__errors.push(String(e.message)));
    window.addEventListener('unhandledrejection', e => window.__rejections.push(String((e.reason && (e.reason.message || e.reason)) || e)));
  })();`;

  // speech stand-ins (the container has no microphone and no voices): a recogniser that "hears" the next line queued in window.__utter (or waits for window.__say(text)), and a
  // speech-synthesis stub that records what DuSu says. Same idea as tests/daily_voice/browser/lib.cjs.
  const SPEECH = `(() => {
    window.__utter = []; window.__spoken = []; window.__srStarts = 0; window.__srActive = null; window.__hold = false; window.__ttsMs = 60;
    class FakeSR {
      constructor() { this.lang = 'en-US'; this.interimResults = false; this.maxAlternatives = 1; this._on = false; }
      start() { window.__srStarts++; setTimeout(() => { this._on = true; window.__srActive = this; try { this.onstart && this.onstart(); } catch (e) {}
          const t = window.__utter.shift();
          if (t !== undefined) { setTimeout(() => { if (this._on) this._finish(t); }, 30); return; }
          if (window.__hold) return;
          setTimeout(() => { if (!this._on) return; this._on = false; if (window.__srActive === this) window.__srActive = null; try { this.onend && this.onend(); } catch (e) {} }, 400); }, 20); }
      _finish(t) { this._on = false; if (window.__srActive === this) window.__srActive = null; try { this.onresult && this.onresult({ results: [[{ transcript: t, confidence: 0.9 }]] }); } catch (e) {} setTimeout(() => { try { this.onend && this.onend(); } catch (e) {} }, 20); }
      stop() { this._on = false; if (window.__srActive === this) window.__srActive = null; }
      abort() { this.stop(); }
    }
    window.SpeechRecognition = FakeSR; window.webkitSpeechRecognition = FakeSR;
    window.__say = t => { const a = window.__srActive; if (!a) return false; a._finish(t); return true; };
    const ss = window.speechSynthesis; let cur = null;
    if (ss) {
      ss.speak = function (u) { window.__spoken.push(u.text); cur = u; const mine = u; setTimeout(() => { if (cur !== mine) return; try { mine.onstart && mine.onstart(); } catch (e) {}
          setTimeout(() => { if (cur !== mine) return; cur = null; try { mine.onend && mine.onend(); } catch (e) {} }, window.__ttsMs); }, 5); };
      ss.cancel = function () { const c = cur; cur = null; if (c) setTimeout(() => { try { c.onerror && c.onerror({ error: 'canceled' }); } catch (e) {} }, 0); };
      ss.resume = function () {}; ss.getVoices = () => [];
    }
  })();`;

  /** A browser context. device: 'returning' = the learner's own phone (this account's keys already on it), 'new' = nothing in localStorage but the sign-in. */
  async function ctx(browser, who, o = {}) {
    const u = TOK[who];
    const vp = o.viewport || { width: 390, height: 844 };
    const phone = vp.width < 800;
    const c = await browser.newContext({ viewport: vp, deviceScaleFactor: o.dpr || (phone ? 2 : 1), isMobile: phone, hasTouch: phone, serviceWorkers: o.sw ? 'allow' : 'block',
      reducedMotion: o.motion ? 'no-preference' : 'reduce', userAgent: o.ua || (phone ? PHONE_UA : undefined), locale: 'en-IN', timezoneId: 'Asia/Kolkata',
      permissions: o.permissions || [] });
    await c.addInitScript(INIT);
    if (o.speech !== false) await c.addInitScript(SPEECH);
    const base = { dusu_token: u.token, dusu_user: u.user, dusu_lang: o.lang || 'en' };
    const returning = o.device !== 'new';
    const keys = u.keys ? Object.fromEntries(Object.entries(u.keys).slice(0, 2)) : null;
    const quiet = o.firstRun ? {} : { dusu_rewards_intro_seen: '1', dusu_tutorial_seen: '1', dusu_pl_pushhint: '1' };      // first-run overlays are photographed on their own; the sweep skips them
    const seed = Object.assign({}, base, quiet, returning && keys ? { dusu_usemode: 'office', dusu_office_keys: keys, dusu_keys_ok: '1', dusu_keys_owner: u.user.email, dusu_onboarded: 'true' } : {},
      o.seed || {});
    await c.addInitScript(`(() => { try { if (localStorage.getItem('__seeded')) return; localStorage.setItem('__seeded', '1'); const s = ${JSON.stringify(seed)};
      for (const k of Object.keys(s)) localStorage.setItem(k, typeof s[k] === 'string' ? s[k] : JSON.stringify(s[k])); } catch (e) {} })();`);
    if (o.init) await c.addInitScript(o.init);
    // nothing leaves the box; the app's two web fonts are served from the copy made on the host, the Google sign-in script is an empty stub
    // o.html (or the HTML_OVERRIDE env var: a path to a page) replaces the app's HTML for every navigation to the shell - the page before the fixes (OLD_HTML) or a deliberately broken copy (mutants.sh)
    const shell = o.html || OVERRIDE;
    await c.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin === BASE) {
        if (shell && route.request().resourceType() === 'document' && !/^\/(privacy|terms|account-deletion|assets|\.well-known)/.test(url.pathname)) return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: shell });
        return route.continue();
      }
      if (url.hostname === 'fonts.googleapis.com' && fontCss) return route.fulfill({ status: 200, contentType: 'text/css', body: fontCss });
      if (url.hostname === 'fonts.gstatic.com' && FONTS) {
        const f = path.join(FONTS, path.basename(url.pathname));
        if (fs.existsSync(f)) return route.fulfill({ status: 200, contentType: 'font/woff2', body: fs.readFileSync(f), headers: { 'access-control-allow-origin': '*' } });
      }
      if (url.hostname === 'accounts.google.com') return route.fulfill({ status: 200, contentType: 'application/javascript', body: '/* stubbed in the audit */' });
      return route.abort();
    });
    return c;
  }

  /** Open a page and wait for what a learner waits for: /me answered (when signed in) and the first screen settled. */
  async function open(c, urlPath = '/', o = {}) {
    const page = await c.newPage();
    page.__log = { console: [], failed: [], bad: [], dialogs: [] };
    page.on('pageerror', e => page.__log.console.push('pageerror: ' + String((e && e.message) || e)));
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') { const t = m.text(); if (!/Failed to load resource|net::ERR_FAILED|favicon|Autofocus/i.test(t)) page.__log.console.push(m.type() + ': ' + t.slice(0, 240)); } });
    page.on('requestfailed', r => { const u = r.url(); if (u.startsWith(BASE)) page.__log.failed.push(r.method() + ' ' + u.replace(BASE, '')); });
    page.on('response', r => { const u = r.url(); if (u.startsWith(BASE) && r.status() >= 400) page.__log.bad.push(r.status() + ' ' + r.request().method() + ' ' + u.replace(BASE, '').slice(0, 90)); });
    page.on('dialog', d => { page.__log.dialogs.push(d.message()); d.accept(); });
    const me = o.waitMe === false ? null : page.waitForResponse(r => new URL(r.url()).pathname === '/me' && r.request().method() === 'GET', { timeout: 20000 }).catch(() => null);
    await page.goto(BASE + urlPath, { waitUntil: 'domcontentloaded' });
    if (me) await me;
    await sleep(o.settle || 900);
    return page;
  }

  const screenId = page => page.evaluate(() => (document.querySelector('.screen.on') || {}).id || '');

  /** Everything we can measure about what is on screen right now. Runs in the page. */
  function measure() {
    const out = {};
    const vw = window.innerWidth, vh = window.innerHeight;
    const parkedFixed = e => { for (let n = e; n && n !== document.body; n = n.parentElement) { if (getComputedStyle(n).position === 'fixed') { const q = n.getBoundingClientRect(); if (q.top >= vh - 1 || q.bottom <= 1 || q.left >= vw - 1 || q.right <= 1) return true; } } return false; };
    const vis = e => { const r = e.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return false; const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) return false;
      if (parkedFixed(e)) return false;
      for (let n = e; n && n !== document.body; n = n.parentElement) { const s = getComputedStyle(n); if (s.display === 'none' || s.visibility === 'hidden') return false; if (n.hasAttribute && n.hasAttribute('hidden')) return false; } return true; };
    const scr = document.querySelector('.screen.on') || document.body;
    const all = [...document.querySelectorAll('body *')].filter(vis);
    const inScreen = e => scr.contains(e) || e.closest('#bnav,.bnav,#hdr,header,.hdr,#kySheet,#msheet,.msheet');
    const label = e => { const t = (e.getAttribute('aria-label') || e.innerText || e.value || e.getAttribute('title') || e.getAttribute('placeholder') || '').trim().replace(/\s+/g, ' ').slice(0, 40); return (e.id ? '#' + e.id : e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/)[0] : '')) + (t ? ' "' + t + '"' : ''); };
    out.screen = scr.id || '';
    out.viewport = [vw, vh];
    // 1. horizontal overflow: the page itself, and anything sticking out of the viewport on the right (not inside a deliberate horizontal scroller)
    out.pageOverflowX = document.documentElement.scrollWidth > vw + 1;
    const wrap = document.querySelector('.wrap');
    out.wrapOverflowX = !!wrap && wrap.scrollWidth > wrap.clientWidth + 1;
    out.scroll = wrap ? { h: wrap.scrollHeight, view: wrap.clientHeight } : null;
    const scrollers = e => { for (let n = e.parentElement; n; n = n.parentElement) { const s = getComputedStyle(n); if (/(auto|scroll)/.test(s.overflowX) && n.scrollWidth > n.clientWidth + 1) return true; } return false; };
    out.sticksOut = all.filter(e => inScreen(e)).filter(e => { const r = e.getBoundingClientRect(); return (r.right > vw + 1 || r.left < -1) && !scrollers(e) && getComputedStyle(e).position !== 'fixed'; }).slice(0, 8).map(label);
    // 2. tap targets
    const ix = all.filter(e => /^(A|BUTTON|INPUT|SELECT|TEXTAREA|SUMMARY)$/.test(e.tagName) || e.getAttribute('role') === 'button' || e.getAttribute('role') === 'tab' || e.hasAttribute('onclick') || e.getAttribute('tabindex') === '0');
    const seen = new Set();
    out.interactive = ix.length;
    out.smallTargets = ix.filter(e => inScreen(e) && e.type !== 'hidden' && e.type !== 'radio' && e.type !== 'checkbox').map(e => { const r = e.getBoundingClientRect(); return { l: label(e), w: Math.round(r.width), h: Math.round(r.height) }; })
      .filter(x => (x.w < 44 || x.h < 44) && Math.min(x.w, x.h) < 40).filter(x => { if (seen.has(x.l)) return false; seen.add(x.l); return true; }).slice(0, 14);
    // 3. text size
    const texts = all.filter(e => inScreen(e) && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1));
    const sizes = {};
    let tiny = [];
    for (const e of texts) { const fs_ = parseFloat(getComputedStyle(e).fontSize); const k = Math.round(fs_ * 2) / 2; sizes[k] = (sizes[k] || 0) + 1;
      if (fs_ < 12) tiny.push({ l: label(e), px: fs_ }); }
    out.fontSizes = sizes;
    out.textNodes = texts.length;
    out.tinyText = { count: tiny.length, sample: tiny.slice(0, 8) };
    // 4. contrast (only where the background is a plain colour all the way up; gradients and images are left to the eye)
    const parse = s => { const m = s && s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
    const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const mix = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
    const bgOf = e => { const layers = []; for (let n = e; n && n.nodeType === 1; n = n.parentElement) { const cs = getComputedStyle(n); if (cs.backgroundImage !== 'none' && n !== document.body) return null;
        const b = parse(cs.backgroundColor); if (b && b.a > 0) { layers.push(b); if (b.a >= 0.99) break; } } let base = { r: 11, g: 16, b: 32, a: 1 }; for (let i = layers.length - 1; i >= 0; i--) base = mix(layers[i], base); return base; };
    const low = [];
    let checked = 0;
    for (const e of texts.slice(0, 500)) { const cs = getComputedStyle(e); const fg = parse(cs.color); const bg = bgOf(e); if (!fg || !bg) continue; checked++;
      const f = mix(fg, bg); const L1 = lum(f), L2 = lum(bg); const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      const px = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700; const need = (px >= 24 || (px >= 18.66 && bold)) ? 3 : 4.5;
      if (ratio < need) low.push({ l: label(e), ratio: Math.round(ratio * 100) / 100, need, color: cs.color }); }
    out.contrast = { checked, low: low.length, sample: low.slice(0, 8) };
    // 5. names and alt text
    const hasName = e => { if ((e.getAttribute('aria-label') || '').trim() || (e.getAttribute('aria-labelledby') || '').trim() || (e.getAttribute('title') || '').trim()) return true;
      if ((e.innerText || '').trim()) return true; if (e.tagName === 'INPUT' && (e.value || e.getAttribute('placeholder') || (e.labels && e.labels.length))) return true; if (e.querySelector && e.querySelector('img[alt]:not([alt=""]),svg title')) return true;
      if (e.tagName === 'SELECT' && e.labels && e.labels.length) return true; if (e.tagName === 'TEXTAREA' && (e.getAttribute('placeholder') || (e.labels && e.labels.length))) return true; return false; };
    out.noName = ix.filter(e => inScreen(e) && !hasName(e)).slice(0, 10).map(label);
    out.imgNoAlt = [...document.images].filter(i => vis(i) && !i.hasAttribute('alt')).slice(0, 6).map(i => i.getAttribute('src') || '');
    out.inputsNoLabel = [...document.querySelectorAll('input:not([type=hidden]),select,textarea')].filter(e => vis(e) && inScreen(e) && !(e.labels && e.labels.length) && !e.getAttribute('aria-label') && !e.getAttribute('aria-labelledby')).slice(0, 8)
      .map(e => label(e) + (e.getAttribute('placeholder') ? ' [placeholder only]' : ' [no label at all]'));
    // 6. structure
    out.headings = [...scr.querySelectorAll('h1,h2,h3')].filter(vis).slice(0, 12).map(h => h.tagName + ': ' + h.innerText.trim().replace(/\s+/g, ' ').slice(0, 50));
    out.h1Count = [...document.querySelectorAll('h1')].filter(vis).length;
    const ids = {}; for (const e of document.querySelectorAll('[id]')) ids[e.id] = (ids[e.id] || 0) + 1;
    out.dupIds = Object.keys(ids).filter(k => ids[k] > 1).slice(0, 8);
    out.lang = document.documentElement.lang;
    out.text = (scr.innerText || '').replace(/\n{3,}/g, '\n\n').trim().slice(0, 3500);
    out.dom = document.querySelectorAll('*').length;
    return out;
  }

  /** Photograph + measure the current screen. opts.full: also photograph the whole scroll height (the app scrolls inside `.wrap`, so a taller window shows it all). */
  async function capture(page, name, o = {}) {
    const tag = o.tag || 'x';
    const file = `${tag}__${name}`.replace(/[^a-zA-Z0-9_.-]+/g, '-');
    await sleep(o.settle || 500);
    const m = await page.evaluate(measure);
    await page.screenshot({ path: path.join(OUT, file + '.png') }).catch(() => {});
    let shots = [file + '.png'];
    if (o.full !== false && m.scroll && m.scroll.h > m.scroll.view + 60) {
      const vp = page.viewportSize();
      const extra = (vp.height - m.scroll.view);                      // header + bottom nav
      const target = Math.min(m.scroll.h + extra + 8, 3600);
      await page.setViewportSize({ width: vp.width, height: target });
      await sleep(350);
      await page.screenshot({ path: path.join(OUT, file + '-full.png') }).catch(() => {});
      shots.push(file + '-full.png');
      await page.setViewportSize(vp);
      await sleep(250);
    }
    const rec = Object.assign({ name, tag, shots, console: page.__log.console.slice(-6), failed: page.__log.failed.slice(-6), bad: page.__log.bad.slice(-6) }, m);
    page.__log.console.length = 0; page.__log.failed.length = 0; page.__log.bad.length = 0;
    RESULTS.push(rec);
    return rec;
  }

  const save = (n) => fs.writeFileSync(path.join(OUT, `results-${n || name}.json`), JSON.stringify(RESULTS, null, 1));
  const post = async (p, body) => { const r = await fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); let j = null; try { j = await r.json(); } catch (e) {} return { status: r.status, body: j }; };
  async function api(who, p, method = 'GET', body) {
    const r = await fetch(BASE + p, { method, headers: { Authorization: 'Bearer ' + TOK[who].token, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, body: j };
  }
  const setLang = (who, lang) => api(who, '/lang', 'POST', { token: TOK[who].token, lang });
  const settings = s => post('/__audit/settings', { settings: s });
  return { BASE, OUT, TOK, RESULTS, sleep, ctx, open, capture, save, screenId, post, api, setLang, settings, measure };
}

module.exports = { create, PHONE_UA, sleep };
