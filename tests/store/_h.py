"""Shared helpers + the models the store tests use."""

from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import traceback

sys.path.insert(0, "/app")

from app import store                                                      # noqa: E402
from app.store import (Base, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSONB, Mapped, SmallInteger, String, Text, and_, delete, desc,   # noqa: E402
                       func, insert, mapped_column, or_, select, update)

UTC = dt.timezone.utc


def now():
    return dt.datetime.now(UTC)


class TUser(Base):
    __tablename__ = "t_users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), default="")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    ratio: Mapped[float] = mapped_column(default=0.5)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    born: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    last: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    tags: Mapped[list] = mapped_column(JSONB, default=list)


class TItem(Base):
    __tablename__ = "t_items"
    __table_args__ = (
        Index("uq_t_items_client", "user_id", "client_key", unique=True, where={"client_key": {"$type": "string"}}),
        Index("ix_t_items_user_status", "user_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("t_users.id"), index=True)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="open")
    n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flag: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class TDay(Base):
    __tablename__ = "t_days"
    user_id: Mapped[str] = mapped_column(ForeignKey("t_users.id"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)


class TWeek(Base):
    __tablename__ = "t_weeks"
    user_id: Mapped[str] = mapped_column(ForeignKey("t_users.id"), primary_key=True)
    week_start: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    xp: Mapped[int] = mapped_column(Integer, default=0, index=True)


MODELS = [TUser, TItem, TDay, TWeek]
Sess = store.SessionFactory()

PASS = FAIL = 0
FAILED: list = []


def ok(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"FAIL {name}" + (f"  [{extra}]" if extra else ""))


_T0 = __import__("time").monotonic()


def section(title):
    print(f"\n== {title}  (+{__import__('time').monotonic() - _T0:.1f}s)", flush=True)


async def raises(exc, fn):
    """Run the coroutine function `fn`; return the exception if it raised `exc`, None if it raised nothing. Anything else propagates."""
    try:
        await fn()
    except exc as e:
        return e
    return None


async def reset(models=MODELS):
    db = store.core.database()
    for n in await db.list_collection_names():
        await db.drop_collection(n)
    await store.init(models)


async def wipe(models=MODELS):
    db = store.core.database()
    for M in models:
        await db[M.__tablename__].delete_many({})
    await db["counters"].delete_many({})


def finish():
    print(f"\n{PASS + FAIL} checks: {PASS} passed, {FAIL} failed")
    if FAILED:
        print("failed:", *FAILED, sep="\n  ")
    sys.exit(1 if FAIL else 0)


def run(main):
    store.configure(os.environ["MONGODB_URI"])
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        print("\nTEST RUN CRASHED")
        sys.exit(2)
    finish()
