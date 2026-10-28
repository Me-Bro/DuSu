'use strict';
/*
 * Shared helpers for the "a locked screen must not kill Daily Talk / Learn" browser spec (Playwright library API, no test runner).
 *
 *  - FAKE SpeechRecognition: each start "hears" the next line queued in window.__utter; with window.__hold it just LISTENS until the spec speaks (window.__say) - the state a
 *    learner is in when the screen locks. Like a real browser it refuses to start on a hidden page, and ends a live recognition when the page becomes hidden.
 *  - a speech-synthesis stub with a controllable length (window.__ttsMs) that records what is spoken and what is spoken WHILE hidden.
 *  - window.__setHidden(true|false): the lock / the unlock - overrides document.hidden / visibilityState and fires visibilitychange (what Chrome does).
 *  - a WebSocket PROXY (Playwright routeWebSocket) between the page and the REAL server: every frame in both directions is recorded per connection, inbound frames can be
 *    HELD and released, the connection can be KILLED, or FROZEN (frames silently dropped both ways while the page still believes the socket is open = a half-open socket).
 * The server is the real app on a scratch Postgres with scripted fake providers (tests/keys/e2e_server.py); reads BASE / TOKENS / OUT from the environment run_real.sh sets.
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
    window.__errors = []; window.__rejections = []; window.__utter = []; window.__spoken = []; window.__spokenHidden = []; window.__heard = 0; window.__ttsMs = 60;
    window.__hold = false; window.__srStarts = 0; window.__srActive = null; window.__hiddenNow = false; window.__cancels = 0;
    window.addEventListener('error', e => window.__errors.push(String(e.message)));
    window.addEventListener('unhandledrejection', e => window.__rejections.push(String((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
    class FakeSR {
      constructor() { this.lang = 'en-US'; this.interimResults = false; this.maxAlternatives = 1; this._on = false; }
      start() {
        window.__srStarts++;
        setTimeout(() => {
          if (window.__hiddenNow) { try { this.onerror && this.onerror({ error: 'aborted' }); } catch (e) {} try { this.onend && this.onend(); } catch (e) {} return; }   // a hidden page cannot listen
          this._on = true; window.__srActive = this;
          try { this.onstart && this.onstart(); } catch (e) {}
          const t = window.__utter.shift();
          if (t !== undefined) { window.__heard++; setTimeout(() => { if (this._on) this._finish(t); }, 30); return; }
          if (window.__hold) return;                                                   // listening; the spec speaks with __say()
          setTimeout(() => { if (!this._on) return; this._on = false; if (window.__srActive === this) window.__srActive = null; try { this.onend && this.onend(); } catch (e) {} }, 60);
        }, 20);
      }
      _finish(t) {
        this._on = false; if (window.__srActive === this) window.__srActive = null;
        try { this.onresult && this.onresult({ results: [[{ transcript: t, confidence: 0.9 }]] }); } catch (e) {}
        setTimeout(() => { try { this.onend && this.onend(); } catch (e) {} }, 20);
      }
      stop() { this._on = false; if (window.__srActive === this) window.__srActive = null; }
      abort() { this.stop(); }
    }
    window.SpeechRecognition = FakeSR; window.webkitSpeechRecognition = FakeSR;
    window.__say = t => { const a = window.__srActive; if (!a) return false; window.__heard++; a._finish(t); return true; };
    window.__setHidden = h => {
      window.__hiddenNow = h;
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => h });
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (h ? 'hidden' : 'visible') });
      document.dispatchEvent(new Event('visibilitychange'));
      if (h) { const a = window.__srActive; if (a) { a._on = false; window.__srActive = null; try { a.onend && a.onend(); } catch (e) {} } }   // the browser stops listening when the page is hidden
    };
    const ss = window.speechSynthesis; let cur = null;
    if (ss) {
      ss.speak = function (u) {
        window.__spoken.push(u.text); if (window.__hiddenNow) window.__spokenHidden.push(u.text);
        cur = u; const mine = u;
        setTimeout(() => { if (cur !== mine) return; try { mine.onstart && mine.onstart(); } catch (e) {}
          setTimeout(() => { if (cur !== mine) return; cur = null; try { mine.onend && mine.onend(); } catch (e) {} }, window.__ttsMs); }, 5);
      };
      // like a real browser, cancelling an utterance in flight ENDS it (an error event, canceled): the page's awaited say() resolves and a chain would carry on to its next line
      ss.cancel = function () { window.__cancels++; const c = cur; cur = null; if (c) setTimeout(() => { try { c.onerror && c.onerror({ error: 'canceled' }); } catch (e) {} }, 0); };
      ss.resume = function () {}; ss.getVoices = () => [];
    }
  })();`;

  async function ctxFor(browser, who, o = {}) {
    const u = TOK[who];
    const vp = o.viewport || { width: 390, height: 844 };
    const ctx = await browser.newContext({ viewport: vp, isMobile: true, hasTouch: true, serviceWorkers: 'block', reducedMotion: 'reduce' });
    await ctx.addInitScript(INIT);
    const seed = Object.assign({ dusu_token: u.token, dusu_user: u.user, dusu_onboarded: 'true', dusu_state: { onboarded: true }, dusu_rewards_intro_seen: '1', dusu_usemode: 'office',
      dusu_office_keys: { groq: 'gsk_test_key_123', gemini: 'AIzaTestKey' }, dusu_keys_ok: '1', dusu_keys_owner: u.user.email, dusu_lang: 'en', dusu_pl_pushhint: '1' }, o.seed || {});
    await ctx.addInitScript(`(() => { try { if (localStorage.getItem('__seeded')) return; localStorage.setItem('__seeded', '1'); const s = ${JSON.stringify(seed)};
      for (const k of Object.keys(s)) localStorage.setItem(k, typeof s[k] === 'string' ? s[k] : JSON.stringify(s[k])); } catch (e) {} })();`);
    await ctx.route('**/*', route => new URL(route.request().url()).origin !== BASE ? route.abort() : route.continue());          // nothing leaves the box
    return ctx;
  }

  /** The WebSocket proxy for a context: one record per connection the page opens. */
  async function proxy(ctx) {
    const P = { conns: [], get last() { return this.conns[this.conns.length - 1]; } };
    await ctx.routeWebSocket(/\/ws\/interview/, ws => {
      const server = ws.connectToServer();
      const c = { n: P.conns.length + 1, frames: [], held: [], hold: !!P.holdNew, frozen: false, pageClosed: false, serverClosed: false, killed: false };
      const rec = (dir, m) => { let j = null; try { j = JSON.parse(m); } catch (e) {} c.frames.push({ dir, j, t: Date.now() }); return j; };
      ws.onMessage(m => { rec('out', m); if (!c.frozen) server.send(m); });
      server.onMessage(m => {
        rec('in', m);
        if (c.frozen) return;
        if (c.hold) { c.held.push(m); return; }
        ws.send(m);
      });
      ws.onClose(() => { c.pageClosed = true; try { server.close(); } catch (e) {} });
      server.onClose(() => { c.serverClosed = true; if (!c.frozen) { try { ws.close(); } catch (e) {} } });
      c.release = () => { c.hold = false; const h = c.held.splice(0); for (const m of h) { try { ws.send(m); } catch (e) {} } };
      c.kill = () => { c.killed = true; try { ws.close({ code: 1006, reason: 'gone' }); } catch (e) {} try { server.close(); } catch (e) {} };
      c.out = type => c.frames.filter(f => f.dir === 'out' && f.j && f.j.type === type).map(f => f.j);
      c.in = type => c.frames.filter(f => f.dir === 'in' && f.j && f.j.type === type).map(f => f.j);
      P.conns.push(c);
    });
    P.starts = () => P.conns.flatMap(c => c.out('start'));
    return P;
  }

  const post = async (p, body) => { const r = await fetch(BASE + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); let j = null; try { j = await r.json(); } catch (e) {} return { status: r.status, body: j }; };
  const behave = (provider, mode) => post('/__world/behave', { provider, mode, clear_gate: true });
  const calls = () => post('/__world/calls', { kind: 'chat' }).then(r => (r.body && r.body.n) || 0);
  async function me(who) {
    const r = await fetch(BASE + '/me', { headers: { Authorization: 'Bearer ' + TOK[who].token } });
    return r.json();
  }
  const xp = async who => ((await me(who)).progress || {}).xp;

  async function boot(ctx, urlPath = '/') {
    const page = await ctx.newPage();
    page.on('pageerror', e => ERRS.push('pageerror: ' + String((e && e.message) || e)));
    page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|favicon|WebSocket connection/i.test(m.text())) ERRS.push('console.error: ' + m.text()); });
    const meDone = page.waitForResponse(r => new URL(r.url()).pathname === '/me' && r.request().method() === 'GET', { timeout: 30000 });
    await page.goto(BASE + urlPath, { waitUntil: 'domcontentloaded' });
    await meDone; await sleep(700);
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
  // How many times the page counted a session (usageInc). Counting itself is skipped for an "unlimited" learner, so the CALL is what is observed.
  const spyUsage = page => page.evaluate(() => { window.__usageCalls = 0; const f = window.usageInc; window.usageInc = function () { window.__usageCalls++; return f.apply(this, arguments); }; });
  const usageCalls = page => page.evaluate(() => window.__usageCalls);
  const lock = page => page.evaluate(() => window.__setHidden(true));
  const unlock = page => page.evaluate(() => window.__setHidden(false));
  const micOn = page => page.evaluate(() => !document.getElementById('dailyMic').disabled);
  const spoken = page => page.evaluate(() => window.__spoken.slice());
  const spokenHidden = page => page.evaluate(() => window.__spokenHidden.slice());

  /** Open Daily Talk the way a learner does (the bottom tab) and wait until the greeting is done and the mic is handed over. */
  async function openDaily(page, o = {}) {
    await page.click('.btab[data-tab="daily"]');
    await page.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'daily', null, { timeout: 10000 });
    if (o.noWait) return;
    if (!(await until(() => micOn(page), 15000))) throw new Error('Daily Talk never handed the mic over');
  }
  /** One spoken turn: the learner says `text` (queued for the recogniser), taps the mic, and we wait until DuSu's reply card shows. */
  async function sayTurn(page, text, o = {}) {
    await page.evaluate(t => { window.__utter.push(t); }, text);
    const n0 = await page.evaluate(() => document.querySelectorAll('#dailyFeed .msg.ai').length);
    await page.click(o.reply ? '#dcNext' : '#dailyMic');
    return until(() => page.evaluate(n => document.querySelectorAll('#dailyFeed .msg.ai').length > n && !document.getElementById('dailyCard').hidden, n0), o.ms || 15000);
  }
  const bubbles = page => page.evaluate(() => ({ me: document.querySelectorAll('#dailyFeed .msg.user').length, ai: document.querySelectorAll('#dailyFeed .msg.ai').length }));

  return { BASE, OUT, TOK, T, ERRS, sleep, until, ctxFor, proxy, post, behave, calls, me, xp, boot, screen, vis, txt, shot, spyUsage, usageCalls, lock, unlock, micOn, spoken, spokenHidden, openDaily, sayTurn, bubbles };
}

module.exports = { create };
