'use strict';
/*
 * Three more services a learner can add from the Keys screen (2026-11-17): Cloudflare Workers AI (TWO values: Account ID + API token, saved as ONE key), Z.ai (GLM Flash) and Sarvam.
 * A real Chromium against the real app (uvicorn + scratch MongoDB + the real key engine; every AI provider is a scripted fake - see run_real.sh). What is checked is read back from the
 * SERVER (/keys/status, /me, the fake providers' call log), never from the screen alone.
 *
 *   A  the first-run wizard: the first screen is as it was (Groq first, the same two other links), "More free options" is there and COLLAPSED; opened, three cards, each with a one-tap link
 *   B  Cloudflare: two boxes -> one key (the token is the only credential on the wire; no zero-quota probe; masked on the server); a missing half; a wrong token; the whole "id:token" pasted
 *   C  Z.ai and Sarvam: one box each; out of credit is said as such; a key pasted into the main box that no prefix recognises is picked from a list (no Cloudflare guess)
 *   D  two keys from the new services take the learner in (the count is per service)
 *   E  the manage screen (More -> My AI keys): the three blocks, masked values, "used today" + honest "how many are left", Test, Remove; Cloudflare's two boxes
 *   F  the pop-up and the Keys screen name them correctly (Cloudflare / Z.ai / Sarvam, their own avatars)
 *   G  Hindi (Devanagari + Latin everyday words) and English; no leftover English in the Hindi cards
 *   H  layout at 360 / 390 / 1280, tap targets, no horizontal overflow; an XSS canary in every box; no console error in the whole run
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('keys: Cloudflare / Z.ai / Sarvam (real server)');
const { T, ERRS, TOK, sleep, until, ctxFor, behave, reset, calls, server, boot, screen, vis, txt, shot, openKeys, setLang } = L;

const ACCT = tag => require('crypto').createHash('md5').update('acct' + tag).digest('hex');                  // a distinct 32-hex account id per scenario
const CFTOK = tag => 'cft' + tag + 'C'.repeat(30 - tag.length) + 'xCq9';
const ZKEY = tag => require('crypto').createHash('md5').update('z' + tag).digest('hex') + '.' + ('Z' + tag).repeat(3) + 'QzXy';
const SKEY = tag => 'sk_' + tag + 'S'.repeat(30 - tag.length) + 'xSq9';
const status = async who => (await server(who, '/keys/status')).body;
const got = (st, p) => ((st && st.keys) || []).find(k => k.provider === p);
const det = (p, id = '#ksDet') => txt(p, id);
const sent = async (provider, key) => (await calls({ provider, key })).n;
const sentKind = async (provider, key, kind) => (await calls({ provider, key, kind })).n;

async function fresh(browser, who, o = {}) {
  const c = await ctxFor(browser, who, Object.assign({ seed: { dusu_tutorial_seen: '1' } }, o));
  const p = await boot(c, o.path || '/', o);
  return { c, p };
}
async function wizard(p) { await until(() => p.evaluate(() => !!document.getElementById('ksWiz')), 10000); return vis(p, '#ksPaste'); }
// a card inside a CLOSED <details> has layout boxes but is not rendered: checkVisibility() (Chromium 105+) is the truth, getBoundingClientRect is not
const rendered = (p, sel) => p.evaluate(s => { const e = document.querySelector(s); return !!e && e.checkVisibility({ checkVisibilityCSS: true, contentVisibilityAuto: true }); }, sel);
const openMore = async p => { await p.click('#ksMoreSum'); await until(() => rendered(p, '#ksSvc_cloudflare')); };
const boxes = p => p.evaluate(() => ['ksCfAcct', 'ksCfTok', 'ksIn_zai', 'ksIn_sarvam', 'ksPaste', 'kCfAcct', 'kCloudflare', 'kZai', 'kSarvam'].map(i => (document.getElementById(i) || {}).value || '').join('|'));

(async () => {
  const browser = await chromium.launch();
  await reset({ key_health: 'on', keys_ui: 'on', install_mode: 'on', bilingual: 'on' });
  for (const who of ['new', 'fresh', 'nt1', 'zero', 'inst1', 'inst2', 'owner']) await setLang(who, 'en');
  await setLang('wa2', 'hi'); await setLang('wa3', 'en');

  // =========================================================================================== A  the first screen is as it was; "More free options" is collapsed
  T.section('A - the first-run wizard keeps its first screen; the new services are behind a collapsed "More free options"');
  {
    const { c, p } = await fresh(browser, 'new', { device: 'new', lang: 'en' });
    T.ok(await wizard(p), 'a learner with no keys sees the first-run wizard');
    T.has(await txt(p, '#ksGet'), 'Get free key from Groq', 'the ONE big button still says Groq first');
    T.eq(await p.evaluate(() => document.getElementById('ksGet').href), 'https://console.groq.com/keys', '... and goes to Groq');
    const ors = await p.evaluate(() => [...document.querySelectorAll('#ksOr a')].map(a => a.textContent.trim() + ' ' + a.href));
    T.eq(ors, ['Gemini ↗ https://aistudio.google.com/apikey', 'OpenRouter ↗ https://openrouter.ai/keys'], 'the "Or use" links are still just Gemini and OpenRouter (the new services are not promoted on the first screen)');
    T.has(await txt(p, '#ksStep'), 'Key 1 of 2', 'still "Key 1 of 2" - two keys to start');
    T.ok(await vis(p, '#ksMore') && await vis(p, '#ksMoreSum'), '"More free options" is on the first screen ...');
    T.eq(await p.evaluate(() => document.getElementById('ksMore').open), false, '... COLLAPSED');
    T.eq([await rendered(p, '#ksSvc_cloudflare'), await rendered(p, '#ksSvc_zai'), await rendered(p, '#ksSvc_sarvam')], [false, false, false], 'while it is closed none of the three cards is drawn');
    T.has(await txt(p, '#ksMoreSum'), 'More free options', 'its summary says so');
    await shot(p, 'providers-wizard-closed');
    await openMore(p);
    const links = await p.evaluate(() => ['cloudflare', 'zai', 'sarvam'].map(x => { const a = document.getElementById('ksSvcGet_' + x); return [a.getAttribute('href'), a.target, a.rel, a.textContent.trim()]; }));
    T.eq(links, [['https://dash.cloudflare.com/?to=/:account/ai/workers-ai', '_blank', 'noopener noreferrer', 'Get free key ↗'], ['https://z.ai/manage-apikey/apikey-list', '_blank', 'noopener noreferrer', 'Get free key ↗'],
                 ['https://indus.sarvam.ai/key-management', '_blank', 'noopener noreferrer', 'Get free key ↗']], 'opened: three cards, each with a one-tap "Get free key" link to the provider\'s own key page (a new tab)');
    T.eq(await p.evaluate(() => ['cloudflare', 'zai', 'sarvam'].map(x => document.querySelector('#ksSvc_' + x + ' .ks-svc-h b').textContent)), ['Cloudflare Workers AI', 'Z.ai (GLM Flash)', 'Sarvam'], 'named properly');
    const d = await p.evaluate(() => ['cloudflare', 'zai', 'sarvam'].map(x => document.getElementById('ksSvcD_' + x).textContent));
    T.ok(/Account ID/.test(d[0]) && /doesn.t train on your chats/.test(d[0]) && /10,000 neurons/.test(d[0]), 'Cloudflare: says it needs two things, the free daily amount, and that it does not train on chats (its own data-usage page)');
    T.ok(/Singapore/.test(d[1]) && /unclear/.test(d[1]), 'Z.ai: says honestly - data processed mainly in Singapore, training terms unclear');
    T.ok(/₹100/.test(d[2]) && /one time/.test(d[2]) && /then paid/.test(d[2]), 'Sarvam: says honestly - ₹100 once, then paid');
    T.eq(await p.evaluate(() => [document.querySelectorAll('#ksCfAcct').length, document.querySelectorAll('#ksCfTok').length, document.querySelectorAll('#ksIn_zai').length, document.querySelectorAll('#ksIn_sarvam').length]), [1, 1, 1, 1], 'Cloudflare has TWO boxes, the others one each');
    await shot(p, 'providers-wizard-open');
    // the existing three still work the way they did: a Groq key is recognised by its prefix
    await p.fill('#ksPaste', 'gsk_' + 'Q'.repeat(40));
    T.ok(await until(async () => /Groq key recognised/.test(await det(p))), 'a Groq key is still recognised by its prefix (nothing about the first flow changed)');
    await p.fill('#ksPaste', '');
    // an unrecognised key: pick from a list - Cloudflare is never offered (it needs two values), the other four are
    await p.fill('#ksPaste', 'unknownkey-without-any-known-prefix-1234'); await p.click('#ksSave');
    T.ok(await until(() => vis(p, '#ksPick')), 'a key no prefix recognises asks which service it is from');
    T.eq(await p.evaluate(() => [...document.querySelectorAll('#ksPick button')].map(b => b.textContent)), ['This is a Groq key', 'This is a Gemini key', 'This is a OpenRouter key', 'This is a Z.ai key', 'This is a Sarvam key'],
      '... offering Groq, Gemini, OpenRouter, Z.ai and Sarvam - never Cloudflare (two values: guessing would be wrong)');
    T.eq((await status('new')).stored, 0, 'nothing was sent or stored yet');
    await c.close();
  }

  // =========================================================================================== B  Cloudflare: two boxes, one key
  T.section('B - Cloudflare: two boxes become ONE key');
  {
    const who = 'fresh', acct = ACCT('fresh'), tok = CFTOK('fresh'), comp = acct + ':' + tok;
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'en' });
    await wizard(p); await openMore(p);
    // a missing half
    await p.fill('#ksCfTok', tok); await p.click('#ksSvcSave_cloudflare');
    T.ok(await until(async () => /both the Account ID and the API token/.test(await txt(p, '#ksM_cloudflare'))), 'only the token filled: "Paste both the Account ID and the API token." - and no request leaves');
    T.eq((await calls({ provider: 'cloudflare' })).n, 0, '... the fake Cloudflare was asked nothing');
    // a wrong token
    const badTok = CFTOK('wrong');
    await behave('cloudflare', 'invalid', badTok);
    await p.fill('#ksCfAcct', acct); await p.fill('#ksCfTok', badTok); await p.click('#ksSvcSave_cloudflare');
    T.ok(await until(async () => /Cloudflare didn.t accept that/.test(await txt(p, '#ksM_cloudflare')), 12000), 'a wrong token: "Cloudflare didn\'t accept that. Check the Account ID and the token (the token needs the Workers AI permission)."');
    T.eq((await status(who)).stored, 0, '... and nothing is stored');
    T.eq(await sent('cloudflare', badTok), 1, '... one request was made (the real check - there is no zero-quota probe)');
    // the right pair
    await p.fill('#ksCfTok', tok); await p.click('#ksSvcSave_cloudflare');
    T.ok(await until(async () => /works and is saved/.test(await txt(p, '#ksM_cloudflare')), 12000), 'the right pair: "Cloudflare works and is saved."');
    const st = await status(who), k = got(st, 'cloudflare');
    T.ok(!!k && k.status === 'ok', 'the SERVER holds one working Cloudflare key');
    T.eq(k && k.masked, `acct ••••${acct.slice(-4)} · token ••••${tok.slice(-4)}`, 'masked: the last four of each value - never the account id in full, never the token');
    T.eq(st.stored, 1, 'ONE key toward the two needed - two values do not count twice');
    T.eq(await sent('cloudflare', tok), 1, 'the token alone is the credential on the wire: ONE request for this pair (the one real call - no probe)');
    T.eq(await sent('cloudflare', comp), 0, '... the stored "account:token" string is never sent as a credential');
    T.eq(await sentKind('cloudflare', tok, 'models') + await sentKind('cloudflare', tok, 'key'), 0, '... and no zero-quota "models" / "key" request exists for it');
    T.ok(await until(async () => /Key 2 of 2/.test(await txt(p, '#ksStep'))), 'the wizard moves on to "Key 2 of 2"');
    T.eq((await boxes(p)).split('|').slice(0, 4).join('|'), '|||', 'the boxes are emptied after a save');
    const html = await p.evaluate(() => document.documentElement.outerHTML);
    T.ok(!html.includes(acct) && !html.includes(tok.slice(6, -6)), 'neither the account id nor the token is anywhere in the page afterwards');
    await shot(p, 'providers-cloudflare-saved');
    await c.close();
  }
  {
    // the whole "account:token" pasted into the ONE main box
    const who = 'nt1', acct = ACCT('nt1'), tok = CFTOK('nt1');
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'en' });
    await wizard(p);
    await p.fill('#ksPaste', acct + ':' + tok);
    T.ok(await until(async () => /Cloudflare key recognised/.test(await det(p))), 'the whole "account:token" pasted into the main box is recognised as a Cloudflare key');
    await p.click('#ksSave');
    T.ok(await until(async () => !!got(await status(who), 'cloudflare'), 12000), '... and Save stores it as one Cloudflare key');
    T.eq(await sent('cloudflare', tok), 1, '... with the token alone as the credential');
    await c.close();
  }

  // =========================================================================================== C  Z.ai and Sarvam
  T.section('C - Z.ai and Sarvam: one box each; out of credit is said as such');
  {
    const who = 'zero', zk = ZKEY('zero'), sk = SKEY('zero');
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'en' });
    await wizard(p); await openMore(p);
    await p.fill('#ksIn_zai', zk); await p.click('#ksSvcSave_zai');
    T.ok(await until(async () => /Z\.ai works and is saved/.test(await txt(p, '#ksM_zai')), 12000), 'Z.ai: "Z.ai works and is saved."');
    const z = got(await status(who), 'zai');
    T.ok(!!z && z.status === 'ok' && z.masked.endsWith('QzXy') && !z.masked.includes(zk.slice(6, -6)), 'the server holds it, masked');
    T.eq(await sent('zai', zk), 1, 'one real call');
    // out of credit
    await behave('sarvam', 'credit', sk);
    await p.fill('#ksIn_sarvam', sk); await p.click('#ksSvcSave_sarvam');
    T.ok(await until(async () => /no credit left/.test(await txt(p, '#ksM_sarvam')), 12000), 'Sarvam with no credit: "Sarvam says that key has no credit left. Add credit there, or use another service." (not "couldn\'t reach")');
    T.eq(got(await status(who), 'sarvam'), undefined, '... and it is not stored');
    await behave('sarvam', 'ok', sk);
    await p.click('#ksSvcSave_sarvam');
    T.ok(await until(async () => /Sarvam works and is saved/.test(await txt(p, '#ksM_sarvam')), 12000), 'with credit, the same box saves it');
    // two services = set up: the learner is taken in
    T.ok(await until(async () => (await screen(p)) !== 'keys', 15000), 'Z.ai + Sarvam (two services, neither of the original three) take the learner into the app');
    T.eq((await server(who, '/me')).body.has_keys, true, '/me says has_keys');
    await c.close();
  }
  {
    // a Z.ai key pasted into the main box (no prefix to recognise) is picked from the list
    const who = 'inst1', zk = ZKEY('inst1');
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'en' });
    await wizard(p);
    await p.fill('#ksPaste', zk); await p.click('#ksSave');
    T.ok(await until(() => vis(p, '#ksPick')), 'a Z.ai-shaped key in the main box: "I can\'t tell which service this key is from. Pick one:"');
    await p.click('#ksPick button:has-text("Z.ai")');
    T.ok(await until(async () => !!got(await status(who), 'zai'), 12000), 'picking Z.ai saves it as a Z.ai key');
    await c.close();
  }

  // =========================================================================================== E  the manage screen
  T.section('E - the manage screen (More -> My AI keys)');
  {
    const who = 'two';
    const acct = ACCT('two'), tok = CFTOK('two'), comp = acct + ':' + tok;
    const { c, p } = await fresh(browser, who, { lang: 'en' });
    await openKeys(p);
    T.ok(await vis(p, '#kyMoreSum') && /More free options/.test(await txt(p, '#kyMoreSum')), 'a learner with Groq + Gemini sees "More free options" under their keys');
    T.eq(await p.evaluate(() => document.getElementById('kyMore').open), false, '... collapsed (nothing of the new services in the way)');
    await p.click('#kyMoreSum');
    T.ok(await until(() => vis(p, '#kCfAcct')), 'opened: the Cloudflare block with TWO boxes (Account ID, API token)');
    T.ok(await vis(p, '#kCloudflare') && await vis(p, '#kZai') && await vis(p, '#kSarvam'), '... and the Z.ai and Sarvam boxes');
    T.eq(await p.evaluate(() => [...document.querySelectorAll('#kyMore .keyblk-get')].map(a => a.getAttribute('href'))), ['https://dash.cloudflare.com/?to=/:account/ai/workers-ai', 'https://z.ai/manage-apikey/apikey-list', 'https://indus.sarvam.ai/key-management'], 'each block has its own "Get free key" link');
    // save Cloudflare from the manage screen
    await p.fill('#kCfAcct', acct); await p.fill('#kCloudflare', tok); await p.click('#kySave_cloudflare');
    T.ok(await until(() => p.evaluate(() => /acct ••••/.test(document.getElementById('kyb_cloudflare').textContent)), 12000), 'Cloudflare saved from the manage screen: shown masked');
    const blk = await txt(p, '#kyb_cloudflare');
    T.ok(blk.includes(`acct ••••${acct.slice(-4)}`) && blk.includes(`token ••••${tok.slice(-4)}`) && !blk.includes(acct) && !blk.includes(tok), 'masked as "acct ••••<last 4> · token ••••<last 4>": the account id is never shown in full');
    T.ok(/Working/.test(blk) && /1 request today/.test(blk), '... status Working, "1 request today" (the check call)');
    T.ok(/10,000 neurons a day but doesn.t show how many are left/.test(blk), '... and honestly says Cloudflare does not show how many neurons are left');
    T.eq(await p.evaluate(() => { const a = document.getElementById('kCfAcct'), t = document.getElementById('kCloudflare'); return [a.closest('.keyrow').hidden, t.closest('.keyrow').hidden, a.value, t.value]; }), [true, true, '', ''], 'the two boxes are hidden and empty once a key is saved (nothing of it stays in a hidden box)');
    T.eq(got(await status(who), 'cloudflare').masked, `acct ••••${acct.slice(-4)} · token ••••${tok.slice(-4)}`, 'the server agrees');
    // Test
    await p.click('#kyb_cloudflare button:has-text("Test")');
    T.ok(await until(async () => /Cloudflare works/.test(await txt(p, '#kym_cloudflare')), 12000), 'Test: "Cloudflare works."');
    T.eq(await sentKind('cloudflare', tok, 'chat'), 2, '... one more real call (save + Test = 2): there is no cheaper check');
    // Change opens BOTH boxes
    await p.click('#kyb_cloudflare button:has-text("Change")');
    T.ok(await vis(p, '#kCfAcct') && await vis(p, '#kCloudflare'), 'Change opens both boxes');
    await p.click('#kyCancel_cloudflare');
    T.ok(!(await vis(p, '#kCfAcct')) && await vis(p, '#kyb_cloudflare'), 'Cancel goes back to the saved view');
    // Z.ai + the "how many are left" line
    const zk = ZKEY('two');
    await p.fill('#kZai', zk); await p.click('#kySave_zai');
    T.ok(await until(() => p.evaluate(() => /Working/.test(document.getElementById('kyb_zai').textContent)), 12000), 'Z.ai saved from the manage screen');
    T.ok(/Z\.ai doesn.t show how many are left/.test(await txt(p, '#kyb_zai')), '... with the honest "doesn\'t show how many are left" line');
    // Remove
    await p.click('#kyb_zai button:has-text("Remove")');
    T.ok(await until(async () => !got(await status(who), 'zai'), 12000), 'Remove: gone from the server');
    T.ok(await until(() => vis(p, '#kZai')), '... and its box is open again');
    // the page never holds a key
    const html = await p.evaluate(() => document.documentElement.outerHTML);
    T.ok(!html.includes(acct) && !html.includes(tok.slice(6, -6)) && !html.includes(zk.slice(6, -6)), 'no account id, token or key anywhere in the page');
    T.eq(await sent('cloudflare', comp), 0, 'the composite string was never used as a credential');
    await shot(p, 'providers-manage');
    await c.close();
    // a learner who already holds one of the new services finds it without hunting: the section opens by itself
    const r = await server('ph', '/keys/save', 'POST', { provider: 'sarvam', key: SKEY('ph') });
    T.eq(r.body && r.body.ok, true, '(setup) a learner with Groq + Gemini + Sarvam');
    const n = await fresh(browser, 'ph', { lang: 'en' });
    await openKeys(n.p);
    T.eq(await n.p.evaluate(() => document.getElementById('kyMore').open), true, 'a learner who already uses Sarvam finds "More free options" OPEN, with their key in it');
    T.ok(/Working/.test(await txt(n.p, '#kyb_sarvam')) && /one-time gift/.test(await txt(n.p, '#kyb_sarvam')), '... Sarvam shown as Working, with the honest one-time-credit line');
    await n.c.close();
  }

  // =========================================================================================== D  two new services take the learner in (the count is per service)
  T.section('D - the count of keys is per service');
  {
    const who = 'inst2', acct = ACCT('inst2'), tok = CFTOK('inst2');
    const { c, p } = await fresh(browser, who, { device: 'new', lang: 'en' });
    await wizard(p); await openMore(p);
    await p.fill('#ksCfAcct', acct); await p.fill('#ksCfTok', tok); await p.click('#ksSvcSave_cloudflare');
    await until(async () => !!got(await status(who), 'cloudflare'), 12000);
    await sleep(900);
    T.eq(await screen(p), 'keys', 'ONE Cloudflare key (two values) is not enough: still on the Keys screen');
    T.eq(await p.evaluate(() => document.getElementById('ksStep').textContent), 'Key 2 of 2', '... "Key 2 of 2"');
    T.eq((await server(who, '/me')).body.has_keys, false, '/me: not set up yet');
    const gk = 'gsk_INST2' + 'A'.repeat(30) + 'q1w2';
    await p.fill('#ksPaste', gk); await p.click('#ksSave');
    T.ok(await until(async () => (await screen(p)) !== 'keys', 15000), 'Cloudflare + Groq: the second key takes the learner in');
    await c.close();
  }

  // =========================================================================================== F  the pop-up and the card name them
  T.section('F - the key pop-up and the card name them correctly');
  {
    const who = 'wa3';
    const acct = ACCT('wa3'), tok = CFTOK('wa3'), zk = ZKEY('wa3');
    await server(who, '/keys/save', 'POST', { provider: 'cloudflare', key: acct + ':' + tok });
    await server(who, '/keys/save', 'POST', { provider: 'zai', key: zk });
    T.eq((await status(who)).stored, 2, '(setup) the learner holds a Cloudflare key and a Z.ai key');
    await behave('cloudflare', 'limited', tok); await behave('zai', 'limited', zk);
    await server(who, '/lesson/evaluate', 'POST', { token: TOK[who].token, lang: 'en', type: 'speak', prompt: 'p', target: 't', said: 's' });     // the server learns both keys are at their limits
    T.eq((await status(who)).state, 'all_limited', '(setup) the server now knows both are at their limits');
    const { c, p } = await fresh(browser, who, { lang: 'en', settle: 1500 });
    const open = await until(() => vis(p, '#kySheet.on'), 12000);
    T.ok(open, 'both services at their limit: the key pop-up opens on Home');
    const rows = await p.evaluate(() => [...document.querySelectorAll('#kySheet .ky-k')].map(li => [li.querySelector('b').textContent, li.querySelector('.ky-chip').textContent, li.querySelector('.ky-av').className]));
    T.eq(rows.map(r => r[0]), ['Cloudflare', 'Z.ai'], 'the pop-up names them: Cloudflare and Z.ai');
    T.ok(rows[0][2].includes('ky-av-cloudflare') && rows[1][2].includes('ky-av-zai'), '... each with its own avatar class');
    T.ok(/Daily limit reached/.test(rows[0][1]), 'Cloudflare\'s 3036 reads as the DAILY limit');
    await shot(p, 'providers-popup');
    await c.close();
    await behave('cloudflare', 'ok', tok); await behave('zai', 'ok', zk);
  }

  // =========================================================================================== G  Hindi
  T.section('G - Hindi');
  {
    const { c, p } = await fresh(browser, 'wa2', { device: 'new', lang: 'hi' });
    await wizard(p);
    T.has(await txt(p, '#ksMoreSum'), 'और free options', 'Hindi summary: "और free options"');
    await openMore(p);
    const t = await p.evaluate(() => ({ p: document.getElementById('ksMoreP').textContent, cf: document.getElementById('ksSvcD_cloudflare').textContent, z: document.getElementById('ksSvcD_zai').textContent, s: document.getElementById('ksSvcD_sarvam').textContent,
      ph: [document.getElementById('ksCfAcct').placeholder, document.getElementById('ksCfTok').placeholder, document.getElementById('ksIn_zai').placeholder], btn: document.getElementById('ksSvcSave_zai').textContent, link: document.getElementById('ksSvcGet_zai').textContent }));
    T.ok(/[ऀ-ॿ]/.test(t.p) && /[ऀ-ॿ]/.test(t.cf) && /[ऀ-ॿ]/.test(t.z) && /[ऀ-ॿ]/.test(t.s), 'every card is in Hindi (Devanagari + everyday English words in Latin)');
    T.ok(/Account ID/.test(t.cf) && /Singapore/.test(t.z) && /₹100/.test(t.s), '... with the facts intact (Account ID, Singapore, ₹100)');
    T.ok(!/\b(aap|aapko|आप)\b/.test(t.cf + t.z + t.s) && !/तू\b/.test(t.cf + t.z + t.s), '... तुम style: no आप, no तू');
    T.ok(/[ऀ-ॿ]/.test(t.ph[0]) && /paste/i.test(t.ph[2]) && /[ऀ-ॿ]/.test(t.btn) && /[ऀ-ॿ]/.test(t.link), '... placeholders, the Save button and the link are in Hindi too');
    await p.fill('#ksIn_zai', ZKEY('wa2')); await p.click('#ksSvcSave_zai');
    T.ok(await until(async () => /चल रही है और सेव हो गई/.test(await txt(p, '#ksM_zai')), 12000), 'Hindi: saving Z.ai says "Z.ai चल रही है और सेव हो गई।"');
    await shot(p, 'providers-hindi');
    await p.fill('#ksCfAcct', 'tooshort'); await p.fill('#ksCfTok', 'x'.repeat(20)); await p.click('#ksSvcSave_cloudflare');
    T.ok(await until(async () => /Account ID देखो|दोनों paste करो|Cloudflare ने ये नहीं माना/.test(await txt(p, '#ksM_cloudflare')), 12000), 'Hindi: a malformed Cloudflare pair gets a Hindi message (422 key_shape)');
    await c.close();
  }

  // =========================================================================================== H  layout, targets, XSS
  T.section('H - layout at 360 / 390 / 1280, tap targets, an XSS canary');
  for (const [w, h] of [[360, 740], [390, 844], [1280, 800]]) {
    const { c, p } = await fresh(browser, 'new', { device: 'new', lang: 'en', viewport: { width: w, height: h } });
    await wizard(p); await openMore(p);
    const m = await p.evaluate(() => {
      const de = document.documentElement; const out = { over: de.scrollWidth > de.clientWidth + 1, small: [] };
      for (const sel of ['#ksMoreSum', '#ksSvcGet_cloudflare', '#ksSvcGet_zai', '#ksSvcGet_sarvam', '#ksCfAcct', '#ksCfTok', '#ksIn_zai', '#ksIn_sarvam', '#ksSvcSave_cloudflare', '#ksSvcSave_zai', '#ksSvcSave_sarvam']) {
        const e = document.querySelector(sel); if(!e) { out.small.push(sel + ' missing'); continue; } const r = e.getBoundingClientRect(); if (r.height < 44 || r.width < 44) out.small.push(sel + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)); }
      const wiz = document.getElementById('ksWiz').getBoundingClientRect(); out.wizRight = Math.round(wiz.right); out.vw = de.clientWidth;
      out.clipped = [...document.querySelectorAll('#ksSvc_cloudflare, #ksSvc_zai, #ksSvc_sarvam')].filter(e => e.getBoundingClientRect().right > de.clientWidth + 1).length;
      return out;
    });
    T.eq([m.over, m.small, m.clipped], [false, [], 0], `${w}px: no horizontal scroll, every control in "More free options" is at least 44 x 44, no card is clipped`);
    if (w === 360) await shot(p, 'providers-360');
    if (w === 1280) await shot(p, 'providers-1280');
    await c.close();
  }
  {
    const { c, p } = await fresh(browser, 'plain', { lang: 'en', device: 'returning' });
    await p.evaluate(() => { window.__xss = 0; });
    await openKeys(p);
    await p.click('#kyMoreSum');
    const canary = '<svg/onload=window.__xss=1>';
    const img = '"><img src=x onerror=window.__xss=2>';
    await p.fill('#kCfAcct', img); await p.fill('#kCloudflare', canary); await p.click('#kySave_cloudflare');
    await sleep(900);
    await p.fill('#kZai', canary); await p.click('#kySave_zai');
    await until(async () => /Working|didn.t|Couldn/.test(await txt(p, '#kyb_zai')) || got(await status('plain'), 'zai'), 8000);
    await p.fill('#kSarvam', canary + 'x'); await p.click('#kySave_sarvam');
    await sleep(1200);
    const x = await p.evaluate(() => ({ xss: window.__xss, injected: document.querySelectorAll('#keys svg[onload], #keys img[onerror], #keys img[src="x"]').length }));
    T.eq([x.xss, x.injected, p.__dialogs.length], [0, 0, 0], 'markup typed into every new box (and shown back as a masked value) runs nothing and injects nothing');
    const zz = got(await status('plain'), 'zai');
    T.ok(!zz || (!zz.masked.includes('<svg') && zz.masked.length <= 12), 'a stored value is masked to its first three and last four characters at most');
    await c.close();
  }

  T.section('the whole run');
  T.eq(ERRS, [], 'no console error, page error or unhandled rejection in the whole run');
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED:', e); process.exit(2); });
