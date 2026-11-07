'use strict';
/*
 * Gemini keys that start with "AQ." (2026-11-07: "I add my Gemini key, tap Save and nothing happens").
 * Since 2026-05-28 Google AI Studio hands out ONLY keys that start with "AQ." (its "auth keys"). The first-run wizard refused every such key in the browser - it repainted the same red
 * line the paste had already drawn, so Save looked dead - and nothing ever reached the server. And Google answers a WRONG AQ. key with 400 "Invalid Auth key.", which the server read as
 * "couldn't reach Gemini". What is checked is read back from the SERVER (/keys/status and the fake provider's call log), never from the screen alone.
 *
 *   A  the wizard: an AQ. key is recognised as Gemini, Save sends it, the server stores it, the wizard moves on
 *   B  the wizard: a WRONG AQ. key is called a rejected key (not "couldn't reach") and the learner is told any two services will do
 *   C  the manage screen (More -> My AI keys): an AQ. key replaces a stored Gemini key; no false "short-lived" hint anywhere
 *   D  Hindi
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('keys: Gemini AQ. keys (real server)');
const { T, ERRS, TOK, sleep, until, ctxFor, behave, reset, calls, server, boot, screen, vis, txt, shot, openKeys, setLang } = L;

const AQ = tag => 'AQ.Ab8RN6' + tag + 'x'.repeat(40 - tag.length) + 'k9Zq';          // the shape of a real AI Studio key (53 characters)
const status = async who => (await server(who, '/keys/status')).body;
const det = p => txt(p, '#ksDet');
const sent = async key => (await calls({ provider: 'gemini', key })).n;              // requests the fake Google received WITH this key

async function fresh(browser, who, o = {}) {
  const c = await ctxFor(browser, who, Object.assign({ seed: { dusu_tutorial_seen: '1' } }, o));
  const p = await boot(c, o.path || '/', o);
  return { c, p };
}
async function wizard(p) {
  await until(() => p.evaluate(() => !!document.getElementById('ksWiz')), 10000);
  return vis(p, '#ksPaste');
}

(async () => {
  const browser = await chromium.launch();
  await reset({ key_health: 'on', keys_ui: 'on' });
  for (const who of ['fresh', 'nt1', 'cap']) await setLang(who, 'en');
  await setLang('wa2', 'hi');

  // =========================================================================================== A
  T.section('A - the wizard saves an AQ. Gemini key');
  {
    const who = 'fresh', k = AQ('FRESH');
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'en' });
    T.eq(await screen(p), 'keys', 'a learner with no keys is on the Keys screen');
    T.ok(await wizard(p), 'the first-run wizard is shown');
    await p.fill('#ksPaste', k);
    T.ok(await until(async () => /Gemini key recognised/.test(await det(p))), 'pasting an AQ. key says "Gemini key recognised"');
    T.ok(!/short-lived|stops working/i.test(await det(p)), '... and never calls it a short-lived token');
    await p.click('#ksSave');
    T.ok(await until(async () => (await sent(k)) > 0, 12000), 'Save SENDS the key: Google is asked about exactly this key');
    T.ok(await until(async () => /works and is saved/.test(await det(p)), 12000), 'the wizard says the Gemini key works and is saved');
    const st = await status(who);
    const g = (st.keys || []).find(x => x.provider === 'gemini');
    T.ok(!!g && g.status === 'ok', 'the server stores it as a working Gemini key');
    T.eq(g && g.masked, 'AQ.••••k9Zq', 'masked as AQ.••••<last four>');
    T.ok(await until(async () => /Key 2 of 2/.test(await txt(p, '#ksStep'))), 'the wizard moves on to "Key 2 of 2"');
    T.eq(await p.evaluate(() => document.getElementById('ksPaste').value), '', 'and the box is emptied');
    // the second key takes the learner in
    const gk = 'gsk_FRESHAQ' + 'A'.repeat(30) + 'q1w2';
    await p.fill('#ksPaste', gk); await p.click('#ksSave');
    T.ok(await until(async () => (await screen(p)) !== 'keys', 15000), 'Gemini (AQ.) + Groq take the learner into the app');
    await shot(p, 'gemini-aq-wizard');
    await c.close();
  }

  // =========================================================================================== B
  T.section('B - a wrong AQ. key is a rejected key, not "couldn\'t reach"');
  {
    const who = 'nt1', bad = AQ('WRONG');
    await behave('gemini', 'invalid_aq', bad);
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'en' });
    T.ok(await wizard(p), 'the first-run wizard is shown');
    await p.fill('#ksPaste', bad); await p.click('#ksSave');
    T.ok(await until(async () => (await sent(bad)) > 0, 12000), 'Save sends the key to Google');
    T.ok(await until(async () => /didn.t accept/.test(await det(p)), 12000), 'Google\'s "Invalid Auth key." is shown as "Gemini didn\'t accept that key"');
    T.ok(!/Couldn.t reach/.test(await det(p)), '... never as "Couldn\'t reach Gemini"');
    T.ok(/any two|Groq|OpenRouter/.test(await det(p)), '... and says another service will do (Gemini is not required)');
    T.eq((await status(who)).stored, 0, 'nothing was stored');
    T.ok(await vis(p, '#ksPaste'), 'the box stays open for another try');
    // the same box, the right key: it works
    const good = AQ('RIGHT');
    await p.fill('#ksPaste', good); await p.click('#ksSave');
    T.ok(await until(async () => /works and is saved/.test(await det(p)), 12000), 'the correct key right after is saved');
    await shot(p, 'gemini-aq-wrong');
    await c.close();
  }

  // =========================================================================================== C
  T.section('C - the manage screen takes an AQ. key');
  {
    const who = 'cap', k = AQ('CAPKEY');
    const { c, p } = await fresh(browser, who, { lang: 'en' });
    await openKeys(p);
    T.ok(!/short-lived|stops working/i.test(await txt(p, '#keysForm')), 'no false "short-lived token" hint on the Keys screen');
    await p.click('#kyb_gemini button:has-text("Change")');
    T.ok(await until(async () => /start with AQ\./.test(await txt(p, '#kyGemHint'))), 'Change opens the Gemini box, and its hint says new Gemini keys start with AQ.');
    T.ok(!/short-lived|stops working/i.test(await txt(p, '#keysForm')), '... and nothing calls an AQ. key short-lived');
    await p.fill('#kGemini', k); await p.click('#kySave_gemini');
    T.ok(await until(() => p.evaluate(() => /AQ\.••••k9Zq/.test(document.getElementById('kyb_gemini').textContent)), 12000), 'the AQ. key replaces the old one (shown masked)');
    T.eq(((await status(who)).keys || []).find(x => x.provider === 'gemini').masked, 'AQ.••••k9Zq', 'the server agrees');
    await c.close();
  }

  // =========================================================================================== D
  T.section('D - Hindi');
  {
    const who = 'wa2', k = AQ('HINDI');
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'hi' });
    T.ok(await wizard(p), 'the first-run wizard is shown');
    await p.fill('#ksPaste', k);
    T.ok(await until(async () => /Gemini/.test(await det(p)) && /पहचान/.test(await det(p))), 'Hindi: the AQ. key is recognised as Gemini');
    T.ok(!/थोड़े समय/.test(await det(p)), '... and never called a short-lived token');
    await p.click('#ksSave');
    T.ok(await until(async () => ((await status(who)).keys || []).some(x => x.provider === 'gemini'), 12000), 'Hindi: Save stores it');
    await c.close();
  }

  T.section('the whole run');
  T.eq(ERRS, [], 'no console error, page error or unhandled rejection in the whole run');
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED:', e); process.exit(2); });
