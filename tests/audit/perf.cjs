'use strict';
/*
 * First-visit weight of the sign-in screen, BEFORE and AFTER the audit's performance fixes (P0-3), measured the same way for both: a fresh browser (nothing cached, no service worker), the page behind
 * the audit server's gzip (like Cloudflare), the network throttled by CDP, CPU 4x slower. "Before" is the page as it was at the git revision in BEFORE_REV (the logo, the Google Fonts and the Google
 * sign-in script are served from local copies the way the live site would deliver them: same bytes); "after" is the working tree.
 *
 *   BEFORE_HTML=/repo/tests/audit/.out/before.html tests/audit/spec.sh perf.cjs
 *   (make it first:  git show HEAD:backend/test_client.html | sed -e 's/__GOOGLE_CLIENT_ID__/audit-client/' -e 's/__AUTH_ENABLED__/true/' -e 's/__MAX_SESSIONS__/20/' > tests/audit/.out/before.html)
 *
 * Read-only against the scratch app. What it reports per profile: requests, KB transferred (by type), first contentful paint, largest contentful paint, load. The live site's tunnel latency is NOT
 * in these numbers (it can only be measured after a deploy, with live.sh) - what matters here is how much each version asks the network for.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const BASE = process.env.BASE;
const OUT = process.env.OUT || '/tmp';
const FONTS = process.env.FONTS || '';
const BEFORE = process.env.BEFORE_HTML && fs.existsSync(process.env.BEFORE_HTML) ? fs.readFileSync(process.env.BEFORE_HTML, 'utf8') : null;
const UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';
const PROFILES = { none: null, slow4g: { latency: 150, down: 1.6 * 1024 * 1024 / 8, up: 750 * 1024 / 8, cpu: 4 }, '3g': { latency: 400, down: 400 * 1024 / 8, up: 400 * 1024 / 8, cpu: 4 } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fontCss = FONTS && fs.existsSync(path.join(FONTS, 'fonts.css')) ? fs.readFileSync(path.join(FONTS, 'fonts.css'), 'utf8') : '';

async function run(browser, variant, prof) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: UA, serviceWorkers: 'block', locale: 'en-IN' });
  await ctx.addInitScript(`(() => { window.__lcp = 0; try { new PerformanceObserver(l => { for (const e of l.getEntries()) window.__lcp = Math.max(window.__lcp, e.startTime); }).observe({ type: 'largest-contentful-paint', buffered: true }); } catch (e) {} })();`);
  await ctx.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.origin === BASE) {
      if (variant === 'before' && u.pathname === '/' && BEFORE) return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: BEFORE });
      return route.continue();
    }
    if (u.hostname === 'fonts.googleapis.com' && fontCss) return route.fulfill({ status: 200, contentType: 'text/css', body: fontCss });
    if (u.hostname === 'fonts.gstatic.com' && FONTS) { const f = path.join(FONTS, path.basename(u.pathname)); if (fs.existsSync(f)) return route.fulfill({ status: 200, contentType: 'font/woff2', body: fs.readFileSync(f), headers: { 'access-control-allow-origin': '*' } }); }
    if (u.hostname === 'accounts.google.com') return route.fulfill({ status: 200, contentType: 'application/javascript', body: '/* the sign-in script, stubbed */' });
    return route.abort();
  });
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Network.enable');
  if (prof) { await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: prof.latency, downloadThroughput: prof.down, uploadThroughput: prof.up }); await cdp.send('Emulation.setCPUThrottlingRate', { rate: prof.cpu }); }
  const reqs = [];
  page.on('requestfinished', async r => { try { const s = await r.sizes(); const resp = await r.response(); reqs.push({ url: r.url().replace(/^https?:\/\/[^/]+/, '').slice(0, 60) || '/', host: new URL(r.url()).host, type: r.resourceType(), status: resp ? resp.status() : 0, bytes: s.responseBodySize + s.responseHeadersSize }); } catch (e) {} });
  const t0 = Date.now();
  await page.goto(BASE + '/', { waitUntil: 'commit', timeout: 90000 }).catch(() => {});
  await page.waitForLoadState('load', { timeout: 120000 }).catch(() => {});
  const loadMs = Date.now() - t0;
  await sleep(2500);
  const m = await page.evaluate(() => { const paints = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, Math.round(p.startTime)])); return { fcp: paints['first-contentful-paint'] || null, lcp: Math.round(window.__lcp || 0), screen: (document.querySelector('.screen.on') || {}).id || '' }; }).catch(() => ({}));
  const total = reqs.reduce((a, r) => a + r.bytes, 0), byType = {};
  for (const r of reqs) byType[r.type] = (byType[r.type] || 0) + r.bytes;
  const res = { variant, profile: Object.keys(PROFILES).find(k => PROFILES[k] === prof), requests: reqs.length, kb: Math.round(total / 1024), byTypeKB: Object.fromEntries(Object.entries(byType).map(([k, v]) => [k, Math.round(v / 1024)])), loadMs, ...m,
    biggest: reqs.sort((a, b) => b.bytes - a.bytes).slice(0, 4).map(r => `${Math.round(r.bytes / 1024)}KB ${r.type} ${r.host === new URL(BASE).host ? '' : r.host}${r.url}`) };
  await ctx.close();
  return res;
}

const RUNS = Math.max(1, Number(process.env.RUNS || 1));
const median = a => { const b = a.slice().sort((x, y) => x - y); return b[Math.floor(b.length / 2)]; };
(async () => {
  const browser = await chromium.launch();
  const out = [];
  for (const [name, prof] of Object.entries(PROFILES)) {
    for (const variant of BEFORE ? ['before', 'after'] : ['after']) {
      const runs = [];
      for (let i = 0; i < RUNS; i++) runs.push(await run(browser, variant, prof));          // a single load is noisy (LCP in particular): RUNS=5 reports the median of five fresh loads
      const r = Object.assign({}, runs[0], { runs: RUNS, fcp: median(runs.map(x => x.fcp || 0)), lcp: median(runs.map(x => x.lcp || 0)), loadMs: median(runs.map(x => x.loadMs)), lcpAll: runs.map(x => x.lcp) });
      out.push(r); console.log(JSON.stringify(r));
    }
  }
  console.log(`\nmedian of ${RUNS} fresh load(s) per row\nprofile  variant  requests     KB   FCP ms   LCP ms  load ms`);
  for (const r of out) console.log(`${String(r.profile).padEnd(8)} ${r.variant.padEnd(8)} ${String(r.requests).padStart(8)} ${String(r.kb).padStart(6)} ${String(r.fcp).padStart(8)} ${String(r.lcp).padStart(8)} ${String(r.loadMs).padStart(8)}`);
  fs.writeFileSync(path.join(OUT, 'perf-first-visit.json'), JSON.stringify(out, null, 1));
  await browser.close();
})();
