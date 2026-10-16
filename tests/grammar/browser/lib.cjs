'use strict';
/* Shared helpers for the Grammar Coach browser spec (Playwright library API, no test runner): a signed-in context for a seeded learner with a FAKE
   SpeechRecognition (the learner "says" whatever is queued in window.__utter) and a stub speechSynthesis, page helpers that WAIT for an outcome, and the
   real HTTP API as that learner. */
const fs = require('fs');
const path = require('path');
const { makeT, sleep } = require('../../resume_interview/browser/harness.cjs');

function create(name) {
  const BASE = process.env.BASE, OUT = process.env.OUT || '/tmp';
  const TOK = JSON.parse(fs.readFileSync(process.env.TOKENS, 'utf8'));
  const T = makeT(name);
  const ERRS = [];

  const INIT = `(() => {
    window.__errors = []; window.__rejections = []; window.__xss = 0; window.__utter = []; window.__spoken = []; window.__heard = 0;
    window.addEventListener('error', e => window.__errors.push(String(e.message)));
    window.addEventListener('unhandledrejection', e => window.__rejections.push(String((e.reason && (e.reason.stack || e.reason.message)) || e.reason)));
    // the learner: each recogniser start "hears" the next queued line (then ends)
    class FakeSR { constructor(){ this.lang = 'en-US'; this.interimResults = false; this.maxAlternatives = 1; }
      start(){ setTimeout(() => { try{ this.onstart && this.onstart(); }catch(e){}
        const t = window.__utter.shift();
        if(t === undefined){ setTimeout(() => { try{ this.onend && this.onend(); }catch(e){} }, 60); return; }
        window.__heard++;
        setTimeout(() => { try{ this.onresult && this.onresult({ results:[[{ transcript:t, confidence:0.9 }]] }); }catch(e){}
          setTimeout(() => { try{ this.onend && this.onend(); }catch(e){} }, 20); }, 30); }, 20); }
      stop(){ } abort(){ } }
    window.SpeechRecognition = FakeSR; window.webkitSpeechRecognition = FakeSR;
    const ss = window.speechSynthesis; let cur = null;
    if(ss){ ss.speak = function(u){ window.__spoken.push(u.text); cur = u; const mine = u; setTimeout(() => { if(cur !== mine) return; try{ mine.onstart && mine.onstart(); }catch(e){}
        setTimeout(() => { if(cur !== mine) return; cur = null; try{ mine.onend && mine.onend(); }catch(e){} }, 60); }, 5); };
      ss.cancel = function(){ cur = null; }; ss.getVoices = () => []; }
  })();`;

  async function ctxFor(browser, who, o = {}) {
    const u = TOK[who];
    const vp = o.viewport || { width: 390, height: 844 };
    const ctx = await browser.newContext({ viewport: vp, isMobile: vp.width < 800, hasTouch: vp.width < 800, serviceWorkers: 'block', reducedMotion: 'reduce' });
    await ctx.addInitScript(INIT);
    const seed = Object.assign({ dusu_token: u.token, dusu_user: u.user, dusu_onboarded: 'true', dusu_state: { onboarded: true, grammar_coach: true }, dusu_rewards_intro_seen: '1',
      dusu_usemode: 'office', dusu_office_keys: { groq: 'gsk_test_key_123', gemini: 'AIzaTestKey' }, dusu_keys_ok: '1', dusu_keys_owner: u.user.email, dusu_lang: 'en' }, o.seed || {});
    await ctx.addInitScript(`(() => { try { if (localStorage.getItem('__seeded')) return; localStorage.setItem('__seeded', '1'); const s = ${JSON.stringify(seed)};
      for (const k of Object.keys(s)) localStorage.setItem(k, typeof s[k] === 'string' ? s[k] : JSON.stringify(s[k])); } catch (e) {} })();`);
    await ctx.route('**/*', route => new URL(route.request().url()).origin !== BASE ? route.abort() : route.continue());
    return ctx;
  }
  const H = who => ({ Authorization: 'Bearer ' + TOK[who].token, 'Content-Type': 'application/json' });
  const api = async (who, method, p, body) => {
    const r = await fetch(BASE + '/gcoach' + p, { method, headers: H(who), body: body ? JSON.stringify(body) : undefined });
    let j = null; try { j = await r.json(); } catch (e) {}
    return { status: r.status, body: j };
  };
  async function boot(ctx, urlPath, waitSel = '#gc.on') {
    const page = await ctx.newPage();
    page.on('pageerror', e => ERRS.push('pageerror: ' + String((e && e.message) || e)));
    page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|favicon/i.test(m.text())) ERRS.push('console.error: ' + m.text()); });
    page.__dialogs = [];
    page.on('dialog', d => { page.__dialogs.push(d.message()); d.accept(); });
    const meDone = page.waitForResponse(r => new URL(r.url()).pathname === '/me' && r.request().method() === 'GET', { timeout: 30000 });
    await page.goto(BASE + urlPath, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector(waitSel, { timeout: 15000 });
    await meDone; await sleep(400);
    return page;
  }
  const settled = page => page.waitForFunction(() => { const b = document.getElementById('gcBody'); return b && !b.querySelector('.spin') && b.textContent.trim().length > 0; }, null, { timeout: 15000 });
  const body = page => page.evaluate(() => document.getElementById('gcBody').innerText);
  const vis = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); if (!e) return false; const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return !e.closest('[hidden]') && cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0; }, sel);
  async function until(fn, ms = 10000, every = 100) { const end = Date.now() + ms; for (;;) { try { if (await fn()) return true; } catch (e) {} if (Date.now() > end) return false; await sleep(every); } }
  const shot = (page, n) => page.screenshot({ path: path.join(OUT, n + '.png'), fullPage: false }).catch(() => {});
  async function tab(page, k) { await page.click(`.gc-tab:nth-child(${k})`); await sleep(100); await settled(page); }
  return { BASE, OUT, TOK, T, ERRS, sleep, until, ctxFor, api, boot, settled, body, vis, shot, tab };
}
module.exports = { create };
