'use strict';
/*
 * The service worker's push handling, run in a plain Node `vm` (no browser: a service worker cannot be driven reliably in headless Chromium here, and what matters is the
 * ORDER and the CONTENT of what it does):
 *   1  a Notifications nudge is shown FIRST and the "it arrived" receipt follows - never the other way round (the old worker awaited the receipt before showing)
 *   2  the receipt is sent even if showing failed (the push DID arrive), and a failing receipt never blocks or breaks showing
 *   3  while a DuSu window is visible the nudge is SILENT (iPhone insists that every push raises a notification) and the window is told, so it can draw its own notice
 *   4  a My Day reminder keeps its old behaviour: nothing shown while a window is visible, a normal notification otherwise, the window told either way
 *   5  the icon is the small real icon and the badge is the monochrome one (not the 1.7 MB colour logo)
 *   6  notification taps are unchanged: a button acts with its signed token, the body opens the right place, a nudge's id is reported
 *   7  the cache version moved, and static icons stay cache-first while per-user data is never cached
 * Run:  tests/keys/browser/run.sh sw.spec.cjs        (or:  node tests/keys/browser/sw.spec.cjs)
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { makeT } = require('../../resume_interview/browser/harness.cjs');

const SRC = fs.readFileSync(path.join(process.env.REPO || path.join(__dirname, '..', '..', '..'), 'backend', 'sw.js'), 'utf8');
const T = makeT('service worker (push)');

function load(o = {}) {
  const handlers = {}, log = [];
  const self = {
    addEventListener: (t, f) => { handlers[t] = f; },
    registration: { showNotification: async (title, opts) => { log.push(['show', title, opts]); if (o.showThrows) throw new Error('boom'); } },
    clients: { matchAll: async () => (o.wins || []).map(w => Object.assign({ postMessage: m => log.push(['post', m]), focus: async () => { log.push(['focus']); } }, w)), claim() {}, openWindow: async u => { log.push(['open', u]); } },
    skipWaiting() {},
  };
  const ctx = { self, console, URL, caches: { open: async () => ({ addAll: async () => {}, put: async () => {} }), keys: async () => [], match: async () => null, delete: async () => true },
    fetch: async (url, init) => { log.push(['fetch', String(url), init && init.body]); if (o.fetchThrows) throw new Error('offline'); return { ok: true, headers: { get: () => '' }, clone() { return this; } }; } };
  vm.runInNewContext(SRC, ctx);
  const fire = async (type, ev) => { let p = null; await handlers[type](Object.assign({ waitUntil: x => { p = x; } }, ev)); await p; };
  return { handlers, log, fire, ctx };
}
const push = d => ({ data: { json: () => d } });
const NUDGE = { title: 'DuSu', body: 'A few minutes today keeps your streak alive.', tag: 'dusu-nudge', data: { nid: 7, ack: 'TOKEN.SIG', url: '/' } };
const order = log => log.map(e => e[0]);

(async () => {
  T.section('1 - a nudge is shown first, the receipt follows');
  {
    const w = load();
    await w.fire('push', push(NUDGE));
    T.eq(order(w.log).filter(x => x === 'show' || x === 'fetch'), ['show', 'fetch'], 'showNotification runs BEFORE the receipt is sent');
    const shown = w.log.find(e => e[0] === 'show'), ack = w.log.find(e => e[0] === 'fetch');
    T.eq(ack[1], '/notify/ack', 'the receipt goes to /notify/ack');
    T.eq(JSON.parse(ack[2]), { t: 'TOKEN.SIG' }, 'and carries the signed single-purpose token (nothing else)');
    T.eq([shown[1], shown[2].body, shown[2].tag], ['DuSu', NUDGE.body, 'dusu-nudge'], 'the notification carries the server\'s title, words and tag');
    T.eq(shown[2].silent, false, 'with no window open it makes its normal sound');
    T.eq(shown[2].data.nid, 7, 'and keeps the id so a tap can be reported');
  }

  T.section('2 - the receipt and the notification do not depend on each other');
  {
    const w = load({ showThrows: true });
    await w.fire('push', push(NUDGE));
    T.ok(order(w.log).includes('fetch'), 'showing failed: the receipt is STILL sent (the push arrived)');
    const w2 = load({ fetchThrows: true });
    await w2.fire('push', push(NUDGE));
    T.ok(order(w2.log).includes('show'), 'the receipt failed (offline): the notification was shown anyway');
    const w3 = load();
    await w3.fire('push', push({ title: 'DuSu', body: 'x', data: { nid: 8 } }));
    T.eq(order(w3.log).filter(x => x === 'fetch').length, 0, 'a nudge with no receipt token sends no receipt');
    T.eq(order(w3.log).filter(x => x === 'show').length, 1, '... and is still shown');
    const w4 = load();
    await w4.fire('push', { data: { json: () => { throw new Error('not json'); } } });
    T.eq(order(w4.log), ['post'].slice(0, 0).concat(order(w4.log)), '(a payload that is not JSON does not crash the worker)');
  }

  T.section('3 - while the app is open the nudge is silent and the app is told');
  {
    const w = load({ wins: [{ visibilityState: 'visible' }, { visibilityState: 'hidden' }] });
    await w.fire('push', push(NUDGE));
    const shown = w.log.find(e => e[0] === 'show');
    T.ok(!!shown && shown[2].silent === true, 'a window is visible: the system notification is still raised (iPhone needs one per push) but SILENT');
    const posts = w.log.filter(e => e[0] === 'post').map(e => e[1]);
    T.eq(posts.length, 1, 'exactly the VISIBLE window is told');
    T.eq(posts[0], { type: 'nt-nudge', id: 7, title: 'DuSu', body: NUDGE.body, url: '/' }, 'with the words to draw as an in-app notice');
    T.eq(order(w.log).filter(x => x === 'show' || x === 'fetch'), ['show', 'fetch'], 'and the order is still: shown, then the receipt');
    const hidden = load({ wins: [{ visibilityState: 'hidden' }] });
    await hidden.fire('push', push(NUDGE));
    T.eq(hidden.log.find(e => e[0] === 'show')[2].silent, false, 'only hidden windows: a normal (audible) notification');
    T.eq(hidden.log.filter(e => e[0] === 'post').length, 0, 'and no message to a window that is not on screen');
  }

  T.section('4 - a My Day reminder behaves as before');
  {
    const REM = { title: 'Reminder', body: 'Take your tablet', tag: 'r1', data: { act: { done: 'T1', later: 'T2' }, url: '/my-day' }, actions: [{ action: 'done', title: 'Done' }, { action: 'later', title: 'Later' }] };
    const vis = load({ wins: [{ visibilityState: 'visible' }] });
    await vis.fire('push', push(REM));
    T.eq(vis.log.filter(e => e[0] === 'show').length, 0, 'a window is visible: no second alert (the in-app reminder card shows it)');
    T.eq(vis.log.filter(e => e[0] === 'post').map(e => e[1]), [{ type: 'pl-due' }], 'the window is told to refresh');
    T.eq(vis.log.filter(e => e[0] === 'fetch').length, 0, 'and no nudge receipt is involved');
    const hid = load({ wins: [{ visibilityState: 'hidden' }] });
    await hid.fire('push', push(REM));
    const shown = hid.log.find(e => e[0] === 'show');
    T.ok(!!shown && shown[2].tag === 'r1' && shown[2].actions.length === 2 && shown[2].silent === undefined, 'no visible window: a normal notification with its Done / Later buttons');
    T.eq(hid.log.filter(e => e[0] === 'post').map(e => e[1]), [{ type: 'pl-due' }], '(and the hidden window is told too)');
    const none = load();
    await none.fire('push', push(REM));
    T.eq(none.log.filter(e => e[0] === 'show').length, 1, 'no window at all: shown');
  }

  T.section('5 - the icons');
  {
    const w = load();
    await w.fire('push', push(NUDGE));
    const o = w.log.find(e => e[0] === 'show')[2];
    T.eq([o.icon, o.badge], ['/assets/icons/dusu-192-v1.png', '/assets/icons/badge-96-v1.png'], 'the small real icon and the monochrome badge');
    T.ok(!/logo\.png/.test(JSON.stringify(o)), 'the 1.7 MB colour logo is not used for either');
    const r = load();
    await r.fire('push', push({ title: 'R', body: 'b', data: { act: { done: 'T' } } }));
    const ro = r.log.find(e => e[0] === 'show')[2];
    T.eq([ro.icon, ro.badge], ['/assets/icons/dusu-192-v1.png', '/assets/icons/badge-96-v1.png'], 'a My Day reminder uses them too');
  }

  T.section('6 - taps are unchanged');
  {
    const n = { close() {}, data: { nid: 7, url: '/' } };
    const open = load();
    await open.fire('notificationclick', { notification: n, action: '' });
    T.eq(open.log.find(e => e[0] === 'open')[1], '/?n=7', 'a nudge tapped with no window open: opens the app with ?n=<id> (the tap is reported from there)');
    const focus = load({ wins: [{ visibilityState: 'hidden' }] });
    await focus.fire('notificationclick', { notification: n, action: '' });
    T.ok(focus.log.some(e => e[0] === 'focus') && focus.log.some(e => e[0] === 'post' && e[1].type === 'nt-open' && e[1].id === 7), 'with a window open: it is focused and told which nudge was tapped');
    const act = load({ wins: [{ visibilityState: 'hidden' }] });
    await act.fire('notificationclick', { notification: { close() {}, data: { act: { done: 'TOK-DONE' } } }, action: 'done' });
    const f = act.log.find(e => e[0] === 'fetch');
    T.eq([f[1], JSON.parse(f[2])], ['/planner/r/act', { t: 'TOK-DONE' }], 'a My Day button acts with its own signed token and no login');
  }

  T.section('7 - versions and caching');
  {
    const w = load();
    T.has(SRC, 'const CACHE = "dusu-v37"', 'the cache moved on (v33 = the install icons + manifest id, v34 = the locked-screen fix for Daily / Learn, v35 = the same for the other chats, v36 = the redrawn key pop-up, v37 = free-version limits in the pop-up): old shells and the old manifest are dropped on activate');
    T.has(SRC, 'CACHEABLE_PREFIXES = ["/logo.png", "/manifest.webmanifest", "/assets/"]', 'static icons stay cache-first (they have versioned names)');
    T.ok(!/\/keys|\/notify|\/planner|\/me/.test(/CACHEABLE_PREFIXES = \[[^\]]*\]/.exec(SRC)[0]), 'per-user endpoints (/keys, /notify, /planner, /me) are never cached');
    T.ok(typeof w.handlers.install === 'function' && typeof w.handlers.activate === 'function' && typeof w.handlers.fetch === 'function', 'install, activate and fetch handlers are all still registered');
  }
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED:', e); process.exit(2); });
