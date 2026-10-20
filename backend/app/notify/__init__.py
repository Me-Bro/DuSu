"""Notifications - dynamic, personal nudges chosen from the learner's own rows and delivered as Web Push (to the Android app via TWA notification
delegation, to the PWA, and to the browser: one pipeline).

rules      pure: which nudge, for whom, when, in which words (Hindi + English), plus the send-time re-check
models     the `nt_*` tables (both new - no existing table is altered)
tokens     the signed single-purpose "it arrived" receipt the service worker sends back
service    every read / write, scoped to the learner: prefs, deciding, the queue, delivery, beacons, health, data rights
scheduler  the engine: one asyncio loop, Postgres as the queue (a separate loop from My Day's)
api        the `/notify/*` router

Devices are My Day's `pl_push_subs` and the push sender is `planner.push.send` - nothing is duplicated.
Switch: settings.notifications = off (default) / owner / on. While it is off the endpoints answer 404 and the loop idles.
"""
