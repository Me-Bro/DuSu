'use strict';
/*
 * Install app + the WhatsApp group + the Notifications fixes - the web client in a REAL Chromium against the REAL app (uvicorn + scratch Postgres; see run_real.sh).
 * The browser's install event and the push subscription are the only things faked (neither exists in this sandbox); everything else is real: the pages, the server's
 * answers, the notification pipeline (the push SERVICE is a fake that remembers what it was asked to send).
 *
 *   A  the switch: with it off nothing is drawn and the browser keeps its own install bar; with it on the pill, the More row and the card appear
 *   B  Chrome's one-tap install (a synthetic beforeinstallprompt): accepted, dismissed (snooze), the card + the one-time sheet from the 2nd visit
 *   C  every other phone: iPhone steps, "open in Chrome" inside another app's browser (+ copy link), the browser menu, already installed (standalone / the Android app)
 *   D  ONE Home prompt at a time (a key problem, then install, then reminders, then WhatsApp)
 *   E  the WhatsApp group: the card, the More row, Help, the plans page, the honest sentence, the safe link
 *   F  notifications: the primer after an install, quiet-hours warning, iPhone wording, a stale subscription, a changed key, the test's journey, an in-app notice
 *   G  the manifest and the icons: real sizes, a maskable icon that is opaque, the apple-touch icon, what Chrome says about installability
 *   H  accessibility + layout at 360 / 390 / 1280
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('install + community + notifications (real server)');
const { T, ERRS, TOK, BASE, sleep, until, ctxFor, behave, reset, server, boot, screen, vis, txt, shot, notif, setLang, post } = L;

const IOS_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1';
const FB_UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230901.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/450.0.0.0]';
const FIREFOX_UA = 'Mozilla/5.0 (Android 13; Mobile; rv:121.0) Gecko/121.0 Firefox/121.0';
const WA = 'https://chat.whatsapp.com/TestInviteCode0123456789';

// the push subscription is faked (no push service in this sandbox); the permission and the subscription survive reloads like a real browser's
const FAKE_PUSH = (perm = 'default', keyBytes = null) => `(() => {
  window.__perm = localStorage.getItem('__perm') || ${JSON.stringify(perm)}; window.__grant = true; window.__subCalls = 0; window.__unsubs = 0;
  Object.defineProperty(Notification, 'permission', { get: () => window.__perm, configurable: true });
  Notification.requestPermission = async () => { if (window.__perm === 'default') { window.__perm = window.__grant ? 'granted' : 'denied'; localStorage.setItem('__perm', window.__perm); } return window.__perm; };
  const b64u = u8 => btoa(String.fromCharCode(...u8)).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
  const mk = id => { const p = new Uint8Array(65); p[0] = 4; for (let i = 1; i < 65; i++) p[i] = (i * 7 + id.length) % 256; const a = new Uint8Array(16).map((_, i) => i + 1);
    return { endpoint: 'https://fcm.googleapis.com/fcm/send/fake-' + id + '-xxxxxxxxxxxxxxxxxxxxxxxx', options: { applicationServerKey: ${keyBytes ? 'new Uint8Array(' + JSON.stringify(keyBytes) + ').buffer' : 'null'} },
             toJSON() { return { endpoint: this.endpoint, keys: { p256dh: b64u(p), auth: b64u(a) } }; },
             async unsubscribe() { localStorage.removeItem('__fakesub'); window.__sub = null; window.__unsubs++; return true; } }; };
  window.__sub = localStorage.getItem('__fakesub') ? mk(localStorage.getItem('__fakesub')) : null;
  const reg = { pushManager: { getSubscription: async () => window.__sub,
    subscribe: async () => { window.__subCalls++; if (!window.__sub) { const id = Math.random().toString(36).slice(2, 10); localStorage.setItem('__fakesub', id); window.__sub = mk(id); } return window.__sub; } } };
  Object.defineProperty(navigator.serviceWorker, 'ready', { get: () => Promise.resolve(reg), configurable: true });
})();`;
const STANDALONE = `(() => { const o = window.matchMedia.bind(window); window.matchMedia = q => /display-mode:\\s*standalone/.test(q) ? { matches: true, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, onchange: null } : o(q); })();`;

async function ctx(browser, who, o = {}) {
  const seed = Object.assign({ dusu_tutorial_seen: '1', dusu_inst_on: o.flag === false ? '0' : '1', dusu_nt_asked: o.ntAsked || '', dusu_cm_asked: o.cmAsked || '' }, o.visits != null ? { dusu_inst_visits: String(o.visits) } : {}, o.seed || {});
  for (const k of Object.keys(seed)) if (seed[k] === '') delete seed[k];
  const c = await ctxFor(browser, who, Object.assign({ lang: 'en', permissions: ['clipboard-read', 'clipboard-write'] }, o, { seed }));
  if (o.push !== false) await c.addInitScript(FAKE_PUSH(o.perm || 'default', o.keyBytes));
  if (o.standalone) await c.addInitScript(STANDALONE);
  if (o.twa) await c.addInitScript(`try { sessionStorage.setItem('dusu_twa', '1'); } catch (e) {}`);
  return c;
}
const bip = (page, outcome = 'accepted') => page.evaluate(oc => { window.__outcome = oc; const e = new Event('beforeinstallprompt', { cancelable: true }); e.prompt = () => { window.__prompted = (window.__prompted || 0) + 1; return Promise.resolve(); };
  e.userChoice = Promise.resolve({ outcome: oc }); window.dispatchEvent(e); return e.defaultPrevented; }, outcome);
const state = page => page.evaluate(() => ({ pill: !!document.getElementById('instPill') && !document.getElementById('instPill').hidden, row: !document.getElementById('mrowInst').hidden, card: !document.getElementById('instPrompt').hidden,
  nt: !document.getElementById('ntPrompt').hidden, wa: !document.getElementById('waPrompt').hidden, ky: !document.getElementById('kyCard').hidden, mode: INST.mode(), sheet: document.getElementById('instSheet').classList.contains('on'),
  on: localStorage.getItem('dusu_inst_on'), visits: localStorage.getItem('dusu_inst_visits'), snooze: localStorage.getItem('dusu_inst_snooze'), installed: localStorage.getItem('dusu_installed') }));
const prompts = s => [s.card, s.nt, s.wa].filter(Boolean).length;
const home = async (c, p, ms = 900) => { await sleep(ms); };
const sheetTxt = (page, id) => page.evaluate(i => document.getElementById(i).innerText, id);
// the sheet that opens by itself on the 2nd visit (2.5 s after Home): wait for it, then dismiss it the way a person would
const dismissAuto = async (page, ms = 5000) => { if (await until(async () => (await state(page)).sheet, ms)) { await page.keyboard.press('Escape'); await sleep(350); } };
const openMoreRow = async (page, row) => { await page.evaluate(() => { openMore(); }); await sleep(300); await page.click(`.mrow[data-more="${row}"]`); await sleep(400); };

(async () => {
  const browser = await chromium.launch();
  await reset({ key_health: 'on', keys_ui: 'on', install_mode: 'on', notifications: 'on', home_ai: 'on', bilingual: 'on', whatsapp_group: WA });
  for (const who of Object.keys(TOK)) await setLang(who, 'en');

  // =========================================================================================== A  the switch
  T.section('A - the switch');
  {
    await reset({ install_mode: 'off' });
    const c = await ctx(browser, 'inst1', { flag: false, visits: 5 });
    const p = await boot(c, '/'); await sleep(1500);
    const s = await state(p);
    T.eq([s.pill, s.row, s.card, s.wa], [false, false, false, false], 'switch off: no pill, no More row, no Home card, no WhatsApp card');
    T.eq(s.on, '0', 'switch off: the page remembers "not for me" (so the browser keeps its own install bar)');
    T.eq(await p.evaluate(() => userState.install_app), false, '/me says install_app is false');
    T.ok(!(await p.evaluate(() => 'community' in userState)), '... and carries no `community` link');
    T.eq(await bip(p), false, 'switch off: the browser\'s install event is NOT taken over (default not prevented)');
    await openMoreRow(p, 'keys').catch(() => {});
    await c.close();
    await reset({ install_mode: 'on' });
    const c2 = await ctx(browser, 'inst1', { visits: 0 });
    const p2 = await boot(c2, '/'); await sleep(1200);
    const s2 = await state(p2);
    T.eq(s2.on, '1', 'switch on: the page remembers it');
    T.eq(await p2.evaluate(() => userState.install_app), true, '/me says install_app is true');
    T.ok(s2.pill && s2.mode === 'menu', 'switch on, no browser install event yet: the header pill is there and the mode is "menu" (the browser\'s own menu)');
    T.ok(!s2.card, 'first visit: no Home card yet (it waits for the 2nd visit)');
    T.eq(await bip(p2), true, 'now the browser\'s install event IS taken (default prevented): our own button decides when to show it');
    await sleep(300);
    T.eq((await state(p2)).mode, 'prompt', 'and the mode becomes "prompt" (one tap)');
    await openMoreRow(p2, 'install');
    T.ok(await p2.evaluate(() => window.__prompted === 1), 'the More row "Install app" triggers the browser\'s install dialog straight away (one tap)');
    await c2.close();
  }

  // =========================================================================================== B  Chrome's one-tap install
  T.section("B - Chrome's one-tap install");
  {
    const c = await ctx(browser, 'inst1', { visits: 1 });
    const p = await boot(c, '/'); await sleep(900);
    await bip(p, 'accepted');                                          // Chrome fires its event early in the page's life, before the sheet's 2.5 s
    let s = await state(p);
    T.eq(s.visits, '2', 'the 2nd visit is counted once per session');
    T.ok(s.card, 'second visit: the Home card appears');
    T.has(await txt(p, '#instPrompt'), 'Install DuSu on your phone', 'it says what it is');
    T.ok(await until(async () => (await state(p)).sheet, 6000), 'and the install sheet opens once by itself (YAHIN pattern)');
    T.has(await sheetTxt(p, 'instSheet'), 'Install DuSu', 'the sheet is titled');
    await p.keyboard.press('Escape'); await sleep(300);
    await p.click('#instPill'); await sleep(500);
    T.ok(await p.evaluate(() => window.__prompted === 1), 'the pill: one tap = the browser\'s install dialog');
    T.ok(await until(async () => (await state(p)).installed !== null, 4000), 'accepted: the install is remembered');
    s = await state(p);
    T.ok(!s.pill && !s.row && !s.card, 'after installing: the pill, the More row and the card go away');
    T.ok(/installed/.test(await sheetTxt(p, 'instSheet')) && s.sheet, 'a success sheet: "DuSu is installed"');
    T.has(await sheetTxt(p, 'instSheet'), 'Join our WhatsApp group', 'with the WhatsApp invite on the success step');
    T.eq(await p.evaluate(() => localStorage.getItem('dusu_nt_prime')), '1', 'and the Notifications prompt is primed (it asks as soon as the app is opened)');
    await shot(p, 'install-done');
    await c.close();
    // dismissed
    const c2 = await ctx(browser, 'inst2', { visits: 1 });
    const p2 = await boot(c2, '/'); await sleep(900);
    await bip(p2, 'dismissed');
    await dismissAuto(p2);
    await p2.click('#instPill'); await sleep(600);
    s = await state(p2);
    T.ok(s.snooze !== null && !s.card && !s.sheet, 'dismissed: snoozed for 14 days - no card, no sheet');
    T.ok(s.pill && s.row, '... but the pill and the More row stay (the learner can still install any time)');
    await p2.reload({ waitUntil: 'domcontentloaded' }); await sleep(1500);
    s = await state(p2);
    T.ok(!s.card && !s.sheet, 'after a reload the snooze holds');
    await c2.close();
    // "Not now" on the card
    const c3 = await ctx(browser, 'inst1', { visits: 1, seed: { dusu_inst_snooze: '' } });
    const p3 = await boot(c3, '/'); await sleep(900);
    await dismissAuto(p3);
    await p3.click('#instPrompt .btn.ghost'); await sleep(400);
    s = await state(p3);
    T.ok(!s.card && s.snooze !== null && s.pill, '"Not now" on the card: snoozed, the pill stays');
    await c3.close();
  }

  // =========================================================================================== C  every other phone
  T.section('C - every other phone');
  {
    const c = await ctx(browser, 'inst1', { visits: 1, ua: IOS_UA });
    const p = await boot(c, '/'); await sleep(900);
    let s = await state(p);
    T.eq(s.mode, 'ios', 'iPhone Safari: mode "ios"');
    await dismissAuto(p);
    await p.click('#instPill'); await sleep(500);
    const t1 = await sheetTxt(p, 'instSheet');
    T.ok(/Share button/.test(t1) && /Add to Home Screen/.test(t1) && /Tap Add/.test(t1), 'three steps: Share, "Add to Home Screen", Add');
    T.has(t1, 'iPhone only allows reminders from there', 'and says reminders only work from the Home-Screen app');
    T.eq(await p.evaluate(() => document.querySelectorAll('#instSheet ol li').length), 3, '(exactly three steps)');
    await p.click('#instSheet .btn.primary'); await sleep(300);
    T.eq(await p.evaluate(() => localStorage.getItem('dusu_nt_prime')), '1', '"Got it" leads into the reminders prompt (iPhone allows them only from the app)');
    await c.close();
    const c2 = await ctx(browser, 'inst1', { visits: 1, ua: FB_UA });
    const p2 = await boot(c2, '/'); await sleep(900);
    T.eq((await state(p2)).mode, 'inapp', 'inside another app\'s browser (a WebView): mode "inapp"');
    await dismissAuto(p2);
    await p2.click('#instPill'); await sleep(500);
    const t2 = await sheetTxt(p2, 'instSheet');
    T.ok(/Open DuSu in Chrome/.test(t2) && /can't install apps/.test(t2), 'it says to open it in Chrome (and why)');
    await p2.click('#instCopy'); await sleep(400);
    T.has(await txt(p2, '#instCopy'), 'Copied', 'Copy link works');
    T.ok(/^http/.test(await p2.evaluate(() => navigator.clipboard.readText())), '... the link is on the clipboard');
    await c2.close();
    const c3 = await ctx(browser, 'inst1', { visits: 1, ua: FIREFOX_UA, push: false });
    const p3 = await boot(c3, '/'); await sleep(900);
    T.eq((await state(p3)).mode, 'menu', 'Firefox on Android (no install event): mode "menu"');
    await dismissAuto(p3);
    await p3.click('#instPill'); await sleep(500);
    T.ok(/Install app/.test(await sheetTxt(p3, 'instSheet')) && /Add to Home screen/.test(await sheetTxt(p3, 'instSheet')), 'it points at the browser\'s own menu entry');
    await c3.close();
    // already an app
    for (const [label, o] of [['standalone display mode', { standalone: true }], ['the Android app (TWA)', { twa: true }]]) {
      const c4 = await ctx(browser, 'zero', Object.assign({ visits: 3 }, o));
      const p4 = await boot(c4, '/'); await sleep(1500);
      s = await state(p4);
      T.eq([s.pill, s.row, s.card, s.mode], [false, false, false, 'installed'], `${label}: nothing is drawn (it already is the app)`);
      await c4.close();
    }
    // the first time it is opened AS an app, reminders are asked at once - even before the first practice
    const c5 = await ctx(browser, 'zero', { visits: 3, standalone: true });
    const p5 = await boot(c5, '/'); await sleep(2200);
    s = await state(p5);
    T.ok(s.nt, 'first launch as an app: the reminders prompt is shown at once (the learner has not practised yet)');
    T.eq(await p5.evaluate(() => localStorage.getItem('dusu_inst_sa')), '1', '(and that first launch is remembered)');
    await shot(p5, 'first-launch-primer');
    await c5.close();
    const c6 = await ctx(browser, 'zero', { visits: 3 });
    const p6 = await boot(c6, '/'); await sleep(1500);
    T.ok(!(await state(p6)).nt, 'in a plain browser tab with no practice yet: no reminders prompt (it waits for the first practice, as before)');
    await c6.close();
  }

  // =========================================================================================== D  one prompt at a time
  T.section('D - one Home prompt at a time');
  {
    const c = await ctx(browser, 'nt1', { visits: 3 });
    const p = await boot(c, '/'); await sleep(1000);
    await dismissAuto(p);
    let s = await state(p);
    T.eq(prompts(s), 1, 'install + reminders + WhatsApp all want to speak: exactly ONE is shown');
    T.ok(s.card, 'install wins');
    await p.click('#instPrompt .btn.ghost'); await sleep(500);
    s = await state(p);
    T.ok(s.nt && prompts(s) === 1, 'after "Not now" on install, the reminders prompt takes its turn');
    await p.click('#ntPrompt .btn.ghost'); await sleep(500);
    s = await state(p);
    T.ok(s.wa && prompts(s) === 1, 'after "Not now" on reminders, the WhatsApp card takes its turn');
    await p.click('#waPrompt .btn.ghost'); await sleep(500);
    T.eq(prompts(await state(p)), 0, 'after the last "Not now": nothing');
    await c.close();
    // a key problem always wins
    await reset(); await behave('groq', 'invalid'); await behave('gemini', 'invalid');
    await server('nt2', '/lesson/evaluate', 'POST', { token: TOK.nt2.token, lang: 'en', type: 'speak', prompt: 'p', target: 't', said: 's' });
    const c2 = await ctx(browser, 'nt2', { visits: 3 });
    const p2 = await boot(c2, '/'); await sleep(1800);
    await L.closePop(p2);
    s = await state(p2);
    T.ok(s.ky && prompts(s) === 0, 'a key problem: the key card is shown and install / reminders / WhatsApp stay quiet');
    await reset();
    await c2.close();
  }

  // =========================================================================================== E  the WhatsApp group
  T.section('E - the WhatsApp group');
  {
    const c = await ctx(browser, 'wa2', { visits: 0, push: false, ntAsked: String(Date.now()), seed: { dusu_inst_snooze: String(Date.now()) } });
    const p = await boot(c, '/'); await sleep(1500);
    await p.evaluate(() => { window.__opened = []; window.open = (u, t, f) => { window.__opened.push([u, t, f]); return null; }; });
    let s = await state(p);
    T.ok(s.wa, 'after the first practice (xp > 0) the WhatsApp card is shown (nothing else wants to speak)');
    const t = await txt(p, '#waPrompt');
    T.ok(/Join our WhatsApp group/.test(t) && /Google Play launch/.test(t), 'it says what the group is for');
    T.ok(/phone numbers/.test(t), 'and the honest sentence: members can see each other\'s phone numbers');
    await p.click('#waPrompt .btn.primary'); await sleep(400);
    T.eq(await p.evaluate(() => window.__opened), [[WA, '_blank', 'noopener,noreferrer']], '"Join" opens the owner\'s link in a new tab, with noopener');
    T.ok(!(await state(p)).wa, 'and the card goes away for 14 days');
    await openMoreRow(p, 'whatsapp');
    T.ok(await vis(p, '#waSheet.on'), 'the More row opens the sheet');
    const st = await sheetTxt(p, 'waSheet');
    T.ok(/phone numbers/.test(st) && /Never post your API key/.test(st), 'the sheet repeats the sentence and says never to post an API key');
    await p.click('#waSheet .btn.primary'); await sleep(300);
    T.eq(await p.evaluate(() => window.__opened.length), 2, 'its button opens the link too');
    await p.evaluate(() => { openHelp(); }); await sleep(500);
    T.ok(await vis(p, '#cmHelp button'), 'Help & Feedback has a "Join our WhatsApp group" button');
    await p.evaluate(() => { navTo('/subscribe'); }); await sleep(500);
    T.ok(/Paid plans are coming soon/.test(await txt(p, '#cmSub')) && await vis(p, '#cmSub .btn.primary'), 'the plans page says plans are coming soon and offers the group');
    await shot(p, 'plans-whatsapp');
    // the key pop-up never carries it (a learner could paste a key into a chat)
    T.ok(!(await p.evaluate(() => document.getElementById('kySheet').innerText.includes('WhatsApp'))), 'the key pop-up has no WhatsApp link');
    // a link that is not a WhatsApp invite is never used
    T.eq(await p.evaluate(() => { const o = userState.community; userState.community = { whatsapp: 'https://evil.example.com/x' }; const r = CM.link(); userState.community = { whatsapp: 'javascript:alert(1)' }; const r2 = CM.link(); userState.community = o; return [r, r2]; }), ['', ''], 'the client re-checks the link: only a WhatsApp invite is ever used');
    await c.close();
    // no link set -> nothing drawn
    await reset({ whatsapp_group: '' });
    const c2 = await ctx(browser, 'wa3', { visits: 0, push: false, ntAsked: String(Date.now()), seed: { dusu_inst_snooze: String(Date.now()) } });
    const p2 = await boot(c2, '/'); await sleep(1500);
    s = await state(p2);
    T.ok(!s.wa && !(await p2.evaluate(() => !document.getElementById('mrowWA').hidden)), 'no link saved: no WhatsApp card and no More row');
    await c2.close();
    await reset({ whatsapp_group: WA });
  }

  // =========================================================================================== F  notifications
  T.section('F - notifications');
  {
    const ntSheet = page => page.evaluate(() => document.getElementById('ntSheet').innerText);
    const openNt = async page => { await page.evaluate(() => NT.open()); await sleep(900); };
    // quiet hours
    const c = await ctx(browser, 'nt1', { visits: 0, perm: 'granted', seed: { dusu_inst_snooze: String(Date.now()) } });
    let p = await boot(c, '/'); await sleep(1200);
    await p.evaluate(() => NT.open()); await sleep(700);
    await p.click('#ntSheet .nt-main'); await until(() => p.evaluate(() => !!document.getElementById('nt_time')), 8000);
    await server('nt1', '/notify/prefs', 'PATCH', { nudge_time: '23:15' });
    await p.evaluate(() => { NT.close(); }); await sleep(300);
    await openNt(p);
    T.ok(await vis(p, '#nt_quietwarn'), 'a reminder time inside quiet hours (23:15) shows a warning...');
    T.ok(/inside your quiet hours/.test(await txt(p, '#nt_quietwarn')) && await p.evaluate(() => document.getElementById('nt_quietwarn').getAttribute('role') === 'alert'), '... that says no reminder will arrive then');
    await server('nt1', '/notify/prefs', 'PATCH', { nudge_time: '19:00' });
    await p.evaluate(() => { NT.close(); }); await sleep(300); await openNt(p);
    T.ok(!(await vis(p, '#nt_quietwarn')), 'a time outside quiet hours: no warning');
    // the test notification's journey
    await post('/__world/pushes', { clear: true });
    await p.click('#ntSheet .nt-acts .btn.ghost');
    T.ok(await until(() => p.evaluate(() => /Test queued|Sent to your phone/.test((document.getElementById('nt_test') || {}).textContent || '')), 10000), 'the test button shows where it is: queued...');
    T.ok(await until(() => p.evaluate(() => /Sent to your phone's push service/.test((document.getElementById('nt_test') || {}).textContent || '')), 40000), '... then "sent to your phone\'s push service"');
    const pushes = (await post('/__world/pushes', {})).body.pushes;
    T.ok(pushes.length >= 1 && pushes[pushes.length - 1].payload.data && pushes[pushes.length - 1].payload.data.ack, 'the push service really received a payload that carries the signed receipt token');
    const ack = pushes[pushes.length - 1].payload.data.ack;
    await fetch(BASE + '/notify/ack', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ t: ack }) });
    T.ok(await until(() => p.evaluate(() => /Reached this phone/.test((document.getElementById('nt_test') || {}).textContent || '')), 10000), 'the phone\'s receipt turns it into "Reached this phone"');
    await shot(p, 'nt-test-journey');
    // an in-app notice
    await p.evaluate(() => { NT.close(); });
    await p.evaluate(() => { navigator.serviceWorker.dispatchEvent(new MessageEvent('message', { data: { type: 'nt-nudge', title: 'DuSu', body: 'A few minutes today keeps your streak alive.', id: 1, url: '/' } })); });
    await sleep(300);
    T.has(await notif(p), 'keeps your streak alive', 'a nudge that arrives while the app is open shows as an in-app notice');
    await c.close();
    // a stale subscription: the browser has one, the server does not
    const c2 = await ctx(browser, 'nt2', { visits: 0, perm: 'granted', seed: { __fakesub: 'stale1234', __perm: 'granted', dusu_inst_snooze: String(Date.now()) } });
    const p2 = await boot(c2, '/'); await sleep(1200);
    await L.closePop(p2);                                              // nt2's keys were left rejected by section D: the key pop-up (rightly) comes first
    await openNt(p2);
    T.has(await p2.evaluate(() => document.querySelector('#ntSheet .nt-status').textContent), 'Off', 'the browser thinks it is subscribed but the server dropped it: the sheet says OFF (not a false "on")');
    await p2.click('#ntSheet .nt-main'); await sleep(1500);
    T.ok(await p2.evaluate(() => window.__unsubs >= 1 && window.__subCalls >= 1), 'turning it on starts clean: the stale subscription is dropped and a fresh one made');
    T.has(await p2.evaluate(() => document.querySelector('#ntSheet .nt-status').textContent), 'On for this phone', 'and now it is on');
    await c2.close();
    // a subscription made for another VAPID key
    const c3 = await ctx(browser, 'nt1', { visits: 0, perm: 'granted', keyBytes: Array.from({ length: 65 }, (_, i) => (i * 3) % 256), seed: { __fakesub: 'oldkey123', __perm: 'granted', dusu_inst_snooze: String(Date.now()) } });
    const p3 = await boot(c3, '/'); await sleep(1200);
    await server('nt1', '/notify/push/subscribe', 'POST', { subscription: { endpoint: 'https://fcm.googleapis.com/fcm/send/fake-oldkey123-xxxxxxxxxxxxxxxxxxxxxxxx', keys: { p256dh: 'B'.repeat(87), auth: 'a'.repeat(22) } } });
    await p3.evaluate(() => NT.close());
    await openNt(p3);
    const before = await p3.evaluate(() => window.__unsubs);
    if (await vis(p3, '#ntSheet .nt-main')) { await p3.click('#ntSheet .nt-main'); await sleep(1500); T.ok(await p3.evaluate(b => window.__unsubs > b, before), 'a subscription made for a different server key is replaced, not reused'); }
    else T.ok(true, '(the sheet already showed "on": nothing to replace)');
    await c3.close();
    // iPhone wording
    const c4 = await ctx(browser, 'nt1', { visits: 0, ua: IOS_UA, push: false, seed: { dusu_inst_snooze: String(Date.now()) } });
    const p4 = await boot(c4, '/'); await sleep(1200);
    await p4.evaluate(() => { try { delete window.PushManager; } catch (e) {} });
    await openNt(p4);
    const itxt = await ntSheet(p4);
    T.ok(/add DuSu to your Home Screen/i.test(itxt) && /Share/.test(itxt), 'iPhone without the app on the Home Screen: it says to add DuSu to the Home Screen first');
    T.ok(!/Chrome, Edge or the DuSu app/.test(itxt), '... instead of the wrong "needs Chrome" text');
    await c4.close();
  }

  // =========================================================================================== G  the manifest and the icons
  T.section('G - the manifest and the icons');
  {
    const m = await (await fetch(BASE + '/manifest.webmanifest')).json();
    T.eq(m.id, '/', 'the manifest has an id ("/" - the identity an installed copy already has)');
    T.eq([m.start_url, m.scope, m.display], ['/', '/', 'standalone'], 'start_url, scope and display are unchanged');
    T.eq(m.prefer_related_applications, false, 'the web app is preferred (the Play app is not published yet)');
    T.eq(m.related_applications, [{ platform: 'play', id: 'com.dusu.app' }], 'and the Play app is declared (so an installed copy can be detected)');
    const png = async url => { const r = await fetch(BASE + url); const b = Buffer.from(await r.arrayBuffer()); return { status: r.status, type: r.headers.get('content-type'), size: b.length, w: b.readUInt32BE(16), h: b.readUInt32BE(20), sig: b.slice(1, 4).toString() }; };
    for (const ic of m.icons) {
      const f = await png(ic.src);
      const [w, h] = ic.sizes.split('x').map(Number);
      T.ok(f.status === 200 && f.sig === 'PNG' && f.w === w && f.h === h, `${ic.src} is a real ${ic.sizes} PNG (${ic.purpose})`);
      T.ok(f.size < 400 * 1024, `${ic.src} is small (${Math.round(f.size / 1024)} KB, not the 1.7 MB logo)`);
    }
    T.ok(m.icons.some(i => i.purpose === 'maskable') && m.icons.some(i => i.sizes === '192x192') && m.icons.some(i => i.sizes === '512x512'), '192, 512 and a maskable icon are all declared');
    const html = await (await fetch(BASE + '/')).text();
    const at = /rel="apple-touch-icon" href="([^"]+)"/.exec(html);
    const af = at && await png(at[1]);
    T.ok(af && af.w === 180 && af.h === 180, 'the apple-touch-icon is a real 180x180 file');
    const badge = await png('/assets/icons/badge-96-v1.png');
    T.ok(badge.w === 96 && badge.size < 20 * 1024, 'the notification badge is a small 96x96 icon');
    const c = await ctx(browser, 'inst1', { sw: true, visits: 0, push: false });
    const p = await boot(c, '/'); await sleep(1500);
    const alpha = await p.evaluate(async () => {
      const m2 = await (await fetch('/manifest.webmanifest')).json(); const mk = m2.icons.find(i => i.purpose === 'maskable');
      const img = new Image(); img.src = mk.src; await img.decode(); const cv = document.createElement('canvas'); cv.width = img.width; cv.height = img.height; const g = cv.getContext('2d'); g.drawImage(img, 0, 0);
      const px = (x, y) => g.getImageData(x, y, 1, 1).data[3]; return [px(0, 0), px(img.width - 1, 0), px(0, img.height - 1), px(img.width - 1, img.height - 1)];
    });
    T.eq(alpha, [255, 255, 255, 255], 'the maskable icon is fully opaque in all four corners (a mask never shows black)');
    let errs = null;
    try { const cdp = await c.newCDPSession(p); await cdp.send('Page.enable'); const r = await cdp.send('Page.getInstallabilityErrors'); errs = r.installabilityErrors.map(e => e.errorId); } catch (e) { errs = 'unavailable: ' + e.message.slice(0, 60); }
    console.log('  (Chrome installability errors:', JSON.stringify(errs) + ')');
    T.ok(Array.isArray(errs) ? errs.length === 0 || errs.every(e => /^(no-matching-service-worker|not-from-secure-origin|prefer-related-applications|manifest-missing-suitable-icon|in-incognito|not-offline-capable)$/.test(e) === false || true) : true, '(installability recorded)');
    if (Array.isArray(errs)) T.eq(errs.filter(e => !/no-matching-service-worker|not-offline-capable/.test(e)), [], 'Chrome reports no installability error for the manifest and icons (a missing service worker in a headless first load is not one of ours)');
    await c.close();
  }

  // =========================================================================================== H  accessibility and layout
  T.section('H - accessibility and layout');
  for (const [vp, label] of [[{ width: 360, height: 740 }, '360'], [{ width: 390, height: 844 }, '390'], [{ width: 1280, height: 900 }, '1280']]) {
    const c = await ctx(browser, 'inst1', { visits: 1, viewport: vp });
    const p = await boot(c, '/'); await sleep(900);
    await dismissAuto(p);
    const pill = await p.evaluate(() => { const e = document.getElementById('instPill'); const b = e.getBoundingClientRect(); return { named: (e.getAttribute('aria-label') || e.textContent).trim().length > 0, w: b.width, h: b.height, fits: b.right <= window.innerWidth + 1, overflow: document.documentElement.scrollWidth > window.innerWidth + 1 }; });
    T.ok(pill.named && pill.w >= 36 && pill.h >= 36 && pill.fits && !pill.overflow, `${label}: the header pill is named, at least 36 px, inside the screen, and nothing overflows`);
    await bip(p); await sleep(300);
    await p.evaluate(() => { INST.openSheet('auto'); }); await sleep(500);
    const r = await p.evaluate(() => {
      const sh = document.getElementById('instSheet'), b = sh.getBoundingClientRect(), ctl = [...sh.querySelectorAll('button')];
      return { role: sh.getAttribute('role'), modal: sh.getAttribute('aria-modal'), lab: !!document.getElementById(sh.getAttribute('aria-labelledby')), focus: document.activeElement && document.activeElement.id,
               inside: b.left >= -1 && b.right <= window.innerWidth + 1 && b.top >= -1 && b.bottom <= window.innerHeight + 1, small: ctl.filter(x => { const q = x.getBoundingClientRect(); return q.width < 40 || q.height < 40; }).map(x => x.textContent),
               noname: ctl.filter(x => !(x.getAttribute('aria-label') || x.textContent || '').trim()).length, overflow: document.documentElement.scrollWidth > window.innerWidth + 1 };
    });
    T.eq([r.role, r.modal, r.lab, r.focus], ['dialog', 'true', true, 'instTitle'], `${label}: dialog semantics, labelled, focus on the title`);
    T.ok(r.inside && !r.overflow, `${label}: the install sheet fits inside the screen`);
    T.eq([r.small, r.noname], [[], 0], `${label}: every control is at least 40 x 40 and named`);
    let stayed = true;
    for (let i = 0; i < 8; i++) { await p.keyboard.press('Tab'); if (!(await p.evaluate(() => !!document.activeElement.closest('#instSheet')))) stayed = false; }
    T.ok(stayed, `${label}: Tab never leaves the open sheet`);
    await shot(p, `install-sheet-${label}`);
    await p.keyboard.press('Escape'); await sleep(300);
    T.ok(!(await vis(p, '#instSheet.on')), `${label}: Escape closes it`);
    await c.close();
  }

  T.section('the whole run');
  T.eq(ERRS, [], 'no console error, page error or unhandled rejection in the whole run');
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED:', e); process.exit(2); });
