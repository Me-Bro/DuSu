# The MongoDB migration - store layer + proofs (tests/store)

`backend/app/store/` is MongoDB behind the SQLAlchemy-2.0 shape DuSu's code is written against (see `DUSU_MONGO_MIGRATION_PLAN.md`, section 4, for the contract).
Everything here runs on **scratch** infrastructure: a `mongo:7` one-member replica set (and, where needed, a `postgres:18-alpine`) on an `--internal` docker network - **never** the
shared `rooted-mongo`, never `dusu-db-1`. `DUSU_SCRATCH_ONLY=1` (set by every runner) makes the store refuse any host that is not a scratch container.

One-time: `printf 'FROM dusu-backend:latest\nRUN pip install --no-cache-dir pymongo==4.20.0\n' | docker build -t dusu-mongo-test -f - .`
(the base keeps SQLAlchemy + asyncpg on purpose: the differential test, the golden master of the OLD tree and the ETL need them. The application image does not.)

| Tier | What it proves | Command |
|---|---|---|
| unit | every row of the contract: types, NULL semantics, ordering, aggregates, identity map, change detection, transactions, rollback, upserts, claims, foreign keys, subqueries, coalesce | `tests/store/run.sh unit.py` (STORE_PG=0 skips the Postgres) |
| concurrency | locked read-modify-write loses nothing, deadlock -> loud timeout, racing creators (one wins), atomic claims, all-or-nothing, WriteConflict wait-and-replay, replay divergence -> ConcurrencyError | `STORE_PG=0 tests/store/run.sh concurrency.py` |
| differential | the SAME random filters / orderings / limits / aggregates / group_by / LIKE / coalesce on REAL SQLAlchemy+Postgres and on the store give identical answers | `tests/store/run.sh differential.py [seed] [queries]` |
| mutants | 35 planted bugs in a copy of the store; each must fail a tier above | `tests/store/mutants.sh [S1 S5 ...]` -> `.out/mutants.txt` |
| golden master | one scripted scenario (fake clock) over every public `db.*` function: the OLD tree (`tests/store/.old/backend` = git archive of the commit before the migration, on Postgres) vs the NEW tree (on Mongo): every return value and every table row identical | `tests/store/golden.sh core\|full [old\|new\|both]` |
| shadow + ETL rehearsal | a fresh read-only `pg_dump` of the live Postgres -> scratch Postgres -> `backend/scripts/pg_to_mongo.py --verify` into a scratch Mongo -> the OLD app (on Postgres) and the NEW app (on Mongo) answer ~30 read-only questions for every real learner; the answers are diffed | `tests/store/etl_rehearsal.sh [dump.sql.gz]` |
| baked image | EVERY server-side suite (store, insights, keys, notify, grammar, my_day, daily_voice, resume_interview) against the code INSIDE a built image, after a sha256 proves the image's source files equal the tree | `tests/store/baked_all.sh [image]` -> `.out/baked.txt` |
| browser tiers | every browser spec (My Day, Notifications, Keys / install / Gemini, Grammar Coach, Job Interview Practice, "AI busy", the two voice-lock specs, the audit) on the real app in a real Chromium + a scratch Mongo | `BROWSER_IMAGE=dusu-backend:<tag> tests/store/browser_all.sh [name ...]` -> `.out/browser.txt` (long: ~25 min) |
| soak + explain | the three background loops (My Day reminders, Notifications, the key ledger) + learners on top + a launch-day burst, with the MongoDB profiler on: no error, nothing stuck, requests stay fast, and **no recurring query reads a big collection to throw most of it away** | `SOAK_IMAGE=dusu-backend:<tag> SOAK_BACKEND=baked tests/store/soak.sh` (~8 min; `SOAK_LEARNERS`, `SOAK_SECONDS`) |
| index parity | every index / unique constraint / primary key of the OLD SQLAlchemy models exists in the new models | `tests/store/index_parity.sh` |
| open-a-chat timing | `start` -> opener frame in Home / Face-to-Face / Daily on the OLD tree (scratch Postgres) vs the NEW tree (scratch Mongo) | `tests/store/bench_ws_start.sh old|new` |
| Play Store report | the closed-test daily report (`backend/scripts/playstore_report.py`, the MongoDB version of Appendix B's five SQL queries) on synthetic learners: every query's numbers hand-checked, mixed-case emails, read-only (no document added or changed) | `STORE_PG=0 tests/store/run.sh playstore_report_test.py` |
| pre-flight on the real server | the app's start-up (`init_db()`) against the real shared Mongo as DuSu's scoped user: every collection and index can be created; writes only empty collections into DuSu's OWN database | `docker run --rm --network rooted-shared-net --env-file ~/Desktop/RootEd_ALL/shared-services/creds/dusu-prod.env -v "$PWD/tests":/tests:ro dusu-backend:<tag> python /tests/store/preflight_shared.py` |
| shared server | the shared `rooted-mongo` behaves as the store assumes, as DuSu's scoped user (isolation, transactions, partial unique indexes, ...). Touches one throwaway collection family in `dusu`, drops it | `docker run --rm --network rooted-shared-net --env-file ~/Desktop/RootEd_ALL/shared-services/creds/dusu-prod.env -v "$PWD/tests":/tests dusu-mongo-test python /tests/store/probe_shared_mongo.py` |

Every other suite (`tests/keys`, `my_day`, `notify`, `grammar`, `resume_interview`, `insights`, `daily_voice`, `audit`) now bootstraps the same scratch Mongo through
`tests/lib/scratch_mongo.sh`; their counts are the pre-migration ones (see the plan's status log).

## Gotchas that cost time
* **MongoDB uses an index only when the query names its FIRST key** - a partial index `Index("ix_x", "sent_at", where={"status": "sent"})` is never picked for `find({status: "sent"})`; lead with the field the filter uses (`"status", "sent_at"`). The soak's profiler is what shows it.
* A shell script must be `chmod +x` before `nohup path` (otherwise it silently never starts); `bash path` always works.
* A faster server can break a racy test: the busy spec's F3 injected a frame while a typed line was still waiting for `home_ready`. Wait for the real round trip, not for the first bubble.
* Docker here only bind-mounts paths under the repo / home - not `/tmp`. Put scratch scripts under `tests/`.
* Python buffers its output when piped: runners use `python -u` / `PYTHONUNBUFFERED=1`.
* The bash tool backgrounds anything over 120 s: run long suites with `run_in_background` and wait for the notification; never `pkill -f` a pattern that appears in your own command line.
* A GET can WRITE (weekly missions are generated on first read, `last_seen` moves, the key ledger rechecks): copy data BEFORE anyone reads it (the rehearsal does).
* SQL leaves some orders undefined (ties on XP, the rows of an export): the shadow harness canonicalises them; a real difference is still a difference.
* The mutation scripts of the OLD suites (`tests/*/mutants.sh`) patch exact SQL source text and no longer apply to the ported code; they need re-deriving (not a gate of the migration).
