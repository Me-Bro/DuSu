"""Insights - the `ev_*` tables and `plan_interest`. All three are NEW: `create_all` adds them, no existing table is altered (CLAUDE.md schema rule).

    ev_milestones  one row per learner x milestone: the FIRST time that learner reached it ("saved a first key", "said a first sentence" ...). Written once, never
                   updated - which is what makes it a funnel. No text, no key, no IP, no device: just a name and a time.
    ev_days        one row per learner x calendar day (India time) on which the app was opened. Day-1 / Day-7 return is a join on this.
    plan_interest  one row per learner x plan they reserved ("tell me when payment opens"), plus an optional one-tap "does the price feel high / fair / great".
                   No payment data of any kind lives here - there is no payment yet.

Column widths are checked against every value the code writes (tests/insights/unit.py): a too-narrow String(n) is only caught by a real database otherwise.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, _now

TS = DateTime(timezone=True)


class EvMilestone(Base):
    __tablename__ = "ev_milestones"
    __table_args__ = (Index("ix_ev_milestones_name", "name", "first_at"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(24), primary_key=True)
    first_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class EvDay(Base):
    __tablename__ = "ev_days"
    __table_args__ = (Index("ix_ev_days_day", "day"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)                # 'YYYY-MM-DD', the app's own (India) day


class PlanInterest(Base):
    __tablename__ = "plan_interest"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    plan: Mapped[str] = mapped_column(String(12), primary_key=True)               # starter | plus | pro
    price_feel: Mapped[str] = mapped_column(String(8), default="")                # '' | too_high | fair | great
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
