'use strict';
/* Grammar Lab - static checks (node only, no browser): the GL module of backend/test_client.html
 *   1  builds the page with DOM calls only (no innerHTML-family call, no eval)
 *   2  has the same keys in TXT.hi and TXT.en, every key it uses exists, no key is dead
 *   3  every Hindi string follows the house rules (tum never aap / tu, no gendered second-person verb endings) - look-arounds, NOT \b (it does not work on Devanagari)
 *   4  the wiring is all there (routes for the hub, Review and the twelve units that are the server's catalog order; FLAG_ROUTES, NAV_TAB, VOICE_SCREENS, the entry points, the dashboard row, the service worker cache)
 *   5  the CSS of the Lab has no font-size under 12px, no letter-spacing / text-transform, no innerHTML-like trick
 * Run:  tests/lab/browser/run.sh static.spec.cjs        (REPO is mounted at /repo) */
const fs = require('fs');
const path = require('path');
const { makeT } = require('../../resume_interview/browser/harness.cjs');

const REPO = process.env.REPO || path.resolve(__dirname, '../../..');
const HTML = fs.readFileSync(process.env.HTML_SRC || path.join(REPO, 'backend/test_client.html'), 'utf8');
const SW = fs.readFileSync(path.join(REPO, 'backend/sw.js'), 'utf8');
const CATALOG = fs.readFileSync(path.join(REPO, 'backend/app/lab/catalog.py'), 'utf8');
const T = makeT('lab-static');

const a = HTML.indexOf('const GL = (function(){'), b = HTML.indexOf('window.GL = GL;');
T.ok(a > 0 && b > a, 'the GL module is in the page');
const MOD = HTML.slice(a, b);

T.section('1. DOM calls only');
const BAD = [/\binnerHTML\b/, /\bouterHTML\b/, /\binsertAdjacentHTML\b/, /document\s*\.\s*write/, /\bDOMParser\b/, /createContextualFragment/, /\bsrcdoc\b/, /\beval\s*\(/, /new\s+Function\b/, /javascript:/i, /\.setAttribute\(\s*["']on/i, /\bsetTimeout\(\s*["']/];
BAD.forEach(re => T.ok(!re.test(MOD), `the module never uses ${re}`));
T.ok(/ATTR_OK = /.test(MOD) && !/\|style\|/.test(MOD.match(/ATTR_OK = [^\n]+/)[0]), 'the builder only sets allow-listed attributes (no style, no on* attribute)');
// the section markup of the Lab itself is static and has no inline handler
const sec = HTML.slice(HTML.indexOf('<section id="gl"'), HTML.indexOf('</section>', HTML.indexOf('<section id="gl"')));
T.ok(!/\son[a-z]+\s*=/i.test(sec), 'the #gl markup has no inline event handler');

T.section('2. TXT');
const lit = MOD.slice(MOD.indexOf('const TXT = ') + 12, MOD.indexOf('\n\n  /* ---------- a tiny DOM builder'));
const TXT = new Function('return ' + lit.replace(/;\s*$/, ''))();
const kh = Object.keys(TXT.hi).sort(), ke = Object.keys(TXT.en).sort();
T.eq(kh, ke, 'TXT.hi and TXT.en have identical key sets');
T.ok(kh.length > 90, `${kh.length} keys`);
const used = new Set([...MOD.matchAll(/\bt\(\s*"([A-Za-z0-9_]+)"\s*[,)]/g)].map(m => m[1]));
['s0', 's1', 's2', 's3', 'fAff', 'fNeg', 'fQ'].forEach(k => used.add(k));       // t("s" + n) and t(k) over a table
const missing = [...used].filter(k => !(k in TXT.en));
T.eq(missing, [], 'every key the module asks for exists');
const dead = kh.filter(k => !used.has(k) && !new RegExp('"' + k + '"').test(MOD.replace(lit, '')));
T.eq(dead, [], 'no dead key in TXT');
T.ok(Object.values(TXT.en).every(v => typeof v === 'string' && v.trim()) && Object.values(TXT.hi).every(v => typeof v === 'string' && v.trim()), 'no empty string');
const ph = s => [...String(s).matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort().join(',');
T.eq(kh.filter(k => ph(TXT.hi[k]) !== ph(TXT.en[k])), [], 'the {placeholders} of every Hindi string are the English string\'s');

T.section('3. Hindi house rules');
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
for (const [k, v] of Object.entries(TXT.hi)) for (const [re, why] of RULES) { n++; T.ok(!re.test(v), `TXT.hi.${k}: ${why} (${JSON.stringify(v.slice(0, 60))})`); }
T.ok(n > 500, `${n} rule checks`);
T.ok(Object.entries(TXT.hi).every(([k, v]) => /[ऀ-ॿ]/.test(v) || /^[A-Za-z0-9 .,:;!?/()%{}\-–·'"]+$/.test(v)), 'every Hindi string is Devanagari (with Latin grammar terms) or a bare Latin term (Formula, Example, Review ...)');
T.ok(Object.values(TXT.en).every(v => !/[ऀ-ॿ]/.test(v)), 'the English strings carry no Devanagari');

T.section('4. wiring');
const units = [...CATALOG.matchAll(/\("([a-z_]+)",\s*"(present|past|future)",\s*"[a-z_]+",\s*"[a-z]+"\)/g)].map(m => m[1]);
T.eq(units.length, 12, 'the catalog has twelve units');
const mu = MOD.match(/const UNITS = \[([^\]]+)\]/)[1].replace(/\s+/g, '').split(',').map(s => s.replace(/"/g, ''));
T.eq(mu, units, 'the module\'s UNITS are the catalog\'s, in order');
T.ok(/ROUTES\[BASE\] = /.test(MOD) && /ROUTES\[BASE \+ "\/review"\]/.test(MOD) && /UNITS\.forEach\(u => \{ ROUTES\[BASE \+ "\/" \+ u\]/.test(MOD), 'routes for the hub, Review and every unit');
T.ok(/const BASE = "\/grammar-lab"|BASE = "\/grammar-lab"/.test(MOD), 'the base route is /grammar-lab');
T.ok(HTML.includes('["/grammar-lab", "grammar_lab"]'), 'FLAG_ROUTES has /grammar-lab -> grammar_lab');
T.ok(/NAV_TAB = \{[^}]*gl:"practice"/.test(HTML), 'NAV_TAB: gl -> practice');
T.ok(/const VOICE_SCREENS = new Set\(\[[^\]]*"gl"/.test(HTML), 'VOICE_SCREENS has gl');
T.ok(/function stopAllVoice\(\)\{[\s\S]*?GL\.stopVoice\(\)/.test(HTML), 'stopAllVoice stops the Lab\'s recogniser');
T.ok(/cur === "gl" && id !== "gl"[^\n]*GL\.leave\(\)/.test(HTML), 'show() calls GL.leave() when the Lab is left');
T.ok(/gl:\(window\.GL && GL\.path\(\)\) \|\| "\/grammar-lab"/.test(HTML), 'pathForScreen knows the Lab');
T.ok((HTML.match(/GL\.syncEntries\(\)/g) || []).length >= 3, 'GL.syncEntries() is called from show(), openMore() and refreshMe()');
T.ok(/id="glEntry" hidden/.test(HTML) && /id="mrowGL" hidden/.test(HTML), 'the Practice-hub entry and the More row ship hidden');
T.ok(/grammar_lab:\s+'<path/.test(HTML), 'the Home tile has an icon');
T.ok(/id="glSel"/.test(HTML) && /grammar_lab: gls/.test(HTML) && /d\.grammar_lab/.test(HTML), 'the owner dashboard has the switch row, reads d.grammar_lab and saves grammar_lab');
T.ok(/const enabled = \(\) => !!\(userState && userState\.grammar_lab\)/.test(MOD), 'everything is gated on userState.grammar_lab');
const cacheNow = Number((/const CACHE = "dusu-v(\d+)"/.exec(SW) || [])[1] || 0);       // the Lab shipped with v43; every later release moves the name on, so this follows the real value instead of a hard-coded one
T.ok(cacheNow >= 43, 'sw.js cache is at least dusu-v43 (it is dusu-v' + cacheNow + ')');
const pin = fs.readFileSync(path.join(REPO, 'tests/keys/browser/sw.spec.cjs'), 'utf8');
T.ok(pin.indexOf('const CACHE = "dusu-v' + cacheNow + '"') >= 0, 'the one service-worker pin test expects the current cache name (dusu-v' + cacheNow + ')');
T.ok(!/Authorization|authToken/.test(MOD.replace(/headers:\{ Authorization:"Bearer " \+ authToken \}/, '')), 'the only place the token is used is the API header');
T.ok(!/localStorage\.(setItem|getItem)\(\s*["'](?!dusu_gl_lang)/.test(MOD), 'the only localStorage key the module touches is dusu_gl_lang');

T.section('5. CSS');
const cssAt = HTML.lastIndexOf('/*', HTML.indexOf('GRAMMAR LAB (a Hindi sentence in'));
const cssStop = (() => { const styleEnd = HTML.indexOf('</style>', cssAt), talkAt = HTML.indexOf('/* ===================== TALK', cssAt); return (talkAt > 0 && talkAt < styleEnd) ? talkAt : styleEnd; })();   // Talk's own CSS block follows the Lab's in the same <style>: it is not the Lab's
const css = HTML.slice(cssAt, cssStop).replace(/\/\*[\s\S]*?\*\//g, '');
const sizes = [...css.matchAll(/font-size:\s*([\d.]+)px/g)].map(m => parseFloat(m[1]));
T.ok(sizes.length > 20 && sizes.every(x => x >= 12), `no font-size under 12px (${sizes.length} declarations, smallest ${Math.min(...sizes)})`);
T.ok(!/letter-spacing|text-transform/.test(css), 'no letter-spacing / text-transform in the Lab CSS (they break Devanagari conjuncts)');
T.ok(!/font-variant-numeric|font-feature-settings/.test(css), 'the Lab CSS does not override the page\'s lining numerals');
T.ok(!/(^|[;{\s])font:\s*(?!inherit)[^;}]*\d/.test(css), 'no `font:` shorthand with values (it would reset the lining numerals)');
// every selector the Lab CSS writes is rooted in a gl-* class or #gl: nothing here can touch an old screen
const selectors = [];
for (const m of css.matchAll(/([^{}@]+)\{/g)) { const sel = m[1].trim(); if (!sel || /^(from|to|\d+%|0%,\s*100%|50%)/.test(sel) || /^@/.test(sel) || /^media|^keyframes/.test(sel)) continue; sel.split(',').forEach(x => selectors.push(x.trim())); }
const stray = selectors.filter(x => x && !/\.gl-|#gl\b/.test(x));
T.ok(selectors.length > 100 && stray.length === 0, `every selector in the Lab CSS is rooted in .gl-* or #gl (${selectors.length} selectors; stray: ${JSON.stringify(stray.slice(0, 5))})`);
const ids = [...css.matchAll(/#([a-zA-Z][\w-]*)/g)].map(m => m[1]).filter(x => !/^[0-9a-fA-F]{3,8}$/.test(x));
T.ok(ids.every(i => i === 'gl'), 'the only id the Lab CSS names is #gl (' + [...new Set(ids)].join(', ') + ')');

process.exit(T.done() ? 0 : 1);
