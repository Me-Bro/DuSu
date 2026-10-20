'use strict';
/*
 * Notifications - the web client in a REAL Chromium against the REAL app (uvicorn + scratch Postgres; see run_real.sh).
 *
 * The browser cannot reach Google's push service from this sandbox, so ONE thing is faked: the page's push subscription (`pushManager.subscribe`
 * returns a well-formed fake subscription, `Notification.permission` is scriptable). Everything else is real: the settings sheet, the Home prompt, every
 * request to /notify/*, the server's validation and the database it writes to - the spec reads the truth back from the server, never from the screen.
 *
 *   A  who sees what: the More row and the Home prompt only for a learner who has the feature and has practised
 *   B  the Home prompt: text, "Not now" (and it stays away), turning on from it
 *   C  the settings sheet: turn on (a real subscription reaches the server), the three reminders, the time, the lock-screen switch, the test button, turn off
 *   D  states: blocked (denied) and unsupported browsers say so and offer no dead button
 *   E  Hindi: the sheet and the prompt in Devanagari, no gendered forms toward the learner
 *   F  the tap beacon: /?n=<id> reports the tap once and cleans the address; the service worker's message does too; junk ids do nothing
 *   G  the rollout switch: off / owner stage / on hides and shows everything, and a refused call never breaks the page
 *   H  accessibility + layout at 360 / 390 / 1280: dialog semantics, focus, Escape, a Tab trap, names, tap targets, no overflow
 */
const { chromium } = require('playwright');
const L = require('../../my_day/browser/lib.cjs').create('notifications (real server)');
const { T, ERRS, BASE, TOK, sleep, until, ctxFor, setLang, shot } = L;

// ----------------------------------------------------------------------------- the fake push service (only the subscription is faked)
const FAKE_PUSH = (perm, supported = true) => `(() => {
  window.__perm = localStorage.getItem('__perm') || ${JSON.stringify(perm)}; window.__grant = true; window.__subCalls = 0;     // a real browser keeps its permission across reloads
  Object.defineProperty(Notification, 'permission', { get: () => window.__perm, configurable: true });
  Notification.requestPermission = async () => { if (window.__perm === 'default') { window.__perm = window.__grant ? 'granted' : 'denied'; localStorage.setItem('__perm', window.__perm); } return window.__perm; };
  const b64u = u8 => btoa(String.fromCharCode(...u8)).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
  const mk = id => { const p = new Uint8Array(65); p[0] = 4; for (let i = 1; i < 65; i++) p[i] = (i * 7 + id.length) % 256; const a = new Uint8Array(16).map((_, i) => i + 1);
    return { endpoint: 'https://fcm.googleapis.com/fcm/send/fake-' + id + '-xxxxxxxxxxxxxxxxxxxxxxxx',
             toJSON() { return { endpoint: this.endpoint, keys: { p256dh: b64u(p), auth: b64u(a) } }; },
             async unsubscribe() { localStorage.removeItem('__fakesub'); window.__sub = null; return true; } }; };
  window.__sub = localStorage.getItem('__fakesub') ? mk(localStorage.getItem('__fakesub')) : null;           // a real browser keeps its subscription across reloads
  const reg = { pushManager: { getSubscription: async () => window.__sub,
    subscribe: async () => { window.__subCalls++; if (!window.__sub) { const id = Math.random().toString(36).slice(2, 10); localStorage.setItem('__fakesub', id); window.__sub = mk(id); } return window.__sub; } } };
  Object.defineProperty(navigator.serviceWorker, 'ready', { get: () => Promise.resolve(reg), configurable: true });
  ${supported ? '' : 'delete window.PushManager;'}
})();`;

async function ctx(browser, who, o = {}) {
  const c = await ctxFor(browser, who, {
    lang: o.lang || 'en', viewport: o.viewport,
    seed: { dusu_state: { onboarded: true, notifications: o.notifications !== false, bilingual: true, progress: { xp: 40, streak_days: 3 } } },
  });
  await c.addInitScript(FAKE_PUSH(o.perm || 'default', o.supported !== false));
  return c;
}

async function home(c, who, path = '/') {
  const page = await c.newPage();
  page.__posts = [];
  page.on('pageerror', e => ERRS.push('pageerror: ' + String((e && e.message) || e)));
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|favicon/i.test(m.text())) ERRS.push('console.error: ' + m.text()); });
  page.on('request', r => { if (new URL(r.url()).pathname.startsWith('/notify/') && r.method() !== 'GET') page.__posts.push(r.method() + ' ' + new URL(r.url()).pathname + ' ' + (r.postData() || '')); });
  const me = page.waitForResponse(r => new URL(r.url()).pathname === '/me' && r.request().method() === 'GET', { timeout: 30000 });
  await page.goto(BASE + path, { waitUntil: 'domcontentloaded' });
  await me; await sleep(700);
  return page;
}

// ----------------------------------------------------------------------------- what the SERVER says
const nt = async (who, method, p, body) => {
  const r = await fetch(BASE + '/notify' + p, { method, headers: { Authorization: 'Bearer ' + TOK[who].token, 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  let j = null; try { j = await r.json(); } catch (e) {}
  return { status: r.status, body: j };
};
const setSwitch = async mode => {
  const r = await fetch(BASE + '/admin/settings', { method: 'POST', headers: { Authorization: 'Bearer ' + TOK.owner.token, 'Content-Type': 'application/json' }, body: JSON.stringify({ notifications: mode }) });
  return r.ok;
};

// ----------------------------------------------------------------------------- what a person does / sees
const hidden = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return !e || e.hidden || getComputedStyle(e).display === 'none'; }, sel);
const text = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); return e ? e.innerText || e.textContent : ''; }, sel);
const sheetOn = page => page.evaluate(() => { const s = document.getElementById('ntSheet'); return !!s && s.classList.contains('on') && getComputedStyle(s).visibility === 'visible'; });
async function openSheet(page) {                                                       // the way a person does: More tab -> the Notifications row
  await page.click('.btab[data-tab="more"]');
  await page.waitForSelector('#msheet.on', { timeout: 5000 });
  await page.click('.mrow[data-more="notifications"]');
  await page.waitForFunction(() => document.getElementById('ntSheet').classList.contains('on'), null, { timeout: 5000 });
  await sleep(500);                                                                    // the sheet fetches the settings and re-draws
}
const notif = page => page.evaluate(() => { const e = document.getElementById('notifTxt'); return e ? e.textContent : ''; });
const switchOn = (page, id) => page.evaluate(i => { const e = document.getElementById('nt_' + i); return e ? e.checked : null; }, id);
const clickText = (page, re) => page.evaluate(src => { const b = [...document.querySelectorAll('#ntSheet button, #ntPrompt button')].find(x => new RegExp(src, 'i').test(x.textContent)); if (!b) return false; b.click(); return true; }, re.source);
const buttons = page => page.evaluate(() => [...document.querySelectorAll('#ntSheet button')].filter(b => !b.disabled && b.offsetParent !== null).map(b => b.textContent.trim()));
const GENDERED = ['रहे हो', 'सकते हो', 'बोलोगे', 'करोगे', 'रही हो', 'सकती हो', 'बोलोगी', 'करोगी', 'तू '];

(async () => {
  const browser = await chromium.launch({});
  for (const who of ['ann', 'bob', 'cat', 'eve', 'fay', 'gus', 'hal', 'ivy']) await setLang(who, 'en');
  await setLang('dan', 'hi');

  // =========================================================================================== A  who sees what
  T.section('A - who sees what');
  {
    const c = await ctx(browser, 'bob'); const p = await home(c, 'bob');
    T.ok(!(await hidden(p, '#mrowNT')), 'a learner who has the feature gets the More row (even before their first practice)');
    T.ok(await hidden(p, '#ntPrompt'), 'bob has not practised yet: no prompt on Home (a prompt belongs after a first practice, never on first launch)');
    await c.close();
  }

  // =========================================================================================== B  the Home prompt
  T.section('B - the Home prompt');
  {
    const c = await ctx(browser, 'cat'); const p = await home(c, 'cat');
    T.ok(await until(async () => !(await hidden(p, '#ntPrompt'))), 'cat has practised: the prompt appears');
    const pt = await text(p, '#ntPrompt');
    T.has(pt, 'Want a reminder to practise?', 'the prompt asks plainly');
    T.has(pt, '7:00 pm', 'it names the time (the default 19:00)');
    T.ok(/Turn on/.test(pt) && /Not now/.test(pt), 'two clear buttons: Turn on / Not now');
    await p.locator('#ntPrompt').scrollIntoViewIfNeeded(); await sleep(300);
    await shot(p, 'nt-prompt-390');
    await clickText(p, /Not now/);
    T.ok(await until(() => hidden(p, '#ntPrompt')), '"Not now" hides it');
    T.ok(!!(await p.evaluate(() => localStorage.getItem('dusu_nt_asked'))), '...and remembers when (so it does not nag)');
    await p.close();
    const p2 = await home(c, 'cat');
    await sleep(800);
    T.ok(await hidden(p2, '#ntPrompt'), 'after a reload the prompt stays away (14 days)');
    await c.close();
  }
  {
    const c = await ctx(browser, 'ann'); const p = await home(c, 'ann');
    T.ok(await until(async () => !(await hidden(p, '#ntPrompt'))), 'ann: the prompt appears');
    await clickText(p, /^Turn on$/);                                                  // turning on from the prompt: real permission flow, real subscription
    T.ok(await until(() => sheetOn(p)), 'turning on from the prompt opens the settings so she can see what she chose');
    T.ok(await until(async () => (await nt('ann', 'GET', '/prefs')).body.devices === 1), 'the server now holds exactly one device for ann');
    T.ok(await hidden(p, '#ntPrompt'), 'the prompt is gone once notifications are on');
    T.eq(await p.evaluate(() => window.__subCalls), 1, 'one browser subscription was created');
    await c.close();
  }

  // =========================================================================================== C  the settings sheet
  T.section('C - the settings sheet (hal: from the More row)');
  {
    await nt('hal', 'DELETE', '/x').catch(() => {});
    const c = await ctx(browser, 'hal'); const p = await home(c, 'hal');
    await openSheet(p);
    T.ok(await sheetOn(p), 'the sheet opens from More -> Notifications');
    T.ok(await p.evaluate(() => document.getElementById('msheet').classList.contains('on') === false), 'the More sheet closed behind it');
    T.eq(await p.evaluate(() => { const s = document.getElementById('ntSheet'); return [s.getAttribute('role'), s.getAttribute('aria-modal'), s.getAttribute('aria-hidden')]; }), ['dialog', 'true', 'false'], 'it is a modal dialog');
    T.eq(await p.evaluate(() => document.activeElement && document.activeElement.id), 'ntTitle', 'focus moves into the dialog (to its title)');
    T.has(await text(p, '#ntSheet'), 'Off. DuSu can remind you to practise.', 'before turning on it says it is off');
    T.ok((await buttons(p)).includes('Turn on notifications'), 'one clear primary button: Turn on notifications');
    T.ok(!(await p.evaluate(() => !!document.getElementById('nt_practice'))), 'no reminder switches are shown while it is off');
    await clickText(p, /Turn on notifications/);
    T.ok(await until(async () => (await nt('hal', 'GET', '/prefs')).body.devices === 1), 'turning on: a real subscription reached the server (1 device)');
    T.ok(await until(async () => /On for this phone/.test(await text(p, '#ntSheet'))), 'the sheet says it is on for this phone');
    T.has(await notif(p), 'Notifications are on', 'a toast confirms it');
    const pr = (await nt('hal', 'GET', '/prefs')).body;
    T.ok(pr.enabled === true && pr.push_on === true && pr.nudge_time === '19:00' && pr.kinds.practice && pr.kinds.streak && pr.kinds.weekly, 'the server: on, 19:00, all three reminders');
    T.eq([await switchOn(p, 'practice'), await switchOn(p, 'streak'), await switchOn(p, 'weekly')], [true, true, true], 'the three switches show what the server holds');

    // one reminder off -> the server changes, the others stay
    await p.click('label[for="nt_streak"]');
    T.ok(await until(async () => (await nt('hal', 'GET', '/prefs')).body.kinds.streak === false), 'switching "My streak" off reaches the server');
    const k = (await nt('hal', 'GET', '/prefs')).body.kinds;
    T.eq([k.practice, k.streak, k.weekly], [true, false, true], 'and only that one changed');
    T.eq(await switchOn(p, 'streak'), false, 'the switch shows off');
    // the time
    await p.fill('#nt_time', '20:15');
    T.ok(await until(async () => (await nt('hal', 'GET', '/prefs')).body.nudge_time === '20:15'), 'changing the time to 20:15 reaches the server');
    // lock-screen privacy (My Day's own setting, one place)
    await p.click('label[for="nt_hide"]');
    T.ok(await until(async () => (await nt('hal', 'GET', '/prefs')).body.hide_details === true), 'the lock-screen switch reaches the server');
    T.has(await text(p, '#ntSheet'), 'No notifications between', 'quiet hours are stated (read-only here)');
    // the test button
    await clickText(p, /Send me a test notification/);
    T.ok(await until(async () => /Sent!/.test(await notif(p))), 'the test button says it was sent');
    await clickText(p, /Send me a test notification/);
    T.ok(await until(async () => /wait a few minutes/.test(await notif(p))), 'a second test within 3 minutes is refused with a human sentence');
    await shot(p, 'nt-sheet-on-390');

    // it is still like that after a reload (the server holds it; the browser kept its subscription)
    await p.close();
    const p2 = await home(c, 'hal'); await openSheet(p2);
    T.has(await text(p2, '#ntSheet'), 'On for this phone', 'after a reload: still on');
    T.eq([await switchOn(p2, 'practice'), await switchOn(p2, 'streak'), await switchOn(p2, 'weekly'), await switchOn(p2, 'hide')], [true, false, true, true], 'the choices survived the reload');
    T.eq(await p2.evaluate(() => document.getElementById('nt_time').value), '20:15', 'the time survived the reload');
    // Escape closes it
    await p2.keyboard.press('Escape');
    T.ok(await until(async () => !(await sheetOn(p2))), 'Escape closes the sheet');
    T.eq(await p2.evaluate(() => document.getElementById('ntSheet').getAttribute('aria-hidden')), 'true', '...and hides it from assistive technology');
    // turn off
    await openSheet(p2);
    await clickText(p2, /Turn off on this phone/);
    T.ok(await until(async () => (await nt('hal', 'GET', '/prefs')).body.devices === 0), 'turning off removes this phone from the server');
    T.ok(await until(async () => /Off\. DuSu can remind/.test(await text(p2, '#ntSheet'))), 'the sheet says it is off again');
    T.ok(await p2.evaluate(() => !localStorage.getItem('__fakesub')), 'and the browser subscription is gone too');
    await c.close();
  }

  // =========================================================================================== D  blocked / unsupported
  T.section('D - blocked and unsupported browsers say so and offer no dead button');
  {
    const c = await ctx(browser, 'eve', { perm: 'denied' }); const p = await home(c, 'eve'); await sleep(600);
    T.ok(await hidden(p, '#ntPrompt'), 'blocked: the Home prompt stays away (it cannot help)');
    await openSheet(p);
    const st = await text(p, '#ntSheet');
    T.has(st, 'Blocked', 'blocked: the status says so');
    T.ok(/Allow them in your browser|Allow them in your browser's site settings/.test(st) || /site settings/.test(st), 'blocked: it says where to allow them (the web wording outside the app)');
    T.ok(!(await buttons(p)).some(b => /Turn on/.test(b)), 'blocked: there is no "Turn on" button that could not work');
    await c.close();
  }
  {
    const c = await ctx(browser, 'gus', { supported: false }); const p = await home(c, 'gus'); await sleep(600);
    await openSheet(p);
    const st = await text(p, '#ntSheet');
    T.has(st, "Notifications need Chrome, Edge or the DuSu app.", 'unsupported: the status says what is needed');
    T.ok(!(await buttons(p)).some(b => /Turn on/.test(b)), 'unsupported: no dead button');
    T.ok(await hidden(p, '#ntPrompt'), 'unsupported: no Home prompt');
    await c.close();
  }

  // =========================================================================================== E  Hindi
  T.section('E - Hindi');
  {
    const c = await ctx(browser, 'dan', { lang: 'hi' }); const p = await home(c, 'dan');
    T.ok(await until(async () => !(await hidden(p, '#ntPrompt'))), 'dan (Hindi): the prompt appears');
    const pt = await text(p, '#ntPrompt');
    T.ok(/[ऀ-ॿ]/.test(pt) && pt.includes('Practice का reminder चाहिए?'), 'the prompt is in Hindi with everyday English words in Latin');
    T.ok(!GENDERED.some(g => pt.includes(g)), 'no gendered form toward the learner in the prompt');
    await p.locator('#ntPrompt').scrollIntoViewIfNeeded(); await sleep(300);
    await shot(p, 'nt-prompt-hi-390');
    await openSheet(p);
    const st = await text(p, '#ntSheet');
    T.ok(st.includes('बंद है') && st.includes('Notifications चालू करो'), 'the sheet is in Hindi');
    T.ok(!GENDERED.some(g => st.includes(g)), 'no gendered form toward the learner in the sheet');
    await shot(p, 'nt-sheet-hi-390');
    await c.close();
  }

  // =========================================================================================== F  the tap beacon
  T.section('F - a notification tap reports itself');
  {
    const rowId = TOK._rows.fay;
    const c = await ctx(browser, 'fay'); const p = await home(c, 'fay', '/?n=' + rowId);
    T.ok(await until(async () => { const ex = (await nt('fay', 'GET', '/export')).body; const r = ((ex && ex.nt_outbox) || []).find(x => x.id === rowId); return !!(r && r.opened_at); }), 'opening the app with ?n=<id> marks that notification opened, on the server');
    T.eq(await p.evaluate(() => new URL(location.href).search), '', 'the address is cleaned (a reload will not report it again)');
    T.eq(p.__posts.filter(x => x.startsWith('POST /notify/open')).length, 1, 'exactly one tap report was sent');
    // the service worker's message (the app was already open when the notification was tapped)
    await p.evaluate(() => navigator.serviceWorker.dispatchEvent(new MessageEvent('message', { data: { type: 'nt-open', id: 987654 } })));
    T.ok(await until(() => p.__posts.some(x => x.startsWith('POST /notify/open') && x.includes('987654'))), 'the service worker\'s "nt-open" message reports the tap too (a stranger\'s id is a harmless no-op on the server)');
    T.eq(await p.evaluate(() => location.pathname), '/', 'and lands on Home');
    await p.close();
    for (const bad of ['abc', '0x10', '1;DROP', '99999999999999', '-3']) {
      const q = await home(c, 'fay', '/?n=' + encodeURIComponent(bad));
      await sleep(300);
      T.eq(q.__posts.filter(x => x.startsWith('POST /notify/open')).length, 0, `?n=${bad}: nothing is sent (not a notification id)`);
      T.eq(await q.evaluate(() => new URL(location.href).search), '', `?n=${bad}: the address is still cleaned`);
      await q.close();
    }
    await c.close();
  }

  // =========================================================================================== G  the rollout switch
  T.section('G - the rollout switch');
  {
    const c = await ctx(browser, 'ivy'); let p = await home(c, 'ivy');
    T.ok(!(await hidden(p, '#mrowNT')), 'switch ON: the row is there');
    T.ok(await setSwitch('owner'), 'the owner sets the switch to "owner"');
    p = await home(c, 'ivy', '/');
    await sleep(800);
    T.ok(await hidden(p, '#mrowNT'), 'owner stage: an ordinary learner no longer has the row');
    T.ok(await hidden(p, '#ntPrompt'), '...nor the Home prompt');
    T.eq((await nt('ivy', 'GET', '/prefs')).status, 404, '...and the server answers 404 to her');
    await p.evaluate(() => { try { NT.open(); } catch (e) {} });
    await sleep(300);
    T.ok(!(await sheetOn(p)), '...and the sheet cannot be opened by script either');
    T.ok(await setSwitch('off'), 'the owner switches it off');
    p = await home(c, 'ivy', '/'); await sleep(600);
    T.ok(await hidden(p, '#mrowNT'), 'switch OFF: nothing is drawn');
    T.ok(await setSwitch('on'), 'the owner switches it back on');
    p = await home(c, 'ivy', '/'); await sleep(600);
    T.ok(!(await hidden(p, '#mrowNT')), 'switch ON again: the row returns');
    await c.close();
  }

  // =========================================================================================== H  accessibility + layout
  T.section('H - accessibility and layout (360 / 390 / 1280)');
  for (const [label, vp] of [['360', { width: 360, height: 640 }], ['390', { width: 390, height: 844 }], ['1280', { width: 1280, height: 800 }]]) {
    const c = await ctx(browser, 'ann', { viewport: vp }); const p = await home(c, 'ann');
    await openSheet(p);
    await clickText(p, /Turn on notifications/);                                       // this browser is new: turn it on, so the sheet is in its fullest state
    T.ok(await until(() => p.evaluate(() => !!document.getElementById('nt_practice'))), `${label}: turning on shows the reminder switches`);
    const r = await p.evaluate(() => {
      const sh = document.getElementById('ntSheet'), box = sh.getBoundingClientRect(), vw = innerWidth, vh = innerHeight;
      const out = { overflowX: document.documentElement.scrollWidth > vw + 1, sheetInside: box.left >= -1 && box.right <= vw + 1 && box.top >= -1 && box.bottom <= vh + 1, small: [], noname: [], controls: 0 };
      for (const e of sh.querySelectorAll('button, input, select')) {
        const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const b = e.getBoundingClientRect(); if (!b.width || !b.height) continue;
        out.controls++;
        const lab = e.getAttribute('aria-label') || (e.labels && e.labels[0] && e.labels[0].textContent) || e.textContent || '';
        if (!lab.trim()) out.noname.push(e.outerHTML.slice(0, 80));
        const h = e.type === 'checkbox' ? Math.max(b.height, (e.closest('label') || e).getBoundingClientRect().height) : b.height;      // a switch's tap target is its whole row
        if (h < 39.5 || (b.width < 39.5 && e.type !== 'checkbox')) out.small.push((e.id || e.textContent || e.type).slice(0, 30) + ' ' + Math.round(b.width) + 'x' + Math.round(h));
      }
      return out;
    });
    T.ok(r.controls >= 5, `${label}: the sheet has its controls (${r.controls})`);
    T.ok(!r.overflowX, `${label}: no horizontal overflow`);
    T.ok(r.sheetInside, `${label}: the sheet fits inside the screen`);
    T.eq(r.small, [], `${label}: every control is at least 40 x 40`);
    T.eq(r.noname, [], `${label}: every control has a name`);
    // a Tab trap: twelve Tabs (and four Shift+Tabs) never leave the dialog
    let stayed = true;
    for (let i = 0; i < 12; i++) { await p.keyboard.press('Tab'); if (!(await p.evaluate(() => !!document.activeElement.closest('#ntSheet')))) stayed = false; }
    for (let i = 0; i < 4; i++) { await p.keyboard.press('Shift+Tab'); if (!(await p.evaluate(() => !!document.activeElement.closest('#ntSheet')))) stayed = false; }
    T.ok(stayed, `${label}: Tab / Shift+Tab stay inside the open dialog`);
    await shot(p, `nt-sheet-${label}`);
    await c.close();
  }

  // =========================================================================================== I  the owner's dashboard
  T.section('I - the owner\'s dashboard switch');
  {
    const ov = async () => (await (await fetch(BASE + '/admin/overview', { headers: { Authorization: 'Bearer ' + TOK.owner.token } })).json());
    const before = await ov();
    const c = await ctx(browser, 'owner'); const p = await home(c, 'owner');
    await p.click('.btab[data-tab="more"]'); await p.waitForSelector('#msheet.on', { timeout: 5000 });
    await p.click('.mrow[data-more="admin"]');
    T.ok(await until(() => p.evaluate(() => !!document.getElementById('ntSel')), 15000), 'the dashboard has a Notifications select');
    T.eq(await p.evaluate(() => document.getElementById('ntSel').value), before.notifications, 'it shows the server\'s current value');
    T.eq(await p.evaluate(() => [...document.getElementById('ntSel').options].map(o => o.value)), ['off', 'owner', 'on'], 'with the three stages');
    T.ok(/Notifications \(last 24 h\)/.test(await p.evaluate(() => document.body.innerText)), 'and a health line (sent / accepted / arrived / opened / devices)');
    await p.selectOption('#ntSel', 'owner');
    T.ok(await until(async () => (await ov()).notifications === 'owner'), 'choosing "Owner + early access" reaches the server');
    const mid = await ov();
    const others = o => JSON.stringify({ a: o.access_phase, l: o.level_test, b: o.owner_byok, pr: o.practice_room, lc: o.life_context, bi: o.bilingual, h: o.home_ai, p: o.planner, r: o.resume_interview, g: o.grammar_coach });
    T.eq(others(mid), others(before), 'and no OTHER switch changed (this endpoint writes whatever it receives)');
    await p.selectOption('#ntSel', 'on');
    T.ok(await until(async () => (await ov()).notifications === 'on'), 'back to "Everyone" reaches the server');
    T.eq(others(await ov()), others(before), 'still no other switch changed');
    await c.close();
  }

  T.section('the whole run');
  T.eq(ERRS, [], 'no console error, page error or unhandled rejection in the whole run');
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED:', e); process.exit(2); });
