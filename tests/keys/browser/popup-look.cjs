'use strict';
/* The key-problem pop-up and the Keys screen: every state at phone and desktop width, English and Hindi - screenshots to LOOK at (and a few layout checks).
 *   tests/keys/browser/run_real.sh popup-look.cjs      (screenshots land in ~/.cache/dusu-ky-shots/look-*.png) */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('key pop-up: how it looks');
const { T, ctxFor, reset, boot, sleep, shot, vis, setLang, behave, post, server, TOK, openKeys } = L;

const now = () => Math.floor(Date.now() / 1000);
const STATES = {
  limited: () => ({ state: 'all_limited', now: now(), keys: [{ provider: 'groq', kind: 'limited', scope: 'day', reset_at: now() + 7 * 60 }, { provider: 'gemini', kind: 'limited', scope: 'day', approx: true, reset_at: now() + 20 * 3600 }] }),
  invalid: () => ({ state: 'all_invalid', now: now(), keys: [{ provider: 'groq', kind: 'invalid' }, { provider: 'gemini', kind: 'invalid', expired: true }] }),
  mixed: () => ({ state: 'all_limited', now: now(), keys: [{ provider: 'groq', kind: 'invalid' }, { provider: 'gemini', kind: 'limited', scope: 'day', reset_at: now() + 3 * 3600 }, { provider: 'openrouter', kind: 'limited', scope: 'minute' }] }),
  oneBad: () => ({ state: 'degraded', now: now(), keys: [{ provider: 'gemini', kind: 'invalid', expired: true }] }),
  none: () => ({ state: 'no_keys', now: now(), keys: [] }),
  blocked: () => ({ state: 'all_invalid', now: now(), keys: [{ provider: 'groq', kind: 'forbidden' }, { provider: 'openrouter', kind: 'needs_credit' }] }),
};

(async () => {
  const browser = await chromium.launch();
  await reset({ key_health: 'on', keys_ui: 'on', install_mode: 'on', home_ai: 'on', bilingual: 'on' });
  for (const [vp, vl] of [[{ width: 390, height: 844 }, '390'], [{ width: 360, height: 740 }, '360'], [{ width: 1280, height: 900 }, '1280']]) {
    for (const [lang, ll] of [['en', 'en'], ['hi', 'hi']]) {
      if (ll === 'hi' && vl !== '390') continue;
      await setLang('ph', lang);
      const c = await ctxFor(browser, 'ph', { lang, viewport: vp, seed: { dusu_tutorial_seen: '1' } });
      const p = await boot(c, '/');
      await sleep(900);
      const PLANS = { planDaily: () => KY.plan('daily', { limit: 5 }), planTrial: () => KY.plan('trial', {}), planSessions: () => KY.plan('sessions', { limit: 20 }), generic: () => KY.generic() };
      for (const [name, mk] of Object.entries(Object.assign({}, STATES, PLANS))) {
        if (vl !== '390' && !['limited', 'mixed', 'planDaily'].includes(name)) continue;
        if (ll === 'hi' && !['limited', 'invalid', 'planDaily', 'planTrial'].includes(name)) continue;
        await p.evaluate(() => { try { localStorage.removeItem('dusu_ky_seen'); } catch (e) {} KY.closeSheet(); });
        if (name in PLANS) await p.evaluate(`(${PLANS[name].toString()})()`); else await p.evaluate(kp => KY.problem(kp), mk());
        await sleep(650);
        T.ok(await vis(p, '#kySheet.on'), `${vl}/${ll}/${name}: the pop-up is open`);
        const r = await p.evaluate(() => { const sh = document.getElementById('kySheet'), b = sh.getBoundingClientRect(); return { inside: b.left >= -1 && b.right <= innerWidth + 1 && b.top >= -1 && b.bottom <= innerHeight + 1, overflowX: sh.scrollWidth > sh.clientWidth + 1,
          small: [...sh.querySelectorAll('button')].filter(x => { const q = x.getBoundingClientRect(); return q.width < 40 || q.height < 40; }).map(x => x.textContent) }; });
        T.ok(r.inside && !r.overflowX, `${vl}/${ll}/${name}: fits the screen, nothing overflows`);
        const reach = await p.evaluate(() => { const b = document.querySelector('#kySheet .ky-pop-acts .btn.primary'); if (!b) return null; const q = b.getBoundingClientRect(); return q.top >= 0 && q.bottom <= innerHeight + 1; });
        T.ok(reach === true, `${vl}/${ll}/${name}: the main button is on screen without scrolling`);
        T.eq(r.small, [], `${vl}/${ll}/${name}: every control is at least 40 x 40`);
        await shot(p, `look-${vl}-${ll}-${name}`);
        await p.keyboard.press('Escape'); await sleep(300);
      }
      await c.close();
    }
  }
  // the Keys screen with a rejected, a limited and an empty block
  await setLang('ph', 'en');
  await behave('groq', 'limited'); await behave('gemini', 'invalid');
  await server('ph', '/lesson/evaluate', 'POST', { token: TOK.ph.token, lang: 'en', type: 'speak', prompt: 'p', target: 't', said: 's' });
  const c = await ctxFor(browser, 'ph', { lang: 'en', viewport: { width: 390, height: 844 }, seed: { dusu_tutorial_seen: '1' } });
  const p = await boot(c, '/'); await sleep(1200);
  await p.evaluate(() => { try { localStorage.setItem('dusu_ky_seen', JSON.stringify({ sig: 'x', at: Date.now() })); } catch (e) {} });
  await openKeys(p); await sleep(1500);
  const f = await p.$('#keysForm'); if (f) { await f.scrollIntoViewIfNeeded(); await shot(p, 'look-keys-screen-390'); }
  // the "Replace" button on a rejected key opens THAT key's box on the Keys screen
  await p.evaluate(() => KY.closeSheet());
  await p.evaluate(kp => KY.problem(kp), STATES.oneBad());
  await sleep(600);
  await p.click('#kySheet .ky-rep'); await sleep(1500);
  T.eq(await p.evaluate(() => (document.querySelector('.screen.on') || {}).id), 'keys', 'Replace goes to the Keys screen');
  T.eq(await p.evaluate(() => document.activeElement && document.activeElement.id), 'kGemini', 'with the Gemini box open and focused');
  T.ok(await vis(p, '#kySave_gemini'), 'and its Save button showing');
  await shot(p, 'look-replace-gemini-390');
  await c.close();
  await browser.close();
  const ok = T.done();
  process.exit(ok ? 0 : 1);
})();
