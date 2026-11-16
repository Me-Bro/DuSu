"""PRE-FLIGHT against the REAL shared MongoDB, as DuSu's own scoped user: run the app's startup (`init_db()` = create every collection and index) against the still-empty
database `dusu`, then list what exists. Proves - before the cutover - that the scoped user may create everything the app creates, on the server version that will host it.
It writes nothing but empty collections + indexes into DuSu's OWN database (idempotent: a second run changes nothing) and prints counts only, never the URI.

  docker run --rm --network rooted-shared-net --env-file ~/Desktop/RootEd_ALL/shared-services/creds/dusu-prod.env \
      -v "$PWD/tests":/tests dusu-backend:<tag> python /tests/store/preflight_shared.py
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app")
assert os.environ.get("MONGODB_URI"), "MONGODB_URI is not set (pass the creds file with --env-file)"

from app import db, main as _main, store                     # noqa: E402,F401  (importing main registers every model, as the production start-up does)


async def main():
    before = set(await store.core.database().list_collection_names()) if db.db_enabled else set()
    await db.init_db()
    d = store.core.database()
    models = db.Base.models()
    names = set(await d.list_collection_names())
    missing = sorted(m.__tablename__ for m in models if m.__tablename__ not in names)
    n_idx = 0
    per = {}
    for n in sorted(names):
        info = await d[n].index_information()
        per[n] = len(info)
        n_idx += len(info)
    docs = sum([await d[n].estimated_document_count() for n in names])
    print(f"models {len(models)} | collections now {len(names)} (before: {len(before)}) | missing {missing or 'none'} | indexes {n_idx} (incl. _id) | documents {docs}")
    # every index the models declare must exist under its own name
    lack = []
    for m in models:
        have = set((await d[m.__tablename__].index_information()).keys())
        for ix in getattr(m, "__indexes__", []) or []:
            if getattr(ix, "name", None) and ix.name not in have:
                lack.append((m.__tablename__, ix.name))
    print("declared indexes missing:", lack or "none")
    await store.close()
    sys.exit(1 if missing or lack else 0)


asyncio.run(main())
