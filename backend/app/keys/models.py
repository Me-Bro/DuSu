"""Keys - the `kh_*` tables. Both are NEW: `create_all` adds them, no existing table is altered (CLAUDE.md schema rule).

    kh_status  one row per learner x provider x key fingerprint: what we last learned about that key (ok / limited / invalid / forbidden), when, why, and the
               provider's own allowance numbers when it reports them. NO key text: the fingerprint is HMAC(server secret, provider|key)[:12].
    kh_usage   one row per learner x provider-quota-day x provider x key fingerprint: how many provider attempts were made and how they ended. The ledger
               paid plans will reuse - which is why every attempt is counted, including the ones that failed or were cancelled.

Column widths are checked against every value the code writes (tests/keys/unit.py) - a too-narrow String(n) is only caught by a real database otherwise.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, _now

TS = DateTime(timezone=True)


class KhStatus(Base):
    __tablename__ = "kh_status"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(12), primary_key=True)           # groq | gemini | openrouter
    fp: Mapped[str] = mapped_column(String(16), primary_key=True)                 # HMAC fingerprint of the key (12 hex)
    status: Mapped[str] = mapped_column(String(10), default="unknown")            # ok | limited | invalid | forbidden | unknown
    kind: Mapped[str] = mapped_column(String(16), default="")                     # the classifier kind behind it (needs_credit, model_gone ...)
    scope: Mapped[str] = mapped_column(String(10), default="")                    # limited: minute | day | upstream | ''
    since: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)          # when the CURRENT status began
    reset_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)       # when a limit should end (provider's word, or its published daily rule)
    evidence: Mapped[bool] = mapped_column(Boolean, default=False)                # reset_at came from the provider's own response
    approx: Mapped[bool] = mapped_column(Boolean, default=False)                  # reset_at came from the published daily rule
    expired: Mapped[bool] = mapped_column(Boolean, default=False)                 # invalid because the provider said the key expired
    last_http: Mapped[int] = mapped_column(Integer, default=0)
    last_ok_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    last_error_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    checked_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)     # the last time a probe (not a chat turn) looked at this key
    rl_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)          # the provider's own daily request allowance (Groq reports it)
    rl_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rl_reset_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    rl_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)          # when those numbers were read
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)                       # provider specifics, e.g. {"is_free_tier": true}
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class KhUsage(Base):
    __tablename__ = "kh_usage"
    __table_args__ = (Index("ix_kh_usage_day", "day"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)                # the PROVIDER's quota day, 'YYYY-MM-DD' (UTC; Pacific for Gemini)
    provider: Mapped[str] = mapped_column(String(12), primary_key=True)
    fp: Mapped[str] = mapped_column(String(16), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, default=0)                     # every attempt, counted when it is dispatched
    ok: Mapped[int] = mapped_column(Integer, default=0)
    limited: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)
    other: Mapped[int] = mapped_column(Integer, default=0)                        # timeouts, 5xx, empty answers, cancelled attempts
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)


KY_TABLES = (KhUsage, KhStatus)               # child-first order for deletes
