'use strict';
/*
 * READ-ONLY: open the LIVE sign-in page like any first-time visitor (fresh browser, nothing cached, no service worker yet) and check that Google's own "Sign in with Google" button
 * really renders - the audit moved Google's script from the page head to a lazy load (loadGIS), and the offline sandbox has no route to Google, so only the live site can show that the
 * button still appears. Nothing is typed, clicked or sent. Prints one JSON line per address.
 *   LIVE_URLS="https://dusu.ranabrothers.online/ https://dusu.ruralrootcloud.com/" node live_gis.cjs
 */
const { chromium } = require('playwright');
const path = require('path');
const URLS = (process.env.LIVE_URLS || 'https://dusu.ranabrothers.online/').split(/\s+/).filter(Boolean);
const OUT = process.env.OUT || '/tmp';
const UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';
(async () => {
  const browser = await chromium.launch();
  let bad = 0;
  for (const url of URLS) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: UA, locale: 'en-IN' });
    const page = await ctx.newPage();
    const errs = [], reqs = [];
    page.on('pageerror', e => errs.push('pageerror: ' + String(e.message).slice(0, 160)));
    page.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
    page.on('request', r => { const u = r.url(); if (/accounts\.google\.com|gstatic\.com|googleapis\.com/.test(u)) reqs.push(u.replace(/\?.*/, '').slice(0, 90)); });
    const t0 = Date.now();
    await page.goto(url, { waitUntil: 'load', timeout: 60000 }).catch(e => errs.push('goto: ' + e.message.slice(0, 120)));
    const loginShown = await page.waitForSelector('#login.on', { timeout: 15000 }).then(() => true).catch(() => false);
    // Google renders the button into #gbtn as an iframe from accounts.google.com/gsi/button
    const btn = await page.waitForSelector('#gbtn iframe', { timeout: 25000 }).then(async el => ({ src: ((await el.getAttribute('src')) || '').replace(/\?.*/, '').slice(0, 80), ms: Date.now() - t0 })).catch(() => null);
    const box = btn ? await page.$eval('#gbtn iframe', el => { const r = el.getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; }).catch(() => null) : null;
    await page.screenshot({ path: path.join(OUT, 'live-gis-' + new URL(url).hostname + '.png') }).catch(() => {});
    const res = { url, loginShown, googleButton: !!btn, button: btn, size: box, googleRequests: reqs.slice(0, 6), errors: errs.slice(0, 6) };
    console.log(JSON.stringify(res));
    if (!loginShown || !btn) bad++;
    await ctx.close();
  }
  await browser.close();
  console.log(bad ? 'RESULT: ' + bad + ' address(es) without the Google button' : 'RESULT: the Google sign-in button renders on every address');
  process.exit(bad ? 1 : 0);
})();
