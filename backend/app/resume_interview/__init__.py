"""Resume Interview - upload a resume + a job description, see the mismatch, then a recorded mock interview built from both
(DUSU_RESUME_INTERVIEW_PLAN.md).

docs          pure: sniff / clean / redact a document, run the sandboxed extraction child
extract_child standalone script (stdlib + pypdf only) that turns PDF / DOCX / text bytes into plain text
rules         pure: limits, input cleaning, match score, answer scoring, question validation + bank, the computed report
prompts       the model prompts (data fenced, boundary text, JSON shapes)
engine        async orchestrators for the four model calls (A requirements, B match, C plan, D answer feedback)
models        the `ri_*` tables (all new - no existing table is altered)
service       every read / write, scoped to the learner, idempotent, claim-pattern around model calls
api           the `/rinterview/*` router
life_lines    the learner's interviews as exact lines for DuSu (life.EXTRA_LINES)

Switch: settings.resume_interview = off (default) / owner / on. While it is off the endpoints answer 404 (export / delete excepted).
"""
