'use strict';
/*
 * The sweep: every screen a learner can reach, as each kind of learner, on a phone, a small phone and a desktop, in English and Hindi - photographed and measured.
 *   tests/audit/spec.sh walk.cjs                       (all phases)     AUD_ENV="PHASES=A,C" tests/audit/spec.sh walk.cjs
 */
const { chromium } = require('playwright');
const A = require('./lib.cjs').create('walk');
const { sleep } = A;

const PHASES = (process.env.PHASES || 'A,B,C,D,E,F,G').split(',');
const ROUTES = [
  ['/', 'home'], ['/practice', 'practice'], ['/daily-talk', 'daily', { wait: 3200 }], ['/face-to-face', 'facetoface', { wait: 3200 }], ['/interview', 'interview-setup'],
  ['/learn', 'learn', { wait: 2500 }], ['/learning-journey', 'journey'], ['/profile', 'profile'], ['/leaderboard', 'ranks'], ['/league', 'league'], ['/achievements', 'achievements'],
  ['/interview-reports', 'interview-reports'], ['/career-path', 'career'], ['/keys', 'keys'], ['/subscribe', 'subscribe'], ['/about', 'about'], ['/home-chat', 'homechat', { wait: 3200 }],
  ['/my-day', 'myday-today'], ['/my-day/tasks', 'myday-tasks'], ['/my-day/goals', 'myday-goals'], ['/my-day/habits', 'myday-habits'], ['/my-day/reminders', 'myday-reminders'],
  ['/my-day/settings', 'myday-settings'],
  ['/resume-interview', 'jip-hub'], ['/resume-interview/resume', 'jip-resume'], ['/resume-interview/job', 'jip-job'], ['/resume-interview/settings', 'jip-settings'],
  ['/grammar', 'grammar-overview'], ['/grammar/mistakes', 'grammar-mistakes'], ['/grammar/sentences', 'grammar-sentences'], ['/grammar/practice', 'grammar-practice'],
  ['/grammar/rules', 'grammar-rules'], ['/grammar/settings', 'grammar-settings'], ['/practice-room', 'practice-room'],
];
const SMALL_SET = new Set(['home', 'practice', 'daily', 'journey', 'myday-today', 'grammar-overview', 'keys', 'subscribe', 'ranks', 'jip-hub', 'practice-room', 'profile']);
const HINDI_SET = new Set(['home', 'homechat', 'about', 'myday-today', 'myday-tasks', 'practice', 'journey', 'practice-room', 'grammar-overview', 'jip-hub']);

const ymd = (d = 0) => new Date(Date.now() + d * 864e5).toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

async function seedPlanner(who) {
  const ck = () => Math.random().toString(36).slice(2, 10);
  const post = (p, b) => A.api(who, '/planner' + p, 'POST', Object.assign({ client_key: ck() }, b));
  await post('/tasks', { title: 'Revise tenses for 20 minutes', priority: 1, remind: 'none', due_date: ymd(0), due_time: '18:00', pin: true });
  await post('/tasks', { title: "Practise 'Tell me about yourself' aloud", priority: 2, remind: 'none', due_date: ymd(0) });
  await post('/tasks', { title: 'Finish slides for the project demo', priority: 2, remind: 'none', due_date: ymd(1), due_time: '11:00' });
  await post('/tasks', { title: 'Message the placement cell about the drive', priority: 3, remind: 'none' });
  await post('/tasks', { title: 'Read one English news article', priority: 3, remind: 'none', repeat: { freq: 'daily', interval: 1 } });
  await post('/habits', { title: 'Speak English for 10 minutes', target: 10, unit: 'min', partial_ok: true, schedule: { days: 'daily', times: ['19:00'] } });
  await post('/habits', { title: 'Learn 3 new words', target: 3, unit: 'words', partial_ok: true, schedule: { days: 'daily', times: [] } });
  await post('/goals', { title: 'Crack my first campus interview', why: 'I want a software job and my family is counting on me.', target_date: ymd(30), daily_minutes: 20,
    milestones: ['Finish my resume', 'Do 5 mock interviews', 'Apply to 10 companies', 'Prepare a 60-second introduction'] });
  await post('/goals', { title: 'Speak without translating in my head', why: '', target_date: null, daily_minutes: 15, milestones: [] });
  await post('/reminders', { title: 'Call Papa about the fee form', date: ymd(0), time: '20:30' });
  await post('/reminder-rules', { title: 'Morning English practice', time: '07:30', days: [0, 1, 2, 3, 4] });
}

async function sweep(browser, who, vp, lang, tag, filter) {
  const c = await A.ctx(browser, who, { viewport: vp, lang });
  for (const [p, name, o] of ROUTES) {
    if (filter && !filter.has(name)) continue;
    const page = await A.open(c, p, { settle: (o && o.wait) || 1100 });
    const sid = await A.screenId(page);
    const r = await A.capture(page, name, { tag });
    console.log(`${tag.padEnd(14)} ${p.padEnd(28)} -> ${sid.padEnd(14)} tiny:${String(r.tinyText.count).padStart(3)} small:${String(r.smallTargets.length).padStart(2)} lowc:${String(r.contrast.low).padStart(2)} noName:${r.noName.length} overflow:${r.pageOverflowX || r.wrapOverflowX || r.sticksOut.length ? 'YES' : 'no'} h:${r.scroll ? r.scroll.h : '-'}${r.console.some(x => /pageerror|error:/.test(x)) ? '  CONSOLE-ERR' : ''}${r.bad.length ? '  HTTP ' + r.bad.join(',') : ''}`);
    await page.close();
  }
  await c.close();
}

(async () => {
  const browser = await chromium.launch();
  await A.settings({});
  if (PHASES.includes('A') || PHASES.includes('B') || PHASES.includes('C') || PHASES.includes('D')) await seedPlanner('active');
  if (PHASES.includes('A')) await sweep(browser, 'active', { width: 390, height: 844 }, 'en', 'active-390');
  if (PHASES.includes('B')) await sweep(browser, 'active', { width: 360, height: 740 }, 'en', 'active-360', SMALL_SET);
  if (PHASES.includes('C')) await sweep(browser, 'active', { width: 1280, height: 900 }, 'en', 'active-1280');
  if (PHASES.includes('D')) { await A.setLang('active', 'hi'); await sweep(browser, 'active', { width: 390, height: 844 }, 'hi', 'active-hi-390', HINDI_SET); await A.setLang('active', 'en'); }
  if (PHASES.includes('E')) { await sweep(browser, 'keyed', { width: 390, height: 844 }, 'en', 'keyed-390'); }
  if (PHASES.includes('G')) { await sweep(browser, 'lapsed', { width: 390, height: 844 }, 'en', 'lapsed-390', new Set(['home', 'journey', 'ranks'])); }
  A.save('walk');
  await browser.close();
})();
