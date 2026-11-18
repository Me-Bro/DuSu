'use strict';
/* Grammar Lab - real Chromium -> real app (scratch MongoDB, the real checker and bank, no stubs): the hub, a unit page, a full set of ten with every kind of answer, the summary and its
   buttons, the Review set, a resumed set after a reload, the Hindi / English toggle, typed and spoken answers (fake recogniser), a double tap, a network failure, deep links and the browser
   Back button, the switch OFF, layout at 360 / 390 / 1280, an XSS canary, console errors. Run through run_real.sh. */
const { chromium } = require('/pw/node_modules/playwright');
const { create } = require('./lib.cjs');

(async () => {
  const L = create('lab-real'); const { T, sleep, until, api, e2e, lookup, boot, settled, vis, txt, shot, path_ } = L;
  // The harness's T.ok is (condition, message). Most calls in this file read (message, condition[, detail]) - the order the Grammar Coach spec used, where it silently NEVER FAILS (the message
  // string is the "condition"): the planted-bug run (mutants.py) is what showed it. This wrapper takes either order, and refuses two strings (an ambiguous call).
  const _ok = T.ok.bind(T);
  T.ok = (a, b, c) => {
    if (typeof a === 'string' && typeof b === 'string') throw new Error('T.ok called with two strings: ' + a.slice(0, 60));
    return typeof a === 'string' ? _ok(b, a + (c ? '  ' + String(c).slice(0, 220) : '')) : _ok(a, typeof b === 'string' ? b : String(b));
  };
  const browser = await chromium.launch({ args: ['--no-sandbox'] });

  /* ---------- helpers ---------- */
  const page_count = (page, sel) => page.$$eval(sel, e => e.length);
  const waitDrill = page => page.waitForSelector('#glHindi', { timeout: 15000 });
  const itemOf = async page => lookup((await page.textContent('#glHindi')).trim());
  const outcome = page => page.waitForSelector('#glResult, #glMsg, #glErr', { timeout: 15000 });
  async function typeCheck(page, text) { await page.fill('#glIn', text); await page.click('#glCheck'); await outcome(page); }
  const verdictText = page => txt(page, '#glVerdict');
  const prog = page => txt(page, '#glProgN');
  const focused = page => page.evaluate(() => (document.activeElement && document.activeElement.id) || '');
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const hasDeva = s => /[ऀ-ॿ]/.test(s);
  async function clickNext(page, wantProg) {
    await page.click('#glNext');
    if (wantProg) await until(async () => (await prog(page)) === wantProg, 8000);
    else await sleep(300);
  }
  // answer every open item of the set on screen correctly (a wrong-result card is closed with "Show answer"); stops on the summary
  async function clearSet(page) {
    let n = 0;
    for (let guard = 0; guard < 60; guard++) {
      if (await page.$('#glHero')) return n;
      if (await page.$('#glNext')) { await page.click('#glNext'); await sleep(150); continue; }
      if (await page.$('#glTryAgain')) { await page.click('#glShow'); await outcome(page); await sleep(100); continue; }
      if (await page.$('#glIn')) { const it = await itemOf(page); await typeCheck(page, it.en[0]); n++; continue; }
      await sleep(150);
    }
    return n;
  }
  async function audit(page, label) {
    return page.evaluate(label2 => {
      const root = document.getElementById('gl'), bad = [], tiny = [];
      const vis2 = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && !e.closest('[hidden]'); };
      root.querySelectorAll('button, textarea, input, a, [role=button]').forEach(e => { if (!vis2(e)) return; const r = e.getBoundingClientRect(); if (r.width < 43.5 || r.height < 43.5) bad.push((e.id || e.className || e.tagName) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)); });
      const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      while (w.nextNode()) { const n = w.currentNode; if (!n.nodeValue.trim()) continue; const el = n.parentElement; if (!vis2(el)) continue; const fs = parseFloat(getComputedStyle(el).fontSize); if (fs < 12) tiny.push(fs + 'px ' + n.nodeValue.trim().slice(0, 30)); }
      const vw = document.documentElement.clientWidth, wide = [];
      root.querySelectorAll('*').forEach(e => { if (!vis2(e)) return; const r = e.getBoundingClientRect(); if (r.right > vw + 1 || r.left < -1) wide.push((e.id || e.className || e.tagName).toString().slice(0, 30)); });
      return { label: label2, hScroll: document.documentElement.scrollWidth > vw + 1, wide: wide.slice(0, 5), small: bad, tiny: tiny.slice(0, 5) };
    }, label);
  }
  const clean = (r, name) => T.ok(!r.hScroll && !r.wide.length && !r.small.length && !r.tiny.length, `${name}: no horizontal overflow, every control >= 44 px, text >= 12 px ${JSON.stringify(r)}`);
  let reqLog = [];
  const spy = page => page.on('request', r => { const p = new URL(r.url()).pathname; if (p.startsWith('/lab/')) reqLog.push(r.method() + ' ' + p); });
  const noXss = async (page, where) => {
    T.eq(await page.evaluate(() => window.__xss || 0), 0, `xss: nothing ran (${where})`);
    T.eq(await page.evaluate(() => document.querySelectorAll('#gl img, #gl script, #gl iframe, #gl [onerror]').length), 0, `xss: no injected element (${where})`);
  };

  try {
    /* ---------- A. the hub of a brand-new learner ---------- */
    T.section('A. the hub');
    const annCtx = await L.ctxFor(browser, 'ann');
    let page = await boot(annCtx, '/grammar-lab');
    await settled(page);
    T.ok('the page loaded with no script error (a load-time ReferenceError would show here)', L.ERRS.length === 0, L.ERRS.join(' | '));
    T.ok('hub: the Grammar Lab screen opens on /grammar-lab', (await vis(page, '#gl.on')) && (await path_(page)) === '/grammar-lab');
    T.eq(await page.$$eval('.gl-unit', e => e.length), 12, 'hub: twelve unit cards');
    T.eq(await page.$$eval('.gl-lv', e => e.length), 48, 'hub: four level chips on every card');
    T.eq(await page.$$eval('h3.gl-sh', e => e.map(x => x.textContent)), ['Present (अभी का)', 'Past (बीता समय)', 'Future (आने वाला समय)'], 'hub: Present / Past / Future sections');
    T.eq(await page.evaluate(() => [...document.querySelectorAll('#glBody h3.gl-sh')].map(h => { let n = 0, e = h.nextElementSibling; while (e && e.classList.contains('gl-unit')) { n++; e = e.nextElementSibling; } return n; })), [4, 4, 4], 'hub: four unit cards under each section');
    T.eq(await page.$$eval('.gl-unit-name', e => e.map(x => x.textContent)), ['Present Simple', 'Present Continuous', 'Present Perfect', 'Present Perfect Continuous', 'Past Simple', 'Past Continuous', 'Past Perfect', 'Past Perfect Continuous', 'Future Simple', 'Future Continuous', 'Future Perfect', 'Future Perfect Continuous'], 'hub: the unit names, in order');
    T.has(await txt(page, '#glU-present_simple .gl-unit-gist'), 'रोज़ की आदत', 'hub: the Hindi gist of a unit (Hindi is the default)');
    T.eq(await txt(page, '#glStars'), '0', 'hub: the star total starts at 0');
    T.ok('hub: no Review button and no Resume card before any set', !(await vis(page, '#glReviewCard')) && !(await vis(page, '#glResume')));
    T.ok('hub: a new learner sees the three-step "how it works"', await vis(page, '#glHow'));
    T.eq(await page.getAttribute('#glLangHi', 'aria-pressed'), 'true', 'hub: the Hindi toggle is pressed by default');
    T.eq(await page.getAttribute('#glU-present_simple .gl-lv[data-level="easy"]', 'aria-label'), 'आसान: 3 में से 0 stars', 'hub: a level chip says its stars in words');
    const st = await api('ann', 'GET', '/state');
    T.eq(await page.evaluate(() => GL._units), st.body.catalog.order, 'the client\'s twelve unit ids are the server\'s catalog order (the routes need them before /lab/state answers)');
    T.ok('hub: lining numerals (the serif\'s default digits are old-style)', await page.evaluate(() => /lining-nums/.test(getComputedStyle(document.getElementById('glStars')).fontVariantNumeric)));
    await shot(page, 'hub-390-hi');

    /* ---------- B. the entry points ---------- */
    T.section('B. entry points');
    const catCtx0 = await L.ctxFor(browser, 'cat');
    const p2 = await boot(catCtx0, '/', '#home.on');
    await p2.evaluate(() => show('practice'));
    T.ok('entry: the Practice hub has the Grammar Lab entry', await until(async () => await vis(p2, '#glEntry')));
    await p2.click('#glEntry');
    await p2.waitForSelector('#gl.on'); await settled(p2);
    T.eq(await path_(p2), '/grammar-lab', 'entry: it opens /grammar-lab');
    await p2.evaluate(() => { show('home'); openMore(); });
    T.ok('entry: the More sheet has the Grammar Lab row', await vis(p2, '#mrowGL'));
    T.has(await txt(p2, '#mrowGL'), '12 tenses', 'entry: the More row says what it is');
    await p2.click('#mrowGL');
    await p2.waitForSelector('#gl.on'); await settled(p2);
    T.eq(await path_(p2), '/grammar-lab', 'entry: the More row opens /grammar-lab');
    T.eq(await p2.evaluate(() => document.querySelector('.btab.active') && document.querySelector('.btab.active').dataset.tab), 'practice', 'entry: the Practice tab is lit while in the Lab');
    await p2.close(); await catCtx0.close();

    /* ---------- B2. the Home icon tile (Home AI on) ---------- */
    T.section('B2. the Home tile');
    await e2e('/setting', 'POST', { key: 'home_ai', value: 'on' });
    {
      const c = await L.ctxFor(browser, 'gus');
      const p = await boot(c, '/', '#home.on');
      T.ok('home tile: a Grammar Lab tile is drawn in the icon grid', await until(async () => await vis(p, '#hmFeats .hm-feat[data-id="grammar_lab"]'), 15000));
      T.eq(await p.getAttribute('#hmFeats .hm-feat[data-id="grammar_lab"]', 'data-route'), '/grammar-lab', 'home tile: it goes to /grammar-lab');
      T.ok('home tile: the tile has a drawn icon (an SVG), not the fallback glyph', (await p.$$('#hmFeats .hm-feat[data-id="grammar_lab"] svg')).length === 1);
      const r = await p.evaluate(() => { const b = document.querySelector('#hmFeats .hm-feat[data-id="grammar_lab"]').getBoundingClientRect(); return [Math.round(b.width), Math.round(b.height)]; });
      T.ok('home tile: a 44 px target', r[0] >= 44 && r[1] >= 44, JSON.stringify(r));
      await p.evaluate(() => document.getElementById('hmFeats').scrollIntoView({ block: 'center' })); await sleep(300);
      await shot(p, 'home-tiles-390');
      await p.click('#hmFeats .hm-feat[data-id="grammar_lab"]'); await p.waitForSelector('#gl.on'); await settled(p);
      T.eq(await path_(p), '/grammar-lab', 'home tile: a tap opens the Lab');
      await p.close(); await c.close();
    }
    await e2e('/setting', 'POST', { key: 'home_ai', value: 'off' });

    /* ---------- C. a unit page ---------- */
    T.section('C. a unit page');
    await page.click('#glU-present_simple .gl-unit-main'); await settled(page);
    T.eq(await path_(page), '/grammar-lab/present_simple', 'unit: the URL follows');
    T.eq(await page.$$eval('.gl-form code', e => e.map(x => x.textContent)), ['Subject + V1  (he / she / it → V1 + s/es)', 'Subject + do/does + not + V1', 'Do/Does + subject + V1 ?'], 'unit: the three formulas');
    T.has(await txt(page, '#glMarker'), 'ता है', 'unit: the Hindi ending to look for');
    T.has(await txt(page, '#glExample'), 'वह रोज़ स्कूल जाता है।', 'unit: the Hindi example');
    T.has(await txt(page, '#glExample'), 'He goes to school every day.', 'unit: the English example');
    T.eq(await page.$$eval('.gl-lvrow', e => e.length), 4, 'unit: four level buttons');
    await page.click('#glExHear'); await sleep(200);
    const spoken = await page.evaluate(() => window.__spoken);
    T.ok('unit: the example speaker says the English sentence in an English voice', spoken.some(x => x.text === 'He goes to school every day.' && /^en/.test(x.lang)), JSON.stringify(spoken));
    await shot(page, 'unit-390-hi');
    await page.goBack(); await settled(page);
    T.eq(await path_(page), '/grammar-lab', 'unit: the browser Back button returns to the hub');
    T.ok('unit: ...and the hub is drawn', await vis(page, '#glTotal'));
    await page.close();

    /* ---------- D. a full set of ten, every kind of answer ---------- */
    T.section('D. a full set of ten');
    page = await boot(annCtx, '/grammar-lab/present_simple'); await settled(page); spy(page); reqLog = [];
    await page.click('#glLv-easy'); await waitDrill(page);
    T.eq(await prog(page), '1 / 10', 'drill: progress starts at 1 / 10');
    T.eq(await path_(page), '/grammar-lab/present_simple', 'drill: the URL stays the unit\'s');
    T.has(await txt(page, '#glSub'), 'Present Simple', 'drill: the header names the unit'); T.has(await txt(page, '#glSub'), 'आसान', 'drill: ...and the level');
    T.eq(await page.getAttribute('#glHindi', 'lang'), 'hi', 'drill: the Hindi sentence is marked lang=hi');
    T.ok('drill: landing on a sentence speaks nothing and opens no microphone', (await page.evaluate(() => window.__spoken.length)) === 0 && (await page.evaluate(() => window.__srStarts)) === 0);
    T.ok('drill: mic button, text box and Check are there', (await vis(page, '#glMic')) && (await vis(page, '#glIn')) && (await vis(page, '#glCheck')));
    T.ok('drill: lining numerals on the progress', await page.evaluate(() => /lining-nums/.test(getComputedStyle(document.getElementById('glProgN')).fontVariantNumeric)));
    await page.click('#glHear'); await sleep(200);
    const hi1 = await page.evaluate(() => window.__spoken);
    T.ok('drill: the replay button says the Hindi sentence in a Hindi voice', hi1.length === 1 && /^hi/.test(hi1[0].lang) && hasDeva(hi1[0].text), JSON.stringify(hi1));
    await shot(page, 'drill-390-hi');
    const audits = [await audit(page, 'drill input 390')]; clean(audits[0], 'drill input');

    const tally = { right: 0, wrong: 0, unsure: 0, first: 0 };
    const queue = ['ok', 'wrong3', 'shown', 'unsure', 'lang', 'voice', 'edit'];
    const done = {};
    for (let pos = 0; pos < 10; pos++) {
      const it = await itemOf(page);
      let kind = queue.length ? queue[0] : 'ok';
      if (((kind === 'wrong3') && !(it.wrong && it.wrong_changes)) || ((kind === 'shown' || kind === 'edit') && !it.wrong) || (kind === 'unsure' && !it.unsure)) kind = 'ok'; else if (queue.length) queue.shift();
      done[kind] = (done[kind] || 0) + 1;
      const tag = `item ${pos + 1} (${kind})`;
      if (kind === 'ok') {
        await typeCheck(page, it.en[0]);
        const cls = await page.getAttribute('#glResult', 'class');
        T.ok(`${tag}: a green result that says "सही!"`, cls.includes('ok') && /सही/.test(await verdictText(page)), cls);
        if (done.ok === 1) {
          T.eq(await txt(page, '#glTarget'), it.en[0], `${tag}: our answer is shown`);
          T.has(await txt(page, '#glResult'), 'पहली बार में ही सही', `${tag}: right on the first try is said`);
          await page.click('#glHearAns'); await sleep(200);
          T.ok(`${tag}: a speaker button plays the answer in an English voice`, (await page.evaluate(() => window.__spoken)).some(x => x.text === it.en[0] && /^en/.test(x.lang)));
          T.ok(`${tag}: the box is gone (nothing to type after a right answer)`, !(await page.$('#glIn')));
          await shot(page, 'drill-ok-390-hi');
        }
        tally.right++; tally.first++;
      } else if (kind === 'wrong3') {
        await typeCheck(page, it.wrong);
        T.ok(`${tag}: first miss - a bad card, "थोड़ा ग़लत"`, (await page.getAttribute('#glResult', 'class')).includes('bad') && /ग़लत/.test(await verdictText(page)));
        T.ok(`${tag}: first miss - the rule is shown (headline + rules + formula)`, (await page.$$('#glResult .gl-head')).length === 1 && (await page.$$('#glResult .gl-rules li')).length >= 1 && (await vis(page, '#glResult .gl-ex-v.code')));
        T.ok(`${tag}: first miss - the exact change is NOT shown yet and neither is the answer`, !(await page.$('#glChanges')) && !(await page.$('#glTarget')));
        T.has(await txt(page, '#glLeft'), '2', `${tag}: two tries left`);
        T.ok(`${tag}: Try again and Show answer are offered, Next is not`, (await vis(page, '#glTryAgain')) && (await vis(page, '#glShow')) && !(await page.$('#glNext')));
        if (done.wrong3 === 1) await shot(page, 'drill-wrong1-390-hi');
        await page.click('#glTryAgain');
        T.ok(`${tag}: Try again clears the box and focuses it`, await until(async () => (await page.inputValue('#glIn')) === '' && (await focused(page)) === 'glIn'));
        await typeCheck(page, it.wrong);
        T.ok(`${tag}: second miss - the exact change appears (the learner's word struck, the fix beside it)`, (await vis(page, '#glChanges')) && (await page.$$('#glChanges .gl-said, #glChanges .gl-fix')).length >= 1);
        if (done.wrong3 === 1) await shot(page, 'drill-wrong2-390-hi');
        T.ok(`${tag}: second miss - still no answer`, !(await page.$('#glTarget')) && /1/.test(await txt(page, '#glLeft')));
        await page.click('#glTryAgain'); await until(async () => (await focused(page)) === 'glIn');
        await typeCheck(page, it.wrong);
        T.ok(`${tag}: third miss - the answer is shown, with a Next button and no Try again`, (await txt(page, '#glTarget')) === it.en[0] && (await vis(page, '#glNext')) && !(await page.$('#glTryAgain')));
        T.has(await verdictText(page), 'यह रहा जवाब', `${tag}: third miss - "here is the answer"`);
        if (done.wrong3 === 1) await shot(page, 'drill-wrong3-390-hi');
        tally.wrong++;
      } else if (kind === 'shown') {
        await typeCheck(page, it.wrong);
        await page.click('#glShow'); await page.waitForSelector('#glNext');
        T.eq(await txt(page, '#glTarget'), it.en[0], `${tag}: Show answer reveals our answer`);
        T.has(await verdictText(page), 'यह रहा जवाब', `${tag}: ...as "here is the answer"`);
        T.ok(`${tag}: the teaching lines (formula) are still shown`, await vis(page, '#glResult .gl-ex-v.code'));
        tally.wrong++;
      } else if (kind === 'unsure') {
        await typeCheck(page, it.unsure);
        T.has(await verdictText(page), 'कोई ग़लती नहीं मिली', `${tag}: "no tense mistake found"`);
        T.ok(`${tag}: our answer is shown to compare, nothing is held against the learner`, (await txt(page, '#glTarget')) === it.en[0] && (await page.getAttribute('#glResult', 'class')).includes('info') && !(await page.$('#glResult .gl-tick.bad')));
        await shot(page, 'drill-unsure-390-hi');
        tally.unsure++;
      } else if (kind === 'lang') {
        const c0 = (await e2e('/stats')).check_calls;
        await typeCheck(page, 'यह एक हिंदी जवाब है');
        T.ok(`${tag}: a Hindi answer gets a message, no result card, and the box stays`, (await vis(page, '#glMsg')) && !(await page.$('#glResult')) && (await vis(page, '#glIn')));
        T.has(await txt(page, '#glMsg'), 'English', `${tag}: the message says to answer in English`);
        T.eq(await prog(page), `${pos + 1} / 10`, `${tag}: the progress did not move`);
        const c1 = (await e2e('/stats')).check_calls;
        await page.fill('#glIn', '   '); await page.click('#glCheck'); await sleep(300);
        T.eq((await e2e('/stats')).check_calls, c1, `${tag}: an empty box sends no request`);
        T.has(await txt(page, '#glHint'), 'पहले जवाब', `${tag}: ...and says to write something first`);
        T.eq(c1, c0 + 1, `${tag}: the Hindi answer itself was one request`);
        await page.fill('#glIn', it.en[0]); await page.click('#glCheck'); await page.waitForSelector('#glResult');
        T.has(await txt(page, '#glResult'), 'पहली बार में ही सही', `${tag}: the refused Hindi answer used no try`);
        tally.right++; tally.first++;
      } else if (kind === 'voice') {
        const said = it.en[0].replace(/[.?!]+$/, '').toLowerCase();
        await page.evaluate(u => window.__utter.push(u), said);
        await page.click('#glMic');
        T.ok(`${tag}: the heard words land in the box`, await until(async () => { const v = await page.inputValue('#glIn'); return v.length > 0 && v.toLowerCase() === said; }));
        T.eq((await page.inputValue('#glIn')).charAt(0), cap(said).charAt(0), `${tag}: shown in sentence case`);
        T.has(await txt(page, '#glInLab'), 'मैंने सुना', `${tag}: labelled "I heard:"`);
        T.ok(`${tag}: the "fix it, then Check" hint is shown`, await vis(page, '#glHeardHint'));
        T.eq(await page.evaluate(() => window.__srLang), 'en-US', `${tag}: the recogniser listens for English (en-US)`);
        await shot(page, 'drill-heard-390-hi');
        await page.click('#glCheck'); await outcome(page);
        T.ok(`${tag}: the spoken answer is checked and right`, (await page.getAttribute('#glResult', 'class')).includes('ok'));
        tally.right++; tally.first++;
      } else if (kind === 'edit') {
        await page.evaluate(u => window.__utter.push(u), it.wrong.replace(/[.?!]+$/, '').toLowerCase());
        await page.click('#glMic');
        await until(async () => (await page.inputValue('#glIn')).length > 0);
        T.has(await txt(page, '#glInLab'), 'मैंने सुना', `${tag}: the mis-heard words are shown as heard`);
        await page.fill('#glIn', it.en[0]);
        T.ok(`${tag}: editing the box switches the label back (it is the learner's text now) and hides the hint`, (await txt(page, '#glInLab')).includes('तुम्हारा जवाब') && !(await vis(page, '#glHeardHint')));
        await page.click('#glCheck'); await outcome(page);
        T.ok(`${tag}: the corrected text is what was checked - right on the first try`, (await page.getAttribute('#glResult', 'class')).includes('ok') && (await txt(page, '#glResult')).includes('पहली बार में ही सही'));
        tally.right++; tally.first++;
      }
      if (pos < 9) await clickNext(page, `${pos + 2} / 10`);
    }
    T.eq(queue, [], 'every kind of answer was exercised (wrong x3, shown, unsure, Hindi refused, spoken, spoken + edited)');
    T.has(await txt(page, '#glNext'), 'Results', 'the last item\'s button says "see results"');
    await shot(page, 'drill-last-390-hi');
    await page.click('#glNext'); await page.waitForSelector('#glHero');

    T.section('D2. the summary');
    const graded = tally.right + tally.wrong, pct = graded ? Math.round(100 * tally.right / graded) : 0, stars = graded < 6 ? 0 : (pct >= 60) + (pct >= 80) + (pct >= 90);
    T.eq(await txt(page, '#glRight'), `सही: ${tally.right}`, 'summary: right'); T.eq(await txt(page, '#glWrong'), `ग़लत: ${tally.wrong}`, 'summary: wrong');
    if (tally.unsure) T.eq(await txt(page, '#glUnsure'), `ग़लती नहीं मिली: ${tally.unsure}`, 'summary: "no mistake found"');
    T.eq(await txt(page, '#glPct'), `${pct}% सही`, 'summary: the percent'); T.has(await txt(page, '#glFirst'), String(tally.first), 'summary: right on the first try');
    T.eq(await page.getAttribute('#glBigStars', 'aria-label'), `3 में से ${stars} stars`, 'summary: the stars, in words for a screen reader');
    T.eq(await page.$$eval('#glBigStars .gl-star.on', e => e.length), stars, 'summary: the filled stars');
    T.ok('summary: the weak rules are listed in Hindi', (await vis(page, '#glWeak')) && (await page.$$('#glWeak li')).length >= 1 && hasDeva(await txt(page, '#glWeak')));
    T.eq(await page.$$eval('#glMissed .gl-miss', e => e.length), tally.wrong, 'summary: the missed sentences are listed (Hindi + English)');
    T.ok('summary: each missed row has the Hindi (lang=hi), the English and a speaker', await page.evaluate(() => [...document.querySelectorAll('#glMissed .gl-miss')].every(r => r.querySelector('.m-hi[lang=hi]') && r.querySelector('.m-en') && r.querySelector('button.gl-speak'))));
    const sumBtns = await page.$$eval('#glSumActs .btn', e => e.map(x => x.id));
    if (stars < 2) T.eq(sumBtns, ['glAgain', 'glBackLab'], 'summary: below 2 stars the suggestion is "try this level again" (one button, not two)');
    else T.eq(sumBtns, ['glNextStep', 'glAgain', 'glBackLab'], 'summary: with 2+ stars: the next step, again, back to the Lab');
    if (stars < 2) T.eq(await txt(page, '#glAgain'), 'यही level फिर से करो', 'summary: the Again button says so');
    T.eq(await path_(page), '/grammar-lab/present_simple', 'summary: the URL is the unit\'s');
    await shot(page, 'summary-390-hi');
    audits.push(await audit(page, 'summary 390')); clean(audits[1], 'summary');
    const afterSet = await api('ann', 'GET', '/state');
    const easy = afterSet.body.units[0].levels.easy;
    T.ok('the server holds the stars and the best percent', easy.stars === stars && easy.best === pct && easy.sets === 1, JSON.stringify(easy));
    T.eq(afterSet.body.review_due, tally.wrong, 'the server queued exactly the missed sentences for Review');
    T.ok('requests: the page asked the server for every answer', reqLog.filter(r => r === 'POST /lab/check' || r === 'POST /lab/show').length >= 10, JSON.stringify(reqLog.length));

    /* ---------- E. hub afterwards + the Review set ---------- */
    T.section('E. hub afterwards, Review');
    await page.click('#glBackLab'); await settled(page);
    T.eq(await txt(page, '#glStars'), String(stars), 'hub: the star total moved');
    T.eq(await page.getAttribute('#glU-present_simple .gl-lv[data-level="easy"]', 'aria-label'), `आसान: 3 में से ${stars} stars`, 'hub: the chip shows the stars');
    T.ok('hub: the "how it works" card is gone once a set is done', !(await page.$('#glHow')));
    T.ok('hub: the Review button is there with the count', (await vis(page, '#glReviewCard')) && (await txt(page, '#glReviewCard')).includes(String(tally.wrong)));
    await shot(page, 'hub-after-390-hi');
    await page.click('#glReviewGo'); await waitDrill(page);
    T.eq(await path_(page), '/grammar-lab/review', 'review: the URL');
    T.eq(await prog(page), `1 / ${tally.wrong}`, 'review: a set of exactly the missed sentences');
    T.eq(await txt(page, '#glSub'), 'Review', 'review: the header');
    await page.goBack(); await settled(page);
    T.eq(await path_(page), '/grammar-lab', 'review: Back returns to the hub');
    T.ok('review: ...and the open review set is offered as "Continue"', (await vis(page, '#glResume')) && (await txt(page, '#glResume')).includes('Review'));
    const meLanded = page.waitForResponse(r => new URL(r.url()).pathname === '/me' && r.request().method() === 'GET', { timeout: 30000 });
    await page.goto(L.BASE + '/grammar-lab/review'); await waitDrill(page); await meLanded; await sleep(1200);   // a cold deep link is routed twice (cached state, then /me): wait for both
    T.eq(await prog(page), `1 / ${tally.wrong}`, 'review: a cold deep link to /grammar-lab/review resumes the same set');
    await page.fill('#glIn', 'typed before the second route'); await sleep(300);
    T.eq(await page.inputValue('#glIn'), 'typed before the second route', 'review: the second routing of a cold link did not restart the drill');
    await page.fill('#glIn', '');
    await clearSet(page);
    T.ok('review: finishing it shows the summary', await vis(page, '#glHero'));
    T.eq(await txt(page, '#glRight'), `सही: ${tally.wrong}`, 'review: all right');
    T.eq(await page.$$eval('#glSumActs .btn', e => e.map(x => x.id)), ['glNextStep', 'glBackLab'], 'review: the buttons are "Review again" and "Back to the Lab"');
    T.has(await txt(page, '#glNextStep'), 'Review', 'review: the suggested step is Review again');
    await page.click('#glBackLab'); await settled(page);
    T.ok('review: nothing left to review - the Review button is gone', !(await page.$('#glReviewCard')));
    T.eq((await api('ann', 'GET', '/state')).body.review_due, 0, 'review: the server cleared them');
    await page.close();

    /* ---------- F. double tap, a failed network, Enter, resume after a reload ---------- */
    T.section('F. double tap, network failure, resume');
    const bobCtx = await L.ctxFor(browser, 'bob');
    page = await boot(bobCtx, '/grammar-lab'); await settled(page); spy(page); reqLog = [];
    await page.click('#glU-present_simple .gl-lv[data-level="easy"]'); await waitDrill(page);
    T.eq(await path_(page), '/grammar-lab/present_simple', 'a level chip on the hub opens the drill straight away');
    let it = await itemOf(page);
    await page.fill('#glIn', it.en[0]);
    const s0 = (await e2e('/stats')).check_calls; reqLog = [];
    await page.evaluate(() => { const b = document.getElementById('glCheck'); b.click(); b.click(); b.click(); });
    await outcome(page); await sleep(500);
    T.eq(reqLog.filter(r => r === 'POST /lab/check').length, 1, 'double tap: ONE request left the page');
    T.eq((await e2e('/stats')).check_calls - s0, 1, 'double tap: the server graded ONE answer');
    T.eq((await api('bob', 'GET', '/state')).body.open_set.answered, 1, 'double tap: one item counted');
    await clickNext(page, '2 / 10');
    it = await itemOf(page);
    await page.route('**/lab/check', r => r.abort('failed'));
    await page.fill('#glIn', it.en[0]); await page.click('#glCheck'); await outcome(page);
    T.ok('network failure: an error with a retry button appears', (await vis(page, '#glErr')) && (await vis(page, '#glRetryCheck')));
    T.has(await txt(page, '#glErr'), 'Internet', 'network failure: in plain words');
    T.eq(await page.inputValue('#glIn'), it.en[0], 'network failure: the typed text is still in the box');
    T.ok('network failure: the buttons are usable again', !(await page.$eval('#glCheck', e => e.disabled)));
    await page.unroute('**/lab/check');
    const s1 = (await e2e('/stats')).check_calls;
    await page.click('#glRetryCheck'); await page.waitForSelector('#glResult');
    T.ok('network failure: Retry sends the same text and it is graded', (await page.getAttribute('#glResult', 'class')).includes('ok'));
    T.eq((await e2e('/stats')).check_calls - s1, 1, 'network failure: the aborted request never counted, the retry counted once');
    await clickNext(page, '3 / 10');
    it = await itemOf(page);
    await page.fill('#glIn', it.en[0]); await page.press('#glIn', 'Enter'); await page.waitForSelector('#glResult');
    T.ok('keyboard: Enter in the box checks the answer', (await page.getAttribute('#glResult', 'class')).includes('ok'));
    await clickNext(page, '4 / 10');
    it = await itemOf(page);
    const hiBefore = (await page.textContent('#glHindi')).trim();
    await typeCheck(page, it.wrong);                       // a miss on item 4, then the page is reloaded
    T.has(await txt(page, '#glLeft'), '2', 'resume: item 4 has a miss on it (2 tries left)');
    await page.reload(); await page.waitForSelector('#gl.on'); await settled(page);
    T.eq(await path_(page), '/grammar-lab/present_simple', 'resume: a reload on a drill URL lands on the unit page');
    T.ok('resume: the unit page is drawn', await vis(page, '#glUnitCard'));
    await page.click('#glBack'); await settled(page);
    T.ok('resume: the hub offers the open set', await vis(page, '#glResume'));
    T.has(await txt(page, '#glResume'), '10 में से 3', 'resume: "3 of 10 done"');
    await shot(page, 'hub-resume-390-hi');
    await page.click('#glResumeGo'); await waitDrill(page);
    T.eq(await prog(page), '4 / 10', 'resume: back on item 4');
    T.eq((await page.textContent('#glHindi')).trim(), hiBefore, 'resume: the SAME sentence');
    T.has(await txt(page, '#glInput'), '2', 'resume: the miss survived the reload (2 tries left shown)');
    const same = await api('bob', 'POST', '/set', { unit: 'present_simple', level: 'easy' });
    T.ok('resume: the server resumes the same set (not a new one)', same.body.answered === 3 && same.body.items.filter(x => x.done).length === 3);

    /* ---------- G. the Hindi / English toggle ---------- */
    T.section('G. Hindi <-> English');
    await typeCheck(page, it.wrong);                        // a miss again: the explanation is on screen
    const hiText = await page.innerText('#glResult');
    reqLog = [];
    T.ok('toggle: the explanation is in Hindi', hasDeva(await txt(page, '#glResult .gl-head')) && (await page.getAttribute('#glResult .gl-head', 'lang')) === 'hi');
    await page.click('#glLangEn'); await sleep(200);
    const enText = await page.innerText('#glResult');
    T.ok('toggle: the same card is now in English (no request needed)', reqLog.length === 0 && enText !== hiText && /Not quite/.test(enText) && !hasDeva(await txt(page, '#glResult .gl-head')), enText.slice(0, 120));
    T.eq(await page.getAttribute('#glResult .gl-head', 'lang'), 'en', 'toggle: lang=en on the English explanation');
    T.eq(await page.evaluate(() => localStorage.getItem('dusu_gl_lang')), 'en', 'toggle: remembered in localStorage');
    T.eq(await page.getAttribute('#glLangEn', 'aria-pressed'), 'true', 'toggle: English is pressed');
    T.has(await txt(page, '#glSub'), 'Easy', 'toggle: the header\'s level name is English');
    await shot(page, 'drill-wrong1-390-en');
    await page.reload(); await page.waitForSelector('#gl.on'); await settled(page);
    T.eq(await page.getAttribute('#glLangEn', 'aria-pressed'), 'true', 'toggle: English survives a reload');
    await page.click('#glLangHi'); await sleep(100);
    T.eq(await page.getAttribute('#glLangHi', 'aria-pressed'), 'true', 'toggle: back to Hindi');
    await page.close();
    // no choice of the Lab's own: it follows the learner's Hindi / English choice, which the SERVER holds (POST /lang), then Hindi
    await fetch(L.BASE + '/lang', { method: 'POST', headers: { Authorization: 'Bearer ' + L.TOK.cat.token, 'Content-Type': 'application/json' }, body: JSON.stringify({ lang: 'en' }) });
    const catCtx2 = await L.ctxFor(browser, 'cat');
    page = await boot(catCtx2, '/grammar-lab'); await settled(page);
    T.eq(await page.getAttribute('#glLangEn', 'aria-pressed'), 'true', 'toggle: with no choice of its own the Lab follows the learner\'s Hindi / English choice (English)');
    T.has(await txt(page, '#glSub'), 'Say or type', 'toggle: the whole chrome is English');
    T.eq(await page.$$eval('h3.gl-sh', e => e.map(x => x.textContent)), ['Present', 'Past', 'Future'], 'toggle: the section names come in English');
    await page.close(); await catCtx2.close();
    await fetch(L.BASE + '/lang', { method: 'POST', headers: { Authorization: 'Bearer ' + L.TOK.cat.token, 'Content-Type': 'application/json' }, body: JSON.stringify({ lang: 'hi' }) });

    /* ---------- H. the microphone: listening, denied, absent, reduced motion ---------- */
    T.section('H. microphone');
    for (const motion of ['reduce', 'no-preference']) {
      const c = await L.ctxFor(browser, 'cat', { motion });
      const p = await boot(c, '/grammar-lab/present_simple'); await settled(p);
      await p.evaluate(() => { window.__srHold = true; });
      await p.click('#glLv-medium'); await waitDrill(p);
      await p.click('#glMic'); await until(async () => (await p.$('#glMic.on')) !== null);
      T.ok('mic: while listening the button says so', (await p.getAttribute('#glMic', 'aria-pressed')) === 'true' && (await txt(p, '#glMicT')).includes('Listening'));
      const an = await p.evaluate(() => getComputedStyle(document.getElementById('glMic')).animationName);
      T.ok(`mic: the pulse ${motion === 'reduce' ? 'is NOT animated (reduced motion respected)' : 'animates'}`, motion === 'reduce' ? an === 'none' : /glPulse/.test(an), an);
      await p.click('#glMic'); await until(async () => !(await p.$('#glMic.on')));
      T.has(await txt(p, '#glHint'), 'कुछ सुनाई नहीं दिया', 'mic: stopping with nothing heard says so (and offers typing)');
      if (motion === 'reduce') {
        await p.click('#glMic'); await until(async () => (await p.$('#glMic.on')) !== null);
        await p.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); });
        T.ok('hidden tab: the microphone is stopped and the button stops saying "listening"', await until(async () => !(await p.$('#glMic.on')) && (await p.getAttribute('#glMic', 'aria-pressed')) === 'false'));
        await p.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false }); document.dispatchEvent(new Event('visibilitychange')); });
        await p.evaluate(() => { window.__srHold = false; window.__srError = 'not-allowed'; });
        await p.click('#glMic'); await until(async () => !(await p.$('#glMic')));
        T.ok('mic denied: the mic button is gone, only typing is offered', !(await p.$('#glMic')) && (await vis(p, '#glIn')) && (await txt(p, '#glMicNote')).includes('इजाज़त'));
        const it2 = await itemOf(p); await typeCheck(p, it2.en[0]);
        T.ok('mic denied: a typed answer still works', (await p.getAttribute('#glResult', 'class')).includes('ok'));
        await shot(p, 'drill-micdenied-390-hi');
      }
      await p.close(); await c.close();
    }
    {
      const c = await L.ctxFor(browser, 'dan', { noSR: true });
      const p = await boot(c, '/grammar-lab/present_simple'); await settled(p);
      await p.click('#glLv-easy'); await waitDrill(p);
      T.ok('no recogniser: no mic button, a note and the text box', !(await p.$('#glMic')) && (await vis(p, '#glMicNote')) && (await vis(p, '#glIn')));
      const it2 = await itemOf(p); await typeCheck(p, it2.en[0]);
      T.ok('no recogniser: typing works', (await p.getAttribute('#glResult', 'class')).includes('ok'));
      await p.close(); await c.close();
    }

    /* ---------- I. the next level, the in-app Back chain, a bad unit link ---------- */
    T.section('I. next level and Back');
    {
      const c = await L.ctxFor(browser, 'dan');
      const p = await boot(c, '/grammar-lab'); await settled(p);
      await p.click('#glU-present_simple .gl-unit-main'); await settled(p);
      await p.click('#glLv-easy'); await waitDrill(p);
      await clearSet(p);
      T.eq(await p.getAttribute('#glBigStars', 'aria-label'), '3 में से 3 stars', 'next level: ten right = three stars');
      T.eq(await txt(p, '#glPct'), '100% सही', 'next level: 100%');
      T.ok('next level: a "New best!" badge', await vis(p, '#glNewBest'));
      T.eq(await p.$$eval('#glSumActs .btn', e => e.map(x => x.id)), ['glNextStep', 'glAgain', 'glBackLab'], 'next level: next step, again, back');
      T.has(await txt(p, '#glNextStep'), 'अगला level: मध्यम', 'next level: the suggested step names the next level');
      T.ok('next level: no "missed" or "weak" card when nothing was missed', !(await p.$('#glMissed')) && !(await p.$('#glWeak')));
      await shot(p, 'summary3-390-hi');
      await p.click('#glNextStep'); await waitDrill(p);
      T.has(await txt(p, '#glSub'), 'मध्यम', 'next level: the medium drill opens');
      T.eq(await prog(p), '1 / 10', 'next level: a fresh set');
      await p.click('#glBack'); await settled(p);
      T.ok('Back chain: the drill\'s back arrow goes to the unit page', await vis(p, '#glUnitCard'));
      T.has(await txt(p, '#glLv-easy'), '100', 'Back chain: the unit page shows the best (100%)');
      await p.click('#glBack'); await settled(p);
      T.ok('Back chain: ...then the hub', await vis(p, '#glTotal'));
      T.eq(await txt(p, '#glStars'), '3', 'Back chain: three stars on the hub');
      await p.click('#glBack'); await p.waitForSelector('#practice.on');
      T.eq(await path_(p), '/practice', 'Back chain: ...then the Practice hub');
      await p.goto(L.BASE + '/grammar-lab/not_a_unit'); await p.waitForSelector('#home.on');
      T.ok('a link to a unit that does not exist lands on Home', await vis(p, '#home.on'));
      await p.goto(L.BASE + '/grammar-lab/review'); await p.waitForSelector('#gl.on');
      // a cold deep link is routed twice (cached state, then /me): the second pass asks again, so the note and the spinner may swap once - poll for the settled state, then prove it STAYS
      const hubNote = async () => (await vis(p, '#glTotal')) && (await vis(p, '#glNote')) && (await txt(p, '#glNote')).includes('review');
      T.ok('a cold link to Review with nothing to review lands on the hub with a kind note', await until(hubNote, 15000));
      await sleep(1500);
      T.ok('...and it stays there (the second routing pass does not lose the note)', await hubNote());
      await p.close(); await c.close();
    }

    /* ---------- J. the switch OFF ---------- */
    T.section('J. the switch is off');
    await e2e('/switch', 'POST', { mode: 'off' });
    {
      const c = await L.ctxFor(browser, 'eve', { cachedOn: false });
      const p = await boot(c, '/', '#home.on');
      await p.evaluate(() => show('practice')); await sleep(300);
      T.ok('off: no Practice-hub entry', !(await vis(p, '#glEntry')));
      await p.evaluate(() => { show('home'); openMore(); }); await sleep(300);
      T.ok('off: no More-sheet row', !(await vis(p, '#mrowGL')));
      T.eq((await api('eve', 'GET', '/state')).status, 404, 'off: /lab/state answers 404');
      T.eq((await api('eve', 'POST', '/set', { unit: 'present_simple', level: 'easy' })).status, 404, 'off: /lab/set answers 404');
      await p.goto(L.BASE + '/grammar-lab'); await p.waitForSelector('#home.on', { timeout: 15000 });
      T.ok('off: the route goes Home', (await vis(p, '#home.on')) && !(await vis(p, '#gl.on')));
      T.eq(await p.evaluate(() => location.pathname), '/', 'off: ...and the address bar says so');
      await p.close(); await c.close();
      // a stale cache that still says "on" (the owner switched it off since): the page may draw first, the server's 404 / the first /me sends it Home
      const c2 = await L.ctxFor(browser, 'eve', { cachedOn: true });
      const p2b = await c2.newPage();
      await p2b.goto(L.BASE + '/grammar-lab');
      T.ok('off (stale cache says on): it still ends on Home', await until(async () => await vis(p2b, '#home.on'), 20000));
      T.ok('off (stale cache): the entries are hidden', !(await vis(p2b, '#glEntry')));
      await p2b.close(); await c2.close();
    }
    await e2e('/switch', 'POST', { mode: 'on' });

    /* ---------- J2. the owner switches it off while a learner has the app open ---------- */
    T.section('J2. switched off while the app is open');
    {
      const c = await L.ctxFor(browser, 'eve');
      const p = await boot(c, '/', '#home.on');
      await p.evaluate(() => show('practice'));
      T.ok('off while open: the entry is there (the learner loaded the app while it was on)', await until(async () => await vis(p, '#glEntry')));
      await e2e('/switch', 'POST', { mode: 'off' });
      await p.click('#glEntry');
      T.ok('off while open: opening the hub (its /lab/state answers 404) sends the learner Home - not a dead screen', await until(async () => (await vis(p, '#home.on')) && !(await vis(p, '#gl.on')), 15000));
      await e2e('/switch', 'POST', { mode: 'on' });
      await p.evaluate(() => navTo('/grammar-lab')); await p.waitForSelector('#glTotal', { timeout: 15000 });
      await p.click('#glU-present_simple .gl-lv[data-level="easy"]'); await waitDrill(p);
      await e2e('/switch', 'POST', { mode: 'off' });
      await p.fill('#glIn', 'x'); await p.click('#glCheck');
      T.ok('off while open: checking an answer (404) sends the learner Home too', await until(async () => (await vis(p, '#home.on')) && !(await vis(p, '#gl.on')), 15000));
      await e2e('/switch', 'POST', { mode: 'on' });
      await p.close(); await c.close();
    }

    /* ---------- K. an XSS canary: hostile text from the server must appear as text and run nothing ---------- */
    T.section('K. XSS canary');
    {
      const CAN = '<img src=x onerror="window.__xss=(window.__xss||0)+1"><script>window.__xss=(window.__xss||0)+100</script>';
      const taint = (o, key) => {
        if (typeof o === 'string') return ['family', 'type', 'code', 'reason', 'unit', 'level'].includes(key) ? o : o + ' ' + CAN;
        if (Array.isArray(o)) return key === 'order' ? o : o.map(x => taint(x, key));
        if (o && typeof o === 'object') { const r = {}; for (const k of Object.keys(o)) r[k] = taint(o[k], k); return r; }
        return o;
      };
      const E = { headline: CAN, rules: [CAN], changes: [{ said: CAN, fix: CAN }], formula: CAN, marker: CAN, gist: CAN, trap: CAN };
      const c = await L.ctxFor(browser, 'fay');
      const p = await c.newPage();
      p.on('pageerror', e => L.ERRS.push('pageerror: ' + e.message));
      await p.route('**/lab/state', async route => { const r = await route.fetch(); const j = await r.json(); j.catalog = taint(j.catalog, 'catalog'); await route.fulfill({ json: j }); });
      await p.route('**/lab/set', route => route.fulfill({ json: { set: 777, unit: 'present_simple', level: 'easy', total: 1, answered: 0, items: [{ id: 'prs-e-01', hi: CAN + ' राम रोज़ चाय पीता है।', done: false, tries: 0 }] } }));
      await p.route('**/lab/check', route => route.fulfill({ json: { verdict: 'wrong', tries: 1, left: 2, done: false, answered: 0, total: 1, explain: { hi: E, en: E } } }));
      await p.route('**/lab/show', route => route.fulfill({ json: { verdict: 'shown', tries: 1, left: 0, done: true, target: CAN, model: CAN, also: [CAN], explain: { hi: E, en: E }, answered: 1, total: 1,
        summary: { right: 0, wrong: 1, unsure: 0, first_try: 0, total: 1, graded: 1, pct: 0, stars: 0, weak: [{ code: 'x', n: 1, rule: { hi: CAN, en: CAN } }], missed: [{ id: 'prs-e-01', hi: CAN, en: CAN }], new_best: false, best_stars: 0, best_pct: 0, next: { unit: 'present_simple', level: 'easy', reason: 'again' } } } }));
      await p.goto(L.BASE + '/grammar-lab'); await p.waitForSelector('#glTotal'); await sleep(300);
      T.has(await txt(p, '#glBody'), '<img src=x', 'xss: the hub shows hostile catalog text AS TEXT');
      await noXss(p, 'hub');
      await p.click('#glU-present_simple .gl-unit-main'); await p.waitForSelector('#glUnitCard'); await sleep(200);
      T.has(await txt(p, '#glUnitCard'), '<img src=x', 'xss: the unit page shows the hostile formulas AS TEXT'); await noXss(p, 'unit page');
      await p.click('#glLv-easy'); await p.waitForSelector('#glHindi');
      T.has(await txt(p, '#glHindi'), '<img src=x', 'xss: the sentence shows hostile text AS TEXT'); await noXss(p, 'drill');
      await p.fill('#glIn', 'x'); await p.click('#glCheck'); await p.waitForSelector('#glResult');
      T.has(await txt(p, '#glResult'), '<img src=x', 'xss: the explanation shows hostile text AS TEXT (headline, rules, changes, formula, marker, trap)'); await noXss(p, 'wrong result');
      await p.click('#glLangEn'); await sleep(100); await noXss(p, 'wrong result, English');
      await p.click('#glShow'); await p.waitForSelector('#glNext');
      T.has(await txt(p, '#glTarget'), '<img src=x', 'xss: our answer shows hostile text AS TEXT'); await noXss(p, 'answer');
      await p.click('#glNext'); await p.waitForSelector('#glHero'); await sleep(100);
      T.has(await txt(p, '#glMissed'), '<img src=x', 'xss: the missed list shows hostile text AS TEXT'); T.has(await txt(p, '#glWeak'), '<img src=x', 'xss: the weak rules show hostile text AS TEXT');
      await noXss(p, 'summary');
      await p.close(); await c.close();
    }

    /* ---------- K2. a failed load keeps a retry; the server's refusals are said kindly ---------- */
    T.section('K2. failures');
    {
      const c = await L.ctxFor(browser, 'eve'); const p = await c.newPage();
      p.on('pageerror', e => L.ERRS.push('pageerror: ' + e.message));
      await p.route('**/lab/state', r => r.abort('failed'));
      await p.goto(L.BASE + '/grammar-lab'); await p.waitForSelector('#glRetry', { timeout: 15000 });
      // a cold deep link is routed twice (cached state, then /me): the second pass puts the spinner back for a moment before the next /lab/state fails - poll for the SETTLED state, never read once
      T.ok('hub load failure: an error in plain words and a retry button', await until(async () => (await txt(p, '#glBody')).includes('Internet') && (await vis(p, '#glRetry')), 15000));
      await sleep(400);
      await p.unroute('**/lab/state'); await p.click('#glRetry'); await p.waitForSelector('#glTotal');
      T.ok('hub load failure: Retry draws the hub', (await page_count(p, '.gl-unit')) === 12);
      await p.route('**/lab/set', r => r.abort('failed'));
      await p.click('#glU-present_simple .gl-lv[data-level="hard"]'); await p.waitForSelector('#glRetry');
      T.ok('set load failure: an error and a retry', (await txt(p, '#glBody')).includes('Internet'));
      await p.unroute('**/lab/set'); await p.click('#glRetry'); await waitDrill(p);
      T.eq(await prog(p), '1 / 10', 'set load failure: Retry opens the set');
      T.has(await txt(p, '#glSub'), 'कठिन', 'a level chip opens THAT level (hard), not the first one');
      await p.route('**/lab/check', r => r.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ detail: { error: 'slow_down' } }) }));
      await p.fill('#glIn', 'x'); await p.click('#glCheck'); await p.waitForSelector('#glErr');
      T.has(await txt(p, '#glErr'), 'धीरे', 'a 429 slow-down is said kindly, the text is kept'); T.eq(await p.inputValue('#glIn'), 'x', 'a 429: the typed text is kept');
      await p.unroute('**/lab/check');
      await p.route('**/lab/check', r => r.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: { error: 'closed' } }) }));
      await p.click('#glRetryCheck'); await p.waitForSelector('#glTotal');
      T.ok('a finished set (422 closed): back on the hub with a note, not stuck on a retry', (await vis(p, '#glNote')) && (await txt(p, '#glNote')).includes('पूरा'));
      await p.unroute('**/lab/check');
      await p.route('**/lab/state', async route => { const r = await route.fetch(); const j = await r.json(); j.ready = false; await route.fulfill({ json: j }); });
      await p.click('#glBack'); await p.waitForSelector('#practice.on'); await p.evaluate(() => navTo('/grammar-lab')); await p.waitForSelector('#glNoBank');
      T.ok('bank not ready: a calm message, no empty cards', (await txt(p, '#glNoBank')).includes('तैयार') && !(await p.$('.gl-unit')));
      await p.close(); await c.close();
    }

    /* ---------- K3. the owner dashboard's switch ---------- */
    T.section('K3. the owner dashboard');
    {
      const c = await L.ctxFor(browser, 'own'); const p = await boot(c, '/', '#home.on', { noMe: false });
      await p.evaluate(() => openAdmin()); await p.waitForSelector('#glSel', { timeout: 15000 });
      T.eq(await p.inputValue('#glSel'), 'on', 'dashboard: the Grammar Lab row shows the server\'s value (on)');
      T.eq(await p.$$eval('#glSel option', o => o.map(x => x.textContent)), ['Off', 'Owner + early access', 'Everyone'], 'dashboard: Off / Owner + early access / Everyone');
      T.ok('dashboard: the row sits next to the Grammar Coach row', await p.evaluate(() => { const a = document.getElementById('gcSel').closest('label'), b = document.getElementById('glSel').closest('label'); return a.nextElementSibling === b || a.nextElementSibling.nextElementSibling === b; }));
      T.has(await txt(p, '#adminBody'), 'Grammar Lab:', 'dashboard: the health line (sets / answers / sentences in the bank) is shown');
      const ov = await (await fetch(L.BASE + '/admin/overview', { headers: { Authorization: 'Bearer ' + L.TOK.own.token } })).json();
      // wait for the server's ANSWER to the POST (not just for the request to be sent): the handler writes every switch one by one, so a fixed sleep made this a timing check
      let posted = p.waitForResponse(r => new URL(r.url()).pathname === '/admin/settings' && r.request().method() === 'POST');
      await p.selectOption('#glSel', 'owner');
      const resp1 = await posted; let body = JSON.parse(resp1.request().postData());
      T.eq(body.grammar_lab, 'owner', 'dashboard: changing the select posts grammar_lab');
      T.ok('dashboard: ...with the other switches as the server had them (nothing else changes)', body.grammar_coach === ov.grammar_coach && body.planner === ov.planner && body.notifications === ov.notifications && body.resume_interview === ov.resume_interview, JSON.stringify([body.grammar_coach, ov.grammar_coach]));
      T.eq(resp1.status(), 200, 'dashboard: the switch change was accepted');
      T.eq((await api('bob', 'GET', '/state')).status, 404, 'dashboard: "Owner + early access" hides the Lab from an ordinary learner');
      T.eq((await api('own', 'GET', '/state')).status, 200, 'dashboard: ...and the owner still has it');
      posted = p.waitForResponse(r => new URL(r.url()).pathname === '/admin/settings' && r.request().method() === 'POST');
      await p.selectOption('#glSel', 'on'); await posted;
      T.eq((await api('bob', 'GET', '/state')).status, 200, 'dashboard: "Everyone" gives it back');
      await p.close(); await c.close();
    }

    /* ---------- L. layout at 360 / 390 / 1280, both languages, screenshots ---------- */
    T.section('L. layout');
    for (const [who, w, h2] of [['gus', 360, 740], ['hal', 390, 844], ['ivy', 1280, 800]]) {
      const c = await L.ctxFor(browser, who, { viewport: { width: w, height: h2 } });
      const p = await boot(c, '/grammar-lab'); await settled(p);
      const tag = `${w}`;
      clean(await audit(p, 'hub ' + w), `hub ${w}`); await shot(p, `hub-${tag}-hi`);
      await p.click('#glLangEn'); await sleep(100); clean(await audit(p, 'hub en ' + w), `hub (English) ${w}`); await shot(p, `hub-${tag}-en`); await p.click('#glLangHi');
      await p.click('#glU-present_perfect_continuous .gl-unit-main'); await settled(p);
      clean(await audit(p, 'unit ' + w), `unit ${w}`); await shot(p, `unit-${tag}-hi`);
      await p.click('#glLangEn'); await sleep(100); clean(await audit(p, 'unit en ' + w), `unit (English) ${w}`); await shot(p, `unit-${tag}-en`); await p.click('#glLangHi');
      await p.click('#glLv-hard'); await waitDrill(p);
      clean(await audit(p, 'drill ' + w), `drill input ${w}`); await shot(p, `drill-${tag}-hi`);
      const it2 = await itemOf(p);
      await p.evaluate(u => window.__utter.push(u), (it2.wrong || it2.en[0]).replace(/[.?!]+$/, '').toLowerCase());
      await p.click('#glMic'); await until(async () => (await p.inputValue('#glIn')).length > 0);
      clean(await audit(p, 'heard ' + w), `drill, heard ${w}`); await shot(p, `drill-heard-${tag}-hi`);
      await p.click('#glCheck'); await outcome(p);
      if (await p.$('#glTryAgain')) {
        clean(await audit(p, 'wrong1 ' + w), `drill, first miss ${w}`); await shot(p, `drill-wrong1-${tag}-hi`);
        await p.click('#glLangEn'); await sleep(100); clean(await audit(p, 'wrong1 en ' + w), `drill, first miss (English) ${w}`); await shot(p, `drill-wrong1-${tag}-en`); await p.click('#glLangHi');
        await p.click('#glTryAgain'); await typeCheck(p, it2.wrong);
        if (await p.$('#glTryAgain')) { clean(await audit(p, 'wrong2 ' + w), `drill, second miss ${w}`); await shot(p, `drill-wrong2-${tag}-hi`); await p.click('#glShow'); await p.waitForSelector('#glNext'); }
        clean(await audit(p, 'shown ' + w), `drill, answer shown ${w}`); await shot(p, `drill-answer-${tag}-hi`);
      }
      await clearSet(p);
      clean(await audit(p, 'summary ' + w), `summary ${w}`); await shot(p, `summary-${tag}-hi`);
      await p.click('#glLangEn'); await sleep(100); clean(await audit(p, 'summary en ' + w), `summary (English) ${w}`); await shot(p, `summary-${tag}-en`);
      await p.close(); await c.close();
    }

    T.section('M. console');
    T.ok('console: no page or script error in the whole run', L.ERRS.length === 0, L.ERRS.slice(0, 4).join(' | '));
  } finally { await browser.close(); }
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error(e); process.exit(2); });
