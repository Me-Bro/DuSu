'use strict';
// Keyboard + screen-reader basics on Home, and what happens when the network goes away after the app has been opened once.
const { chromium } = require('playwright');
const A = require('./lib.cjs').create('a11y');
const { sleep } = A;
(async () => {
  const browser = await chromium.launch();
  // ---- 1. keyboard: Tab through Home, is the focus always visible, in a sensible order?
  const c = await A.ctx(browser, 'active', { viewport: { width: 1280, height: 900 } });
  const p = await A.open(c, '/', { settle: 1500 });
  const seen = [];
  for (let i = 0; i < 28; i++) {
    await p.keyboard.press('Tab'); await sleep(60);
    seen.push(await p.evaluate(() => { const e = document.activeElement; if (!e || e === document.body) return { l: 'body' }; const cs = getComputedStyle(e); const r = e.getBoundingClientRect();
      const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none');
      return { l: (e.id ? '#' + e.id : e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className ? '.' + e.className.trim().split(/\s+/)[0] : '')) + ' "' + (e.getAttribute('aria-label') || e.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 24) + '"', ring, onscreen: r.bottom > 0 && r.top < innerHeight }; }));
  }
  console.log('TAB ORDER on Home (desktop width):');
  seen.forEach((s, i) => console.log(String(i + 1).padStart(2), s.ring === false ? 'NO-FOCUS-RING' : 'ring ok     ', s.onscreen === false ? 'OFFSCREEN ' : '          ', s.l));
  const noRing = seen.filter(s => s.ring === false).length;
  console.log('focus stops without a visible ring:', noRing, 'of', seen.length);
  await c.close();
  // ---- 2. offline after first open (service worker installed)
  const c2 = await A.ctx(browser, 'active', { viewport: { width: 390, height: 844 }, sw: true });
  const p2 = await A.open(c2, '/', { settle: 2500 });
  await sleep(2500);
  const swReady = await p2.evaluate(async () => { try { const r = await navigator.serviceWorker.ready; return !!r.active; } catch (e) { return false; } });
  console.log('\nservice worker active:', swReady);
  await c2.setOffline(true);
  await p2.reload({ waitUntil: 'domcontentloaded' }).catch(e => console.log('reload offline threw:', String(e.message).split('\n')[0]));
  await sleep(3500);
  const st = await p2.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id || '(none)', body: (document.body.innerText || '').trim().slice(0, 200).replace(/\s+/g, ' '), notif: (document.getElementById('notifTxt') || {}).textContent || '' }));
  console.log('OFFLINE reload ->', JSON.stringify(st));
  await p2.screenshot({ path: A.OUT + '/a11y__offline-reload.png' });
  // tap Start Speaking offline
  await p2.click('#startSpeak', { timeout: 4000 }).catch(() => {}); await sleep(2500);
  const st2 = await p2.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id || '', notif: (document.getElementById('notifBar') && !document.getElementById('notifBar').hidden ? document.getElementById('notifTxt').textContent : ''), lastBubble: [...document.querySelectorAll('#hmFeed .msg, #feed .msg')].slice(-2).map(x => x.innerText.trim().slice(0, 80)) }));
  console.log('OFFLINE after Start Speaking ->', JSON.stringify(st2));
  await p2.screenshot({ path: A.OUT + '/a11y__offline-start.png' });
  await c2.close();
  await browser.close();
})();
