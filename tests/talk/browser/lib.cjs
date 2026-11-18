'use strict';
/* Shared helpers for the Talk browser specs (Playwright library API, no test runner). Built on the daily_voice harness (the fake recogniser that listens until the spec "speaks", the speech
   stub with a controllable length, the lock / unlock of the page, the WebSocket proxy that can kill / freeze / hold a connection) and adds: a WebSocket proxy that can also REWRITE and
   INJECT frames (hostile text a real server would never send), the recogniser's language log, the XSS canary, and Talk's own page helpers. */
const path = require('path');
const base = require('../../daily_voice/browser/lib.cjs');
const { sleep } = require('../../resume_interview/browser/harness.cjs');

function create(name) {
  const L = base.create(name);
  const { BASE, TOK, T, OUT } = L;

  const INIT = `(() => {
    window.__xss = 0; window.__srLangs = [];
    const S = window.SpeechRecognition;
    if (S && S.prototype && S.prototype.start) { const st = S.prototype.start; S.prototype.start = function () { try { window.__srLangs.push(this.lang); } catch (e) {} return st.apply(this, arguments); }; }
  })();`;
  async function ctxFor(browser, who, o = {}) {
    const seed = Object.assign({ dusu_state: { onboarded: true, talk_v3: o.cachedOn === false ? false : true, grammar_lab: true }, dusu_lang: 'hi' }, o.seed || {});
    const ctx = await base_ctx(browser, who, Object.assign({}, o, { seed }));
    await ctx.addInitScript(INIT);
    return ctx;
  }
  const base_ctx = (browser, who, o) => L.ctxFor(browser, who, o);

  /** The WebSocket proxy of the daily_voice harness plus P.rewrite(frame, conn) -> a frame | false (drop) and conn.inject(frame). */
  async function proxy(ctx) {
    const P = { conns: [], rewrite: null, get last() { return this.conns[this.conns.length - 1]; } };
    await ctx.routeWebSocket(/\/ws\/interview/, ws => {
      if (P.refuse) { try { ws.close({ code: 1006, reason: 'refused' }); } catch (e) {} return; }
      const server = ws.connectToServer();
      const c = { n: P.conns.length + 1, frames: [], held: [], hold: false, frozen: false, pageClosed: false, serverClosed: false, killed: false };
      const rec = (dir, m) => { let j = null; try { j = JSON.parse(m); } catch (e) {} c.frames.push({ dir, j, t: Date.now() }); return j; };
      ws.onMessage(m => { rec('out', m); if (!c.frozen) server.send(m); });
      server.onMessage(m => {
        const j = rec('in', m);
        if (c.frozen) return;
        if (c.hold) { c.held.push(m); return; }
        if (P.rewrite && j) { const r = P.rewrite(j, c); if (r === false) return; if (r && r !== j) m = JSON.stringify(r); }
        ws.send(m);
      });
      ws.onClose(() => { c.pageClosed = true; try { server.close(); } catch (e) {} });
      server.onClose(() => { c.serverClosed = true; if (!c.frozen) { try { ws.close(); } catch (e) {} } });
      c.inject = obj => { try { ws.send(JSON.stringify(obj)); } catch (e) {} };
      c.release = () => { c.hold = false; const h = c.held.splice(0); for (const m of h) { try { ws.send(m); } catch (e) {} } };
      c.kill = () => { c.killed = true; try { ws.close({ code: 1006, reason: 'gone' }); } catch (e) {} try { server.close(); } catch (e) {} };
      c.out = type => c.frames.filter(f => f.dir === 'out' && f.j && f.j.type === type).map(f => f.j);
      c.in = type => c.frames.filter(f => f.dir === 'in' && f.j && f.j.type === type).map(f => f.j);
      P.conns.push(c);
    });
    P.starts = () => P.conns.flatMap(c => c.out('start'));
    return P;
  }

  // ---- the server's test hooks and the Talk API as a learner
  const e2e = async (p, body) => { const r = await fetch(BASE + '/__e2e' + p, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }); return r.json(); };
  const script = replies => e2e('/script', { replies });
  const fail = n => e2e('/fail', { n });
  const setting = (key, value) => e2e('/setting', { key, value });
  const reset = async () => { await e2e('/reset', {}); await setting('talk_v3', 'on'); await setting('grammar_lab', 'on'); await setting('home_ai', 'off'); await setting('bilingual', 'on'); };
  const log = () => e2e('/log');
  const tk = async (who, p, method, bodyObj) => {
    const r = await fetch(BASE + '/tk' + p, { method: method || 'GET', headers: { Authorization: 'Bearer ' + TOK[who].token, 'Content-Type': 'application/json' }, body: bodyObj ? JSON.stringify(bodyObj) : undefined });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, body: j };
  };
  const awards = async who => (await log()).awards.filter(a => a.uid === TOK[who].user.sub);

  // ---- page helpers
  const screen = L.screen, vis = L.vis, until = L.until;
  const txt = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.innerText : null; }, sel);
  const tc = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.textContent : null; }, sel);
  const settled = page => page.waitForFunction(() => { const b = document.getElementById('tkBody'); return b && !b.querySelector('.spin') && b.textContent.trim().length > 0; }, null, { timeout: 15000 });
  const onSession = page => page.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'session', null, { timeout: 12000 });
  async function bootTalk(ctx, urlPath = '/talk') {
    const page = await L.boot(ctx, urlPath);
    await page.waitForSelector('#tk.on', { timeout: 15000 }); await settled(page);
    return page;
  }
  const selectLevel = async (page, id) => { await page.click('#tkLv-' + id); await page.waitForFunction(i => document.getElementById('tkLv-' + i).getAttribute('aria-checked') === 'true', id); };
  /** Start a Talk chat from the topic card; wait for the opener and (unless noMic) the listening recogniser. */
  async function startChat(page, o = {}) {
    await page.evaluate(() => { window.__hold = true; });
    if (o.level) await selectLevel(page, o.level);
    await page.click('#tkStart');
    await onSession(page);
    await L.sessReady(page, { noMic: !!o.noMic });
  }
  const subs = page => page.evaluate(() => [...document.querySelectorAll('#feed .tk-sub')].map(e => ({ text: e.textContent, inBubble: !!e.closest('.bubble'), parentIsMsg: e.parentElement.classList.contains('msg') })));
  const fixes = page => page.evaluate(() => [...document.querySelectorAll('#feed .tk-fix')].map(e => ({ text: e.innerText, c: e.dataset.c, inMsg: !!e.closest('.msg'), inBubble: !!e.closest('.bubble'), prevIsUser: !!(e.previousElementSibling && e.previousElementSibling.classList.contains('user')), prevText: e.previousElementSibling ? e.previousElementSibling.textContent.trim() : null })));
  const order = page => page.evaluate(() => [...document.querySelectorAll('#feed > *')].map(e => e.classList.contains('tk-fix') ? 'fix' : e.classList.contains('thinking') ? 'think' : e.classList.contains('user') ? 'user' : e.classList.contains('ai') ? 'ai' : e.className));
  const shot = (page, n) => L.shot(page, n);
  /** a stable audit of one screen: horizontal overflow, targets < 44 px, text < 12 px */
  const audit = (page, rootSel) => page.evaluate(root => {
    const el = document.querySelector(root), bad = [], tiny = [], wide = [];
    const vis2 = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && !e.closest('[hidden]'); };
    el.querySelectorAll('button, textarea, input, a, [role=button], [role=radio]').forEach(e => { if (!vis2(e)) return; const r = e.getBoundingClientRect(); if (r.width < 43.5 || r.height < 43.5) bad.push((e.id || e.className || e.tagName) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)); });
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) { const n = w.currentNode; if (!n.nodeValue.trim()) continue; const p = n.parentElement; if (!vis2(p)) continue; const fs = parseFloat(getComputedStyle(p).fontSize); if (fs < 12) tiny.push(fs + 'px ' + n.nodeValue.trim().slice(0, 30)); }
    const vw = document.documentElement.clientWidth;
    el.querySelectorAll('*').forEach(e => { if (!vis2(e)) return; const r = e.getBoundingClientRect(); if (r.right > vw + 1 || r.left < -1) wide.push((e.id || e.className || e.tagName).toString().slice(0, 30)); });
    return { hScroll: document.documentElement.scrollWidth > vw + 1, wide: wide.slice(0, 5), small: bad, tiny: tiny.slice(0, 5) };
  }, rootSel);
  const clean = (r, name) => T.ok(!r.hScroll && !r.wide.length && !r.small.length && !r.tiny.length, `${name}: no horizontal overflow, every control >= 44 px, text >= 12 px ${JSON.stringify(r)}`);
  const hasDeva = s => /[ऀ-ॿ]/.test(s);

  return Object.assign({}, L, { ctxFor, proxy, e2e, script, fail, setting, reset, log, tk, awards, txt, tc, settled, onSession, bootTalk, selectLevel, startChat, subs, fixes, order, shot, audit, clean, hasDeva, screen, vis, until, sleep });
}
module.exports = { create };
