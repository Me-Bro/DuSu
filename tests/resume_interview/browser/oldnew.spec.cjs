'use strict';
/*
 * "Old = old": with the feature flag OFF the app must look and behave exactly as it did before Resume Interview existed.
 * The same scripted session is run against the ORIGINAL file (git show HEAD:backend/test_client.html) and the MODIFIED file, under the same mocked /me:
 *   1  visible text of home, practice, the More sheet, daily, journey, profile, keys, admin, leaderboard, achievements, subscribe, help          -> must be identical
 *   2  element order (every displayed element, tag#id.class) of the same screens and of the bottom nav                                       -> must be identical
 *   3  the static DOM (scripts and styles removed) diffed line by line                                                                     -> only ADDED lines, all of them ri-*
 *   4  pixels: a screenshot of each screen at 360x640, 390x844 and 1280x800 with animations off                                              -> must be identical
 * The only legal differences: the new hidden entry markup (#riHomeCard, #riEntry, #mrowRI, #ri…) and, on the owner dashboard, the "Resume Interview" select row.
 *   ORIG_HTML=/path/to/original.html  node oldnew.spec.cjs        (run.sh mounts it for you:  ORIG_HTML_HOST=/abs/path run.sh oldnew.spec.cjs)
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { PNG } = require('pngjs');

const ORIG = process.env.ORIG_HTML;
const OUT = process.env.OUT || '/out';
const VPS = [{ name: '360x640', w: 360, h: 640 }, { name: '390x844', w: 390, h: 844 }, { name: '1280x800', w: 1280, h: 800 }];
const FREEZE = '*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}';

const SCREENS = [
  { id: 'home',         go: () => { show('home'); } },
  { id: 'practice',     go: () => { show('practice'); } },
  { id: 'more-sheet',   go: () => { show('home'); openMore(); } },
  { id: 'daily',        go: () => { toggleSheet(false); show('daily'); } },
  { id: 'journey',      go: () => { toggleSheet(false); show('journey'); } },
  { id: 'profile',      go: () => { toggleSheet(false); show('profile'); } },
  { id: 'keys',         go: () => { toggleSheet(false); show('keys'); loadKeysUI(); const f = document.querySelector('#keys iframe'); if (f) f.remove(); } },
  { id: 'leaderboard',  go: () => { toggleSheet(false); show('leaderboard'); } },
  { id: 'achievements', go: () => { toggleSheet(false); show('achievements'); } },
  { id: 'subscribe',    go: () => { toggleSheet(false); show('subscribe'); } },
  { id: 'help',         go: () => { toggleSheet(false); show('help'); } },
  { id: 'admin',        go: () => { toggleSheet(false); openAdmin(); } },
];

const overview = { you: 'owner@example.com', role: 'owner', db: true, counts: { total: 2, active: 2, pending: 0, blocked: 0 }, access_phase: 'growth', level_test: true, owner_byok: false,
  practice_room: 'owner', life_context: 'owner', bilingual: 'owner', home_ai: 'owner', planner: 'owner', office_emails: [], early_access: ['tester@example.com'], feedback: [],
  users: [{ id: 'u1', name: 'Asha', email: 'asha@example.com', role: 'user', status: 'active', mode: 'personal', level: 'A2', xp: 120, streak_days: 3, total_sessions: 4, total_minutes: 21, words: 80, created_at: '2026-10-01', last_seen: '2026-10-14', daily_stats: {}, early: false }] };

const DUMP = () => {
  const on = document.querySelector('.screen.on'), nav = document.getElementById('bnav'), sheet = document.getElementById('msheet');
  const order = [];
  const walk = el => { for (const c of el.children) { const cs = getComputedStyle(c); if (cs.display === 'none' || c.hidden || cs.visibility === 'hidden') continue; order.push(c.tagName.toLowerCase() + (c.id ? '#' + c.id : '') + ((typeof c.className === 'string' && c.className.trim()) ? '.' + c.className.trim().split(/\s+/)[0] : '')); walk(c); } };
  walk(on); order.push('--nav'); walk(nav); order.push('--sheet'); if (sheet.classList.contains('on')) walk(sheet);
  return { screen: on.id, text: on.innerText.replace(/[ \t]+\n/g, '\n').trim(), nav: nav.innerText.trim(), sheet: sheet.classList.contains('on') ? sheet.innerText.trim() : '', order };
};
const STATIC = (stripRI) => {
  const c = document.body.cloneNode(true);
  if (stripRI) {
    c.querySelectorAll('#riHomeCard, #riEntry, #mrowRI, #ri').forEach(e => e.remove());
    const w = document.createTreeWalker(c, NodeFilter.SHOW_COMMENT), gone = []; while (w.nextNode()) if (/RESUME INTERVIEW/.test(w.currentNode.nodeValue)) gone.push(w.currentNode);
    gone.forEach(n => n.remove());   // the explanatory comment that sits in front of #ri
  }
  c.querySelectorAll('script, style, svg, img, canvas, iframe').forEach(e => e.remove());
  c.querySelectorAll('[style]').forEach(e => e.removeAttribute('style'));
  c.querySelectorAll('.on').forEach(e => e.classList.remove('on'));
  return c.outerHTML.replace(/\s+/g, ' ').replace(/> </g, '><').replace(/></g, '>\n<');   // whitespace-only text nodes are noise (removing a subtree leaves one behind)
};

async function capture(htmlPath, tag, T) {
  const env = await H.newEnv({ htmlSrc: htmlPath, mock: { me: { resume_interview: false, ri_server_stt: false, role: 'owner', office: true, has_keys: true } } });
  env.extra = (route, req, url) => {
    if (url.pathname === '/admin/overview') { route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overview) }); return true; }
    if (url.pathname === '/admin/applink') { route.fulfill({ status: 200, contentType: 'application/json', body: '{"hosts":[],"fingerprints":[],"package":"com.dusu.app"}' }); return true; }
    if (url.pathname === '/leaderboard') { route.fulfill({ status: 200, contentType: 'application/json', body: '{"top":[],"you":null}' }); return true; }
    return false;
  };
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const res = { dumps: {}, shots: {}, html: null };
  for (const vp of VPS) {
    const ctx = await H.newCtx(browser, env, { viewport: { width: vp.w, height: vp.h }, mobile: vp.w < 800 });
    await ctx.addInitScript(() => { let s = 12345; Math.random = () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; }; });   // deterministic "random" greetings / tips
    const page = await H.boot(ctx, env, '/');
    page.setDefaultTimeout(15000);
    await page.waitForSelector('#home.on'); await page.waitForTimeout(900);
    await page.addStyleTag({ content: FREEZE });
    if (vp.name === VPS[1].name) { res.html = await page.evaluate(STATIC, false); res.htmlStripped = await page.evaluate(STATIC, true); }
    for (const sc of SCREENS) {
      await page.evaluate(sc.go);
      await page.waitForTimeout(sc.id === 'admin' ? 900 : 350);
      if (sc.id === 'admin') await page.waitForSelector('#plSel');
      await page.evaluate(() => { const w = document.querySelector('.wrap'); w.scrollTop = 0; });
      if (vp.name === VPS[1].name) res.dumps[sc.id] = await page.evaluate(DUMP);
      res.shots[vp.name + '/' + sc.id] = await page.screenshot({ animations: 'disabled' });
    }
    T.eq(page.__consoleErrors, [], `${tag} ${vp.name}: no console errors`);
    await ctx.close();
  }
  await browser.close(); await env.server.close();
  return res;
}

(async () => {
  const T = H.makeT('old = old');
  if (!ORIG || !fs.existsSync(ORIG)) { console.error('set ORIG_HTML to the original test_client.html (git show HEAD:backend/test_client.html)'); process.exit(2); }
  const A = await capture(ORIG, 'ORIGINAL', T);
  const B = await capture(H.HTML_SRC, 'MODIFIED', T);

  T.section('1+2: visible text and element order, flag OFF');
  const allowed = new Map([['admin', /Job Interview Practice|Resume Interview|riSel|A learner uploads a resume/]]);
  let identical = 0;
  for (const id of Object.keys(A.dumps)) {
    const a = A.dumps[id], b = B.dumps[id];
    const dt = a.text === b.text, dn = a.nav === b.nav, ds = a.sheet === b.sheet, dord = JSON.stringify(a.order) === JSON.stringify(b.order);
    if (dt && dn && ds && dord) { identical++; T.ok(true, `${id}: identical (${a.order.length} elements, ${a.text.length} chars of text)`); console.log(`  = ${id}: identical`); continue; }
    const al = a.text.split('\n'), bl = b.text.split('\n');
    const added = bl.filter(l => !al.includes(l)), removed = al.filter(l => !bl.includes(l));
    const oa = a.order, ob = b.order, oadded = ob.filter(x => !oa.includes(x)), oremoved = oa.filter(x => !ob.includes(x));
    console.log(`  ~ ${id}: text +${added.length}/-${removed.length}, elements +${oadded.length}/-${oremoved.length}`);
    added.forEach(l => console.log('      + ' + JSON.stringify(l.slice(0, 140)))); removed.forEach(l => console.log('      - ' + JSON.stringify(l.slice(0, 140))));
    oadded.forEach(l => console.log('      + element ' + l)); oremoved.forEach(l => console.log('      - element ' + l));
    const legal = allowed.get(id);
    T.ok(!!legal && removed.length === 0 && added.every(l => legal.test(l)) && oremoved.length === 0 && oadded.every(x => x === 'select#riSel.pr-sel') && dn && ds,
      `${id}: the only difference is the owner dashboard's new "Resume Interview" select row (text +${added.length}, elements +${oadded.length}, nothing removed)`);
  }
  T.ok(identical >= Object.keys(A.dumps).length - 1, `${identical} of ${Object.keys(A.dumps).length} screens are identical; the only other one is the owner dashboard`);

  T.section('3: the static DOM (scripts / styles / svg removed)');
  fs.writeFileSync('/tmp/a.dom', A.html); fs.writeFileSync('/tmp/b.dom', B.html);
  let diff = '';
  try { execFileSync('diff', ['-u', '/tmp/a.dom', '/tmp/b.dom']); } catch (e) { diff = String(e.stdout || ''); }
  const added = diff.split('\n').filter(l => l.startsWith('+') && !l.startsWith('+++')), removed = diff.split('\n').filter(l => l.startsWith('-') && !l.startsWith('---'));
  fs.writeFileSync(path.join(OUT, 'oldnew-dom.diff'), diff);
  console.log(`  static DOM line diff: +${added.length} / -${removed.length} (full diff in oldnew-dom.diff)`);
  T.eq(removed, [], 'no line of the original markup was removed or changed');
  T.ok(added.length > 0, 'something was added (the new hidden markup)');
  T.ok(B.htmlStripped === A.html, 'take the MODIFIED markup, remove the four new subtrees (#riHomeCard, #riEntry, #mrowRI, #ri) and what is left is byte-identical to the ORIGINAL markup');
  const hid = await (async () => null)();
  T.ok(/id="riHomeCard"[^>]*hidden|hidden[^>]*id="riHomeCard"/.test(B.html) && /id="riEntry"[^>]*hidden|hidden[^>]*id="riEntry"/.test(B.html) && /id="mrowRI"[^>]*hidden|hidden[^>]*id="mrowRI"/.test(B.html), 'each of the three entry points ships with the hidden attribute');

  T.section('4: pixels (360x640, 390x844, 1280x800, animations off)');
  let same = 0, total = 0; const diffs = [];
  for (const k of Object.keys(A.shots)) {
    total++;
    const a = PNG.sync.read(A.shots[k]), b = PNG.sync.read(B.shots[k]);
    let n = 0;
    if (a.width !== b.width || a.height !== b.height) n = -1;
    else for (let i = 0; i < a.data.length; i += 4) if (a.data[i] !== b.data[i] || a.data[i + 1] !== b.data[i + 1] || a.data[i + 2] !== b.data[i + 2]) n++;
    if (n === 0) same++; else diffs.push({ k, n });
  }
  console.log(`  ${same} of ${total} screenshots are pixel-identical`);
  diffs.forEach(d => console.log('   differs: ' + d.k + ' (' + d.n + ' px)'));
  T.eq(diffs.filter(d => !/\/admin$/.test(d.k)).map(d => d.k), [], 'every screenshot except the owner dashboard is pixel-identical');
  T.ok(diffs.every(d => /\/admin$/.test(d.k)), 'the owner dashboard (one new select row) is the only screen that differs');
  for (const d of diffs) { const a = PNG.sync.read(A.shots[d.k]), b = PNG.sync.read(B.shots[d.k]); const o = new PNG({ width: Math.max(a.width, b.width), height: Math.max(a.height, b.height) }); for (let y = 0; y < o.height; y++) for (let x = 0; x < o.width; x++) { const i = (y * o.width + x) * 4, ia = (y * a.width + x) * 4, ib = (y * b.width + x) * 4; const pa = x < a.width && y < a.height ? [a.data[ia], a.data[ia + 1], a.data[ia + 2]] : [0, 0, 0], pb = x < b.width && y < b.height ? [b.data[ib], b.data[ib + 1], b.data[ib + 2]] : [0, 0, 0]; const dd = pa[0] !== pb[0] || pa[1] !== pb[1] || pa[2] !== pb[2]; o.data[i] = dd ? 255 : pa[0] >> 2; o.data[i + 1] = dd ? 0 : pa[1] >> 2; o.data[i + 2] = dd ? 80 : pa[2] >> 2; o.data[i + 3] = 255; } fs.writeFileSync(path.join(OUT, 'oldnew-' + d.k.replace('/', '-') + '-diff.png'), PNG.sync.write(o)); }
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
