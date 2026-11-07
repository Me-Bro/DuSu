'use strict';
// Cold deep links on a device that has NO cached state (a new phone, cleared data, a notification tap): does a feature that IS available ever claim it is not?
const { chromium } = require('playwright');
const A = require('./lib.cjs').create('race');
const { sleep } = A;
(async () => {
  const browser = await chromium.launch();
  const paths = ['/my-day', '/grammar', '/resume-interview', '/practice-room', '/about', '/home-chat'];
  const out = {};
  for (const p of paths) {
    out[p] = { tries: 0, banner: 0, screens: {} };
    for (let i = 0; i < 6; i++) {
      const c = await A.ctx(browser, 'keyed', { viewport: { width: 390, height: 844 }, speech: true });
      const page = await A.open(c, p, { waitMe: false, settle: 100 });
      await sleep(1800);
      const r = await page.evaluate(() => ({ screen: (document.querySelector('.screen.on') || {}).id || '', notif: (document.getElementById('notifBar') && !document.getElementById('notifBar').hidden ? (document.getElementById('notifTxt') || {}).textContent : '') }));
      out[p].tries++; if (r.notif) { out[p].banner++; out[p].lastBanner = r.notif; }
      out[p].screens[r.screen] = (out[p].screens[r.screen] || 0) + 1;
      await c.close();
    }
    console.log(p.padEnd(20), JSON.stringify(out[p]));
  }
  await browser.close();
})();
