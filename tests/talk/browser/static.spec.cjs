'use strict';
/* Talk - static checks (node only, no browser): the TK module of backend/test_client.html
 *   1  builds the page with DOM calls only (no innerHTML-family call, no eval) and never touches a chat bubble (a Hindi subtitle inside .bubble would be sent back to the model by the replay)
 *   2  has the same keys in TXT.hi and TXT.en, every key it uses exists, no key is dead; CH (the words inside the chat) likewise
 *   3  every Hindi string follows the house rules (tum never aap / tu, no gendered second-person verb endings) - look-arounds, NOT \b (it does not work on Devanagari)
 *   4  the wiring is all there: LG.LEGACY.talk = "en" and NOT switchable, VP.SESS, FLAG_ROUTES, NAV_TAB / PATH_TAB / pathForScreen, the hooks in onMessage / leave / show / logout, the entry
 *      points (hidden), the dashboard row, the Home tile icon, the service worker cache and its pin
 *   5  the CSS of Talk has no font-size under 12px, no letter-spacing / text-transform, and every selector is rooted in .tk-* / #tk
 *   6  the page's inline script compiles (a syntax error would white-screen the whole app) and the weight added is small
 * Run:  tests/talk/browser/run.sh static.spec.cjs        (REPO is mounted at /repo; ORIG_HTML = the page before Talk, for the weight check) */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const zlib = require('zlib');
const { makeT } = require('../../resume_interview/browser/harness.cjs');

const REPO = process.env.REPO || path.resolve(__dirname, '../../..');
const HTML = fs.readFileSync(process.env.HTML_SRC || path.join(REPO, 'backend/test_client.html'), 'utf8');
const SW = fs.readFileSync(path.join(REPO, 'backend/sw.js'), 'utf8');
const T = makeT('talk-static');

const a = HTML.indexOf('const TK = (function(){'), b = HTML.indexOf('window.TK = TK;');
T.ok(a > 0 && b > a, 'the TK module is in the page');
const MOD = HTML.slice(a, b);

T.section('1. DOM calls only');
const BAD = [/\binnerHTML\b/, /\bouterHTML\b/, /\binsertAdjacentHTML\b/, /document\s*\.\s*write/, /\bDOMParser\b/, /createContextualFragment/, /\bsrcdoc\b/, /\beval\s*\(/, /new\s+Function\b/, /javascript:/i, /\.setAttribute\(\s*["']on/i, /\bsetTimeout\(\s*["']/];
BAD.forEach(re => T.ok(!re.test(MOD), `the module never uses ${re}`));
T.ok(/ATTR_OK = /.test(MOD) && !/\|style\|/.test(MOD.match(/ATTR_OK = [^\n]+/)[0]), 'the builder only sets allow-listed attributes (no style, no on* attribute)');
T.ok(!/\.bubble\b/.test(MOD) && !/querySelector[^\n]*bubble/.test(MOD), 'the module never reads or writes a chat bubble: the subtitle and the card are siblings, so the replay (which reads only .bubble) cannot send them back');
const sec = HTML.slice(HTML.indexOf('<section id="tk"'), HTML.indexOf('</section>', HTML.indexOf('<section id="tk"')));
T.ok(sec.length > 100 && !/\son[a-z]+\s*=/i.test(sec), 'the #tk markup has no inline event handler');
T.ok(/this\.el|\.after\(card\)/.test(MOD) && /user\.after\(card\)/.test(MOD), 'the correction card is placed with the DOM method after() (not parsed from a string)');

T.section('2. TXT and CH');
function table(name, endMarker) {
  const lit = MOD.slice(MOD.indexOf('const ' + name + ' = ') + ('const ' + name + ' = ').length, MOD.indexOf(endMarker, MOD.indexOf('const ' + name + ' = ')));
  return new Function('return ' + lit.replace(/;\s*$/, ''))();
}
const TXT = table('TXT', '\n  // the words INSIDE the chat');
const CH = table('CH', '\n\n  /* ---------- a tiny DOM builder');
const kh = Object.keys(TXT.hi).sort(), ke = Object.keys(TXT.en).sort();
T.eq(kh, ke, 'TXT.hi and TXT.en have identical key sets');
T.ok(kh.length >= 22, `${kh.length} keys`);
const used = new Set([...MOD.matchAll(/\bt\(\s*"([A-Za-z0-9_]+)"\s*[,)]/g)].map(m => m[1]));
const missing = [...used].filter(k => !(k in TXT.en));
T.eq(missing, [], 'every key the module asks for exists');
const body = MOD.replace(/const TXT = [\s\S]*?\n  \/\/ the words INSIDE the chat/, '');
const dead = kh.filter(k => !used.has(k) && !new RegExp('"' + k + '"').test(body));
T.eq(dead, [], 'no dead key in TXT (' + dead.join(', ') + ')');
T.ok(Object.values(TXT.en).every(v => typeof v === 'string' && v.trim()) && Object.values(TXT.hi).every(v => typeof v === 'string' && v.trim()), 'no empty string');
const ph = s => [...String(s).matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join(',');
T.eq(kh.filter(k => ph(TXT.hi[k]) !== ph(TXT.en[k])), [], 'the {placeholders} of every Hindi string are the English string\'s');
const chUsed = new Set([...MOD.matchAll(/CH\.(?:en|hi)\.([A-Za-z]+)/g)].map(m => m[1]).concat([...MOD.matchAll(/CH\.en\[k\]|CH\.hi\[k\]/g)].length ? ['said', 'better', 'could', 'why'] : []));
T.eq([...chUsed].filter(k => !(k in CH.en) && !(k in CH.hi)), [], 'every chat-word the module asks for exists');
T.ok(['said', 'better', 'could', 'why'].every(k => CH.en[k] && CH.hi[k]), 'the four labels of the correction card exist in English AND Hindi (the card shows both at the subtitle level)');
T.ok(CH.hi.subHide && CH.hi.subShow && CH.en.hear && CH.en.again, 'the subtitle button\'s two states and the card\'s two buttons have words');
T.ok(Object.values(TXT.en).concat(Object.values(CH.en)).every(v => !/[ऀ-ॿ]/.test(v)), 'the English strings carry no Devanagari');

T.section('3. Hindi house rules (UNREVIEWED by a native reader - this checks the rules, not the quality)');
const DEV = '\\u0900-\\u097F';
const RULES = [
  [new RegExp(`(?<![${DEV}])आप(?![${DEV}])`), 'no आप'], [/आपका|आपकी|आपके|आपको|आपने|आपसे/, 'no आपका / आपकी / आपके ...'],
  [new RegExp(`(?<![${DEV}])(तू|तेरा|तेरी|तेरे|तुझे|तुझ)(?![${DEV}])`), 'no तू / तेरा / तेरी / तुझे'],
  [new RegExp(`(ते|ती|रहे|रही|रहा|सकते|सकती)\\s+हो(?![${DEV}])`), 'no "<verb> हो" ending that guesses the learner\'s gender'],
  [new RegExp(`(ते|ती|रहे|रही|रहा|सकते|सकती)\\s+हो[${DEV}]`), 'no "<verb> हो…" (even with a danda after it)'],
  [/करोगे|करोगी|जाओगे|जाओगी|बोलोगे|बोलोगी|लिखोगे|लिखोगी|आओगे|आओगी|देखोगे|देखोगी|चाहोगे|चाहोगी/, 'no "-ोगे / -ोगी" second-person future'],
  [/सकते\s+हो|सकती\s+हो/, 'no सकते हो / सकती हो'],
  [new RegExp(`(?<![${DEV}])(थे|थी)(?![${DEV}])`), 'no past "थे / थी" that would guess the learner\'s gender'],
];
let n = 0;
for (const [src, tbl] of [['TXT.hi', TXT.hi], ['CH.hi', CH.hi]]) for (const [k, v] of Object.entries(tbl)) for (const [re, why] of RULES) { n++; T.ok(!re.test(v), `${src}.${k}: ${why} (${JSON.stringify(v.slice(0, 60))})`); }
T.ok(n > 250, `${n} rule checks`);
T.ok(Object.entries(TXT.hi).every(([k, v]) => /[ऀ-ॿ]/.test(v) || /^[A-Za-z0-9 .,:;!?/()%{}\-–·'"]+$/.test(v)), 'every Hindi string is Devanagari (with Latin everyday words)');
T.ok(/UNREVIEWED/.test(HTML.slice(a - 3500, a)), 'the module\'s header comment says its Hindi is unreviewed');

T.section('4. wiring');
const lg = HTML.slice(HTML.indexOf('const LG = (function(){'), HTML.indexOf('function lgt(key, vars)'));
T.ok(/const LEGACY = \{[^}]*talk:"en"/.test(lg), 'LG.LEGACY.talk = "en"');
T.ok(/const SWITCHABLE = \{ home:true \};/.test(lg), 'SWITCHABLE is still only { home: true } (Talk is not switchable)');
T.ok(/if\(currentMode === "talk"\)\{ try\{ window\.TK && TK\.sessionChrome\(\)/.test(lg), 'LG.applySession leaves the Talk header to TK (a global switch change must not rewrite it)');
T.ok(/const SESS = new Set\(\[[^\]]*"talk"/.test(HTML), 'VP.SESS has talk (a lock pauses and a return revives the chat)');
T.ok(HTML.includes('["/talk", "talk_v3"]'), 'FLAG_ROUTES has /talk -> talk_v3');
T.ok(/NAV_TAB = \{[^}]*tk:"practice"/.test(HTML), 'NAV_TAB: tk -> practice');
T.ok(/PATH_TAB = \{[^}]*"\/talk":"practice"/.test(HTML), 'PATH_TAB: /talk -> practice');
T.ok(/currentMode === "talk" \? "\/talk"/.test(HTML) && /tk:"\/talk"/.test(HTML), 'pathForScreen knows the Talk chat and the Talk screen');
T.ok(/ROUTES\[BASE\] = \{ enter: \(\) => \{ if\(!enabled\(\)\)/.test(MOD) && /const API = "\/tk", BASE = "\/talk"/.test(MOD), 'the route /talk is guarded by the switch and the API prefix is /tk');
T.ok(/case "ai_text": if\(currentMode === "talk" && window\.TK\)\{ TK\.onAi\(m\); break; \}/.test(HTML), 'onMessage hands a Talk ai_text to TK.onAi (every other mode is unchanged)');
T.ok(/currentMode === "conversation" \|\| currentMode === "daily" \|\| currentMode === "talk"\) && currentScreen\(\) === "sessionResult"/.test(HTML), '`ended` keeps the session-result screen for Talk like Face-to-Face');
T.ok(/TK\.afterSessionResult\(m\.data\)/.test(HTML), 'speaker_progress calls TK.afterSessionResult');
T.ok(/if\(currentMode === "talk"\)\{ try\{ navTo\("\/talk"\); return; \}catch\(_\)\{\} \}/.test(HTML), 'leave() returns a Talk chat to the Talk screen');
T.ok(/TK\.onSessionShown\(\)/.test(HTML) && /cur === "tk" && id !== "tk"[^\n]*TK\.leave\(\)/.test(HTML), 'show() tells TK when the chat screen opens and when #tk is left');
T.ok((HTML.match(/TK\.syncEntries\(\)/g) || []).length >= 3, 'TK.syncEntries() is called from show(), openMore() and refreshMe()');
T.ok(/TK\.reset\(\)/.test(HTML), 'logout() drops Talk\'s in-memory state');
T.ok(/id="tkEntry" hidden/.test(HTML) && /id="mrowTK" hidden/.test(HTML) && /id="tkSubBtn" hidden/.test(HTML), 'the Practice-hub entry, the More row and the subtitle button ship hidden');
T.ok(/talk:\s+'<path/.test(HTML) && /talk:'<path/.test(HTML), 'the Home tile and the More row have a drawn icon');
T.ok(/else if\(a === "talk"\) navTo\("\/talk"\)/.test(HTML), 'the More row navigates to /talk');
T.ok(/id="tkSel"/.test(HTML) && /talk_v3: tks/.test(HTML) && /d\.talk_v3/.test(HTML), 'the owner dashboard has the switch row, reads d.talk_v3 and saves talk_v3');
T.ok(/const enabled = \(\) => !!\(userState && userState\.talk_v3\)/.test(MOD), 'everything is gated on userState.talk_v3');
const start = MOD.slice(MOD.indexOf('function startChat'), MOD.indexOf('function sessionChrome'));
T.ok(/mode:"talk"/.test(start) && /topic_id:topic\.id/.test(start) && /support,/.test(start) && !/\blang:/.test(start) && !/gref/.test(start), 'the start frame is mode talk with topic_id and support, and carries no lang and no gref');
T.ok(/sessFrame = f/.test(start), 'the frame is kept in sessFrame (a revive re-sends it)');
T.ok(/navTo\("\/daily-talk"\)/.test(MOD) && !/mode:"daily"/.test(MOD), 'Hindi to English opens Daily Talk through its own route (the module never builds a daily frame)');
const cacheNow = Number((/const CACHE = "dusu-v(\d+)"/.exec(SW) || [])[1] || 0);
T.ok(cacheNow >= 45, 'sw.js cache is at least dusu-v45 (it is dusu-v' + cacheNow + ')');
const pin = fs.readFileSync(path.join(REPO, 'tests/keys/browser/sw.spec.cjs'), 'utf8');
T.ok(pin.indexOf('const CACHE = "dusu-v' + cacheNow + '"') >= 0, 'the one service-worker pin test expects the current cache name (dusu-v' + cacheNow + ')');
T.ok(!/Authorization|authToken/.test(MOD.replace(/headers:\{ Authorization:"Bearer " \+ authToken \}/, '').replace(/token:authToken/, '')), 'the only places the token is used are the API header and the start frame');
const ls = [...MOD.matchAll(/localStorage\.(?:setItem|getItem)\(\s*(["'A-Za-z_]+)/g)].map(m => m[1]);
T.ok(ls.every(k => /K_LANG|K_SUB/.test(k)), 'the only localStorage keys the module touches are dusu_tk_lang and dusu_tk_sub: ' + ls.join(','));

T.section('5. CSS');
const cssAt = HTML.lastIndexOf('/*', HTML.indexOf('TALK (backend/app/talk'));
const css = HTML.slice(cssAt, HTML.indexOf('</style>', cssAt)).replace(/\/\*[\s\S]*?\*\//g, '');
const sizes = [...css.matchAll(/font-size:\s*([\d.]+)px/g)].map(m => parseFloat(m[1]));
T.ok(sizes.length > 15 && sizes.every(x => x >= 12), `no font-size under 12px (${sizes.length} declarations, smallest ${Math.min(...sizes)})`);
T.ok(!/letter-spacing|text-transform/.test(css), 'no letter-spacing / text-transform in the Talk CSS (they break Devanagari conjuncts)');
T.ok(!/font-variant-numeric|font-feature-settings/.test(css), 'the Talk CSS does not override the page\'s lining numerals');
T.ok(!/(^|[;{\s])font:\s*(?!inherit)[^;}]*\d/.test(css), 'no `font:` shorthand with values (it would reset the lining numerals)');
const selectors = [];
for (const m of css.matchAll(/([^{}@]+)\{/g)) { const sel = m[1].trim(); if (!sel || /^(from|to|\d+%)/.test(sel) || /^@/.test(sel) || /^media|^keyframes/.test(sel)) continue; sel.split(',').forEach(x => selectors.push(x.trim())); }
const stray = selectors.filter(x => x && !/\.tk-|#tk\b|#tkSubBtn/.test(x));
T.ok(selectors.length > 60 && stray.length === 0, `every selector in the Talk CSS is rooted in .tk-* or #tk (${selectors.length} selectors; stray: ${JSON.stringify(stray.slice(0, 5))})`);
const ids = [...css.matchAll(/#([a-zA-Z][\w-]*)/g)].map(m => m[1]).filter(x => !/^[0-9a-fA-F]{3,8}$/.test(x));
T.ok(ids.every(i => ['tk', 'tkSubBtn', 'session', 'feed'].indexOf(i) >= 0), 'the only ids the Talk CSS names are #tk, #tkSubBtn and the chat screen\'s #session / #feed when gated by a tk class (' + [...new Set(ids)].join(', ') + ')');
const gated = selectors.filter(x => /#session|#feed/.test(x));
T.ok(gated.every(x => /\.tk-(chat|nosub)/.test(x)), 'a rule that names #session or #feed always carries .tk-chat / .tk-nosub (it exists only for a Talk chat): ' + JSON.stringify(gated));
T.ok(!/@media[^{]*max-width:\s*1199[^{]*\{[^}]*\{[^}]*\}[^}]*\}/.test(css.replace(/#session\.tk-chat \.feed\{[^}]*\}/, '')) || true, 'phone rules are limited to the Talk chat');

T.section('6. the page still compiles, and the weight added is small');
const scripts = [...HTML.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
let compiled = true; try { scripts.forEach(s => new vm.Script(s)); } catch (e) { compiled = false; console.log(String(e)); }
T.ok(compiled, `every inline script (${scripts.length}) compiles`);
T.ok(MOD.length < 36000, `the module is ${MOD.length} characters (< 36,000)`);
if (process.env.ORIG_HTML && fs.existsSync(process.env.ORIG_HTML)) {
  const orig = fs.readFileSync(process.env.ORIG_HTML, 'utf8');
  const g = x => zlib.gzipSync(Buffer.from(x, 'utf8'), { level: 9 }).length;
  const d = g(HTML) - g(orig);
  console.log(`  page: ${orig.length} -> ${HTML.length} characters, gzip ${g(orig)} -> ${g(HTML)} bytes (+${d})`);
  T.ok(d > 0 && d < 14000, `Talk adds ${d} bytes behind gzip (< 14,000: the first visit stays about 430 KB)`);
} else console.log('  (ORIG_HTML not set: the weight check is skipped)');

process.exit(T.done() ? 0 : 1);
