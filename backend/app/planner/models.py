"""My Day - tables (all new, prefix `pl_`; DUSU_GOALS_PLAN.md §5.1).

Brand-new tables only: `create_all` makes them and no existing table is altered. Every row carries `user_id` and every query in service.py
filters on it. Timestamps are UTC (timestamptz); the learner's IANA timezone is stored next to anything with a local meaning. Soft delete
(`deleted_at`) on goals / tasks / habits; "delete all my data" hard-deletes.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, _now

TS = DateTime(timezone=True)


class PlPrefs(Base):
    __tablename__ = "pl_prefs"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    tz: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    quiet_on: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_start: Mapped[str] = mapped_column(String(5), default="22:00")
    quiet_end: Mapped[str] = mapped_column(String(5), default="07:00")
    followups: Mapped[int] = mapped_column(Integer, default=1)                 # 0-2 follow-ups after the first reminder
    followup_gap_min: Mapped[int] = mapped_column(Integer, default=30)
    snooze_min: Mapped[int] = mapped_column(Integer, default=30)
    push_on: Mapped[bool] = mapped_column(Boolean, default=False)              # push is opt-in (D3)
    hide_details: Mapped[bool] = mapped_column(Boolean, default=False)         # lock-screen text: "You have a reminder" (D6)
    paused_all: Mapped[bool] = mapped_column(Boolean, default=False)
    english_habit: Mapped[bool] = mapped_column(Boolean, default=True)         # the built-in "English practice (DuSu)" strip
    english_target_min: Mapped[int] = mapped_column(Integer, default=15)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class PlGoal(Base):
    __tablename__ = "pl_goals"
    __table_args__ = (
        Index("uq_pl_goals_client", "user_id", "client_key", unique=True, postgresql_where=text("client_key IS NOT NULL")),
        Index("ix_pl_goals_user_status", "user_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    why: Mapped[str] = mapped_column(String(500), default="")
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    daily_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="active")          # active | paused | done | archived
    progress: Mapped[int] = mapped_column(Integer, default=0)                  # cached 0-100
    source: Mapped[str] = mapped_column(String(10), default="manual")          # manual | ai | career
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    completed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class PlMilestone(Base):
    __tablename__ = "pl_milestones"
    __table_args__ = (Index("ix_pl_ms_goal_seq", "goal_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("pl_goals.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[str] = mapped_column(String(300), default="")
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")            # open | done | skipped
    completed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class PlTask(Base):
    __tablename__ = "pl_tasks"
    __table_args__ = (
        Index("uq_pl_tasks_occ", "parent_id", "occ_date", unique=True, postgresql_where=text("parent_id IS NOT NULL")),
        Index("uq_pl_tasks_client", "user_id", "client_key", unique=True, postgresql_where=text("client_key IS NOT NULL")),
        Index("ix_pl_tasks_user_status_due", "user_id", "status", "due_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    milestone_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)     # the series this occurrence belongs to
    occ_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    is_series: Mapped[bool] = mapped_column(Boolean, default=False)           # a repeat template (never listed as a task itself)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=2)
    minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)     # local date
    due_has_time: Mapped[bool] = mapped_column(Boolean, default=False)
    due_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)     # UTC; a date-only task = end of that local day
    orig_due_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")            # open | done | skipped
    completed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    skipped_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    pin_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    recurrence: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    trigger: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)      # {label, fired, fallback_time}
    remind: Mapped[str] = mapped_column(String(12), default="none")
    remind_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)  # UTC; for remind == 'custom'
    reschedules: Mapped[list] = mapped_column(JSONB, default=list)            # [{from, to, at}] <= 20
    tz: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class PlHabit(Base):
    __tablename__ = "pl_habits"
    __table_args__ = (
        Index("uq_pl_habits_client", "user_id", "client_key", unique=True, postgresql_where=text("client_key IS NOT NULL")),
        Index("ix_pl_habits_user_status", "user_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(100), default="")
    target_count: Mapped[int] = mapped_column(Integer, default=1)
    unit: Mapped[str] = mapped_column(String(24), default="")
    partial_ok: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule: Mapped[dict] = mapped_column(JSONB, default=dict)               # {days: 'daily'|[0-6], times: ['HH:MM']}
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="active")         # active | paused | archived
    goal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tz: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class PlHabitLog(Base):
    __tablename__ = "pl_habit_logs"
    __table_args__ = (Index("uq_pl_habit_logs_day", "habit_id", "day", unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    habit_id: Mapped[int] = mapped_column(ForeignKey("pl_habits.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[dt.date] = mapped_column(Date)
    count: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(8), default="logged")           # logged | skipped
    note: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class PlReminder(Base):
    __tablename__ = "pl_reminders"
    __table_args__ = (
        Index("uq_pl_rem_key", "occurrence_key", unique=True),
        Index("ix_pl_rem_due", "fire_at", postgresql_where=text("status = 'scheduled'")),
        Index("ix_pl_rem_user_status", "user_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(10), default="task")       # task | habit | custom
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(10), default="time")              # time | recurring | condition | fallback
    title: Mapped[str] = mapped_column(String(160), default="")
    body: Mapped[str] = mapped_column(String(300), default="")
    occurrence_key: Mapped[str] = mapped_column(String(96))
    fire_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    tz: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(String(10), default="scheduled")       # waiting|scheduled|sending|sent|done|skipped|expired|cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    followups_sent: Mapped[int] = mapped_column(Integer, default=0)
    snooze_count: Mapped[int] = mapped_column(Integer, default=0)
    push_state: Mapped[str] = mapped_column(String(16), default="none")        # none | no_subscription | accepted | failed | stale
    last_error: Mapped[str] = mapped_column(String(120), default="")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)                    # {day, time} for habit reminders
    claimed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    acted_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    action: Mapped[str] = mapped_column(String(10), default="")
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class PlReminderRule(Base):
    """A reminder that REPEATS: "Gym at 7:00 on Mon and Tue", set once, then it rings on every one of those days until the learner pauses or deletes it.
    The rule is the thing that lasts; the reminders that actually ring are ordinary `pl_reminders` rows (entity_type 'custom', kind 'recurring',
    entity_id = this rule's id) that the materializer makes a day ahead - the same pattern habits use, so a restart or a deploy loses nothing.
    A brand-new table: `create_all` adds it, no existing table is altered."""
    __tablename__ = "pl_reminder_rules"
    __table_args__ = (
        Index("uq_pl_rrules_client", "user_id", "client_key", unique=True, postgresql_where=text("client_key IS NOT NULL")),
        Index("ix_pl_rrules_user_status", "user_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    time: Mapped[str] = mapped_column(String(5), default="09:00")             # the learner's wall clock, 'HH:MM'
    days: Mapped[list | str] = mapped_column(JSONB, default="daily")          # 'daily' | [0..6] (Mon = 0), same shape as a habit's days
    status: Mapped[str] = mapped_column(String(10), default="active")         # active | paused
    tz: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class PlPushSub(Base):
    __tablename__ = "pl_push_subs"
    __table_args__ = (Index("uq_pl_push_endpoint", "endpoint", unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(700))
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    ua: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    last_ok_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)


class PlEvent(Base):
    __tablename__ = "pl_events"
    __table_args__ = (Index("ix_pl_events_user_at", "user_id", "at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    entity_type: Mapped[str] = mapped_column(String(10), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(24), default="")
    at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


PL_TABLES = (PlPrefs, PlGoal, PlMilestone, PlTask, PlHabit, PlHabitLog, PlReminder, PlReminderRule, PlPushSub, PlEvent)
