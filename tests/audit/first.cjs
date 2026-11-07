'use strict';
// First look: where does a brand-new account land, and what does a returning learner's Home look like (phone + desktop)?
const { chromium } = require('playwright');
const A = require('./lib.cjs').create('first');

(async () => {
  const browser = await chromium.launch();
  const cases = [
    ['newbie', 'new', { width: 390, height: 844 }, 'newbie-390'],
    ['keyed', 'returning', { width: 390, height: 844 }, 'keyed-390'],
    ['active', 'returning', { width: 390, height: 844 }, 'active-390'],
    ['active', 'returning', { width: 1280, height: 900 }, 'active-1280'],
  ];
  for (const [who, device, vp, tag] of cases) {
    const c = await A.ctx(browser, who, { device, viewport: vp, lang: 'en' });
    const p = await A.open(c, '/');
    await A.sleep(1200);
    const sid = await A.screenId(p);
    const r = await A.capture(p, 'landing', { tag });
    console.log(`${tag}: lands on "${sid}" | tiny text ${r.tinyText.count} | small targets ${r.smallTargets.length} | overflow ${r.pageOverflowX || r.wrapOverflowX} | console ${JSON.stringify(r.console)} | bad ${JSON.stringify(r.bad)}`);
    await c.close();
  }
  A.save('first');
  await browser.close();
})();
