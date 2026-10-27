'use strict';
/*
 * Hygiene of the new client modules (ARB, KY, INST, CM) and of the markup they add - read from the page's source, no browser needed.
 *   1  no HTML-injecting API anywhere in the modules (innerHTML, outerHTML, insertAdjacentHTML, document.write, eval, new Function): a stored XSS here would hand over the
 *      session token and the keys kept in localStorage
 *   2  every t("key") / tk("key") exists in the module's word table; no word is unused; Hindi has exactly the English keys
 *   3  every static id the modules read exists in the markup (or is created by the module itself); no id in the page is duplicated
 *   4  CSS: every class the new block defines starts with ky- / inst- / cm-; the markup uses no unprefixed new class
 *   5  every entry point ships hidden; the dialogs carry role=dialog, aria-modal and aria-hidden; the early <head> script comes before the app script
 *   6  the page carries no key and no WhatsApp invite link (the invite lives in the database, not in this public file)
 *   7  the old wording that named a screen that does not exist ("Settings") is gone from the key messages
 */
const fs = require('fs');
const path = require('path');
const { makeT } = require('../../resume_interview/browser/harness.cjs');
const T = makeT('static (keys / install / community)');

const REPO = process.env.REPO || path.join(__dirname, '..', '..', '..');
const html = fs.readFileSync(path.join(REPO, 'backend', 'test_client.html'), 'utf8');
const cut = (from, to) => { const a = html.indexOf(from), b = html.indexOf(to, a + 1); if (a < 0 || b < 0) throw new Error('marker not found: ' + from + ' / ' + to); return html.slice(a, b); };
const MODULES = {
  ARB: cut('/* ================= ARB - which ONE Home prompt', '/* ================= KEYS - the learner'),
  KY: cut('/* ================= KEYS - the learner', '/* ================= INSTALL - "Install app"'),
  INST: cut('/* ================= INSTALL - "Install app"', '/* ================= COMMUNITY - join'),
  CM: cut('/* ================= COMMUNITY - join', 'window.CM = CM;'),
};

T.section('1 - no HTML-injecting API in the modules');
for (const [n, src] of Object.entries(MODULES)) {
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  for (const bad of ['innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(', 'new Function', 'srcdoc', 'javascript:']) T.ok(!code.includes(bad), `${n}: no ${bad}`);
}

T.section('2 - the word tables');
for (const n of ['KY', 'INST', 'CM']) {
  const src = MODULES[n];
  const m = /const TXT = (\{[\s\S]*?\n  \});\n/.exec(src);
  const TXT = m ? new Function('return ' + m[1])() : null;          // the table is string literals only: evaluate it instead of parsing it
  T.ok(TXT && TXT.en && TXT.hi, `${n}: both tables found`);
  const en = Object.keys(TXT.en), hi = Object.keys(TXT.hi);
  T.eq(en.filter(k => !hi.includes(k)), [], `${n}: every English string has a Hindi twin`);
  T.eq(hi.filter(k => !en.includes(k)), [], `${n}: Hindi has nothing English lacks`);
  const body = src.replace(/const TXT = \{[\s\S]*?\n  \};\n/, '');
  const used = new Set([...body.matchAll(/\b(?:t|tt|tk)\("(\w+)"/g)].map(x => x[1]));
  // KY picks a key from a condition (tt(k.approx ? "resetAbout" : "resetAt"), t(k.expired ? "rExpired" : "rInvalid")): every quoted word that IS a key counts as used
  for (const k of en) if (new RegExp('["\']' + k + '["\']').test(body)) used.add(k);
  T.eq([...used].filter(k => !en.includes(k) && /^[a-z][A-Za-z0-9]+$/.test(k) && /\b(?:t|tt|tk)\("/.test(body) && body.includes('t("' + k + '"') ), [], `${n}: every key the code asks for exists`);
  T.eq(en.filter(k => !used.has(k)), [], `${n}: no English string is unused`);
  const f = x => [...String(x).matchAll(/\{(\w+)\}/g)].map(y => y[1]).sort().join(',');
  T.eq(en.filter(k => f(TXT.en[k]) !== f(TXT.hi[k])), [], `${n}: the {placeholders} of every English string match its Hindi twin`);
  T.eq(hi.filter(k => !/^(rReset|rAbout)$/.test(k) && /[ \t]{2,}|^\s|\s$/.test(TXT.hi[k])), [], `${n}: no stray spaces in the Hindi strings (rReset / rAbout are sentence suffixes: they start with a space on purpose)`);
}

T.section('3 - ids');
const staticIds = new Set([...html.matchAll(/\sid="([\w-]+)"/g)].map(x => x[1]));
const all = [...html.matchAll(/\sid="([\w-]+)"/g)].map(x => x[1]);
const dupSet = list => new Set(list.filter((x, i) => list.indexOf(x) !== i));
const origPath = path.join(REPO, 'tests', 'keys', '.orig.html');
const baseline = fs.existsSync(origPath) ? dupSet([...fs.readFileSync(origPath, 'utf8').matchAll(/\sid="([\w-]+)"/g)].map(x => x[1])) : new Set(['plTitle2', 'plTime', 'plRrDays', 'plDate']);
T.eq([...dupSet(all)].filter(x => !baseline.has(x)), [], 'these changes added no duplicate id (4 older My Day ones sit inside script templates, not in the markup)');
const created = { KY: ['kySum', 'kyAll', 'kym_all', 'kyTitle'], INST: ['instTitle', 'instGo', 'instCopy'], CM: ['waTitle'] };
for (const n of ['KY', 'INST', 'CM']) {
  const ids = new Set([...MODULES[n].matchAll(/\$\("(\w+)"\)/g)].map(x => x[1]));
  const missing = [...ids].filter(id => !staticIds.has(id) && !created[n].includes(id) && !/^ky[bem]_|^kySave_|^kyCancel_/.test(id));
  T.eq(missing, [], `${n}: every static id it reads exists in the markup`);
}
for (const id of ['kyCard', 'instPrompt', 'ntPrompt', 'waPrompt', 'instPill', 'mrowInst', 'mrowWA', 'cmHelp', 'cmSub', 'kyBg', 'kySheet', 'instBg', 'instSheet', 'waBg', 'waSheet']) T.ok(staticIds.has(id), `#${id} exists`);

T.section('4 - CSS');
const css = cut('/* ===================== KEYS / INSTALL / COMMUNITY', '/* ===================== PRACTICE ROOM');
const classes = [...css.matchAll(/\.([a-z][\w-]*)/g)].map(x => x[1]).filter(c => !/^(on|btn|primary|ghost|ok|warn|bad|unk|hidden|ghost|keys-note|keyblk|msheet|nt-prompt|nt-acts|screen|swrow)$/.test(c));
T.eq([...new Set(classes)].filter(c => !/^(ky|inst|cm)-/.test(c)), [], 'every class the new CSS block defines starts with ky- / inst- / cm-');
const tagOf = id => new RegExp('<[a-z]+[^>]*\\sid="' + id + '"[^>]*>').exec(html)[0];
const NEWIDS = ['kyCard', 'instPrompt', 'waPrompt', 'instPill', 'mrowInst', 'mrowWA', 'cmHelp', 'kyBg', 'kySheet', 'instBg', 'instSheet', 'waBg', 'waSheet'];
T.eq(NEWIDS.map(id => [id, (/class="([^"]*)"/.exec(tagOf(id)) || [])[1] || '']).filter(([, c]) => c && !c.split(/\s+/).every(x => /^(ky|inst|cm)-/.test(x) || /^(nt-prompt|mrow)$/.test(x))), [], 'every new element carries only ky- / inst- / cm- classes (or the shared nt-prompt / mrow)');

T.section('5 - markup');
for (const id of ['kyCard', 'instPrompt', 'waPrompt', 'instPill', 'mrowInst', 'mrowWA', 'cmHelp', 'cmSub']) T.ok(new RegExp('<[^>]*id="' + id + '"[^>]*\\shidden').test(html) || new RegExp('<[^>]*\\shidden[^>]*id="' + id + '"').test(html), `#${id} ships hidden`);
for (const id of ['kySheet', 'instSheet', 'waSheet']) { const tag = new RegExp('<div[^>]*id="' + id + '"[^>]*>').exec(html)[0]; T.ok(/role="dialog"/.test(tag) && /aria-modal="true"/.test(tag) && /aria-hidden="true"/.test(tag) && /aria-labelledby=/.test(tag), `#${id} is a labelled modal dialog, closed`); }
T.ok(html.indexOf('window.__dusuBip = null;') > 0 && html.indexOf('window.__dusuBip = null;') < html.indexOf('const INST = (function'), 'the early install script comes before the app script');
T.ok(/rel="apple-touch-icon" href="\/assets\/icons\/apple-touch-180-v1.png"/.test(html) && /rel="icon"[^>]*dusu-192-v1.png/.test(html), 'the page points at the small real icons');
T.ok(!/href="\/logo\.png"/.test(html.slice(0, html.indexOf('</head>'))), 'and no longer at the 1.7 MB logo from the <head>');

T.section('6 - no secrets in the public file');
T.ok(!/chat\.whatsapp\.com\/[A-Za-z0-9]{10,}/.test(html), 'no WhatsApp invite link in the page');
T.ok(!/\bgsk_[A-Za-z0-9]{20,}|\bAIza[A-Za-z0-9_-]{30,}|\bsk-or-v1-[A-Za-z0-9]{20,}/.test(html), 'no API key in the page');

T.section('7 - wording');
T.ok(!/key in Settings/.test(html.replace(/pushHintB[^\n]*\n/, '')), 'no message sends a learner to a "Settings" screen for their keys (the real path is More -> DuSu keys)');
T.ok(/More → DuSu keys/.test(html), 'the real path is named');
process.exit(T.done() ? 0 : 1);
