'use strict';
/*
 * A stateful in-memory stand-in for the Resume Interview API (/rinterview/*) + /me, written FROM THE CONTRACT
 * (client <-> server JSON shapes, endpoints, error codes), not from the real server. It is shared by every browser
 * spec: documents, sessions, queued questions, answers, feedback, finish, export, delete-all, plus fault injection
 * (`faults`) so the failure branches (502, 202 pending, dropped connection, 409 ...) can be driven on demand.
 *
 * `wrapDetail` = true answers errors the FastAPI way ({"detail": {"error": code}} / {"detail": "code"}); false answers
 * with the bare contract shape ({"error": code}). The client must cope with both, so the specs run in each mode.
 */
const crypto = require('crypto');

const LIMITS = { max_upload_bytes: 5 * 1024 * 1024, resume_min_chars: 120, jd_min_chars: 120, max_answer_sec: 180,
  min_answer_words: 25, min_answer_sec: 10, finish_min: 3, max_answers: 40, resumes: 10, jds: 15 };

const QUESTIONS = [
  ['Tell me about the Power BI dashboard you built for the sales team.', 'Your resume says "Built dashboards for the sales team"; the job asks for dashboarding.'],
  ['How do you use SQL to find a data-quality problem?', 'The job lists SQL as a must-have and your resume mentions it once.'],
  ['Describe a time you explained a number to a stakeholder who disagreed.', 'The job asks for stakeholder communication.'],
  ['What would you check first if a weekly report suddenly showed a 30% drop?', 'A common analyst scenario for this role.'],
  ['Why do you want to work in analytics rather than engineering?', 'Motivation for the role.'],
  ['Tell me about a project where you had to learn a tool quickly.', 'Learning speed matters for this job.'],
  ['What is the most useful chart you have made, and why?', 'Dashboards are central to this role.'],
  ['How do you decide what NOT to put on a dashboard?', 'Judgement about scope.'],
];

const RESUME_TEXT = `Asha Rao
Data Analyst
asha.rao@example.com  +91 98765 43210  https://www.linkedin.com/in/asharao

Experience
- Built dashboards for the sales team using Excel and a little Tableau.
- Wrote SQL queries to pull weekly numbers and fix duplicate rows.
- Presented findings to the stakeholder group every month.

Education
B.Com, Delhi University, 2022

Skills: SQL, Excel, Tableau, communication`;

const RESUME_IMPROVED = RESUME_TEXT + `
- Built Power BI dashboards for the sales team and cut report time by 40%.`;

const JD_TEXT = `Data Analyst - Acme Corp
We are hiring a Data Analyst to own our weekly reporting.
Requirements
- SQL for querying databases
- Power BI dashboards
- Stakeholder communication
- Python scripting (nice)
- A/B testing (nice)`;

const TRANSCRIPT_GOOD = 'So in my last role I make dashboard for the sales team and uh basically I used SQL to pull the weekly numbers and then I checked the duplicates before sharing with the stakeholders every Monday morning and they liked it because the report was ready earlier than before';
const TRANSCRIPT_SHORT = 'I built one dashboard once.';

const nowIso = () => new Date().toISOString();
const sha = s => crypto.createHash('sha1').update(String(s)).digest('hex');
const words = s => String(s || '').split(/\s+/).filter(Boolean).length;
const clone = o => JSON.parse(JSON.stringify(o));

function redact(text) {
  const r = { email: 0, phone: 0, link: 0, aadhaar: 0, pan: 0, name: 0, personal_block: 0 };
  let t = String(text);
  t = t.replace(/[\w.+-]+@[\w-]+\.[\w.]+/g, () => { r.email++; return '[EMAIL]'; });
  t = t.replace(/\+?\d[\d\s-]{8,}\d/g, () => { r.phone++; return '[PHONE]'; });
  t = t.replace(/https?:\/\/\S+/g, () => { r.link++; return '[LINK]'; });
  return { text: t, r };
}

class Mock {
  constructor(opts = {}) {
    this.limits = Object.assign({}, LIMITS, opts.limits || {});
    this.wrapDetail = opts.wrapDetail !== false;
    this.strong = !!opts.strong;           // an interview with nothing to fix: no weaknesses, no focus points
    this.reportV1 = !!opts.reportV1;       // an old-format report (no coaching fields): the client must still show it
    this.lastFocus = null;                 // the focus points of the latest finished interview (what /state and an interview in progress hand out)
    this.xss = !!opts.xss;                 // put hostile markup in every string the server sends
    this.flag = true;                      // switch on (false -> every /rinterview endpoint answers 404, like the real server)
    this.userEmail = opts.email || 'learner@example.com';
    this.me = Object.assign({
      onboarded: true, email: this.userEmail, name: 'Asha Rao', role: 'user', office: false, has_keys: false,
      resume_interview: true, ri_server_stt: true, practice_room: false, planner: false, home_ai: false, bilingual: false,
      level_test: true, require_own_keys: false, progress: { xp: 40, coins: 0, streak_days: 2, sessions_today: 0, daily_goal: 3, badges: [], journey: { lang: 'en', current_level: 1 } },
      profile: { level: 'A2', goal: 'job', scores: {}, weak_areas: [] }, memory: {}, requests_left: 5, request_limit: 5,
    }, opts.me || {});
    this.reset();
  }

  reset() {
    this.seq = 100;
    this.docs = [];            // {…DOC, text, redactions, hash}
    this.sessions = [];        // {…SESSION fields, analysis, turns:[], counts…}
    this.calls = [];           // every handled request {method, path, query, headers, body}
    this.answers = [];         // every ACCEPTED answer {tid, body} (a too_short or 409 one is not stored)
    this.faults = {};          // see handle()
    this.delays = {};          // path-suffix -> ms
    this.sttQueue = [];        // canned /transcribe answers
    this.counters = {};
    this.exportBlob = null;
    this.deleted = false;
  }

  id() { return ++this.seq; }
  count(k) { this.counters[k] = (this.counters[k] || 0) + 1; return this.counters[k]; }
  fault(k) { if (this.faults[k] > 0) { this.faults[k]--; return true; } return false; }
  x(s) { return this.xss ? `${s} <img src=x onerror="window.__xss=(window.__xss||0)+1"><script>window.__xss=(window.__xss||0)+10</script>` : s; }

  docOut(d) { return { id: d.id, kind: d.kind, title: this.x(d.title), company: this.x(d.company || ''), source: d.source, chars: d.chars, pages: d.pages || 1, parent_id: d.parent_id || null, created_at: d.created_at }; }
  sessOut(s) {
    const answered = s.turns.filter(t => t.status === 'answered').length, real = s.turns.filter(t => t.real).length;
    return { id: s.id, title: this.x(s.title), status: s.status, settings: s.settings, resume_id: s.resume_id, jd_id: s.jd_id, overall: s.overall, created_at: s.created_at,
      started_at: s.started_at || null, finished_at: s.finished_at || null, answered, real };
  }
  counts(s) {
    const T = s.turns;
    return { asked: T.filter(t => t.status === 'asked').length, answered: T.filter(t => t.status === 'answered').length, real: T.filter(t => t.real).length,
      skipped: T.filter(t => t.status === 'skipped').length, queued: s.queue.length };
  }
  canFinish(s) { const real = s.turns.filter(t => t.real).length; return real >= 3 ? { ok: true, need: 0, reasons: [] } : { ok: false, need: 3 - real, reasons: ['need_real_answers'] }; }
  turnOut(t) {
    const o = { id: t.id, idx: t.idx, kind: t.kind || 'behavioural', source: t.source, question: this.x(t.question), why: this.x(t.why), status: t.status,
      answer: t.answer == null ? null : this.x(t.answer), answer_sec: t.answer_sec == null ? null : t.answer_sec, answer_words: t.answer_words == null ? null : t.answer_words,
      engine: t.engine || null, audio_device: t.audio_device || null, real: !!t.real, feedback_state: t.feedback_state, feedback: t.feedback ? this.fbOut(t.feedback) : null, asked_at: t.asked_at, answered_at: t.answered_at || null };
    return o;
  }
  fbOut(f) {
    const g = clone(f);
    if (this.xss) {
      g.worked = (g.worked || []).map(s => this.x(s));
      g.mistakes = (g.mistakes || []).map(m => ({ ...m, said: this.x(m.said), better: this.x(m.better), why: this.x(m.why) }));
      g.content_notes = (g.content_notes || []).map(s => this.x(s));
      g.improvements = (g.improvements || []).map(m => ({ issue: this.x(m.issue), how: this.x(m.how) }));
      if (g.better_answer) g.better_answer = this.x(g.better_answer);
      if (g.follow_up) g.follow_up = this.x(g.follow_up);
      if (g.resume_check) g.resume_check = { note: this.x(g.resume_check.note), quote: this.x(g.resume_check.quote) };
    }
    return g;
  }

  /* ---------------- analysis ---------------- */
  parseJd(text) {
    const reqs = [];
    String(text).split(/\r?\n/).forEach(line => {
      const m = line.match(/^\s*-\s+(.*)$/); if (!m) return;
      const nice = /\(nice\)\s*$/i.test(m[1]);
      reqs.push({ id: 'r' + (reqs.length + 1), text: m[1].replace(/\s*\(nice\)\s*$/i, ''), type: nice ? 'nice' : 'must' });
    });
    const head = String(text).split(/\r?\n/)[0] || 'Role';
    const mm = head.match(/^(.*?)\s*-\s*(.*)$/);
    return { reqs, role: { title: mm ? mm[1] : head, company: mm ? mm[2] : '', level: 'fresher' } };
  }
  analyse(resume, jd, prev) {
    const { reqs, role } = this.parseJd(jd.text);
    const rt = resume.text.toLowerCase();
    const out = reqs.map(r => {
      const toks = r.text.toLowerCase().split(/[^a-z0-9+#/]+/).filter(w => w.length >= 2);
      const hit = toks.filter(w => rt.includes(w));
      const status = toks.length && hit.length === toks.length ? 'met' : hit.length ? 'partial' : 'missing';
      const line = resume.text.split(/\r?\n/).find(l => hit.length && l.toLowerCase().includes(hit[0])) || '';
      return { id: r.id, text: this.x(r.text), type: r.type, status, evidence: status === 'missing' ? '' : this.x(line.replace(/^-\s*/, '').slice(0, 90)),
        note: status === 'missing' ? 'No clear line in your resume for this.' : status === 'partial' ? 'Mentioned, but not shown with a result.' : '' };
    });
    const w = { met: 1, partial: 0.5, missing: 0 }, wt = r => (r.type === 'must' ? 3 : 1);
    const num = out.reduce((a, r) => a + wt(r) * w[r.status], 0), den = out.reduce((a, r) => a + wt(r), 0) || 1;
    const score = reqs.length >= 4 ? Math.round(100 * num / den) : null;
    const band = score == null ? 'unknown' : score >= 80 ? 'strong' : score >= 60 ? 'good' : score >= 40 ? 'fair' : 'weak';
    const edits = out.filter(r => r.status !== 'met').slice(0, 5).map((r, i) => ({
      id: 'e' + (i + 1), priority: i === 0 ? 'high' : i === 1 ? 'medium' : 'low', type: r.status === 'partial' ? 'quantify' : 'add', section: 'Experience',
      from: r.status === 'partial' ? 'Wrote SQL queries to pull weekly numbers' : '', to: this.x(`Built ${r.text} for the sales team and cut report time by [X]%`),
      why: this.x(`The job asks for "${r.text}" and your resume does not show it clearly.`), only_if_true: true, req: [r.id], picked: false, addressed: false }));
    const a = { state: 'done', match_score: score, band, verdict: this.x(score == null ? '' : `${band[0].toUpperCase() + band.slice(1)} match: ${out.filter(r => r.status === 'met').length} of ${out.length} requirements are clear in your resume.`),
      role: { title: this.x(role.title), company: this.x(role.company), level: role.level }, requirements: out, edits, strengths: [this.x('Clear SQL and reporting experience')],
      notes: [{ issue: this.x('Your resume has no numbers yet'), fix: this.x('Add one result with a number to your best bullet.') }], low_match: score != null && score < 25, rules_version: 1, prev: null };
    if (prev) {
      const changed = out.filter(r => { const p = prev.requirements.find(x => x.id === r.id); return p && p.status !== r.status; }).map(r => ({ id: r.id, text: r.text, from: prev.requirements.find(x => x.id === r.id).status, to: r.status }));
      a.prev = { match_score: prev.match_score, band: prev.band, changed, addressed_edits: prev.edits.filter(e => changed.some(c => e.req.includes(c.id) && c.to === 'met')).map(e => e.id) };
      a.edits.forEach(e => { if (a.prev.addressed_edits.includes(e.id)) e.addressed = true; });
      // an edit that is now satisfied: keep it listed (as the contract says) with addressed:true
      prev.edits.forEach(e => { if (a.prev.addressed_edits.includes(e.id) && !a.edits.some(x => x.id === e.id)) a.edits.push({ ...e, addressed: true, picked: e.picked }); });
    }
    return a;
  }

  feedbackFor(s, tr, transcript, dur, words_) {
    const wc = words(transcript), good = wc >= 45;
    const bands = { content: good ? 'good' : 'fair', language: /make dashboard/.test(transcript) ? 'needs_work' : 'good', delivery: 'good' };
    const f = { bands, scores: { relevance: 70, specificity: 55, structure: 60, language: 52, delivery: 74 }, overall: 62, band: 'fair',
      worked: ['You gave a real example from your own work', 'You named SQL, which the job asks for'],
      mistakes: /make dashboard/.test(transcript) ? [{ type: 'tense', said: 'I make dashboard', better: 'I made a dashboard', why: 'Finished work is in the past tense.' }, { type: 'article', said: 'for the sales team and uh basically', better: 'for the sales team', why: 'Drop the filler before the next point.' }] : [],
      content_notes: ['No number or result in the answer.'], improvements: [{ issue: 'Add one result with a number', how: 'For example: "cut report time by 40%".' }],
      better_answer: 'In my last role I built a sales dashboard in Power BI. I used SQL to pull the weekly numbers and cut the report time by [X]%.', follow_up: 'What was the hardest data problem you solved?',
      resume_check: { note: 'Your resume says you built dashboards for the sales team.', quote: 'Built dashboards for the sales team' },
      evidence: { has_number: /\d/.test(transcript), has_result: false, has_example: true, named_item: /SQL/.test(transcript), sentences: 3, words: wc },
      delivery: { measured: !(tr.engine === 'gemini'), words: wc, seconds: dur, wpm: Math.round(wc / Math.max(dur, 1) * 60), pauses: tr.engine === 'gemini' ? null : 2, longest_pause: tr.engine === 'gemini' ? null : 2.4, restarts: tr.engine === 'gemini' ? null : 1,
        fillers: [{ word: 'uh', n: 1 }, { word: 'basically', n: 1 }] }, feedback_lang: s.settings.feedback_lang, genuine: true };
    return f;
  }

  coach(s, real) {
    if (this.strong) return { v: 2, habits: { n: real.length }, weaknesses: [], focus: [], progress: null };
    const x = t => this.x(t), first = real[0];
    const card = (key, severity, tracked, extra) => ({ key, title: x(extra.title), severity, seen: x(extra.seen), why: x(extra.why), how: extra.how.map(x), drill: x(extra.drill), goal: x(extra.goal), tracked,
      answers: extra.answers || [], examples: (extra.examples || []).map(e => ({ said: x(e.said), better: x(e.better), q: e.q })), items: (extra.items || []).map(x), ...(extra.model ? { model: extra.model } : {}) });
    const weaknesses = [
      card('no_number', 'high', true, { title: 'Add numbers to your stories', seen: `${real.length} of ${real.length} answers had no number or measurable result.`, why: 'Interviewers remember results they can picture.',
        how: ['Choose one number per project.', 'Use: I did X, which moved Y from A to B.', 'Give an honest estimate if unsure.'], drill: 'Write one sentence with a number for each project.', goal: 'A number in every project answer',
        answers: real.map(t => t.idx), model: first ? { q: first.idx, question: x(first.question), text: x('In my last role I built a sales dashboard in Power BI and cut report time by [X]%.') } : null }),
      card('grammar', 'medium', true, { title: 'Fix the grammar slip that keeps coming back', seen: 'The same kind of slip (\u201ctense\u201d) came back 2 times.', why: 'A repeated mistake is a habit, and habits are easy to fix.',
        how: ['Say each corrected sentence three times.', 'Make two new sentences.', 'Slow down on those words next time.'], drill: 'Say each corrected sentence below three times.', goal: 'No repeated grammar slip',
        answers: first ? [first.idx] : [], examples: [{ said: 'I make dashboard', better: 'I made a dashboard', q: first ? first.idx : 1 }] }),
      card('coverage', 'low', false, { title: 'Show the skills the job asks for', seen: '1 of the job\'s requirements were not touched by any of your answers.', why: 'The interviewer checks you against the requirements.',
        how: ['Prepare one example per missing requirement.', 'Say what you would learn if you have none.', 'Use the requirement\'s own words.'], drill: 'Give a 45-second answer about the first requirement.', goal: 'One example per key requirement', items: ['Power BI dashboards'] })];
    const focus = [{ key: 'no_number', title: x('Add numbers to your stories'), goal: x('A number in every project answer'), tracked: true, baseline: { count: real.length, of: real.length } },
      { key: 'grammar', title: x('Fix the grammar slip that keeps coming back'), goal: x('No repeated grammar slip'), tracked: true, baseline: { per100: 2.4 } }];
    const lf = this.lastFocus;
    const progress = lf ? { vs: { session_id: lf.session_id, title: x(lf.title), finished_at: lf.finished_at, overall: lf.overall, answers: 3 },
      items: [{ key: 'no_number', title: x('Add numbers to your stories'), goal: x('A number in every project answer'), was: x('3 of 3 answers'), now: x('1 of 3 answers'), status: 'improved', note: x('Better than last time.') },
              { key: 'grammar', title: x('Fix the grammar slip that keeps coming back'), goal: x('No repeated grammar slip'), was: x('2.4 per 100 words'), now: x('2.5 per 100 words'), status: 'same', note: x('About the same: keep working on it.') }],
      improved: 1, summary: x('1 of 2 focus points improved.') } : null;
    return { v: 2, habits: { n: real.length }, weaknesses, focus, progress };
  }

  report(s) {
    const real = s.turns.filter(t => t.real), per = s.turns.filter(t => t.status === 'answered' || t.status === 'skipped');
    const rep = { overall: 66, band: 'good', categories: [
        { key: 'relevance', label: 'Answering the question', score: 72 }, { key: 'specificity', label: 'Specifics and examples', score: 55 }, { key: 'structure', label: 'Structure', score: 61 },
        { key: 'language', label: 'Language', score: 58 }, { key: 'delivery', label: 'Delivery', score: s.turns.some(t => t.engine === 'gemini') ? null : 74 } ],
      answers: per.length, real: real.length, seconds: real.reduce((a, t) => a + (t.answer_sec || 0), 0), partial: s.turns.some(t => t.feedback_state === 'failed'), feedback_lang: s.settings.feedback_lang,
      coverage: { covered: [{ id: 'r1', text: this.x('SQL for querying databases') }], not_yet: [{ id: 'r2', text: this.x('Power BI dashboards') }], pct: 50 },
      patterns: [{ key: 'no_number', count: real.length, of: real.length, text: this.x(`No number in ${real.length} of ${real.length} answers`) }],
      strengths: [this.x('You always gave a real example')], fixes: [{ title: this.x('Add a result with a number'), tip: this.x('End each answer with what changed because of your work.'), examples: [{ said: this.x('I make dashboard'), better: this.x('I made a dashboard') }] }],
      redo: real.length ? { turn_id: real[0].id, idx: real[0].idx, question: this.x(real[0].question), score: 48, mistakes: [{ type: 'tense', said: this.x('I make dashboard'), better: this.x('I made a dashboard'), why: 'Past tense.' }], better_answer: this.x('In my last role I built a dashboard and cut report time by [X]%.') } : null,
      per_question: per.map(t => ({ turn_id: t.id, idx: t.idx, question: this.x(t.question), band: t.status === 'skipped' ? 'needs_work' : (t.feedback && t.feedback.band) || 'fair', score: t.status === 'skipped' ? null : 60, short: this.x(t.status === 'skipped' ? 'Skipped' : 'A real example, but no result.') })),
      delta: s.prevFinished ? { vs_session: s.prevFinished, language: { delta: 7, significant: true }, delivery: { delta: -2, significant: false } } : null, generated_at: nowIso() };
    return this.reportV1 ? rep : { ...rep, ...this.coach(s, real) };
  }

  /* ---------------- request handling ---------------- */
  // returns {status, body, headers?, abort?}. `ctx` = { method, path, query (URLSearchParams), headers, json, raw (Buffer) }
  handle(c) {
    this.calls.push({ method: c.method, path: c.path, query: c.query.toString(), headers: c.headers, body: c.json !== undefined ? c.json : null, rawLen: c.raw ? c.raw.length : 0, ts: Date.now() });
    // error bodies: FastAPI style ({"detail": {"error": code, ...}} / {"detail": "text"}) or the bare contract shape ({"error": code, ...})
    const err = (status, code, extra) => ({ status, body: this.wrapDetail ? { detail: { error: code, ...(extra || {}) } } : { error: code, ...(extra || {}) } });
    const errStr = (status, s) => ({ status, body: this.wrapDetail ? { detail: s } : { error: s } });
    const p = c.path.replace(/^\/rinterview/, '') || '/';
    if (!this.flag) return { status: 404, body: { detail: 'Job Interview Practice is not available yet' } };
    if (this.faults.status402 > 0 && /\/(analyze|swap-resume|start|answer|feedback)$/.test(p)) { this.faults.status402--; return errStr(402, 'keys_required'); }
    if (this.faults.status403 > 0 && /\/(analyze|swap-resume|start|answer|feedback)$/.test(p)) { this.faults.status403--; return errStr(403, 'Your access has been paused. Please contact the admin.'); }
    let m;

    if (c.method === 'GET' && p === '/state') {
      const ss = this.sessions.slice().reverse().slice(0, 30).map(s => this.sessOut(s));
      const active = this.sessions.slice().reverse().find(s => s.status !== 'finished');
      return { status: 200, body: { limits: this.limits, today: { sessions: this.sessions.length, answers: this.sessions.reduce((a, s) => a + s.turns.filter(t => t.status === 'answered').length, 0), sessions_cap: 10, answers_cap: 120 },
        resumes: this.docs.filter(d => d.kind === 'resume').slice().reverse().map(d => this.docOut(d)), jds: this.docs.filter(d => d.kind === 'jd').slice().reverse().map(d => this.docOut(d)),
        sessions: ss, active: active ? this.sessOut(active) : null, has_more: this.sessions.length > 30, focus: this.focusOut() } };
    }

    /* documents */
    if (c.method === 'POST' && p === '/documents/upload') {
      const kind = c.query.get('kind');
      if (kind !== 'resume' && kind !== 'jd') return err(422, 'bad_kind');
      const raw = c.raw || Buffer.alloc(0);
      if (raw.length > this.limits.max_upload_bytes) return errStr(413, 'too_large');
      const body = raw.toString('utf8');
      if (!raw.length) return err(422, 'empty');
      if (body.startsWith('OLEHDR')) return err(415, 'unsupported_type', { hint: 'doc' });
      if (body.startsWith('WEIRD')) return err(415, 'unsupported_type', { hint: 'other' });
      if (body.startsWith('%PDF-SCAN')) return err(422, 'no_text');
      if (body.startsWith('%PDF-ENC')) return err(422, 'encrypted');
      if (body.startsWith('SHORT')) return err(422, 'doc_too_short');
      if (body.startsWith('BADFILE')) return err(422, 'bad_file');                      // the real server's codes that the contract did not list
      if (body.startsWith('EXTRACT502')) return err(502, 'extract_unavailable');
      if (this.faults.upload500 > 0) { this.faults.upload500--; return errStr(500, 'boom'); }
      const text = body.replace(/^%PDF-FAKE\n/, '');
      return this.storeDoc(kind, text, { title: c.headers['x-ri-name'] ? decodeURIComponent(c.headers['x-ri-name']) : '', source: /pdf/.test(c.headers['content-type'] || '') ? 'pdf' : /word/.test(c.headers['content-type'] || '') ? 'docx' : 'txt' });
    }
    if (c.method === 'POST' && p === '/documents/paste') {
      const j = c.json || {};
      if (j.kind !== 'resume' && j.kind !== 'jd') return err(422, 'bad_kind');
      const min = j.kind === 'jd' ? this.limits.jd_min_chars : this.limits.resume_min_chars;
      if (!String(j.text || '').trim()) return err(422, 'empty');
      if (String(j.text).trim().length < min) return err(422, j.kind === 'jd' ? 'jd_too_vague' : 'doc_too_short');
      return this.storeDoc(j.kind, j.text, { title: j.title || '', company: j.company || '', parent_id: j.parent_id || null, source: 'paste' });
    }
    if ((m = p.match(/^\/documents\/(\d+)$/))) {
      const d = this.docs.find(x => x.id === +m[1]);
      if (!d) return errStr(404, 'Not found');
      if (c.method === 'GET') return { status: 200, body: { document: this.docOut(d), text: this.x(d.text), redactions: d.redactions, role: d.kind === 'jd' ? this.parseJd(d.text).role : null, requirements: d.kind === 'jd' ? this.parseJd(d.text).reqs : null } };
      if (c.method === 'DELETE') { this.docs = this.docs.filter(x => x.id !== d.id); this.sessions.forEach(s => { if (s.resume_id === d.id) s.resume_id = null; if (s.jd_id === d.id) s.jd_id = null; }); return { status: 200, body: { ok: true } }; }
    }

    /* sessions */
    if (c.method === 'POST' && p === '/sessions') {
      const j = c.json || {}, r = this.docs.find(d => d.id === j.resume_id && d.kind === 'resume'), jd = this.docs.find(d => d.id === j.jd_id && d.kind === 'jd');
      if (!r) return err(422, 'no_resume'); if (!jd) return err(422, 'no_jd');
      if (this.faults.limitSessions) return err(409, 'limit_sessions');
      if (this.faults.dailyLimit) return errStr(429, 'daily_limit');
      if (j.client_key) { const ex = this.sessions.find(s => s.client_key === j.client_key); if (ex) return { status: 200, body: { session: this.sessOut(ex) } }; }
      const parsed = this.parseJd(jd.text);
      const s = { id: this.id(), client_key: j.client_key, title: [parsed.role.title, parsed.role.company].filter(Boolean).join(' · ') || jd.title, status: 'draft', settings: Object.assign({ type: 'mixed', level: 'fresher', feedback_lang: 'hinglish' }, j.settings || {}),
        resume_id: r.id, jd_id: jd.id, overall: null, created_at: nowIso(), started_at: null, finished_at: null, analysis: null, turns: [], queue: [], rev: 1, picked: [] };
      this.sessions.push(s);
      return { status: 200, body: { session: this.sessOut(s) } };
    }
    if (c.method === 'GET' && p === '/sessions') {
      const lim = Math.max(1, Math.min(50, parseInt(c.query.get('limit') || '30', 10) || 30)), before = parseInt(c.query.get('before') || '0', 10) || 0;
      const page = this.sessions.slice().reverse().filter(s => !before || s.id < before).slice(0, lim);         // newest first, like the real service
      return { status: 200, body: { sessions: page.map(s => this.sessOut(s)), next_before: page.length === lim ? page[page.length - 1].id : null } };
    }
    if ((m = p.match(/^\/sessions\/(\d+)$/))) {
      const s = this.sessions.find(x => x.id === +m[1]);
      if (!s) return errStr(404, 'Not found');
      if (c.method === 'DELETE') { this.sessions = this.sessions.filter(x => x.id !== s.id); return { status: 200, body: { ok: true } }; }
      if (c.method === 'GET') return { status: 200, body: this.sessionState(s) };
    }
    if ((m = p.match(/^\/sessions\/(\d+)\/(analyze|swap-resume)$/)) && c.method === 'POST') return this.doAnalyze(this.sessions.find(x => x.id === +m[1]), m[2], c, err, errStr);
    if ((m = p.match(/^\/sessions\/(\d+)\/picks$/)) && c.method === 'PATCH') {
      const s = this.sessions.find(x => x.id === +m[1]); if (!s) return errStr(404, 'Not found');
      s.picked = (c.json && c.json.edit_ids) || []; if (s.analysis) s.analysis.edits.forEach(e => { e.picked = s.picked.includes(e.id); });
      return { status: 200, body: { ok: true, picked: s.picked } };
    }
    if ((m = p.match(/^\/sessions\/(\d+)\/start$/)) && c.method === 'POST') {
      const s = this.sessions.find(x => x.id === +m[1]); if (!s) return errStr(404, 'Not found');
      if (s.status === 'active') { const t = s.turns.find(x => x.status === 'asked') || s.turns[s.turns.length - 1]; return { status: 200, body: { turn: this.turnOut(t), counts: this.counts(s), queued_count: s.queue.length } }; }
      if (s.status !== 'matched') return err(409, 'wrong_state');
      if (this.faults.plan502 > 0) { this.faults.plan502--; return err(502, 'plan_unavailable'); }
      if (this.fault('startPending')) { s.planAt = Date.now() + 3000; s.status = 'active'; s.started_at = nowIso(); return { status: 202, body: { pending: true } }; }
      this.openPlan(s);
      const t = s.turns[0];
      return { status: 200, body: { turn: this.turnOut(t), counts: this.counts(s), queued_count: s.queue.length } };
    }

    /* turns */
    if ((m = p.match(/^\/sessions\/(\d+)\/turns\/(\d+)\/(answer|feedback|skip)$/)) && c.method === 'POST') return this.turnAction(this.sessions.find(x => x.id === +m[1]), +m[2], m[3], c, err, errStr);
    if ((m = p.match(/^\/sessions\/(\d+)\/turns\/(\d+)$/)) && c.method === 'GET') {
      const s = this.sessions.find(x => x.id === +m[1]); if (!s) return errStr(404, 'Not found');
      const t = s.turns.find(x => x.id === +m[2]); if (!t) return errStr(404, 'Not found');
      this.settle(t, s);
      return { status: 200, body: { turn: this.turnOut(t), counts: this.counts(s), can_finish: this.canFinish(s) } };
    }
    if ((m = p.match(/^\/sessions\/(\d+)\/next$/)) && c.method === 'POST') {
      const s = this.sessions.find(x => x.id === +m[1]); if (!s) return errStr(404, 'Not found');
      if (s.status === 'finished') return err(409, 'finished');
      const open = s.turns.find(x => x.status === 'asked');
      if (open) return { status: 200, body: { turn: this.turnOut(open), counts: this.counts(s), can_finish: this.canFinish(s), queued_count: s.queue.length } };
      if (s.turns.length >= 40) return err(409, 'session_cap');
      if (this.fault('next500')) return errStr(500, 'boom');
      const q = s.queue.shift() || ['Is there anything you would like to add about your experience?', 'A general closing question.'];
      const t = this.newTurn(s, q, s.queue.length < 0 ? 'bank' : 'plan'); s.turns.push(t);
      return { status: 200, body: { turn: this.turnOut(t), counts: this.counts(s), can_finish: this.canFinish(s), queued_count: s.queue.length } };
    }
    if ((m = p.match(/^\/sessions\/(\d+)\/finish$/)) && c.method === 'POST') {
      const s = this.sessions.find(x => x.id === +m[1]); if (!s) return errStr(404, 'Not found');
      if (s.status === 'finished') return { status: 200, body: { report: s.report, session: this.sessOut(s), progress: null, mission: null } };
      if (this.fault('finishNeedMore')) return err(409, 'need_more', { need: 1, reasons: ['need_real_answers'] });
      if (this.fault('finish500')) return errStr(500, 'boom');
      const cf = this.canFinish(s); if (!cf.ok) return err(409, 'need_more', { need: cf.need, reasons: cf.reasons });
      s.status = 'finished'; s.finished_at = nowIso(); s.queue = []; s.turns.forEach(t => { if (t.status === 'asked') t.status = 'dropped'; });
      s.report = this.report(s); s.overall = s.report.overall;
      if (s.report.focus) this.lastFocus = { session_id: s.id, title: s.title, finished_at: s.finished_at, overall: s.overall, points: s.report.focus };
      return { status: 200, body: { report: s.report, session: this.sessOut(s), progress: { xp_earned: 25, minutes: 3.5, streak_days: 3, speaker_rank: 'speaker', rank_up: false, new_badges: [] }, mission: null } };
    }

    /* transcription proxy */
    if (c.method === 'POST' && p === '/transcribe') {
      if (this.fault('stt502')) return err(502, 'stt_failed');
      if (this.faults.noGroqKey) return err(400, 'no_groq_key');
      if (this.faults.sttDaily) return errStr(429, 'daily_limit');
      const q = this.sttQueue.shift() || { text: TRANSCRIPT_GOOD, dur: 24 };
      return { status: 200, body: this.sttBody(q, 'gemini') };
    }

    /* data rights */
    if (c.method === 'GET' && p === '/export') return { status: 200, body: { exported_at: nowIso(), documents: this.docs.map(d => ({ ...this.docOut(d), text: d.text })), sessions: this.sessions.map(s => this.sessionState(s)) } };
    if (c.method === 'POST' && p === '/delete-all') {
      if (!(c.json && c.json.confirm === true)) return err(422, 'bad_input');
      this.docs = []; this.sessions = []; this.deleted = true;
      return { status: 200, body: { ok: true } };
    }
    return { status: 404, body: { detail: 'Not found: ' + c.method + ' ' + c.path } };
  }

  sttBody(q, engine) {
    const ws = q.text.split(/\s+/).filter(Boolean), dur = q.dur || Math.max(2, ws.length * 0.35), step = dur / Math.max(ws.length, 1);
    return { text: q.text, duration: dur, words: engine === 'gemini' ? [] : ws.map((w, i) => ({ word: w, start: +(i * step).toFixed(2), end: +((i + 0.9) * step).toFixed(2) })),
      segments: engine === 'gemini' ? [] : [{ start: 0, end: dur, avg_logprob: -0.2, no_speech_prob: 0.01 }], engine };
  }

  storeDoc(kind, text, o) {
    const rd = redact(text), h = sha(kind + rd.text);
    const dup = this.docs.find(d => d.hash === h);
    if (dup) return { status: 200, body: { document: this.docOut(dup), preview: dup.text, redactions: dup.redactions, warnings: [], duplicate: true } };
    if (this.docs.filter(d => d.kind === kind).length >= (kind === 'resume' ? this.limits.resumes : this.limits.jds)) return { status: 409, body: this.wrapDetail ? { detail: { error: 'limit_documents' } } : { error: 'limit_documents' } };
    const d = { id: this.id(), kind, title: o.title || (kind === 'jd' ? 'Job' : 'Resume'), company: o.company || '', source: o.source, chars: rd.text.length, pages: 1, parent_id: o.parent_id || null, created_at: nowIso(), text: rd.text, redactions: rd.r, hash: h };
    this.docs.push(d);
    const warnings = this.faults.warn ? ['The text may have come out in the wrong order (two columns).'] : [];
    return { status: 200, body: { document: this.docOut(d), preview: this.x(rd.text), redactions: rd.r, warnings, duplicate: false } };
  }

  sessionState(s) {
    if (s.planAt && Date.now() >= s.planAt && !s.turns.length) this.openPlan(s);
    const shown = s.turns.filter(t => t.status !== 'dropped');
    const open = s.turns.find(t => t.status === 'asked');
    s.turns.forEach(t => this.settle(t, s));
    return { session: this.sessOut(s), rev: s.rev, analysis: s.analysis ? this.analysisOut(s.analysis) : null, turns: shown.map(t => this.turnOut(t)), queued_count: s.queue.length,
      open_turn_id: open ? open.id : null, counts: this.counts(s), can_finish: this.canFinish(s), report: s.report || null, server_now: nowIso(),
      ...(s.status !== 'finished' ? { focus_prev: this.focusOut(s.id) } : {}) };
  }
  focusOut(exclude) {
    const lf = this.lastFocus; if (!lf || lf.session_id === exclude) return null;
    return { session_id: lf.session_id, title: this.x(lf.title), finished_at: lf.finished_at, overall: lf.overall, points: lf.points };
  }
  analysisOut(a) { const o = clone(a); delete o._until; if (o.state === 'pending') { o.match_score = null; o.band = 'unknown'; } return o; }
  settle(t, s) {                                         // pending feedback becomes done after the first poll
    if (t.feedback_state === 'pending' && t.pendingPolls !== undefined) {
      if (t.pendingPolls-- <= 0) { t.feedback = this.feedbackFor(s, t, t.answer, t.answer_sec, t.answer_words); t.feedback_state = 'done'; }
    }
  }
  newTurn(s, q, source) {
    const idx = s.turns.filter(t => t.status !== 'dropped').length + 1;
    return { id: this.id(), idx, kind: 'behavioural', source: source || 'plan', question: q[0], why: q[1], status: 'asked', answer: null, answer_sec: null, answer_words: null, engine: null, audio_device: null, real: false,
      feedback_state: 'none', feedback: null, asked_at: nowIso(), answered_at: null };
  }
  openPlan(s) {
    s.queue = QUESTIONS.slice(1).map(q => q.slice());
    s.status = 'active'; s.started_at = s.started_at || nowIso();
    s.turns.push(this.newTurn(s, QUESTIONS[0], 'plan'));
  }

  doAnalyze(s, kind, c, err, errStr) {
    if (!s) return errStr(404, 'Not found');
    if (kind === 'swap-resume' && s.status !== 'draft' && s.status !== 'matched') return err(409, 'wrong_state');
    const delay = this.delays.analyze || 0;
    const jd = this.docs.find(d => d.id === s.jd_id), r = kind === 'swap-resume' ? this.docs.find(d => d.id === (c.json || {}).resume_id) : this.docs.find(d => d.id === s.resume_id);
    if (!r) return err(422, 'no_resume'); if (!jd) return err(422, 'no_jd');
    if (this.fault('analyze502')) return err(502, 'analysis_unavailable');
    if (this.fault('jdVague')) return err(422, 'jd_too_vague');
    if (this.faults.analyzeQuota > 0) { this.faults.analyzeQuota--; return errStr(429, 'quota'); }
    if (this.fault('analyzePending')) {                  // the same work is "already running": 202 now, done after a few seconds of polling
      const prevA = s.analysis;
      s.analysis = { state: 'pending', match_score: null, band: 'unknown', verdict: '', role: {}, requirements: [], edits: [], strengths: [], notes: [], low_match: false, rules_version: 1, prev: null };
      s.analysisReadyAt = Date.now() + 3500; s.pendingKind = { kind, r, jd, prev: prevA };
      return { status: 202, body: { pending: true } };
    }
    if (this.fault('analyzeDrop')) { const prev = s.analysis; s.analysis = this.analyse(r, jd, kind === 'swap-resume' ? prev : null); s.status = 'matched'; if (kind === 'swap-resume') s.resume_id = r.id; return { abort: 'connectionreset' }; }
    const prev = kind === 'swap-resume' ? s.analysis : null;
    s.analysis = this.analyse(r, jd, prev && prev.state === 'done' ? prev : null);
    if (kind === 'swap-resume') s.resume_id = r.id;
    s.status = 'matched';
    return { status: 200, body: { analysis: this.analysisOut(s.analysis), session: this.sessOut(s) }, delay };
  }

  turnAction(s, tid, action, c, err, errStr) {
    if (!s) return errStr(404, 'Not found');
    const t = s.turns.find(x => x.id === tid); if (!t) return errStr(404, 'Not found');
    const body = c.json || {};
    if (action === 'skip') {
      if (t.status !== 'asked') return err(409, 'wrong_state');
      t.status = 'skipped';
      return { status: 200, body: { turn: this.turnOut(t), counts: this.counts(s), can_finish: this.canFinish(s) } };
    }
    if (action === 'feedback') {
      if (t.status !== 'answered') return err(409, 'wrong_state');
      if (this.fault('feedback502')) { t.feedback_state = 'failed'; t.feedback = { delivery: this.feedbackFor(s, t, t.answer, t.answer_sec).delivery, genuine: true }; return err(502, 'feedback_unavailable', { saved: true, turn: this.turnOut(t) }); }
      if (this.fault('feedbackPending')) { t.feedback_state = 'pending'; t.pendingPolls = 1; return { status: 202, body: { pending: true } }; }
      t.feedback = this.feedbackFor(s, t, t.answer, t.answer_sec, t.answer_words); t.feedback_state = 'done';
      return { status: 200, body: { turn: this.turnOut(t), counts: this.counts(s), can_finish: this.canFinish(s), queued_count: s.queue.length } };
    }
    // answer
    if (this.fault('answerAlready')) { t.status = 'answered'; t.answer = 'Answered on the other phone with a full sentence about my work.'; t.answer_words = 12; t.answer_sec = 14; t.real = false; t.feedback = this.feedbackFor(s, t, t.answer, 14); t.feedback_state = 'done'; t.audio_device = 'other-phone'; return err(409, 'already_answered', { turn: this.turnOut(t) }); }
    if (t.status === 'answered' || t.status === 'skipped') {
      if (t.answer_key && t.answer_key === body.client_key) return { status: 200, body: { turn: this.turnOut(t), counts: this.counts(s), can_finish: this.canFinish(s), queued_count: s.queue.length } };
      return err(409, 'already_answered', { turn: this.turnOut(t) });
    }
    const wc = words(body.transcript), dur = +body.duration_sec || 0;
    if (this.fault('answerNoSpeech')) return { status: 200, body: { too_short: true, reason: 'no_speech', words: wc, seconds: dur, min_words: this.limits.min_answer_words, min_seconds: this.limits.min_answer_sec } };   // the real server's Whisper-hallucination check
    if (wc < this.limits.min_answer_words || dur < this.limits.min_answer_sec) return { status: 200, body: { too_short: true, words: wc, seconds: dur, min_words: this.limits.min_answer_words, min_seconds: this.limits.min_answer_sec } };
    t.status = 'answered'; t.answer = String(body.transcript); t.answer_sec = dur; t.answer_words = wc; t.engine = body.engine; t.audio_device = body.audio_device; t.answer_key = body.client_key; t.answered_at = nowIso();
    t.real = wc >= 25 && dur >= 10 && !this.faults.notReal;
    this.answers.push({ tid, body });
    if (this.fault('answerDrop')) { t.feedback = this.feedbackFor(s, t, t.answer, dur); t.feedback_state = 'done'; return { abort: 'connectionreset' }; }
    if (this.fault('answerPending')) { t.feedback_state = 'pending'; t.pendingPolls = 1; return { status: 202, body: { pending: true } };
    }
    if (this.fault('feedback502')) { t.feedback_state = 'failed'; t.feedback = { delivery: this.feedbackFor(s, t, t.answer, dur).delivery, genuine: true }; return err(502, 'feedback_unavailable', { saved: true, turn: this.turnOut(t) }); }
    if (this.faults.answerQuota > 0) { this.faults.answerQuota--; t.status = 'asked'; t.answer = null; return errStr(429, 'quota'); }
    t.feedback = this.feedbackFor(s, t, t.answer, dur, wc); t.feedback_state = 'done';
    return { status: 200, body: { turn: this.turnOut(t), counts: this.counts(s), can_finish: this.canFinish(s), queued_count: s.queue.length }, delay: this.delays.answer || 0 };
  }

  // analysis that was answered 202: the first poll after analysisReadyAt returns it
  tickPending(s) {
    if (s.analysis && s.analysis.state === 'pending' && s.analysisReadyAt && Date.now() >= s.analysisReadyAt) {
      const k = s.pendingKind; s.analysis = this.analyse(k.r, k.jd, k.kind === 'swap-resume' && k.prev && k.prev.state === 'done' ? k.prev : null); s.status = 'matched'; if (k.kind === 'swap-resume') s.resume_id = k.r.id; s.analysisReadyAt = 0;
    }
  }
}

// the original GET /sessions/{id} must run tickPending first
const origSessionState = Mock.prototype.sessionState;
Mock.prototype.sessionState = function (s) { this.tickPending(s); return origSessionState.call(this, s); };

module.exports = { Mock, LIMITS, QUESTIONS, RESUME_TEXT, RESUME_IMPROVED, JD_TEXT, TRANSCRIPT_GOOD, TRANSCRIPT_SHORT };
