'use strict';
/*
 * Cold-open performance of the LIVE public page as a budget phone sees it: CPU slowed 4x, network throttled (CDP), a fresh browser (nothing cached, no service worker yet) and then a
 * SECOND open (service worker installed, HTTP cache warm). Read-only: it only loads https://dusu.ranabrothers.online/ like any visitor (no login, nothing written).
 *   tests/audit/live.sh
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const URL_ = process.env.LIVE_URL || 'https://dusu.ranabrothers.online/';
const OUT = process.env.OUT || '/tmp';
const UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';
const PROFILES = {
  'none': null,
  'slow4g': { latency: 150, down: 1.6 * 1024 * 1024 / 8, up: 750 * 1024 / 8, cpu: 4 },
  '3g': { latency: 400, down: 400 * 1024 / 8, up: 400 * 1024 / 8, cpu: 4 },
};
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function run(browser, name, prof) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: UA, serviceWorkers: 'allow', locale: 'en-IN' });
  await ctx.addInitScript(`(() => { window.__lcp = 0; window.__long = []; try { new PerformanceObserver(l => { for (const e of l.getEntries()) window.__lcp = Math.max(window.__lcp, e.startTime); }).observe({ type: 'largest-contentful-paint', buffered: true }); } catch (e) {}
    try { new PerformanceObserver(l => { for (const e of l.getEntries()) window.__long.push([Math.round(e.startTime), Math.round(e.duration)]); }).observe({ type: 'longtask', buffered: true }); } catch (e) {} })();`);
  const res = { name, opens: [] };
  for (const open of [1, 2]) {
    const page = await ctx.newPage();
    const cdp = await ctx.newCDPSession(page);
    await cdp.send('Network.enable');
    if (prof) {
      await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: prof.latency, downloadThroughput: prof.down, uploadThroughput: prof.up });
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: prof.cpu });
    }
    const reqs = [];
    page.on('requestfinished', async r => { try { const s = await r.sizes(); const resp = await r.response(); reqs.push({ url: r.url().replace(/^https?:\/\/[^/]+/, '').slice(0, 70) || '/', host: new URL(r.url()).host, type: r.resourceType(), status: resp ? resp.status() : 0, bytes: s.responseBodySize + s.responseHeadersSize }); } catch (e) {} });
    const t0 = Date.now();
    const shots = [];
    const snap = async (ms, label) => { const wait = ms - (Date.now() - t0); if (wait > 0) await sleep(wait); const f = `live-${name}-open${open}-${label}.png`; await page.screenshot({ path: path.join(OUT, f) }).catch(() => {}); shots.push(f); };
    const nav = page.goto(URL_, { waitUntil: 'commit', timeout: 90000 }).catch(() => {});
    await Promise.all([nav, (async () => { await snap(1000, '1s'); await snap(3000, '3s'); await snap(6000, '6s'); })()]);
    await page.waitForLoadState('load', { timeout: 90000 }).catch(() => {});
    const loadMs = Date.now() - t0;
    await sleep(2500);
    const m = await page.evaluate(() => {
      const n = performance.getEntriesByType('navigation')[0] || {};
      const paints = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, Math.round(p.startTime)]));
      const lt = window.__long || [];
      return { ttfb: Math.round(n.responseStart || 0), dcl: Math.round(n.domContentLoadedEventEnd || 0), load: Math.round(n.loadEventEnd || 0), fcp: paints['first-contentful-paint'] || null, lcp: Math.round(window.__lcp || 0),
        longTasks: lt.length, blockingMs: lt.reduce((a, x) => a + Math.max(0, x[1] - 50), 0), longest: lt.reduce((a, x) => Math.max(a, x[1]), 0),
        screen: (document.querySelector('.screen.on') || {}).id || '', hasGoogleBtn: !!document.querySelector('#gbtn iframe, #gbtn div[role=button]') };
    }).catch(() => ({}));
    const total = reqs.reduce((a, r) => a + r.bytes, 0);
    const byType = {}; for (const r of reqs) byType[r.type] = (byType[r.type] || 0) + r.bytes;
    const byHost = {}; for (const r of reqs) byHost[r.host] = (byHost[r.host] || 0) + r.bytes;
    await snap(Date.now() - t0 + 10, 'final');
    res.opens.push({ open, loadMs, ...m, requests: reqs.length, kb: Math.round(total / 1024), byTypeKB: Object.fromEntries(Object.entries(byType).map(([k, v]) => [k, Math.round(v / 1024)])), byHostKB: Object.fromEntries(Object.entries(byHost).map(([k, v]) => [k, Math.round(v / 1024)])),
      biggest: reqs.sort((a, b) => b.bytes - a.bytes).slice(0, 5).map(r => `${Math.round(r.bytes / 1024)}KB ${r.type} ${r.host}${r.url}`), shots });
    await page.close();
    await sleep(1500);                                                   // let the service worker install before the second open
  }
  await ctx.close();
  return res;
}

(async () => {
  const browser = await chromium.launch();
  const out = [];
  for (const [name, prof] of Object.entries(PROFILES)) { const r = await run(browser, name, prof); out.push(r); console.log(JSON.stringify(r, null, 1)); }
  fs.writeFileSync(path.join(OUT, 'live-perf.json'), JSON.stringify(out, null, 1));
  await browser.close();
})();
