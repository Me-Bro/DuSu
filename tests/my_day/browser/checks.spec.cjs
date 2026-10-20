'use strict';
/*
 * My Day - CHECK and UNCHECK, for all four kinds of thing, in a REAL Chromium against the REAL app (uvicorn + scratch Postgres; see run_real.sh).
 *
 * The owner's report: "in My Day I go to reminder, goal, habit, task - a user should be able to check and uncheck. I checked for testing, and after that I
 * am not able to uncheck it." The server log of that session: a habit made on the Habits tab, checked on the Today screen, edited, then tapped three more
 * times - every tap answered 200 and changed nothing. The app decided "check or uncheck?" from the FIRST copy of the item it found, and that copy was the
 * Habits tab's (out of date), not Today's. This spec drives exactly such sequences with real clicks, then every other place an item can be checked.
 *
 *   A  habits - the owner's own sequence (Habits tab -> Today -> tap, tap, tap), a habit with several glasses, the tap-the-last-glass rule, Undo, an edit in between
 *   B  tasks  - checked on the Tasks tab (the row must stay), checked on Today and unchecked there, the stale-copy sequence, a skipped task, the Done chip, an old task
 *   C  goals  - a check on the goal row, the steps inside a goal, Done / Reopen in the goal
 *   D  reminders - checked on All, on Today, on Coming up (where it leaves the list), in History
 *   E  Hindi + accessibility: every check has a name that says what a tap does; the new words exist in both languages
 *   F  layout of the new controls at 360 / 390 / 1280, and no console error in the whole run
 */
const { chromium } = require('playwright');
const L = require('./lib.cjs').create('my day: check and uncheck (real server)');
const { T, ERRS, sleep, until, api, ctxFor, boot, body, goTab, settle, notif, shot, setLang, isoDay, hhmm, DAY } = L;

const TODAY = isoDay(new Date());

// ----------------------------------------------------------------------------- what the SERVER says (the truth the screen must agree with)
const tasksApi = async who => {
  const m = new Map();
  for (const v of ['all', 'done']) for (const x of ((await api(who, 'GET', '/tasks?view=' + v)).body.tasks || [])) m.set(x.id, x);
  return [...m.values()];
};
const taskOf = async (who, title) => (await tasksApi(who)).find(x => x.title === title);
const habitOf = async (who, title) => ((await api(who, 'GET', '/habits')).body.habits || []).find(h => h.title === title);
const goalOf = async (who, title) => ((await api(who, 'GET', '/goals')).body.goals || []).find(g => g.title === title);
const remOf = async (who, title) => {
  const m = new Map();
  for (const v of ['all', 'history']) for (const x of ((await api(who, 'GET', '/reminders?view=' + v)).body.reminders || [])) m.set(x.id, x);
  return [...m.values()].find(x => x.title === title);
};

// ----------------------------------------------------------------------------- what a person does
const row = (page, title) => page.locator('#plBody .pl-row', { hasText: title }).first();
const habitCard = (page, title) => page.locator('#plBody .pl-habit', { hasText: title }).first();
const goalCard = (page, title) => page.locator('#plBody .pl-gwrap', { hasText: title }).first();
async function tap(loc, what) {                                                                  // a tap, then let the screen re-draw before the next one
  try { await loc.click({ timeout: 5000 }); } catch (e) { T.ok(false, `could not tap ${what || String(loc).slice(0, 100)}: it is not on the screen`); return false; }
  await sleep(500); return true;
}
const visible = async loc => (await loc.count()) > 0 && await loc.first().isVisible().catch(() => false);
const hasClass = (loc, c) => loc.first().evaluate((e, k) => e.classList.contains(k), c).catch(() => false);

(async () => {
  const browser = await chromium.launch({});
  for (const who of ['ann', 'bob', 'cat', 'dan', 'eve', 'fay', 'hal']) await setLang(who, 'en');
  await setLang('gus', 'hi');

  // =========================================================================================== A  habits
  T.section('A - habits: the owner\'s own sequence (made on the Habits tab, checked on Today, tapped again)');
  await api('bob', 'POST', '/habits', { title: 'Read a page', target: 1, schedule: { days: 'daily', times: [] }, client_key: 'b-read' });
  await api('bob', 'POST', '/habits', { title: 'Drink water', target: 3, unit: 'glasses', schedule: { days: 'daily', times: [] }, client_key: 'b-water' });
  const ctxB = await ctxFor(browser, 'bob');
  const pb = await boot(ctxB, '/my-day/habits');                                   // the Habits tab loads ITS copy of the habits (nothing checked yet)
  T.ok(await visible(habitCard(pb, 'Read a page')), 'the habits are listed');
  await goTab(pb, 'today');                                                         // ...then the learner uses the Today screen
  const readBtn = () => habitCard(pb, 'Read a page').locator('[data-act="hlog"]').first();
  T.ok(await visible(readBtn()), 'Today shows the habit with something to tap');
  await tap(readBtn());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page')).count_today === 1), 'tap 1: the habit is checked');
  await tap(readBtn());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page')).count_today === 0), 'tap 2: the SAME tap unchecks it (before the fix it stayed checked: every tap answered 200 and changed nothing)');
  await tap(readBtn());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page')).count_today === 1), 'tap 3: checked again');
  await tap(readBtn());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page')).count_today === 0), 'tap 4: unchecked again');

  T.section('A2 - a habit with several glasses');
  const glass = n => habitCard(pb, 'Drink water').locator(`[data-act="hlog"][data-n="${n}"]`).first();
  const water = async () => (await habitOf('bob', 'Drink water')).count_today;
  await tap(glass(2));  T.ok(await until(async () => (await water()) === 2), 'tap glass 2: two of three');
  await tap(glass(2));  T.ok(await until(async () => (await water()) === 1), 'tap glass 2 again: one of three (the last filled glass takes one back)');
  await tap(glass(1));  T.ok(await until(async () => (await water()) === 0), 'tap glass 1 while only one is filled: none');
  await tap(glass(3));  T.ok(await until(async () => (await water()) === 3), 'tap glass 3: all three - the habit is done');
  T.eq((await habitOf('bob', 'Drink water')).state_today, 'done', '...and the server calls it done');
  const undo = habitCard(pb, 'Drink water').locator('[data-act="hlog"][data-undo="1"]').first();
  T.ok(await visible(undo), 'an explicit Undo is offered once something is checked');
  await tap(undo);      T.ok(await until(async () => (await water()) === 2), 'Undo takes one back (3 -> 2)');
  await tap(undo);      T.ok(await until(async () => (await water()) === 1), 'Undo again (2 -> 1)');
  await tap(undo);      T.ok(await until(async () => (await water()) === 0), 'Undo again (1 -> 0)');
  T.ok(!(await visible(undo)), 'with nothing checked there is nothing to undo');

  T.section('A3 - an edit in between (the owner edited the habit, then tapped), and the same on the Habits tab');
  await tap(readBtn());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page')).count_today === 1), 'checked');
  await habitCard(pb, 'Read a page').locator('.pl-ib[data-act="habit"]').first().click();
  await pb.waitForSelector('#plSheet:not([hidden]) #plTitle2', { timeout: 5000 });
  await pb.fill('#plTitle2', 'Read a page (edited)');
  await L.save(pb); await settle(pb); await sleep(400);
  T.ok(await until(async () => !!(await habitOf('bob', 'Read a page (edited)'))), 'the edit was saved');
  const readBtn2 = () => habitCard(pb, 'Read a page (edited)').locator('[data-act="hlog"]').first();
  await tap(readBtn2());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page (edited)')).count_today === 0), 'after the edit one tap still unchecks it');
  await goTab(pb, 'habits');
  await tap(readBtn2());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page (edited)')).count_today === 1), 'on the Habits tab: a tap checks it');
  await tap(readBtn2());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page (edited)')).count_today === 0), 'on the Habits tab: the next tap unchecks it');
  await goTab(pb, 'today');
  await tap(readBtn2());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page (edited)')).count_today === 1), 'back on Today after the Habits tab: checked');
  await goTab(pb, 'habits');
  await tap(readBtn2());
  T.ok(await until(async () => (await habitOf('bob', 'Read a page (edited)')).count_today === 0), 'checked on Today, unchecked on the Habits tab');
  await shot(pb, 'ck-habits-390');

  T.section('A4 - what the habit says about itself');
  await goTab(pb, 'habits');
  const lab0 = await habitCard(pb, 'Read a page (edited)').locator('[data-act="hlog"]').first().evaluate(e => e.textContent.trim() + ' | ' + (e.getAttribute('aria-label') || '') + ' | ' + e.getAttribute('aria-pressed'));
  await tap(readBtn2());
  const lab1 = await habitCard(pb, 'Read a page (edited)').locator('[data-act="hlog"]').first().evaluate(e => e.textContent.trim() + ' | ' + (e.getAttribute('aria-label') || '') + ' | ' + e.getAttribute('aria-pressed'));
  T.ok(/Mark done/i.test(lab0) && /false/.test(lab0), `unchecked: it invites a tap and says it is not pressed (${lab0})`);
  T.ok(/Done today/i.test(lab1) && /undo/i.test(lab1) && /true/.test(lab1), `checked: it says it is done AND how to take it back (${lab1})`);
  await shot(pb, 'ck-habits-checked-390');
  await ctxB.close();

  // =========================================================================================== B  tasks
  T.section('B - tasks: checked on the Tasks tab, the row must stay where it was checked');
  await api('ann', 'POST', '/tasks', { title: 'Alpha task', client_key: 'a-alpha' });                         // no date
  await api('ann', 'POST', '/tasks', { title: 'Bravo task', due_date: TODAY, client_key: 'a-bravo' });        // due today
  await api('ann', 'POST', '/tasks', { title: 'Charlie task', due_date: TODAY, client_key: 'a-charlie' });
  const ctxA = await ctxFor(browser, 'ann');
  const pa = await boot(ctxA, '/my-day/tasks');                                                                // All view: the Tasks tab now holds ITS copy
  const chk = title => row(pa, title).locator('.pl-chk').first();
  await tap(chk('Alpha task'));
  T.ok(await until(async () => (await taskOf('ann', 'Alpha task')).status === 'done'), 'checked: the task is done');
  T.ok(await visible(row(pa, 'Alpha task')), 'the row is STILL on the list it was checked in (it used to vanish, so there was nothing to uncheck)');
  T.ok(await hasClass(chk('Alpha task'), 'done'), '...with a filled check');
  T.ok(await row(pa, 'Alpha task').locator('.pl-ttl.done').count() > 0, '...and its words struck through');
  await shot(pa, 'ck-tasks-checked-390');
  await tap(chk('Alpha task'));
  T.ok(await until(async () => (await taskOf('ann', 'Alpha task')).status === 'open'), 'tap again: open again');
  T.ok(!(await hasClass(chk('Alpha task'), 'done')), '...and the check is empty');

  T.section('B1b - a finished task opened with its pencil can be put back from there');
  await tap(chk('Alpha task'));
  T.ok(await until(async () => (await taskOf('ann', 'Alpha task')).status === 'done'), 'Alpha checked again');
  await tap(row(pa, 'Alpha task').locator('.pl-ib[data-act="task"]').first(), 'the pencil of Alpha');
  await pa.waitForSelector('#plSheet:not([hidden]) #plTitle2', { timeout: 5000 }).catch(() => {});
  const reopenBtn = pa.locator('#plSheet [data-act="treopen"]').first();
  T.ok(await visible(reopenBtn), 'its sheet offers Reopen');
  T.ok(!(await visible(pa.locator('#plSheet [data-act="tskip"]').first())), '...and not Skip (it is already finished)');
  await tap(reopenBtn, 'Reopen in the sheet');
  T.ok(await until(async () => (await taskOf('ann', 'Alpha task')).status === 'open'), 'Reopen puts it back');
  T.ok(!(await L.sheetOpen(pa)), '...and the sheet closes');
  await tap(row(pa, 'Alpha task').locator('.pl-ib[data-act="task"]').first(), 'the pencil of Alpha (open)');
  await pa.waitForSelector('#plSheet:not([hidden]) #plTitle2', { timeout: 5000 }).catch(() => {});
  T.ok(!(await visible(pa.locator('#plSheet [data-act="treopen"]').first())) && await visible(pa.locator('#plSheet [data-act="tskip"]').first()), 'an open task offers Skip, not Reopen');
  await pa.click('#plSheet [data-act="cancel"]');

  T.section('B2 - the stale-copy sequence: Tasks tab, then Today, check, uncheck');
  await goTab(pa, 'today');
  T.ok(await visible(row(pa, 'Bravo task')), 'Today lists a task due today');
  await tap(chk('Bravo task'));
  T.ok(await until(async () => (await taskOf('ann', 'Bravo task')).status === 'done'), 'checked on Today');
  T.ok(await visible(row(pa, 'Bravo task')), 'it moved to "Done today" and is still on screen');
  T.ok(/done today/i.test(await body(pa)), 'there is a "Done today" section (the headings are upper-cased by the CSS)');
  await tap(chk('Bravo task'));
  T.ok(await until(async () => (await taskOf('ann', 'Bravo task')).status === 'open'), 'unchecked on Today (before the fix the Tasks tab\'s old copy said "open" and the tap re-sent "check")');
  await tap(chk('Bravo task'));
  T.ok(await until(async () => (await taskOf('ann', 'Bravo task')).status === 'done'), 'checked again');
  T.ok(await until(async () => /done today/i.test(await notif(pa)) && /undo|again/i.test(await notif(pa))), `checking a task on Today moves it, so a hint says where it went and how to undo (got ${JSON.stringify(await notif(pa))})`);
  await goTab(pa, 'tasks');
  T.ok(await visible(row(pa, 'Bravo task')), 'on the Tasks tab the finished task is still listed (All)');
  T.ok(await hasClass(chk('Bravo task'), 'done'), '...as done');
  await tap(chk('Bravo task'));
  T.ok(await until(async () => (await taskOf('ann', 'Bravo task')).status === 'open'), 'unchecked on the Tasks tab, though it was checked on Today');
  await goTab(pa, 'today');
  T.ok(!(await hasClass(chk('Bravo task'), 'done')), 'back on Today it is open (no old copy comes back)');
  await tap(chk('Bravo task'));
  await goTab(pa, 'tasks');
  await tap(chk('Bravo task'));
  T.ok(await until(async () => (await taskOf('ann', 'Bravo task')).status === 'open'), 'checked on Today, unchecked on the Tasks tab, again');
  await shot(pa, 'ck-tasks-390');

  T.section('B3 - the Today chip of the Tasks tab, a skipped task, the Done chip');
  const tv = v => pa.locator(`[data-act="tview"][data-v="${v}"]`).first();
  await tap(chk('Charlie task'));
  T.ok(await until(async () => (await taskOf('ann', 'Charlie task')).status === 'done'), 'Charlie checked');
  await tap(tv('today')); await settle(pa);
  T.ok(await visible(row(pa, 'Charlie task')), 'the Today chip still lists a task finished today, struck through');
  await tap(chk('Charlie task'));
  T.ok(await until(async () => (await taskOf('ann', 'Charlie task')).status === 'open'), '...and unchecks it there');
  const charlie = await taskOf('ann', 'Charlie task');
  await api('ann', 'POST', `/tasks/${charlie.id}/skip`, {});
  await tap(tv('all')); await settle(pa);
  T.ok(await visible(row(pa, 'Charlie task')), 'a skipped task is listed too');
  T.ok(await hasClass(chk('Charlie task'), 'skip'), '...marked as skipped (dashed check)');
  await tap(chk('Charlie task'));
  T.ok(await until(async () => (await taskOf('ann', 'Charlie task')).status === 'open'), 'a tap on a skipped task puts it back (open)');
  await tap(chk('Charlie task'));
  await tap(tv('done')); await settle(pa);
  T.ok(await visible(row(pa, 'Charlie task')), 'the Done chip lists what was finished');
  await tap(chk('Charlie task'));
  T.ok(await until(async () => (await taskOf('ann', 'Charlie task')).status === 'open'), 'and unchecks from there');
  await ctxA.close();

  T.section('B4 - a task finished five days ago: not on All, but in the Done chip, and still uncheckable');
  const ctxH = await ctxFor(browser, 'hal');
  const ph = await boot(ctxH, '/my-day/tasks');
  T.ok(!(await body(ph)).includes('Old finished task'), 'All keeps the last two days only: the old one is not there');
  await tap(ph.locator('[data-act="tview"][data-v="done"]').first()); await settle(ph);
  T.ok(await visible(row(ph, 'Old finished task')), 'the Done chip lists it');
  await tap(row(ph, 'Old finished task').locator('.pl-chk').first());
  T.ok(await until(async () => (await taskOf('hal', 'Old finished task')).status === 'open'), 'and a tap puts it back');

  T.section('B5 - a repeating task: today\'s occurrence checks and unchecks');
  await api('eve', 'POST', '/tasks', { title: 'Daily stretch', due_date: TODAY, repeat: { freq: 'daily', interval: 1 }, client_key: 'e-stretch' });
  const ctxE = await ctxFor(browser, 'eve');
  const pe = await boot(ctxE, '/my-day/tasks');
  const occ = () => row(pe, 'Daily stretch').locator('.pl-chk').first();
  T.ok(await until(async () => (await tasksApi('eve')).some(x => x.title === 'Daily stretch' && !x.is_series)), 'an occurrence exists');
  await goTab(pe, 'today');
  await tap(occ());
  T.ok(await until(async () => (await tasksApi('eve')).some(x => x.title === 'Daily stretch' && x.status === 'done')), 'the occurrence is checked');
  await tap(occ());
  T.ok(await until(async () => !(await tasksApi('eve')).some(x => x.title === 'Daily stretch' && x.status === 'done' && !x.is_series)), 'and unchecked');
  await ctxE.close();

  // =========================================================================================== C  goals
  T.section('C - goals: a check on the goal row');
  await api('cat', 'POST', '/goals', { title: 'Learn Hindi poetry', milestones: ['Step one', 'Step two'], client_key: 'c-g1' });
  const ctxC = await ctxFor(browser, 'cat');
  const pc = await boot(ctxC, '/my-day/goals');
  const gchk = () => goalCard(pc, 'Learn Hindi poetry').locator('[data-act="gchk"]').first();
  T.ok(await visible(gchk()), 'every goal in the list has a check');
  if (await visible(gchk())) {
    await tap(gchk());
    T.ok(await until(async () => (await goalOf('cat', 'Learn Hindi poetry')).status === 'done'), 'checked: the goal is finished');
    T.ok(await visible(goalCard(pc, 'Learn Hindi poetry')), '...and it stays in the list');
    T.ok(await hasClass(gchk(), 'done'), '...with a filled check');
    T.ok(/finished/i.test(await goalCard(pc, 'Learn Hindi poetry').innerText()), '...and says Finished');
    await shot(pc, 'ck-goals-checked-390');
    await tap(gchk());
    T.ok(await until(async () => (await goalOf('cat', 'Learn Hindi poetry')).status === 'active'), 'tap again: the goal is active again');
    T.ok(!(await hasClass(gchk(), 'done')), '...and the check is empty');
  }
  await shot(pc, 'ck-goals-390');

  T.section('C2 - inside a goal: its steps, and Done / Reopen');
  await tap(goalCard(pc, 'Learn Hindi poetry').locator('.pl-gcard').first());
  await pc.waitForFunction(() => document.querySelector('[data-act="msadd"]'), null, { timeout: 8000 }).catch(() => {});
  const step = t => pc.locator('#plBody .pl-ms', { hasText: t }).locator('[data-act="ms"]').first();
  const msStatus = async t => ((await goalOf('cat', 'Learn Hindi poetry')).milestones.find(m => m.title === t) || {}).status;
  await tap(step('Step one'));
  T.ok(await until(async () => (await msStatus('Step one')) === 'done'), 'a step is checked');
  const p1 = (await goalOf('cat', 'Learn Hindi poetry')).progress;
  T.ok(p1 > 0, `...and the goal's progress moved (${p1}%)`);
  await tap(step('Step one'));
  T.ok(await until(async () => (await msStatus('Step one')) === 'open'), 'the same tap unchecks it');
  T.eq((await goalOf('cat', 'Learn Hindi poetry')).progress, 0, '...and the progress goes back');
  await tap(step('Step two')); await tap(step('Step one'));
  T.ok(await until(async () => (await msStatus('Step one')) === 'done' && (await msStatus('Step two')) === 'done'), 'both steps checked');
  await tap(step('Step two'));
  T.ok(await until(async () => (await msStatus('Step two')) === 'open'), 'one of them unchecked again');
  const doneBtn = pc.locator('[data-act="gstat"][data-a="done"]').first();
  await tap(doneBtn);
  T.ok(await until(async () => (await goalOf('cat', 'Learn Hindi poetry')).status === 'done'), 'Done in the goal finishes it');
  const reopen = pc.locator('[data-act="gstat"][data-a="resume"]').first();
  T.ok(await visible(reopen) && /reopen/i.test(await reopen.innerText()), '...and the button becomes Reopen');
  await tap(reopen);
  T.ok(await until(async () => (await goalOf('cat', 'Learn Hindi poetry')).status === 'active'), 'Reopen puts it back');
  await ctxC.close();

  // =========================================================================================== D  reminders
  T.section('D - reminders: checked on All, on Today, on Coming up, in History');
  const later = new Date(Date.now() + 5 * 3600 * 1000);
  for (const t of ['Remind alpha', 'Remind bravo', 'Remind charlie']) await api('dan', 'POST', '/reminders', { title: t, time: hhmm(later), client_key: 'd-' + t });
  const ctxD = await ctxFor(browser, 'dan');
  const pd = await boot(ctxD, '/my-day/reminders');
  const rchk = t => row(pd, t).locator('.pl-chk').first();
  await tap(rchk('Remind alpha'));
  T.ok(await until(async () => (await remOf('dan', 'Remind alpha')).status === 'done'), 'checked on All: done');
  T.ok(await visible(row(pd, 'Remind alpha')) && await hasClass(rchk('Remind alpha'), 'done'), '...the row stays, with a filled check');
  await tap(rchk('Remind alpha'));
  T.ok(await until(async () => ['scheduled', 'sent'].includes((await remOf('dan', 'Remind alpha')).status)), 'unchecked on All');
  await goTab(pd, 'today');
  T.ok(await visible(row(pd, 'Remind bravo')), 'Today lists the reminders');
  await tap(rchk('Remind bravo'));
  T.ok(await until(async () => (await remOf('dan', 'Remind bravo')).status === 'done'), 'checked on Today');
  T.ok(await visible(row(pd, 'Remind bravo')), '...and it stays on Today, ticked');
  await tap(rchk('Remind bravo'));
  T.ok(await until(async () => ['scheduled', 'sent'].includes((await remOf('dan', 'Remind bravo')).status)), 'unchecked on Today');
  await tap(rchk('Remind bravo'));
  await goTab(pd, 'reminders');
  await tap(rchk('Remind bravo'));
  T.ok(await until(async () => ['scheduled', 'sent'].includes((await remOf('dan', 'Remind bravo')).status)), 'checked on Today, unchecked on the Reminders tab');
  const rv = v => pd.locator(`[data-act="rview"][data-v="${v}"]`).first();
  await tap(rv('upcoming')); await settle(pd);
  await tap(rchk('Remind charlie'));
  T.ok(await until(async () => (await remOf('dan', 'Remind charlie')).status === 'done'), 'checked on Coming up');
  T.ok(await until(async () => /all/i.test(await notif(pd)) && /undo|tap/i.test(await notif(pd))), `...it leaves that list, so a hint says where it went and how to undo (got ${JSON.stringify(await notif(pd))})`);
  await tap(rv('all')); await settle(pd);
  T.ok(await visible(row(pd, 'Remind charlie')), 'it is on All');
  await tap(rchk('Remind charlie'));
  T.ok(await until(async () => ['scheduled', 'sent'].includes((await remOf('dan', 'Remind charlie')).status)), '...and unchecks there');
  await ctxD.close();

  T.section('D2 - History: a reminder ticked four days ago can still be unticked');
  const pr = await boot(await ctxFor(browser, 'hal'), '/my-day/reminders');
  T.ok(!(await body(pr)).includes('Old ticked reminder'), 'All shows the last two days only');
  await tap(pr.locator('[data-act="rview"][data-v="history"]').first()); await settle(pr);
  T.ok(await visible(row(pr, 'Old ticked reminder')), 'History lists it');
  await tap(row(pr, 'Old ticked reminder').locator('.pl-chk').first());
  T.ok(await until(async () => (await remOf('hal', 'Old ticked reminder')).status !== 'done'), 'and a tap puts it back on the list');

  // =========================================================================================== E  Hindi + accessibility
  T.section('E - Hindi, and every check says what a tap will do');
  await api('gus', 'POST', '/tasks', { title: 'हिंदी काम', due_date: TODAY, client_key: 'g-t1' });
  await api('gus', 'POST', '/habits', { title: 'योग', target: 1, schedule: { days: 'daily', times: [] }, client_key: 'g-h1' });
  await api('gus', 'POST', '/goals', { title: 'हिंदी लक्ष्य', client_key: 'g-g1' });
  const ctxG = await ctxFor(browser, 'gus', { lang: 'hi' });
  const pg = await boot(ctxG, '/my-day/tasks');
  const name = loc => loc.first().getAttribute('aria-label');
  const n0 = await name(row(pg, 'हिंदी काम').locator('.pl-chk'));
  await tap(row(pg, 'हिंदी काम').locator('.pl-chk').first());
  const n1 = await name(row(pg, 'हिंदी काम').locator('.pl-chk'));
  T.ok(n0 && n1 && n0 !== n1 && /हिंदी काम/.test(n0) && /हिंदी काम/.test(n1), `a task's check is named, and the name changes with its state (${n0} / ${n1})`);
  await goTab(pg, 'goals');
  const gname = await name(pg.locator('#plBody .pl-gwrap [data-act="gchk"]'));
  T.ok(!!gname && /हिंदी लक्ष्य/.test(gname), `a goal's check is named in Hindi (${gname})`);
  await goTab(pg, 'habits');
  const hn = await pg.locator('#plBody .pl-habit [data-act="hlog"]').first().evaluate(e => (e.textContent + ' ' + (e.getAttribute('aria-label') || '')).trim());
  await shot(pg, 'ck-hi-habits-390');
  await goTab(pg, 'goals'); await shot(pg, 'ck-hi-goals-390'); await goTab(pg, 'tasks'); await shot(pg, 'ck-hi-tasks-390'); await goTab(pg, 'habits');
  T.ok(/[ऀ-ॿ]/.test(hn), `the habit's check speaks Hindi (${hn})`);
  const parity = await pg.evaluate(() => { const e = Object.keys(PL._txt.en), h = Object.keys(PL._txt.hi); return { onlyEn: e.filter(k => !h.includes(k)), onlyHi: h.filter(k => !e.includes(k)) }; });
  T.eq(parity, { onlyEn: [], onlyHi: [] }, 'every My Day string exists in both languages');
  const newKeys = ['hMarkDone', 'hDoneToday', 'hUndo', 'gDoneToast', 'gReopenToast', 'taskDoneMoved', 'remDoneMoved'];
  const missing = await pg.evaluate(ks => ks.filter(k => !PL._txt.en[k] || !PL._txt.hi[k]), newKeys);
  T.eq(missing, [], 'the new words exist in English and Hindi');
  const gendered = await pg.evaluate(ks => ks.map(k => PL._txt.hi[k]).filter(s => /रहे हो|सकते हो|करोगे|बोलोगे|चाहते हो/.test(s || '')), newKeys);
  T.eq(gendered, [], 'no gendered verb forms toward the learner in the new Hindi');
  await ctxG.close();

  // =========================================================================================== F  layout
  T.section('F - layout of the new controls');
  await api('fay', 'POST', '/tasks', { title: 'Layout task with a rather long name to see how the row wraps on a narrow phone', due_date: TODAY, client_key: 'f-t1' });
  await api('fay', 'POST', '/habits', { title: 'Layout habit', target: 1, schedule: { days: 'daily', times: [] }, client_key: 'f-h1' });
  await api('fay', 'POST', '/habits', { title: 'Layout glasses', target: 4, schedule: { days: 'daily', times: [] }, client_key: 'f-h2' });
  await api('fay', 'POST', '/goals', { title: 'Layout goal with a rather long title to see how the card wraps', milestones: ['One'], client_key: 'f-g1' });
  for (const [label, vp] of [['360x640', { width: 360, height: 640 }], ['390x844', { width: 390, height: 844 }], ['1280x800', { width: 1280, height: 800 }]]) {
    const cx = await ctxFor(browser, 'fay', { viewport: vp });
    const pf = await boot(cx, '/my-day/goals');
    for (const tab of ['goals', 'habits', 'tasks', 'today']) {
      await goTab(pf, tab);
      if (tab === 'habits') { const b = pf.locator('#plBody .pl-habit [data-act="hlog"]').first(); await b.click(); await sleep(500); }      // the checked look too
      const r = await pf.evaluate(() => {
        const out = { overflow: [], small: [], noname: [] };
        if (document.documentElement.scrollWidth > innerWidth + 1) out.overflow.push('document ' + document.documentElement.scrollWidth + '>' + innerWidth);
        for (const e of document.querySelectorAll('#plBody *')) {
          const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || e.closest('[hidden]')) continue;
          const b = e.getBoundingClientRect(); if (b.width && b.height && (b.right > innerWidth + 2 || b.left < -2)) out.overflow.push(e.tagName + '.' + e.className + ' ' + Math.round(b.left) + '..' + Math.round(b.right));
        }
        for (const e of document.querySelectorAll('#plBody .pl-chk, #plBody [data-act="hlog"], #plBody [data-act="gchk"], #plBody .pl-ib')) {
          const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || e.closest('[hidden]')) continue;
          const b = e.getBoundingClientRect(); if (!b.width || !b.height) continue;
          if (b.height < 39.5 || b.width < 39.5) out.small.push((e.dataset.act || e.className) + ' ' + Math.round(b.width) + 'x' + Math.round(b.height));
          if (!(e.getAttribute('aria-label') || e.textContent || '').trim()) out.noname.push(e.outerHTML.slice(0, 70));
        }
        return out;
      });
      T.eq(r.overflow, [], `${label} ${tab}: no horizontal overflow`);
      T.eq(r.small, [], `${label} ${tab}: every check / tool is at least 40 x 40`);
      T.eq(r.noname, [], `${label} ${tab}: every check has a name`);
      await shot(pf, `ck-${tab}-${label}`);
    }
    await cx.close();
  }

  T.section('the whole run');
  T.eq(ERRS, [], 'no console error, page error or unhandled rejection in the whole run');
  await browser.close();
  process.exit(T.done() ? 0 : 1);
})().catch(e => { console.error('SPEC CRASHED:', e); process.exit(2); });
