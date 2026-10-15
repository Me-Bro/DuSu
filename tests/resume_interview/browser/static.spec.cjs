'use strict';
/*
 * Flag gating, entry points, router, owner dashboard, hygiene of the module's source, accessibility basics, keyboard handling, account hooks.
 *   1  flag OFF / undefined: no entry point anywhere, RI.open() and every /resume-interview URL bounce home, not a single /rinterview request
 *   2  the server switches the feature off while the app is open (/state 404)
 *   3  flag ON: Home card, Practice hub button, More-sheet row, Home 2.0 tile all lead to the hub; Home card follows `onboarded`
 *   4  owner dashboard: the "Resume Interview" Off / Owner + early access / Everyone select, POSTed with the other switches
 *   5  source hygiene: no innerHTML & co. in the module, every t("key") exists, no unused strings, no unprefixed CSS
 *   6  accessibility: focus moves to the title, live regions, aria-current step, every control is named, reduced motion
 *   7  soft keyboard (a fake visualViewport) · 8 account hooks (reset, wipeLocal, logout while recording) · 9 pruning of old audio · 10 unicode titles
 */
const { chromium } = require('playwright');
const H = require('./harness.cjs');
const M = require('./mock.cjs');
const fs = require('fs');

(async () => {
  const T = H.makeT('static');
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const errors = [];
  async function world(o = {}) {
    const env = await H.newEnv({ mock: Object.assign({ limits: { min_answer_sec: 2 } }, o.mock || {}) });
    if (o.extra) env.extra = o.extra;
    const ctx = await H.newCtx(browser, env, { viewport: o.viewport || { width: 390, height: 844 }, seed: o.seed, reducedMotion: o.reducedMotion });
    const page = await H.boot(ctx, env, o.path || '/'); page.setDefaultTimeout(15000);
    return { env, mock: env.mock, ctx, page, async close() { errors.push(...page.__consoleErrors); const r = await H.collectErrors(page); errors.push(...r.errors, ...r.rejections); await ctx.close(); await env.server.close(); } };
  }
  const hiddenOrAbsent = (page, sel) => page.evaluate(s => { const e = document.querySelector(s); if (!e) return true; return e.hidden || !!e.closest('[hidden]') || getComputedStyle(e).display === 'none'; }, sel);
  const reqs = mock => mock.calls.filter(c => c.path.startsWith('/rinterview')).length;

  /* ------------------------------------------------------------------------------------ 1 flag off */
  for (const variant of [{ name: 'false', me: { resume_interview: false } }, { name: 'undefined', me: { resume_interview: undefined } }]) {
    T.section('flag ' + variant.name + ': nothing is drawn, nothing is reachable');
    const w = await world({ mock: { me: variant.me } }); const { page, mock } = w;
    await page.waitForSelector('#home.on'); await page.waitForTimeout(500);
    T.ok(await hiddenOrAbsent(page, '#riHomeCard'), 'no Home card');
    await page.evaluate(() => show('practice')); await page.waitForTimeout(200);
    T.ok(await hiddenOrAbsent(page, '#riEntry'), 'no Practice hub entry');
    await page.evaluate(() => openMore()); await page.waitForTimeout(300);
    T.ok(await hiddenOrAbsent(page, '#mrowRI'), 'no More-sheet row');
    T.eq(await page.evaluate(() => RI.enabled()), false, 'RI.enabled() is false');
    await page.evaluate(() => { toggleSheet(false); show('home'); });
    await page.evaluate(() => RI.open('hub')); await page.waitForTimeout(300);
    T.eq(await H.onScreen(page), 'home', 'RI.open() bounces home');
    T.has(await page.evaluate(() => document.getElementById('notifTxt').textContent), "isn't available yet", 'with a notice');
    for (const p of ['/resume-interview', '/resume-interview/interview', '/resume-interview/report', '/resume-interview/settings']) {
      await page.evaluate(q => navTo(q), p); await page.waitForTimeout(250);
      T.eq(await H.onScreen(page), 'home', p + ' bounces home');
    }
    T.eq(reqs(mock), 0, 'not a single /rinterview request was made');
    T.eq(await page.evaluate(() => document.getElementById('ri').classList.contains('on')), false, 'the screen never became visible');
    await w.close();
  }
  {
    T.section('flag off: a direct load of the URL');
    const w = await world({ mock: { me: { resume_interview: false } }, path: '/resume-interview/interview' }); const { page, mock } = w;
    await page.waitForFunction(() => (document.querySelector('.screen.on') || {}).id === 'home', null, { timeout: 8000 });
    T.eq(await H.onScreen(page), 'home', 'lands on Home');
    T.eq(reqs(mock), 0, 'without a request');
    await w.close();
  }

  /* ------------------------------------------------------------------------------------ 2 switched off while open */
  {
    T.section('the owner switches the feature off while the app is open');
    const w = await world(); const { page, mock } = w;
    await H.toHub(page);
    mock.flag = false;
    await page.evaluate(() => navTo('/resume-interview/settings')); await H.waitView(page, 'settings');
    await page.evaluate(() => navTo('/resume-interview')); await page.waitForTimeout(800);
    T.eq(await H.onScreen(page), 'home', '/state answers 404 -> the app goes home');
    T.eq(await page.evaluate(() => RI.enabled()), false, 'and hides the feature');
    T.ok(await hiddenOrAbsent(page, '#riEntry') && await hiddenOrAbsent(page, '#mrowRI'), 'entry points disappear');
    await w.close();
  }

  /* ------------------------------------------------------------------------------------ 3 entry points */
  {
    T.section('entry points (flag on)');
    const w = await world(); const { page } = w;
    await page.waitForSelector('#home.on');
    await page.waitForFunction(() => !document.getElementById('riHomeCard').hidden);
    T.has(await H.txt(page, '#riHomeCard'), 'Job Interview Practice', 'Home card');
    await page.click('#riHomeCard'); await H.waitView(page, 'hub'); T.ok(true, 'Home card -> hub');
    await page.evaluate(() => show('practice'));
    await page.waitForFunction(() => !document.getElementById('riEntry').hidden);
    const order = await page.evaluate(() => [...document.querySelectorAll('#practice > *')].map(e => e.id || e.className.split(' ')[0]).filter(Boolean));
    T.ok(order.indexOf('riEntry') === order.indexOf('prEntry') + 1, 'the Practice entry sits right after the Practice Room entry: ' + order.slice(0, 5).join(' > '));
    T.has(await H.txt(page, '#riEntry'), 'Upload your resume', 'its blurb mentions the upload');
    await page.click('#riEntry'); await H.waitView(page, 'hub'); T.ok(true, 'Practice entry -> hub');
    await page.evaluate(() => openMore());
    await page.waitForFunction(() => !document.getElementById('mrowRI').hidden);
    T.eq(await page.evaluate(() => document.getElementById('mrowRI').dataset.more), 'resume-interview', 'More row: data-more="resume-interview"');
    await page.click('#mrowRI'); await H.waitView(page, 'hub'); T.ok(true, 'More row -> hub');
    T.eq(await page.evaluate(() => document.getElementById('msheet').classList.contains('on')), false, 'and the sheet closes');
    await w.close();

    const w2 = await world({ mock: { me: { onboarded: false } } });
    await w2.page.waitForTimeout(800);
    T.ok(await hiddenOrAbsent(w2.page, '#riHomeCard'), 'the Home card needs onboarded (like the other Home cards)');
    await w2.page.evaluate(() => show('practice'));
    await w2.page.waitForTimeout(200);
    T.ok(!(await hiddenOrAbsent(w2.page, '#riEntry')), 'the Practice entry does not');
    await w2.close();

    // Home 2.0 tile with a line icon
    const w3 = await world({ mock: { me: { home_ai: true, home_tiles: [{ id: 'resume_interview', icon: '📄', route: '/resume-interview', t: { hi: 'Resume Interview', en: 'Resume Interview' } }, { id: 'interview', icon: '💼', route: '/interview', t: { hi: 'Interview', en: 'Interview' } }] } } });
    await w3.page.waitForSelector('#hmFeats .hm-feat', { timeout: 10000 });
    const tile = await w3.page.evaluate(() => { const b = document.querySelector('.hm-feat[data-id="resume_interview"]'); return b ? { svg: !!b.querySelector('svg path'), route: b.dataset.route, label: b.getAttribute('aria-label') } : null; });
    T.ok(tile && tile.svg, 'Home 2.0 tile has a drawn SVG icon (not the emoji fallback)');
    T.eq(tile && tile.route, '/resume-interview', 'the tile routes to /resume-interview');
    await w3.page.click('.hm-feat[data-id="resume_interview"]'); await H.waitView(w3.page, 'hub'); T.ok(true, 'tile -> hub');
    await w3.close();
  }

  /* ------------------------------------------------------------------------------------ 4 dashboard */
  {
    T.section('owner dashboard: the third-state select');
    let posted = [];
    const overview = { you: 'owner@example.com', role: 'owner', db: true, counts: { total: 1, active: 1, pending: 0, blocked: 0 }, users: [], office_emails: [], early_access: [], feedback: [], access_phase: 'growth', level_test: true, owner_byok: false,
      practice_room: 'owner', life_context: 'owner', bilingual: 'owner', home_ai: 'owner', planner: 'owner', resume_interview: 'owner',
      resume_interview_health: { documents: 7, sessions: 4, finished: 2, answers_today: 9, feedback_failed_today: 1 } };
    const w = await world({ mock: { me: { role: 'owner' } }, extra: (route, req, url) => {
      if (url.pathname === '/admin/overview') { route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overview) }); return true; }
      if (url.pathname === '/admin/settings') { posted.push(JSON.parse(req.postData() || '{}')); route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }); return true; }
      if (url.pathname === '/admin/applink') { route.fulfill({ status: 200, contentType: 'application/json', body: '{"hosts":[],"fingerprints":[],"package":"x"}' }); return true; }
      return false; } });
    const { page } = w;
    await page.evaluate(() => openAdmin()); await page.waitForSelector('#riSel');
    T.eq(await page.evaluate(() => [...document.getElementById('riSel').options].map(o => o.value + ':' + o.textContent)), ['off:Off', 'owner:Owner + early access', 'on:Everyone'], 'Off / Owner + early access / Everyone');
    T.eq(await page.evaluate(() => document.getElementById('riSel').value), 'owner', 'it shows the server value');
    T.has(await page.evaluate(() => document.getElementById('riSel').closest('label').textContent), 'Job Interview Practice', 'labelled');
    T.has(await H.txt(page, '#adminBody'), 'Job Interview Practice: 7 document(s) · 4 interview(s), 2 finished · answers today 9 · feedback failed today 1', 'the health line (counts only, never text) sits under the switches');
    await page.selectOption('#riSel', 'on'); await page.waitForTimeout(300);
    T.eq(posted.length, 1, 'one POST to /admin/settings');
    T.eq(posted[0].resume_interview, 'on', 'with resume_interview: "on"');
    T.eq(posted[0].planner, 'owner', 'and every other switch posted as before');
    T.ok('practice_room' in posted[0] && 'home_ai' in posted[0] && 'access_phase' in posted[0], 'the whole settings object is still sent');
    await page.evaluate(() => document.getElementById('riSel').remove());
    await page.selectOption('#plSel', 'on'); await page.waitForTimeout(300);
    T.ok(!('resume_interview' in posted[1]), 'when the select is absent the key is left out (undefined), never forced to a value');
    overview.resume_interview_health = {};                                       // the server answers {} when it could not count
    await page.evaluate(() => openAdmin()); await page.waitForSelector('#riSel');
    T.ok(!(await H.txt(page, '#adminBody')).includes('document(s)'), 'an empty health object draws no line and breaks nothing');
    await w.close();
  }

  /* ------------------------------------------------------------------------------------ 5 source hygiene */
  {
    T.section('the module\'s source');
    const html = fs.readFileSync(H.HTML_SRC, 'utf8');
    const a = html.indexOf('const RI = (function(){'), b = html.indexOf('window.RI = RI;');
    T.ok(a > 0 && b > a, 'found the RI module (' + (b - a) + ' chars)');
    const src = html.slice(a, b);
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
    for (const bad of ['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'srcdoc', 'eval(', 'new Function', 'setAttribute("on', "setAttribute('on", 'javascript:']) T.ok(!code.includes(bad), `no "${bad}" in the module`);
    T.ok(!/\.(href|src)\s*=\s*[^;]*(\.|\[)(title|company|text|preview|question|answer|transcript)/.test(code), 'no href / src is ever built from a data field');
    // every string in TXT is used somewhere (quoted in the code outside TXT); "a key that does not exist" is checked at RUN time (flow.spec.cjs records every missed lookup)
    const txtStart = code.indexOf('const TXT = { en: {'), txtEnd = code.indexOf('} };', txtStart);
    const rest = code.slice(0, txtStart) + code.slice(txtEnd);
    const keys = await (async () => { const w = await world(); const k = await w.page.evaluate(() => Object.keys(RI._txt.en)); await w.close(); return k; })();
    T.ok(keys.length > 150, 'RI._txt exposes the string table (' + keys.length + ' strings)');
    const quoted = new Set([...rest.matchAll(/"([A-Za-z][A-Za-z0-9_]*)"/g)].map(m => m[1]));
    const dyn = new Set(['sCat_relevance', 'sCat_specificity', 'sCat_structure', 'sCat_language', 'sCat_delivery',
      'rpProgSt_improved', 'rpProgSt_same', 'rpProgSt_worse', 'rpSev_high', 'rpSev_medium', 'rpSev_low']);   // looked up as "sCat_" + c.key, "rpProgSt_" + status, "rpSev_" + severity
    T.eq(keys.filter(k => !quoted.has(k) && !dyn.has(k)), [], 'no unused strings in TXT');
    // every t("literal") in the code is a real key
    const calls = new Set([...rest.matchAll(/\bt\(\s*"([A-Za-z][A-Za-z0-9_]*)"\s*[,)]/g)].map(m => m[1]));
    T.eq([...calls].filter(k => !keys.includes(k)), [], 'every t("literal") the code calls is defined (' + calls.size + ' literal calls checked)');
    // CSS: every rule added for RI is ri-* / #ri*
    const css = html.slice(html.indexOf('/* ===================== RESUME INTERVIEW (resume + job description'), html.indexOf('</style>', html.indexOf('RESUME INTERVIEW (resume + job description')));
    const sels = [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/(^|\})\s*([^{}@][^{}]*)\{/g)].map(m => m[2].trim()).flatMap(s => s.split(',').map(x => x.trim())).filter(Boolean);
    const stray = sels.filter(s => !/(#ri[A-Za-z]*|\.ri-[A-Za-z0-9_-]+)/.test(s) && !/^(from|to|\d+%)/.test(s) && !s.startsWith('@') && !/^\.spin\.ri-spin-s$/.test(s));
    T.eq(stray, [], 'every CSS selector added for RI is ri-prefixed (#ri…, .ri-…): ' + sels.length + ' selectors checked');
    const kf = [...css.matchAll(/@keyframes\s+([A-Za-z0-9_-]+)/g)].map(m => m[1]);
    T.ok(kf.every(k => /^ri[A-Z]/.test(k)), 'keyframes are ri-prefixed: ' + kf.join(', '));
    // the desktop block is the only place with a min-width media query
    const mqs = [...css.matchAll(/@media\s*\(([^)]*)\)/g)].map(m => m[1]);
    T.eq(mqs, ['prefers-reduced-motion: reduce', 'min-width:1200px'], 'only a reduced-motion query and the >= 1200px desktop block');
    const svh = fs.readFileSync(H.HTML_SRC.replace('test_client.html', 'sw.js'), 'utf8');
    T.has(svh, 'const CACHE = "dusu-v28"', 'sw.js: cache bumped to dusu-v28');
    T.has(svh.split('\n').find(l => l.includes('const CACHE')), 'Job Interview Practice', 'with a note in the version comment');
  }

  /* ------------------------------------------------------------------------------------ 6 accessibility */
  {
    T.section('accessibility basics');
    const w = await world({ reducedMotion: 'reduce' }); const { page, mock, env } = w;
    await H.toHub(page);
    T.eq(await page.evaluate(() => document.activeElement && document.activeElement.id), 'riTitle', 'focus moves to the screen title when a view opens');
    T.eq(await page.evaluate(() => { const l = document.getElementById('riLive'); return l.getAttribute('role') + '/' + l.getAttribute('aria-live'); }), 'status/polite', 'a polite live region');
    const unnamed = async () => page.evaluate(() => [...document.querySelectorAll('#ri button, #ri a, #ri select, #ri textarea, #ri input:not([type=hidden]), #ri summary')].filter(e => { const cs = getComputedStyle(e); if (cs.display === 'none' || e.closest('[hidden]')) return false; const name = (e.getAttribute('aria-label') || e.textContent || e.placeholder || '').trim(); const lab = e.labels && e.labels.length; const lb = e.getAttribute('aria-labelledby'); return !name && !lab && !lb; }).map(e => e.tagName + '#' + e.id + '.' + e.className));
    T.eq(await unnamed(), [], 'hub: every control has a name');
    await page.click('#riNew'); await H.waitView(page, 'resume');
    T.eq(await page.evaluate(() => document.querySelector('#riSteps .cur').getAttribute('aria-current')), 'step', 'the current step carries aria-current="step"');
    T.eq(await unnamed(), [], 'resume: every control has a name');
    await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre');
    T.eq(await page.evaluate(() => document.getElementById('riPre').getAttribute('tabindex') + '/' + !!document.getElementById('riPre').getAttribute('aria-label')), '0/true', 'the preview is keyboard-scrollable and named');
    await page.click('#riLooks'); await H.waitView(page, 'job');
    T.eq(await unnamed(), [], 'job: every control has a name');
    T.eq(await page.evaluate(() => [...document.querySelectorAll('#riType .ri-chip')].map(b => b.getAttribute('aria-pressed'))), ['true', 'false', 'false'], 'chips expose aria-pressed');
    await page.fill('#riJdText', M.JD_TEXT); await page.click('#riNext'); await page.waitForSelector('#riHero', { timeout: 15000 });
    T.eq(await unnamed(), [], 'match: every control has a name');
    T.ok(await page.evaluate(() => [...document.querySelectorAll('.ri-st')].every(e => e.textContent.trim().length > 3)), 'match: statuses are words, not colour');
    T.eq(await page.evaluate(() => document.getElementById('riHero').querySelector('.score-ring').getAttribute('role')), 'img', 'the score ring has role=img');
    T.has(await page.evaluate(() => document.querySelector('#ri .score-ring').getAttribute('aria-label')), 'out of 100', 'and a spoken value');
    await H.startInterview(page);
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    T.eq(await unnamed(), [], 'interview: every control has a name');
    await page.click('#riMic'); await page.waitForSelector('#riRec');
    T.eq(await page.evaluate(() => document.getElementById('riTimer').getAttribute('role')), 'timer', 'the recording timer has role=timer');
    T.eq(await page.evaluate(() => getComputedStyle(document.querySelector('.ri-dot')).animationName), 'none', 'prefers-reduced-motion: the pulsing dot does not animate');
    T.eq(await unnamed(), [], 'recording: every control has a name');
    await H.sleep(1300); await page.click('#riStop'); await page.waitForSelector('#riFbCard', { timeout: 20000 });
    T.eq(await unnamed(), [], 'feedback: every control has a name');
    T.ok(await page.evaluate(() => [...document.querySelectorAll('.ri-band')].every(b => /Strong|Good|Fair|Needs work/.test(b.textContent))), 'band chips carry a word as well as dots');
    T.eq(await page.evaluate(() => document.querySelectorAll('#ri [role=alert]').length <= 1), true, 'at most one alert region at a time');
    await w.close();
  }

  /* ------------------------------------------------------------------------------------ 7 keyboard */
  {
    T.section('soft keyboard (fake visualViewport)');
    const w = await world();
    const { page } = w;
    await page.addInitScript(() => {
      const vv = new EventTarget(); vv.height = innerHeight; vv.offsetTop = 0; vv.width = innerWidth; window.__vv = vv;
      Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
    });
    await page.reload(); await page.waitForSelector('#home.on');
    await page.waitForFunction(() => !document.getElementById('riHomeCard').hidden);
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub');
    await page.click('#riNew'); await H.waitView(page, 'resume');
    await page.fill('#riResText', M.RESUME_TEXT); await page.click('#riUseText'); await page.waitForSelector('#riPre'); await page.click('#riLooks'); await H.waitView(page, 'job');
    await page.fill('#riJdText', 'x'.repeat(10)); await page.click('#riNext'); await H.waitNote(page);
    T.eq(await page.evaluate(() => getComputedStyle(document.getElementById('riBar')).position), 'sticky', 'the dock is sticky with the keyboard closed');
    await page.focus('#riJdText');
    await page.evaluate(() => { __vv.height = innerHeight - 300; __vv.dispatchEvent(new Event('resize')); });
    await page.waitForTimeout(250);
    T.eq(await page.evaluate(() => document.getElementById('ri').classList.contains('ri-kbd')), true, 'a 300px keyboard marks the screen');
    T.eq(await page.evaluate(() => document.getElementById('ri').style.getPropertyValue('--ri-kb')), '300px', 'and publishes its height');
    T.eq(await page.evaluate(() => getComputedStyle(document.getElementById('riBar')).position), 'static', 'the dock steps out of the way (it would sit on the field)');
    T.eq(await page.evaluate(() => parseInt(getComputedStyle(document.getElementById('ri')).paddingBottom)), 300, 'the screen is padded by the keyboard height so the field can be scrolled above it');
    const r = await page.evaluate(() => { const e = document.getElementById('riJdText').getBoundingClientRect(); return { top: e.top, bottom: e.bottom, vh: innerHeight - 300 }; });
    T.ok(r.bottom <= r.vh + 2 || r.top < r.vh, 'the focused field was scrolled into the visible part: ' + JSON.stringify(r));
    await page.evaluate(() => { __vv.height = innerHeight; __vv.dispatchEvent(new Event('resize')); });
    await page.waitForTimeout(150);
    T.eq(await page.evaluate(() => document.getElementById('ri').classList.contains('ri-kbd')), false, 'closing the keyboard restores the layout');
    await w.close();
  }

  /* ------------------------------------------------------------------------------------ 8 account hooks */
  {
    T.section('account hooks: reset on logout, wipeLocal on account deletion, logout while recording');
    const w = await world(); const { page, mock, env } = w;
    await H.toHub(page); await H.toMatch(page, env); await H.startInterview(page);
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    await H.answerOnce(page);
    await page.click('#riNextQ'); await page.waitForFunction(() => /Question 2/.test(document.getElementById('riQ').textContent));
    await page.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    await page.click('#riMic'); await page.waitForSelector('#riRec'); await H.sleep(900);
    await page.evaluate(() => logout());
    await page.waitForTimeout(500);
    T.eq(await H.onScreen(page), 'login', 'logout shows the login screen');
    T.ok(await page.evaluate(() => !window.__streams.at(-1).getAudioTracks().some(t => t.readyState === 'live')), 'logout releases the microphone');
    T.eq(await page.evaluate(() => document.getElementById('riBody').childElementCount), 0, 'and drops the in-memory screen');
    const takes = await page.evaluate(() => new Promise(r => { const q = indexedDB.open('dusu-interview'); q.onsuccess = () => { const c = q.result.transaction('takes').objectStore('takes').getAll(); c.onsuccess = () => { const out = c.result.map(t => ({ status: t.status, owner: t.owner })); q.result.close(); r(out); }; }; }));   // (close our own connection: an open one would block the delete below)
    T.eq(takes.map(t => t.status).sort(), ['recorded', 'sent'], 'logout did NOT wipe the on-device recordings (the sent answer and the interrupted take are still there)');
    T.ok(takes.every(t => t.owner === 'u-1'), 'each take is tagged with its owner');
    await page.evaluate(async () => { await RI.wipeLocal(); });
    const dbs = await page.evaluate(async () => (await indexedDB.databases()).map(d => d.name));
    T.ok(!dbs.includes('dusu-interview'), 'RI.wipeLocal() deletes the whole database: ' + JSON.stringify(dbs));
    await w.close();

    // another account on the same browser never sees someone else's take
    const w2 = await world(); const p2 = w2.page;
    await H.toHub(p2); await H.toMatch(p2, w2.env); await H.startInterview(p2);
    await p2.waitForFunction(() => { const b = document.getElementById('riMic'); return b && !b.disabled; });
    await p2.click('#riMic'); await p2.waitForSelector('#riRec'); await H.sleep(900);
    await p2.click('.btab[data-tab="practice"]'); await p2.waitForTimeout(300);
    await p2.evaluate(() => { authUser = { sub: 'u-2', email: 'someone.else@example.com', name: 'Other' }; userState.email = 'someone.else@example.com'; });
    await p2.evaluate(() => navTo('/resume-interview/interview')); await H.waitView(p2, 'interview');
    await p2.waitForSelector('#riQText');
    T.ok(!(await H.vis(p2, '#riHeld')), 'a second account does not see the first account\'s unsent take');
    await w2.close();
  }

  /* ------------------------------------------------------------------------------------ 9 pruning */
  {
    T.section('the audio of the 10 newest finished interviews is kept; older is pruned; unsent takes never');
    const w = await world(); const { page, mock } = w;
    const now = Date.now();
    for (let i = 1; i <= 12; i++) mock.sessions.push({ id: 1000 + i, title: 'Role ' + i, status: 'finished', settings: { type: 'mixed', level: 'fresher', feedback_lang: 'en' }, resume_id: null, jd_id: null, overall: 60, created_at: new Date(now - (20 - i) * 3600e3).toISOString(),
      started_at: new Date(now - (20 - i) * 3600e3).toISOString(), finished_at: new Date(now - (20 - i) * 3600e3 + 600e3).toISOString(), analysis: null, turns: [], queue: [], rev: 1, picked: [] });
    mock.sessions.push({ id: 2000, title: 'Active one', status: 'active', settings: { type: 'mixed', level: 'fresher', feedback_lang: 'en' }, resume_id: null, jd_id: null, overall: null, created_at: new Date(now).toISOString(), started_at: new Date(now).toISOString(), finished_at: null, analysis: null, turns: [], queue: [], rev: 1, picked: [] });
    await page.evaluate(async (n) => {
      const db = await new Promise(r => { const q = indexedDB.open('dusu-interview', 1); q.onupgradeneeded = () => { q.result.createObjectStore('chunks', { keyPath: ['take', 'seq'] }); q.result.createObjectStore('takes', { keyPath: 'id' }); }; q.onsuccess = () => r(q.result); });
      const put = t => new Promise(r => { const tx = db.transaction('takes', 'readwrite'); tx.objectStore('takes').put(t); tx.oncomplete = r; });
      const blob = () => new Blob(['x'.repeat(200)], { type: 'audio/webm' });
      for (let i = 1; i <= 12; i++) await put({ id: 'k' + i, owner: 'u-1', sid: 1000 + i, tid: 5000 + i, at: n - i, status: 'sent', mime: 'audio/webm', blob: blob(), key: 'x' });
      await put({ id: 'kA', owner: 'u-1', sid: 2000, tid: 6000, at: n, status: 'sent', mime: 'audio/webm', blob: blob(), key: 'x' });
      await put({ id: 'kU', owner: 'u-1', sid: 999, tid: 7000, at: n, status: 'recorded', mime: 'audio/webm', blob: blob(), key: 'x' });
      await put({ id: 'kO', owner: 'someone-else', sid: 1001, tid: 8000, at: n, status: 'sent', mime: 'audio/webm', blob: blob(), key: 'x' });
      db.close();
    }, now);
    await page.evaluate(() => navTo('/resume-interview')); await H.waitView(page, 'hub');
    await page.waitForSelector('#riSessions .ri-row'); await page.waitForTimeout(800);
    const left = await page.evaluate(() => new Promise(r => { const q = indexedDB.open('dusu-interview'); q.onsuccess = () => { const c = q.result.transaction('takes').objectStore('takes').getAll(); c.onsuccess = () => r(c.result.map(t => t.id).sort()); }; }));
    T.eq(left, ['k10', 'k11', 'k12', 'k3', 'k4', 'k5', 'k6', 'k7', 'k8', 'k9', 'kA', 'kO', 'kU'].sort(), 'the 10 newest finished interviews (k3..k12) + the active one + the unsent take stay; the two oldest are pruned; another account\'s take is never touched');
    await w.close();
  }

  /* ------------------------------------------------------------------------------------ 10 unicode */
  {
    T.section('unicode titles survive the X-RI-Name header');
    const w = await world(); const { page, mock } = w;
    await page.click('#riHomeCard').catch(() => {}); await page.waitForTimeout(100);
    await H.toHub(page).catch(() => {});
    await page.click('#riNew'); await H.waitView(page, 'resume');
    const title = 'रिज़्यूमे CV é — Data "Analyst"';
    await page.fill('#riResName', title);
    await page.setInputFiles('#riResFile', { name: 'x.txt', mimeType: 'text/plain', buffer: Buffer.from(M.RESUME_TEXT) });
    await page.waitForSelector('#riPre');
    const up = mock.calls.find(c => c.path.includes('/documents/upload'));
    T.eq(decodeURIComponent(up.headers['x-ri-name']), title, 'the header is percent-encoded and round-trips');
    T.ok(/^[\x20-\x7e]*$/.test(up.headers['x-ri-name']), 'and is pure ASCII on the wire');
    await w.close();
  }

  await browser.close();
  T.eq(errors, [], 'no console errors / page errors / unhandled rejections');
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED', e); process.exit(2); });
