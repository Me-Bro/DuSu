"""Keys - knowing, per key, whether it works, how much it was used and what to tell the learner when it does not.

classify   pure: ONE answer to "what did this provider just tell us about this key?" (typed SDK errors, bodies, headers; only positive evidence marks a key invalid)
gate       the per-key circuit breaker, keyed (provider, fingerprint) - one learner's limit can never make another learner's key look limited
ledger     in-memory counting of every provider attempt + per-key status changes, flushed to Postgres in small batches (never blocks or fails a request)
models     the `kh_*` tables (both new - no existing table is altered)
probe      zero-quota auth probes, the one-call chat check, the server chain's own health (cached)
service    every read / write: the masked status payload, merge-save, remove, re-check, export, data rights
api        the `/keys/*` router (status / save / remove / recheck / export); the legacy `/keys/verify` and `/keys/get` stay in main.py

The walker that uses all of this lives in providers/openrouter_provider.py (`_complete_v2`); today's walker stays there verbatim as `_complete_legacy`.
Switches: settings.key_health (engine + endpoints) and settings.keys_ui (the screens) = off (default) / owner / on; the screens also need the engine.
"""
