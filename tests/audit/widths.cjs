'use strict';
const { chromium } = require('playwright');
const A = require('./lib.cjs').create('widths');
(async () => {
  const browser = await chromium.launch();
  for (const [w, h] of [[768, 1024], [1024, 768], [1440, 900]]) {
    const c = await A.ctx(browser, 'active', { viewport: { width: w, height: h } });
    const p = await A.open(c, '/', { settle: 1500 });
    const r = await A.capture(p, 'home', { tag: `w${w}`, full: false });
    console.log(w, 'x', h, 'overflow', r.pageOverflowX || r.wrapOverflowX, 'sticksOut', r.sticksOut.length);
    await c.close();
  }
  await browser.close();
})();
