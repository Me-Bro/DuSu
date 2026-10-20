'use strict';
/*
 * My Day - REPEATING REMINDERS in a REAL Chromium against the REAL app (uvicorn + a scratch Postgres + the real reminder loop on the real clock;
 * see run_real.sh and ../e2e_server.py). It proves client and server agree: real status codes and bodies, the real HTML served by the real app.
 *
 *   A  the form: Once / Every day / Selected days, the weekday chips, the date that hides, the refusal when no day is picked
 *   B  set a reminder once for Mon + Tue; another for Saturday; one every day - what the screens show (the rule list, the rings of the next two days)
 *   C  tick a ring off and undo it; change a repeating reminder; pause and resume it; delete it (from the row and from the sheet)
 *   D  a one-time reminder that is made to repeat; Today lists today's rings
 *   E  a repeating reminder REALLY rings: the real reminder loop delivers it and the in-app card appears
 *   F  Hindi: the same screens in Hindi, key parity between the two string tables
 *   G  layout on a small phone, a normal phone and a desktop; accessibility of the chips
 *   H  an XSS canary in the title; another learner sees nothing; no console error, no unhandled rejection
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('my day: repeating reminders (real server)');
const { T, ERRS, sleep, ist, hhmm, wd, DAY, SHORT, ctxFor, api, setLang, boot, txt, body, vis, settle, notif, sheetOpen, shot, bodyHas, bodyLacks, openAdd, save } = L;

const t12 = s => { const [h, m] = s.split(':').map(Number); return (h % 12 || 12) + ':' + String(m).padStart(2, '0') + ' ' + (h < 12 ? 'AM' : 'PM'); };
const rules = async who => (await api(who, 'GET', '/reminder-rules')).body.rules;
const rem = async (who, view = 'all') => (await api(who, 'GET', '/reminders?view=' + view)).body.reminders;
async function fillRule(page, { title, time, mode, days }) {
  await page.fill('#plTitle2', title);
  await page.click(`#plSheet [data-chips="rrep"] [data-v="${mode}"]`);
  if (mode === 'days') for (const d of days) await page.click(`#plSheet [data-chips="rrdays"] [data-v="${d}"]`);
  await page.fill('#plTime', time);
}

(async () => {
  const browser = await chromium.launch({});
  const now0 = new Date();
  for (const who of ['ann', 'bob', 'dan', 'eve', 'fay', 'gus']) await setLang(who, 'en');
  await setLang('cat', 'hi');

  // ------------------------------------------------------------------------------------------- A0
  T.section('A0 - /me answering late must not close a form that is being typed in');
  const ctxS = await ctxFor(browser, 'gus');
  await ctxS.route('**/me?*', async route => { await sleep(2500); await route.continue(); });           // a slow connection: /me takes 2.5 s
  const slow = await boot(ctxS, '/my-day/reminders', { waitMe: false });
  const slowMe = slow.waitForResponse(r => new URL(r.url()).pathname === '/me', { timeout: 30000 });
  await openAdd(slow);
  await slow.fill('#plTitle2', 'Typed before /me answered');
  await slow.click('#plSheet [data-chips="rrep"] [data-v="days"]');
  await slow.click('#plSheet [data-chips="rrdays"] [data-v="1"]');
  await slowMe; await sleep(600);
  T.ok(await sheetOpen(slow), 'the form is still open after /me has answered');
  T.eq(await slow.inputValue('#plTitle2'), 'Typed before /me answered', '...with what was typed');
  T.eq(await slow.evaluate(() => [...document.querySelectorAll('#plSheet [data-chips="rrdays"] .on')].map(b => b.dataset.v)), ['1'], '...and the day that was picked');
  await slow.evaluate(() => LG.set(LG.cur() === 'hi' ? 'en' : 'hi'));
  await sleep(300);
  T.ok(!(await sheetOpen(slow)), 'a real language change DOES close it (its labels would be in the wrong language)');
  await ctxS.close();

  // ------------------------------------------------------------------------------------------- A
  T.section('A - the form');
  const ctxA = await ctxFor(browser, 'ann');
  const pg = await boot(ctxA, '/my-day/reminders');
  T.has(await body(pg), 'No reminders yet', 'a new learner: the empty state');
  T.ok(await vis(pg, '#plAddRow [data-act="addnew"]'), 'the Add reminder button is under the tabs');
  await openAdd(pg);
  T.eq(await pg.evaluate(() => [...document.querySelectorAll('#plSheet [data-chips="rrep"] .pl-fchip')].map(b => [b.dataset.v, b.textContent.trim(), b.getAttribute('aria-pressed')])),
       [['once', 'Once', 'true'], ['daily', 'Every day', 'false'], ['days', 'Selected days', 'false']], 'the Repeat choice: Once / Every day / Selected days, Once is on');
  T.ok(await vis(pg, '#plDate') && await vis(pg, '#plTime'), 'Once: a date and a time');
  T.ok(!(await vis(pg, '#plRrDays')) && !(await vis(pg, '#plRrHint')), 'Once: no weekday chips and no hint');
  await pg.click('#plSheet [data-chips="rrep"] [data-v="days"]');
  T.ok(await vis(pg, '#plRrDays'), 'Selected days: the weekday chips appear');
  T.eq(await pg.evaluate(() => [...document.querySelectorAll('#plSheet [data-chips="rrdays"] .pl-fchip')].map(b => b.textContent.trim())), SHORT, 'seven weekday chips, Monday first');
  T.ok(!(await vis(pg, '#plRrDateWrap')), 'a repeating reminder has no date: the date field is gone');
  T.ok(await vis(pg, '#plRrHint'), 'the hint "set it once..." is shown');
  T.eq(await pg.evaluate(() => document.querySelector('#plSheet [data-chips="rrep"] [data-v="days"]').getAttribute('aria-pressed')), 'true', 'aria-pressed follows the choice');
  T.eq(await pg.evaluate(() => document.querySelector('#plSheet [data-chips="rrep"] [data-v="once"]').getAttribute('aria-pressed')), 'false', '...and the one that was left');
  await pg.click('#plSheet [data-chips="rrdays"] [data-v="3"]');
  T.eq(await pg.evaluate(() => document.querySelector('#plSheet [data-chips="rrdays"] [data-v="3"]').getAttribute('aria-pressed')), 'true', 'a weekday chip toggles on');
  await pg.click('#plSheet [data-chips="rrdays"] [data-v="3"]');
  T.eq(await pg.evaluate(() => document.querySelector('#plSheet [data-chips="rrdays"] [data-v="3"]').getAttribute('aria-pressed')), 'false', '...and off again');
  await pg.fill('#plTitle2', 'Gym'); await pg.fill('#plTime', '20:00');
  await save(pg);
  await pg.waitForSelector('#plErr:not([hidden])', { timeout: 5000 });
  T.has(await txt(pg, '#plErr'), 'pick at least one day', 'no day picked: the refusal is in words, right above Save');
  T.ok(await sheetOpen(pg), '...and the sheet stays open (nothing is lost)');
  T.eq((await rules('ann')).length, 0, '...and nothing was saved');
  await pg.click('#plSheet [data-chips="rrep"] [data-v="daily"]');
  T.ok(!(await vis(pg, '#plRrDays')) && await vis(pg, '#plRrHint'), 'Every day: the weekday chips go, the hint stays');
  await pg.click('#plSheet [data-chips="rrep"] [data-v="once"]');
  T.ok(await vis(pg, '#plRrDateWrap') && !(await vis(pg, '#plRrHint')), 'back to Once: the date returns, the hint goes');
  await pg.click('#plSheet [data-act="cancel"]');
  T.ok(!(await sheetOpen(pg)), 'Cancel closes the sheet');
  T.eq((await rules('ann')).length, 0, 'nothing saved by cancelling');

  // ------------------------------------------------------------------------------------------- B
  T.section('B - set once for Mon + Tue, another for Saturday, one every day');
  await openAdd(pg);
  await fillRule(pg, { title: 'Gym', time: '20:00', mode: 'days', days: [0, 1] });
  await save(pg);
  await pg.waitForFunction(() => document.querySelector('#plBody') && document.querySelector('#plBody').textContent.includes('Gym') && !document.querySelector('#plBody .spin'), null, { timeout: 10000 });
  await settle(pg);
  const toast = await notif(pg);
  T.ok(/Repeating reminder set: Mon, Tue at 8:00 PM\. Next: /.test(toast), `the toast says what was set and when it rings next (got ${JSON.stringify(toast)})`);
  T.ok(pg.url().endsWith('/my-day/reminders'), 'it lands on the Reminders tab');
  const r1 = await rules('ann');
  T.eq(r1.length, 1, 'one rule is stored');
  T.eq([r1[0].title, r1[0].time, r1[0].days, r1[0].status], ['Gym', '20:00', [0, 1], 'active'], 'with its words, time and days');
  const b1 = await body(pg);
  T.ok(/repeating reminders/i.test(b1), 'the Repeating reminders section (the headings are upper-cased by the CSS)');
  T.ok(/Gym[\s\S]*Mon, Tue · 8:00 PM/.test(b1), `the row says "Mon, Tue · 8:00 PM" (got ${JSON.stringify(b1.slice(0, 300))})`);
  T.ok(/Next: /.test(b1), 'and when it rings next');
  const nxt = r1[0];
  T.ok(nxt.next_time === '20:00' && [0, 1].includes((new Date(nxt.next_day + 'T00:00:00Z').getUTCDay() + 6) % 7), `the server's next ring is a Monday or Tuesday at 20:00 (${nxt.next_day})`);
  await openAdd(pg);
  await fillRule(pg, { title: 'Call mom', time: '18:00', mode: 'days', days: [5] });
  await save(pg); await settle(pg);
  await openAdd(pg);
  await fillRule(pg, { title: 'Drink water', time: '09:00', mode: 'daily' });
  await save(pg); await settle(pg);
  const r3 = await rules('ann');
  T.eq(r3.map(x => x.title).sort(), ['Call mom', 'Drink water', 'Gym'], 'three repeating reminders stored');
  T.eq(r3.find(x => x.title === 'Drink water').days, 'daily', '"Every day" is stored as daily');
  T.eq(r3.find(x => x.title === 'Call mom').days, [5], 'Saturday is [5]');
  const b3 = await body(pg);
  T.ok(/Call mom[\s\S]*Sat · 6:00 PM/.test(b3) && /Drink water[\s\S]*Every day · 9:00 AM/.test(b3), 'each row reads its days and time');
  const order = await pg.evaluate(() => [...document.querySelectorAll('#plBody .pl-row .pl-main .pl-ttl')].map(e => e.textContent.trim()));
  const apiOrder = (await rules('ann')).map(x => x.title);
  T.eq(order.slice(0, 3), apiOrder, 'the screen lists them in the server order (the soonest ring first)');
  // the rings of the next two days: a daily 09:00 rule always has TOMORROW's ring
  const ringsAll = (await rem('ann')).filter(r => r.rule_id);
  T.ok(ringsAll.some(r => r.title === 'Drink water' && r.repeat && r.repeat.days === 'daily'), 'the daily rule has rings in the reminder list, each carrying its repeat');
  T.ok(!ringsAll.some(r => r.title === 'Call mom') || wd(now0) === 5 || wd(new Date(now0.getTime() + DAY)) === 5, 'the Saturday rule has no ring unless today or tomorrow is Saturday');
  T.ok(/Tomorrow/.test(await body(pg)), 'the list has a Tomorrow group (the rings of the next two days)');
  const ringRow = await pg.evaluate(() => { const r = [...document.querySelectorAll('#plBody .pl-card .pl-row')].find(x => x.querySelector('.pl-chk') && x.textContent.includes('Drink water')); return r ? r.textContent.replace(/\s+/g, ' ') : null; });
  T.ok(ringRow && /🔁 Drink water[\s\S]*Every day/.test(ringRow), `a ring row carries the 🔁 and says how often (got ${JSON.stringify(ringRow)})`);
  T.eq(await pg.evaluate(() => document.querySelectorAll('#plBody .pl-chk').length) > 0, true, 'and a round check to tick it off');
  await shot(pg, 'md-reminders-390');

  // ------------------------------------------------------------------------------------------- C
  T.section('C - tick a ring, change a repeating reminder, pause, resume, delete');
  const ringId = (await rem('ann')).find(r => r.title === 'Drink water' && r.rule_id).id;
  await pg.click(`#plBody .pl-chk[data-id="${ringId}"]`); await settle(pg);
  T.eq((await rem('ann')).find(r => r.id === ringId).status, 'done', 'ticking a ring marks THAT ring done');
  T.eq((await rules('ann')).length, 3, '...and the repeating reminder carries on');
  T.ok(await pg.evaluate(id => { const b = document.querySelector('#plBody .pl-chk[data-id="' + id + '"]'); return !!b && b.classList.contains('done'); }, ringId), 'the ticked ring stays in the list, struck through (not vanished)');
  await pg.click(`#plBody .pl-chk[data-id="${ringId}"]`); await settle(pg);
  T.ok(['scheduled', 'sent'].includes((await rem('ann')).find(r => r.id === ringId).status), 'ticking again undoes it');
  // edit: the pencil on the rule row
  const gymId = (await rules('ann')).find(x => x.title === 'Gym').id;
  await pg.click(`#plBody .pl-ib[data-act="ruleedit"][data-id="${gymId}"]`);
  await pg.waitForSelector('#plSheet:not([hidden]) #plTitle2', { timeout: 5000 });
  T.has(await txt(pg, '#plSheet h3'), 'Edit repeating reminder', 'the pencil opens the repeating reminder, not a single ring');
  T.eq(await pg.inputValue('#plTitle2'), 'Gym', 'the words are filled in');
  T.eq(await pg.inputValue('#plTime'), '20:00', 'the time is filled in');
  T.eq(await pg.evaluate(() => [...document.querySelectorAll('#plSheet [data-chips="rrdays"] .on')].map(b => b.dataset.v)), ['0', '1'], 'Mon and Tue are on');
  T.ok(await vis(pg, '#plSheet [data-act="rulepause"]') && await vis(pg, '#plSheet [data-act="ruledel"]'), 'Pause and Delete are offered');
  T.ok(!(await pg.evaluate(() => !!document.querySelector('#plSheet [data-chips="rrep"] [data-v="once"]'))), 'a repeating reminder cannot be turned back into a one-time one here (no Once)');
  await pg.fill('#plTitle2', 'Gym - legs'); await pg.fill('#plTime', '07:15');
  await pg.click('#plSheet [data-chips="rrdays"] [data-v="1"]');            // Tue off
  await pg.click('#plSheet [data-chips="rrdays"] [data-v="4"]');            // Fri on
  await save(pg); await settle(pg);
  T.ok(!(await sheetOpen(pg)), 'saved: the sheet closes');
  T.has(await notif(pg), 'updated', 'the toast says it was updated');
  const g2 = (await rules('ann')).find(x => x.id === gymId);
  T.eq([g2.title, g2.time, g2.days], ['Gym - legs', '07:15', [0, 4]], 'the changes are stored');
  T.ok(await bodyHas(pg, /Gym - legs[\s\S]*Mon, Fri · 7:15 AM/), 'and shown');
  T.ok(!(await rem('ann')).some(r => r.rule_id === gymId && r.status === 'scheduled' && r.time === '20:00'), 'no ring is left at the old time');
  // pause
  await pg.click(`#plBody .pl-ib[data-act="ruleedit"][data-id="${gymId}"]`);
  await pg.waitForSelector('#plSheet [data-act="rulepause"]');
  await pg.click('#plSheet [data-act="rulepause"]'); await settle(pg);
  T.eq((await rules('ann')).find(x => x.id === gymId).status, 'paused', 'paused (stored)');
  T.has(await notif(pg), 'paused', 'the toast says so');
  T.ok(await bodyHas(pg, /Gym - legs[\s\S]*Paused/), 'the row says Paused');
  T.ok(!(await rem('ann')).some(r => r.rule_id === gymId && ['scheduled', 'waiting'].includes(r.status)), 'a paused reminder has no ring waiting');
  await pg.click(`#plBody .pl-ib[data-act="ruleedit"][data-id="${gymId}"]`);
  await pg.waitForSelector('#plSheet [data-act="ruleresume"]');
  T.has(await txt(pg, '#plSheet [data-act="ruleresume"]'), 'Resume', 'the button now offers Resume');
  await pg.click('#plSheet [data-act="ruleresume"]'); await settle(pg);
  T.eq((await rules('ann')).find(x => x.id === gymId).status, 'active', 'resumed (stored)');
  T.ok(await bodyHas(pg, /Gym - legs[\s\S]*Next: /), 'the row has its Next ring again');
  // delete from the row (a confirm first)
  const callId = (await rules('ann')).find(x => x.title === 'Call mom').id;
  const dlg0 = pg.__dialogs.length;
  await pg.click(`#plBody .pl-ib.del[data-act="ruledel2"][data-id="${callId}"]`); await settle(pg);
  T.eq(pg.__dialogs.length, dlg0 + 1, 'delete asks first');
  T.has(pg.__dialogs[pg.__dialogs.length - 1], 'repeats', 'the question says the reminder repeats');
  T.ok(!(await rules('ann')).some(x => x.id === callId), 'deleted (stored)');
  T.ok(await bodyLacks(pg, 'Call mom'), 'and gone from the screen');
  T.has(await notif(pg), 'deleted', 'the toast says so');
  // delete from the sheet
  const waterId = (await rules('ann')).find(x => x.title === 'Drink water').id;
  await pg.click(`#plBody .pl-ib[data-act="ruleedit"][data-id="${waterId}"]`);
  await pg.waitForSelector('#plSheet [data-act="ruledel"]');
  await pg.click('#plSheet [data-act="ruledel"]'); await settle(pg);
  T.ok(!(await rules('ann')).some(x => x.id === waterId) && !(await sheetOpen(pg)), 'deleted from the sheet: the sheet closes, the rule is gone');
  T.ok(!(await rem('ann')).some(r => r.rule_id === waterId && ['scheduled', 'waiting', 'sent'].includes(r.status)), 'and none of its rings is left to go off');
  // cancelling the confirm keeps it
  const dlgCtx = await ctxFor(browser, 'ann');
  const pgc = await boot(dlgCtx, '/my-day/reminders');
  pgc.removeAllListeners('dialog'); pgc.on('dialog', d => d.dismiss());
  const keepId = (await rules('ann')).find(x => x.title === 'Gym - legs').id;
  await pgc.click(`#plBody .pl-ib.del[data-act="ruledel2"][data-id="${keepId}"]`); await sleep(500);
  T.ok((await rules('ann')).some(x => x.id === keepId), 'saying "no" to the question keeps the reminder');
  await dlgCtx.close();

  // ------------------------------------------------------------------------------------------- D
  T.section('D - a one-time reminder made to repeat; Today lists today\'s rings');
  await pg.click('#plAddRow [data-act="addnew"]');
  await pg.waitForSelector('#plSheet:not([hidden]) #plTitle2');
  const soon = new Date(Date.now() + 5 * 3600 * 1000);
  await pg.fill('#plTitle2', 'One time thing'); await pg.fill('#plTime', hhmm(soon));
  await save(pg); await settle(pg);
  const once = (await rem('ann')).find(r => r.title === 'One time thing');
  T.ok(once && once.kind === 'time' && !once.rule_id, 'a one-time reminder is still a one-time reminder');
  await pg.click(`#plBody .pl-ib[data-act="remedit"][data-id="${once.id}"]`);
  await pg.waitForSelector('#plSheet:not([hidden]) #plTitle2');
  await pg.click('#plSheet [data-chips="rrep"] [data-v="daily"]');
  await save(pg); await settle(pg);
  const conv = (await rules('ann')).find(x => x.title === 'One time thing');
  T.ok(conv && conv.days === 'daily' && conv.time === hhmm(soon), 'edited into "Every day": a repeating reminder now exists');
  T.ok(!(await rem('ann')).some(r => r.id === once.id && ['scheduled', 'waiting'].includes(r.status)), 'and the one-time reminder it replaced is gone');
  const istNow = ist(new Date());
  if (istNow.getUTCHours() < 21) {
    const in2h = new Date(Date.now() + 90 * 60 * 1000);
    await pg.click('#plAddRow [data-act="addnew"]'); await pg.waitForSelector('#plSheet:not([hidden]) #plTitle2');
    await fillRule(pg, { title: 'Today ring', time: hhmm(in2h), mode: 'daily' });
    await save(pg); await settle(pg);
    await pg.click('.pl-tab[data-tab="today"]'); await settle(pg);
    const today = await pg.evaluate(() => document.getElementById('plBody').innerText);
    T.ok(/reminders/i.test(today) && today.includes('Today ring'), `Today lists a repeating reminder's ring under Reminders (got ${JSON.stringify(today.slice(0, 300))})`);
    const todayRow = await pg.evaluate(() => { const r = [...document.querySelectorAll('#plBody .pl-row')].find(x => x.textContent.includes('Today ring')); return r ? r.textContent.replace(/\s+/g, ' ') : ''; });
    T.ok(/🔁 Today ring[\s\S]*Every day/.test(todayRow), `with the 🔁 and how often (got ${JSON.stringify(todayRow)})`);
    await shot(pg, 'md-today-390');
    await pg.click('.pl-tab[data-tab="reminders"]'); await settle(pg);
  } else console.log('  (skipped: the Today check needs the learner\'s clock before 21:00)');

  // ------------------------------------------------------------------------------------------- E
  T.section('E - a repeating reminder REALLY rings (the real reminder loop, the real clock)');
  const m = ist(new Date());
  const secs = m.getUTCSeconds();
  if (m.getUTCHours() === 23 && m.getUTCMinutes() >= 55) console.log('  (skipped: too close to midnight in the learner\'s zone)');
  else {
    await api('eve', 'PUT', '/prefs', { quiet_on: false });                             // the default quiet hours (22:00-07:00) would, correctly, hold a ring back at night: the test must not depend on the hour it runs
    const ctxE = await ctxFor(browser, 'eve');
    const pe = await boot(ctxE, '/my-day/reminders');
    const fire = new Date(Date.now() + (secs > 35 ? 110 : 70) * 1000);                // the next minute that is still >= 25 s away
    await pe.click('#plAddRow [data-act="addnew"]'); await pe.waitForSelector('#plSheet:not([hidden]) #plTitle2');
    await fillRule(pe, { title: 'It really rings', time: hhmm(fire), mode: 'daily' });
    await save(pe); await settle(pe);
    if (!(await rules('eve')).length) console.log('  [diagnostic] the rule was not created; sheet open:', await sheetOpen(pe), '; error box:', JSON.stringify(await txt(pe, '#plErr')), '; time field:', await pe.inputValue('#plTime').catch(() => null), '; chips:', await pe.evaluate(() => [...document.querySelectorAll('#plSheet [data-chips="rrep"] .on')].map(b => b.dataset.v)));
    const er = (await rules('eve'))[0];
    T.ok(er && er.next_time === hhmm(fire), `the rule is set for ${hhmm(fire)} (next ${er && er.next_day} ${er && er.next_time})`);
    let due = [];
    const deadline = Date.now() + 200000;
    let firstSeen = null;
    while (Date.now() < deadline) { due = (await api('eve', 'GET', '/due')).body.due; if (due.length && !firstSeen) firstSeen = due[0].status; if (due.some(d => d.status === 'sent')) break; await sleep(2000); }
    T.ok(due.length === 1 && due[0].title === 'It really rings' && due[0].rule_id === er.id && due[0].status === 'sent', `the real reminder loop rang it (due list: ${JSON.stringify(due.map(d => [d.title, d.status]))})`);
    T.ok(firstSeen === 'scheduled' || firstSeen === 'sent', `it was in the in-app due list from the moment it was due (first seen as ${firstSeen})`);
    await pe.evaluate(() => PL.pollDue()); await sleep(600);
    await pe.click('.pl-tab[data-tab="today"]'); await settle(pe);
    T.ok(await vis(pe, '#plBody .pl-remcard'), 'the in-app card appears on Today');
    T.has(await txt(pe, '#plBody .pl-remcard'), 'It really rings', 'with the words');
    await shot(pe, 'md-rang-390');
    await pe.click('#plBody .pl-remcard [data-a="done"]'); await sleep(800);
    const after = (await rem('eve')).filter(r => r.rule_id === er.id);
    T.ok(after.some(r => r.status === 'done') && (await rules('eve')).length === 1, 'Done ticks that ring off and the repeating reminder carries on');
    const tomorrow = after.filter(r => ['scheduled', 'waiting'].includes(r.status));
    T.ok(tomorrow.length >= 1 && tomorrow.every(r => new Date(r.fire_at) > new Date()), 'the next ring is already waiting, in the future');
    await ctxE.close();
  }

  // ------------------------------------------------------------------------------------------- F
  T.section('F - Hindi');
  const ctxH = await ctxFor(browser, 'cat', { lang: 'hi' });
  const ph = await boot(ctxH, '/my-day/reminders');
  await ph.click('#plAddRow [data-act="addnew"]'); await ph.waitForSelector('#plSheet:not([hidden]) #plTitle2');
  T.eq(await ph.evaluate(() => [...document.querySelectorAll('#plSheet [data-chips="rrep"] .pl-fchip')].map(b => b.textContent.trim())), ['एक बार', 'हर दिन', 'चुने हुए दिन'], 'the Repeat choice in Hindi');
  await ph.click('#plSheet [data-chips="rrep"] [data-v="days"]');
  T.eq(await ph.evaluate(() => [...document.querySelectorAll('#plSheet [data-chips="rrdays"] .pl-fchip')].map(b => b.textContent.trim())), ['सोम', 'मंगल', 'बुध', 'गुरु', 'शुक्र', 'शनि', 'रवि'], 'the weekdays in Hindi');
  T.has(await txt(ph, '#plRrHint'), 'एक बार लगाओ', 'the hint in Hindi');
  await shot(ph, 'md-form-hi-390');
  await ph.fill('#plTitle2', 'व्यायाम'); await ph.fill('#plTime', '06:30');
  await save(ph);
  await ph.waitForSelector('#plErr:not([hidden])');
  T.has(await txt(ph, '#plErr'), 'कम से कम एक दिन', 'the refusal in Hindi');
  await ph.click('#plSheet [data-chips="rrdays"] [data-v="0"]'); await ph.click('#plSheet [data-chips="rrdays"] [data-v="2"]');
  await save(ph); await settle(ph);
  T.has(await notif(ph), 'बार-बार वाला reminder लग गया: सोम, बुध', 'the toast in Hindi');
  const bh = await ph.evaluate(() => document.getElementById('plBody').textContent);        // textContent: the CSS upper-cases the headings in innerText
  T.ok(bh.includes('बार-बार वाले reminders') && bh.includes('व्यायाम') && bh.includes('सोम, बुध · 6:30 AM'), 'the section, the words and the days in Hindi');
  await shot(ph, 'md-reminders-hi-390');
  const parity = await ph.evaluate(() => { const e = Object.keys(PL._txt.en), h = Object.keys(PL._txt.hi); return { onlyEn: e.filter(k => !h.includes(k)), onlyHi: h.filter(k => !e.includes(k)) }; });
  T.eq(parity, { onlyEn: [], onlyHi: [] }, 'every string exists in both languages (My Day)');
  const gendered = await ph.evaluate(() => ['fRepeatRem', 'rrOnce', 'rrDaily', 'rrDays', 'rrHint', 'rrSection', 'rrNext', 'rrPaused', 'rrPause', 'rrResume', 'rrNone', 'editRule', 'rrSet', 'rrDup', 'rrSaved', 'rrDeleted', 'rrDelAsk', 'rrPaused2', 'rrResumed', 'errDays', 'errLimit_repeating']
    .map(k => PL._txt.hi[k]).filter(s => /रहे हो|सकते हो|करोगे|बोलोगे|चाहते हो/.test(s)));
  T.eq(gendered, [], 'no gendered verb forms toward the learner in the new Hindi copy');
  await ctxH.close();

  // ------------------------------------------------------------------------------------------- G
  T.section('G - layout and accessibility');
  for (const [label, vp] of [['360x640', { width: 360, height: 640 }], ['390x844', { width: 390, height: 844 }], ['1280x800', { width: 1280, height: 800 }]]) {
    const cx = await ctxFor(browser, 'dan', { viewport: vp });
    const pd = await boot(cx, '/my-day/reminders');
    if (label === '360x640') {
      for (const [ti, tm, dys] of [['Take the medicine after dinner with a glass of water', '21:15', [0, 1, 2, 3, 4, 5, 6]], ['Gym', '07:00', [0, 1]]]) {
        await pd.click('#plAddRow [data-act="addnew"]'); await pd.waitForSelector('#plSheet:not([hidden]) #plTitle2');
        await fillRule(pd, { title: ti, time: tm, mode: 'days', days: dys }); await save(pd); await settle(pd);
      }
    }
    const audit = async (what) => {
      const r = await pd.evaluate(() => {
        const out = { overflow: [], small: [], noname: [] };
        const w = document.querySelector('.wrap');
        if (document.documentElement.scrollWidth > innerWidth + 1) out.overflow.push('document ' + document.documentElement.scrollWidth + '>' + innerWidth);
        if (w && w.scrollWidth > w.clientWidth + 1) out.overflow.push('wrap ' + w.scrollWidth + '>' + w.clientWidth);
        const root = document.querySelector('#pl.on') || document.body, sh = document.getElementById('plSheet');
        for (const e of [...root.querySelectorAll('*'), ...(sh && !sh.hidden ? sh.querySelectorAll('*') : [])]) {
          const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || e.closest('[hidden]')) continue;
          const b = e.getBoundingClientRect(); if (!b.width || !b.height) continue;
          if (b.right > innerWidth + 2 || b.left < -2) out.overflow.push(e.tagName + '.' + e.className + ' ' + Math.round(b.left) + '..' + Math.round(b.right));
        }
        const mine = new Set(document.querySelectorAll('#plBody .pl-ib, #plBody .pl-main, #plBody .pl-chk, #plAddRow button, #plSheet [data-chips="rrep"] .pl-fchip, #plSheet [data-chips="rrdays"] .pl-fchip, #plSheet .btn, #plSheet input:not([type=hidden])'));
        for (const e of document.querySelectorAll('#plBody button, #plSheet button, #plSheet input:not([type=hidden]), #plAddRow button')) {
          const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || e.closest('[hidden]')) continue;
          const b = e.getBoundingClientRect(); if (!b.width || !b.height) continue;
          if (mine.has(e) && b.height < 39.5) out.small.push((e.dataset.act || e.id || e.className) + ' ' + Math.round(b.width) + 'x' + Math.round(b.height));
          const nm = (e.getAttribute('aria-label') || e.textContent || e.getAttribute('title') || (e.id && document.querySelector('label[for="' + e.id + '"]') && 'label') || '').trim();
          if (!nm) out.noname.push(e.outerHTML.slice(0, 80));
        }
        return out;
      });
      T.eq(r.overflow, [], `${label} ${what}: no horizontal overflow`);
      T.eq(r.small, [], `${label} ${what}: every control of this feature (rows, tools, the repeat and weekday chips, buttons) is at least 40px tall`);
      T.eq(r.noname, [], `${label} ${what}: every control has a name`);
    };
    await audit('the Reminders tab');
    await shot(pd, 'md-reminders-' + label);
    await pd.click('#plAddRow [data-act="addnew"]'); await pd.waitForSelector('#plSheet:not([hidden]) #plTitle2');
    await pd.click('#plSheet [data-chips="rrep"] [data-v="days"]');
    await audit('the form with the weekday chips');
    const inView = await pd.evaluate(() => { const s = document.querySelector('#plSheet [data-act="save"]'); const b = s.getBoundingClientRect(); return b.top >= 0 && b.bottom <= innerHeight + 1; });
    T.ok(inView, `${label}: the Save button is on screen with the weekday chips open`);
    const wrapped = await pd.evaluate(() => { const c = [...document.querySelectorAll('#plSheet [data-chips="rrdays"] .pl-fchip')].map(b => b.getBoundingClientRect()); return { n: c.length, minW: Math.round(Math.min(...c.map(r => r.width))), minH: Math.round(Math.min(...c.map(r => r.height))) }; });
    T.ok(wrapped.n === 7 && wrapped.minW >= 36 && wrapped.minH >= 36, `${label}: the seven weekday chips are tappable (${wrapped.minW}x${wrapped.minH} at least)`);
    await shot(pd, 'md-form-' + label);
    await pd.click('#plSheet [data-act="cancel"]');
    await cx.close();
  }

  // ------------------------------------------------------------------------------------------- H
  T.section('H - an XSS canary, isolation, the console');
  const ctxX = await ctxFor(browser, 'fay');
  const px = await boot(ctxX, '/my-day/reminders');
  const evil = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>';
  await px.click('#plAddRow [data-act="addnew"]'); await px.waitForSelector('#plSheet:not([hidden]) #plTitle2');
  await fillRule(px, { title: evil, time: '10:00', mode: 'days', days: [2] });
  await save(px); await settle(px);
  T.has(await body(px), '<img src=x', 'the title is shown as TEXT');
  T.eq(await px.evaluate(() => window.__xss), 0, 'and nothing in it ran');
  await px.click('#plBody .pl-ib[data-act="ruleedit"]'); await px.waitForSelector('#plSheet:not([hidden]) #plTitle2');
  T.eq(await px.inputValue('#plTitle2'), evil, 'the edit sheet shows it back exactly, as text');
  await px.click('#plSheet [data-act="cancel"]');
  await px.reload({ waitUntil: 'domcontentloaded' }); await px.waitForSelector('#pl.on'); await settle(px);
  T.eq(await px.evaluate(() => window.__xss), 0, 'still nothing after a reload (it is stored, not re-run)');
  T.eq((await rules('bob')).length, 0, 'another learner has no repeating reminders');
  const foreign = (await rules('ann'))[0];
  T.eq((await api('bob', 'PATCH', '/reminder-rules/' + foreign.id, { title: 'x' })).status, 404, 'and cannot change somebody else\'s (404)');
  T.eq((await api('bob', 'DELETE', '/reminder-rules/' + foreign.id)).status, 404, '...or delete it (404)');
  await ctxX.close();
  T.eq(ERRS.concat(await pg.evaluate(() => (window.__errors || []).concat(window.__rejections || []))), [], 'no console error, page error or unhandled rejection in the whole run');
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED:', e); process.exit(2); });
