'use strict';
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('keys smoke');
const { T, ERRS, sleep, ctxFor, boot, shot, txt, screen, vis, until, server, post, setLang, reset } = L;
(async () => {
  const browser = await chromium.launch();
  await reset({ key_health: 'on', keys_ui: 'on', install_mode: 'on', notifications: 'on', home_ai: 'on', bilingual: 'on' });
  await setLang('inst1', 'en');
  const c = await ctxFor(browser, 'inst1', { lang: 'en', seed: { dusu_tutorial_seen: '1', dusu_inst_on: '1', dusu_inst_visits: '1' } });
  const p = await boot(c, '/'); await sleep(900);
  const dump = () => p.evaluate(() => ({ sheet: document.getElementById('instSheet').classList.contains('on'), card: !document.getElementById('instPrompt').hidden, cardHtml: document.getElementById('instPrompt').innerText.slice(0, 40),
    nt: !document.getElementById('ntPrompt').hidden, wa: !document.getElementById('waPrompt').hidden, ky: !document.getElementById('kyCard').hidden, arb: ARB.winner(), visits: localStorage.getItem('dusu_inst_visits'), snooze: localStorage.getItem('dusu_inst_snooze'),
    mode: INST.mode(), screen: (document.querySelector('.screen.on') || {}).id, ob: userState.onboarded, ia: userState.install_app }));
  console.log('t=0.9', JSON.stringify(await dump()));
  await sleep(2500);
  console.log('t=3.4', JSON.stringify(await dump()));
  await p.keyboard.press('Escape'); await sleep(500);
  console.log('after esc', JSON.stringify(await dump()));
  await browser.close();
})().catch(e => { console.error('CRASH', e); process.exit(2); });
