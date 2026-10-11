"""My Day - tasks, goals, habits and reminders (DUSU_GOALS_PLAN.md, DUSU_ALL_FEATURES_PLAN.md W3).

timeutil  pure: per-user timezone, DST-safe wall clock -> UTC, recurrence, quiet hours
rules     pure: input cleaning, limits, task status, goal progress, habit consistency
models    the `pl_*` tables (all new - no existing table is altered)
service   every read / write, scoped to the learner, idempotent, reminders cancelled with their entity
scheduler the reminder engine: one asyncio loop, Postgres as the queue
push      Web Push (VAPID) + the signed one-action tokens for the notification buttons
api       the `/planner/*` router
life_lines the learner's plan as exact lines for DuSu (life.EXTRA_LINES)

Switch: settings.planner = off (default) / owner / on. While it is off the endpoints answer 404 and the scheduler idles.
"""
