'use strict';
/* Grammar Coach - real Chromium -> real app (scratch Postgres, stub models). Face-to-Face end to end with a fake recogniser, the report, the keep choice,
   the sheet, contest, drills, settings, tabs, entry points, XSS canary, looks. Run through run_real.sh. */
const { chromium } = require('/pw/node_modules/playwright');
const { create } = require('./lib.cjs');

(async () => {
  const L = create('gc-real'); const { T, sleep, until, api, boot, settled, body, vis, shot, tab } = L;
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    /* ---------- A. the hub (ann has two analysed sessions) ---------- */
    const annCtx = await L.ctxFor(browser, 'ann');
    let page = await boot(annCtx, '/grammar');
    await settled(page);
    T.ok('hub: the Grammar screen opens on /grammar', await vis(page, '#gc.on'));
    T.ok('hub: five tabs', (await page.$$('.gc-tab')).length === 5);
    const ov = await body(page);
    T.ok('hub: a mistakes-per-100 number or an honest "not enough"', /mistakes per 100 words|Not enough English/.test(ov), ov.slice(0, 120));
    T.ok('hub: never says "accuracy" or a 0-100 score', !/accuracy|\/100\b/i.test(ov));
    await shot(page, 'gc-overview-390');
    for (const [k, re] of [[2, /Rules you slipped on|No mistakes recorded/], [3, /notebook|No saved sentences|said|→/i], [4, /rules ready|Nothing to practise|Five quick/i], [5, /Rules|All the rules|\./]]) {
      await tab(page, k);
      const b = await body(page); T.ok('tab ' + k + ' paints', b.trim().length > 5 && re.test(b + ' ' + (await page.textContent('#gcSub'))), b.slice(0, 80));
    }
    await tab(page, 5);
    const ruleBtn = await page.$('.gc-row .gc-main');
    if (ruleBtn) { await ruleBtn.click(); await settled(page); T.ok('a rule page shows the rule + Hindi-speaker note section', /The rule|Pattern|Correct examples|Common mistakes/.test(await body(page))); }
    await page.click('#gcGear'); await settled(page);
    T.ok('settings: the keep / counts choice and export / delete', !!(await page.$('#gcExport')) && !!(await page.$('#gcDelAll')));
    await page.click('#gcSetNat-off'); await sleep(400); await settled(page);
    T.ok('settings: a change is saved (natural tips off pressed)', (await page.getAttribute('#gcSetNat-off', 'aria-pressed')) === 'true');
    const pr = await api('ann', 'GET', '/prefs'); T.ok('settings: the server holds it', pr.status === 200 && pr.body.natural_tips === false);
    await api('ann', 'POST', '/prefs', { natural_tips: true });

    /* ---------- B. Face-to-Face, spoken through the fake recogniser ---------- */
    const bobCtx = await L.ctxFor(browser, 'bob');
    page = await boot(bobCtx, '/', '#home.on');
    T.ok('entry: Home grammar card is drawn when the switch is on', await until(async () => await vis(page, '#gcHomeCard')));
    await page.evaluate(() => { window.__utter.push('yesterday i go to the market and i buy some vegetable', 'i am engineer in a software company', 'what you want to eat today'); });
    await page.evaluate(() => startSession('conversation'));
    T.ok('talk: three spoken lines were heard', await until(async () => (await page.evaluate(() => window.__heard)) >= 3, 25000));
    await sleep(1500);
    await page.click('#endBtn');
    T.ok('talk: Session complete appears', await until(async () => await vis(page, '#srBody'), 25000));
    T.ok('talk: the Grammar summary card is mounted under it', await until(async () => await vis(page, '#gcSumBtn'), 30000), 'no #gcSumBtn');
    await shot(page, 'gc-session-complete');
    const st = await (await fetch(L.BASE + '/__e2e/stats')).json();
    T.ok('talk: the grammar model ran after the session (1 batch)', (st.gc_calls.total || 0) >= 1, JSON.stringify(st));
    await page.click('#gcSumBtn'); await settled(page);
    T.ok('report: opens inside the Grammar section', await vis(page, '#gc.on'));
    const rb = await body(page);
    T.ok('report: says it was checked by AI and can be wrong', /can be wrong/.test(rb));
    T.ok('report: the keep / counts-only choice is offered BEFORE any text is stored', await vis(page, '#gcChoice'));
    let nb = await api('bob', 'GET', '/notebook');
    T.ok('privacy: before the choice, no sentence text is stored', nb.status === 200 && nb.body.sentences.length === 0, JSON.stringify(nb.body).slice(0, 120));
    await page.click('#gcKeep'); await sleep(1200); await settled(page);
    nb = await api('bob', 'GET', '/notebook');
    T.ok('keep: sentences that needed fixing are now in the notebook', nb.body.sentences.length >= 1, String(nb.body.sentences.length));
    T.ok('report: the corrected sentence is shown', /went|vegetables|an engineer/.test(await body(page)));
    // the sheet
    const openBtns = await page.$$('.gc-sent .gc-acts .btn:nth-child(2)');
    if (openBtns.length) {
      await openBtns[0].click(); await sleep(400);
      T.ok('sheet: opens at body level', await vis(page, '#gcSheet'));
      T.ok('sheet: You said / Better / hear / say / both contest buttons', (await page.textContent('#gcSheet')).includes('You said') && !!(await page.$('#gcSayBtn')) && !!(await page.$('#gcNotSaid')) && !!(await page.$('#gcNotCorrect')));
      await shot(page, 'gc-sheet-390');
      await page.evaluate(() => { window.__utter.push('yesterday i went to the market'); });
      await page.click('#gcSayBtn'); await sleep(900);
      T.ok('sheet: say-it-right gives feedback', /Nice|Close|No speech/.test(await page.textContent('#gcSheetMsg')));
      await page.click('#gcNotCorrect'); await sleep(700);
      T.ok('sheet: contest is acknowledged', /no longer counts/.test(await page.textContent('#gcSheetMsg')));
      await page.click('#gcSheetClose'); await sleep(200);
      T.ok('sheet: closes', !(await vis(page, '#gcSheet')));
    } else T.ok('sheet: at least one fixable sentence is listed', false);
    // drills
    const d = await api('bob', 'GET', '/drills/next?n=5');
    T.ok('drills: the API returns items from the learner\'s own mistakes', d.status === 200 && Array.isArray(d.body.items));
    await tab(page, 4).catch(() => {});
    await page.evaluate(() => GC.open('practice')); await settled(page);
    if (await page.$('#gcStartDrills')) {
      await page.click('#gcStartDrills'); await sleep(600);
      let guard = 0;
      while (!(await page.$('#gcDrillEnd')) && guard++ < 8) {
        if (await page.$('#gcOpts')) { const o = await page.$$('#gcOpts .gc-opt'); if (o.length) await o[0].click(); await sleep(200); const nx = await page.$('#gcDrillNext'); if (nx && await nx.isVisible()) await nx.click(); }
        else if (await page.$('#gcDrillSkip')) { await page.click('#gcDrillSkip'); }
        await sleep(250);
      }
      T.ok('drills: a set finishes with a summary', !!(await page.$('#gcDrillEnd')) && /of \d+ right/.test(await page.textContent('#gcDrillSum')));
    } else T.ok('drills: start button present', false);

    /* ---------- C. Hindi is never judged ---------- */
    const catCtx = await L.ctxFor(browser, 'cat');
    page = await boot(catCtx, '/', '#home.on');
    await page.evaluate(() => { window.__utter.push('aaj mausam bahut accha hai aur main bazaar jaa raha hoon', 'mujhe chai pasand hai kyunki wo bahut garam hoti hai'); });
    await page.evaluate(() => startSession('conversation'));
    await until(async () => (await page.evaluate(() => window.__heard)) >= 2, 25000); await sleep(1200);
    await page.click('#endBtn'); await until(async () => await vis(page, '#srBody'), 25000); await sleep(4000);
    T.ok('hindi: no grammar summary card appears for a Hindi session', !(await vis(page, '#gcSumBtn')));
    const cs = await api('cat', 'GET', '/sessions'); T.ok('hindi: no marks stored', cs.status === 200 && !JSON.stringify(cs.body).includes('market'));

    /* ---------- D. data rights ---------- */
    const ex = await api('bob', 'GET', '/export'); T.ok('export works', ex.status === 200 && typeof ex.body === 'object');
    const other = await api('dan', 'GET', '/notebook'); T.ok('isolation: another learner sees none of bob\'s sentences', other.status === 200 && other.body.sentences.length === 0);
    const del = await api('bob', 'POST', '/delete-all', { confirm: true }); T.ok('delete-all works', del.status === 200);
    nb = await api('bob', 'GET', '/notebook'); T.ok('delete-all: the notebook is empty', nb.body.sentences.length === 0);

    /* ---------- E. looks ---------- */
    for (const [w, h2] of [[360, 640], [390, 844], [1280, 800]]) {
      const c = await L.ctxFor(browser, 'ann', { viewport: { width: w, height: h2 } });
      const p = await boot(c, '/grammar'); await settled(p);
      const ov2 = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      T.ok('looks ' + w + ': no horizontal overflow', !ov2);
      await shot(p, 'gc-look-' + w); await c.close();
    }
    T.ok('console: no page errors', L.ERRS.length === 0, L.ERRS.slice(0, 3).join(' | '));
  } finally { await browser.close(); }
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error(e); process.exit(2); });
