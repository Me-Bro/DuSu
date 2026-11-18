'use strict';
/* Shared helpers for the Grammar Lab browser specs (Playwright library API, no test runner): a signed-in context for a seeded learner with a FAKE SpeechRecognition (the
   learner "says" whatever is queued in window.__utter) and a stub speechSynthesis, page helpers that WAIT for an outcome, and the real HTTP API as that learner. */
const fs = require('fs');
const path = require('path');
const { makeT, sleep } = require('../../resume_interview/browser/harness.cjs');

function create(name) {
  const BASE = process.env.BASE, OUT = process.env.OUT || '/tmp';
  const TOK = JSON.parse(fs.readFileSync(process.env.TOKENS, 'utf8'));
  const T = makeT(name);
  const ERRS = [];

  const INIT = `(() => {
    window.__errors = []; window.__rejections = []; window.__xss = 0; window.__utter = []; window.__spoken = []; window.__heard = 0; window.__srStarts = 0; window.__srError = null;
    window.addEventListener('error', e => window.__errors.push(String(e.message)));
    window.addEventListener('unhandledrejection', e => window.__rejections.push(String((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
    // the learner: each recogniser start "hears" the next queued line (then ends); window.__srError = 'not-allowed' makes the next start fail like a denied microphone
    class FakeSR { constructor(){ this.lang = 'en-US'; this.interimResults = false; this.maxAlternatives = 1; }
      start(){ window.__srStarts++; window.__srLang = this.lang; setTimeout(() => { try{ this.onstart && this.onstart(); }catch(e){}
        if(window.__srHold){ this.__held = true; return; }                       // a recogniser that keeps listening until it is stopped (to look at the listening state)
        if(window.__srError){ const er = window.__srError; setTimeout(() => { try{ this.onerror && this.onerror({ error: er }); this.onend && this.onend(); }catch(e){} }, 20); return; }
        const t = window.__utter.shift();
        if(t === undefined){ setTimeout(() => { try{ this.onend && this.onend(); }catch(e){} }, 60); return; }
        window.__heard++;
        setTimeout(() => { try{ this.onresult && this.onresult({ results:[[{ transcript:t, confidence:0.9 }]] }); }catch(e){}
          setTimeout(() => { try{ this.onend && this.onend(); }catch(e){} }, 20); }, 30); }, 20); }
      stop(){ if(this.__held){ this.__held = false; setTimeout(() => { try{ this.onend && this.onend(); }catch(e){} }, 10); } } abort(){ this.__held = false; } }
    window.SpeechRecognition = FakeSR; window.webkitSpeechRecognition = FakeSR;
    const ss = window.speechSynthesis; let cur = null;
    if(ss){ ss.speak = function(u){ window.__spoken.push({ text:u.text, lang:u.lang }); cur = u; const mine = u; setTimeout(() => { if(cur !== mine) return; try{ mine.onstart && mine.onstart(); }catch(e){}
        setTimeout(() => { if(cur !== mine) return; cur = null; try{ mine.onend && mine.onend(); }catch(e){} }, 60); }, 5); };
      ss.cancel = function(){ cur = null; }; ss.getVoices = () => []; }
  })();`;
  const NO_SR = `(() => { try{ delete window.SpeechRecognition; delete window.webkitSpeechRecognition; }catch(e){} window.SpeechRecognition = undefined; window.webkitSpeechRecognition = undefined; })();`;

  async function ctxFor(browser, who, o = {}) {
    const u = TOK[who];
    const vp = o.viewport || { width: 390, height: 844 };
    const ctx = await browser.newContext({ viewport: vp, isMobile: vp.width < 800, hasTouch: vp.width < 800, serviceWorkers: 'block', reducedMotion: o.motion || 'reduce' });
    await ctx.addInitScript(INIT);
    if (o.noSR) await ctx.addInitScript(NO_SR);
    const seed = Object.assign({ dusu_token: u.token, dusu_user: u.user, dusu_onboarded: 'true', dusu_state: { onboarded: true, grammar_lab: o.cachedOn === false ? false : true }, dusu_rewards_intro_seen: '1',
      dusu_usemode: 'office', dusu_office_keys: { groq: 'gsk_test_key_123', gemini: 'AIzaTestKey' }, dusu_keys_ok: '1', dusu_keys_owner: u.user.email, dusu_lang: 'hi' }, o.seed || {});
    await ctx.addInitScript(`(() => { try { if (localStorage.getItem('__seeded')) return; localStorage.setItem('__seeded', '1'); const s = ${JSON.stringify(seed)};
      for (const k of Object.keys(s)) localStorage.setItem(k, typeof s[k] === 'string' ? s[k] : JSON.stringify(s[k])); } catch (e) {} })();`);
    await ctx.route('**/*', route => new URL(route.request().url()).origin !== BASE ? route.abort() : route.continue());
    return ctx;
  }
  const H = who => ({ Authorization: 'Bearer ' + TOK[who].token, 'Content-Type': 'application/json' });
  const api = async (who, method, p, body) => {
    const r = await fetch(BASE + '/lab' + p, { method, headers: H(who), body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, body: j };
  };
  const e2e = async (p, method, body) => { const r = await fetch(BASE + '/__e2e' + p, { method: method || 'GET', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }); return r.json(); };
  const lookup = hi => e2e('/lookup?hi=' + encodeURIComponent(hi));
  async function boot(ctx, urlPath, waitSel = '#gl.on', o = {}) {
    const page = await ctx.newPage();
    page.on('pageerror', e => ERRS.push('pageerror: ' + String((e && e.message) || e)));
    page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|favicon/i.test(m.text())) ERRS.push('console.error: ' + m.text()); });
    page.__dialogs = [];
    page.on('dialog', d => { page.__dialogs.push(d.message()); d.accept(); });
    const meDone = o.noMe ? Promise.resolve() : page.waitForResponse(r => new URL(r.url()).pathname === '/me' && r.request().method() === 'GET', { timeout: 30000 });
    await page.goto(BASE + urlPath, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector(waitSel, { timeout: 15000, state: o.state || 'attached' });
    await meDone; await sleep(400);
    return page;
  }
  const settled = page => page.waitForFunction(() => { const b = document.getElementById('glBody'); return b && !b.querySelector('.spin') && b.textContent.trim().length > 0; }, null, { timeout: 15000 });
  const body = page => page.evaluate(() => document.getElementById('glBody').innerText);
  const vis = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return !e.closest('[hidden]') && cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0; }, sel);
  const txt = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.textContent : null; }, sel);
  async function until(fn, ms = 10000, every = 100) { const end = Date.now() + ms; for (;;) { try { if (await fn()) return true; } catch (e) {} if (Date.now() > end) return false; await sleep(every); } }
  const shot = (page, n) => page.screenshot({ path: path.join(OUT, n + '.png'), fullPage: false }).catch(() => {});
  const shotFull = async (page, n) => { await page.evaluate(() => { const w = document.querySelector('.wrap'); if (w) w.scrollTop = 0; }); return page.screenshot({ path: path.join(OUT, n + '.png'), fullPage: false }).catch(() => {}); };
  const path_ = page => page.evaluate(() => location.pathname);
  return { BASE, OUT, TOK, T, ERRS, sleep, until, ctxFor, api, e2e, lookup, boot, settled, body, vis, txt, shot, shotFull, path_ };
}
module.exports = { create };
