"""Notifications - the `nt_*` tables. Both are NEW: `create_all` adds them, no existing table is altered (CLAUDE.md schema rule).

    nt_prefs   one row per learner, created on first use: the master switch, which kinds they want, the time of day they want their nudge.
               (Time zone, quiet hours and lock-screen privacy are My Day's `pl_prefs` - one place for them, not two.)
    nt_outbox  what DuSu decided to tell a learner and what happened to it. One row per notification; `dedupe_key` is unique per learner, so
               "one nudge a day" and "one weekly note a week" are enforced by the database, not by hope.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, _now

TS = DateTime(timezone=True)


class NtPrefs(Base):
    __tablename__ = "nt_prefs"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)                  # the master switch (nothing is sent without a push subscription anyway)
    kinds: Mapped[dict] = mapped_column(JSONB, default=dict)                      # {"practice": true, "streak": true, "weekly": true}
    nudge_time: Mapped[str] = mapped_column(String(5), default="19:00")           # 'HH:MM' on the learner's own clock
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class NtOutbox(Base):
    __tablename__ = "nt_outbox"
    __table_args__ = (
        Index("uq_nt_out_dedupe", "user_id", "dedupe_key", unique=True),
        Index("ix_nt_out_due", "fire_at", postgresql_where=text("status = 'scheduled'")),
        Index("ix_nt_out_user_created", "user_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(10), default="practice")             # practice | streak | weekly | test
    dedupe_key: Mapped[str] = mapped_column(String(64))                           # 'day:2026-10-21' | 'weekly:2026-W43' | 'test:<uid>:<stamp>'
    fire_at: Mapped[dt.datetime] = mapped_column(TS)
    title: Mapped[str] = mapped_column(String(80), default="")                    # written at SEND time, from the facts as they are then
    body: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(64), default="/")                     # an in-app path
    status: Mapped[str] = mapped_column(String(10), default="scheduled")          # scheduled | sending | sent | cancelled
    why: Mapped[str] = mapped_column(String(24), default="")                      # why it was cancelled: done | off | quiet | paused | stale | no_device ...
    push_state: Mapped[str] = mapped_column(String(16), default="none")           # none | accepted | failed | no_subscription
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claimed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    received_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)    # the phone's service worker said "it arrived"
    opened_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)      # the learner tapped it
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)                       # the facts it was written from, e.g. {"streak": 5, "lang": "hi"}
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


NT_TABLES = (NtOutbox, NtPrefs)               # child-first order for deletes
