"""Copy every DuSu table from one Postgres to another (data only).

Used for the one-time cutover off a managed/external provider onto this stack's
own `db` container, and re-usable for any future move (new host, restored volume).

Data only, on purpose: the DESTINATION schema must already exist, created by the
app itself via `init_db()` — so the target is exactly what the running models
expect and this script never has to duplicate DDL or stay in sync with it.

  Why a row copy and not pg_dump: the source ran PostgreSQL 18 while the target
  image was on another major version, and pg_dump refuses a newer server. A copy
  driven by the app's own SQLAlchemy metadata is version-agnostic, and
  `Base.metadata.sorted_tables` gives a foreign-key-safe order for free.

Usage (inside the backend container, which can reach both databases):

    SRC_DATABASE_URL='postgresql://...' python scripts/migrate_db.py
    SRC_DATABASE_URL='postgresql://...' python scripts/migrate_db.py --force

Destination defaults to the app's own configured database (settings.database_url).
Existing rows in a destination table make it SKIP that table, so a re-run is safe;
--force truncates the destination table first instead.
"""

import asyncio
import os
import sys

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings          # noqa: E402
from app.db import Base, _normalize_url  # noqa: E402


def _engine(url: str, ssl: bool):
    return create_async_engine(
        _normalize_url(url), pool_pre_ping=True,
        connect_args={"ssl": True} if ssl else {},
    )


def _truthy(v: str, default: bool) -> bool:
    return default if v == "" else v.strip().lower() in ("1", "true", "yes", "on")


async def copy_all(src_url: str, src_ssl: bool, dst_url: str, dst_ssl: bool, force: bool) -> int:
    src, dst = _engine(src_url, src_ssl), _engine(dst_url, dst_ssl)
    copied = skipped = 0
    try:
        async with src.connect() as s, dst.begin() as d:
            for table in Base.metadata.sorted_tables:     # parents before children
                have = (await d.execute(select(func.count()).select_from(table))).scalar() or 0
                if have and not force:
                    print(f"  {table.name:<16} SKIP (destination already has {have} rows)")
                    skipped += 1
                    continue
                if have and force:
                    await d.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))
                rows = [dict(r) for r in (await s.execute(select(table))).mappings().all()]
                if rows:
                    await d.execute(table.insert(), rows)
                # An explicitly-inserted serial/identity PK leaves the sequence behind
                # the data — the next natural insert would then collide on the PK.
                for col in table.primary_key.columns:
                    seq = (await d.execute(text(
                        "select pg_get_serial_sequence(:t, :c)"),
                        {"t": table.name, "c": col.name})).scalar()
                    if seq and rows:
                        await d.execute(text(
                            f'select setval(:s, (select coalesce(max("{col.name}"), 1) from "{table.name}"))'),
                            {"s": seq})
                print(f"  {table.name:<16} {len(rows):>5} rows copied")
                copied += len(rows)
    finally:
        await src.dispose()
        await dst.dispose()
    print(f"\n  copied {copied} rows, skipped {skipped} table(s)")
    return copied


async def verify(src_url: str, src_ssl: bool, dst_url: str, dst_ssl: bool) -> bool:
    src, dst = _engine(src_url, src_ssl), _engine(dst_url, dst_ssl)
    ok = True
    try:
        async with src.connect() as s, dst.connect() as d:
            print(f"\n  {'table':<16} {'source':>8} {'dest':>8}")
            for table in Base.metadata.sorted_tables:
                a = (await s.execute(select(func.count()).select_from(table))).scalar() or 0
                b = (await d.execute(select(func.count()).select_from(table))).scalar() or 0
                mark = "ok" if a == b else "MISMATCH"
                ok = ok and a == b
                print(f"  {table.name:<16} {a:>8} {b:>8}  {mark}")
    finally:
        await src.dispose()
        await dst.dispose()
    return ok


async def main() -> int:
    src_url = os.environ.get("SRC_DATABASE_URL", "").strip()
    if not src_url:
        print("SRC_DATABASE_URL is required (the database to copy FROM).")
        return 2
    dst_url = os.environ.get("DST_DATABASE_URL", "").strip() or settings.database_url
    if not dst_url:
        print("No destination: set DST_DATABASE_URL or configure DATABASE_URL.")
        return 2
    src_ssl = _truthy(os.environ.get("SRC_DATABASE_SSL", ""), True)    # managed providers need TLS
    dst_ssl = _truthy(os.environ.get("DST_DATABASE_SSL", ""), settings.database_ssl)
    force = "--force" in sys.argv

    print(f"copying -> {_normalize_url(dst_url).split('@')[-1]}  (from {_normalize_url(src_url).split('@')[-1]})\n")
    await copy_all(src_url, src_ssl, dst_url, dst_ssl, force)
    ok = await verify(src_url, src_ssl, dst_url, dst_ssl)
    print("\n" + ("All tables match. ✅" if ok else "Counts differ — see MISMATCH above. ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
