"""Grammar Coach - tables (all new, prefix `gc_`; plan section 8).

Brand-new tables only: `create_all` makes them and no existing table is altered - anything that may evolve lives in JSONB next to a
`rules_version`. Every row carries `user_id` (FK to users) and every query in service.py filters on it. Links between these tables are plain
indexed integers; deletion order is explicit in `service.delete_rows` (called by db.delete_user / admin_wipe_users) and `service.delete_by_ref`
(called when a Practice attempt or an interview is deleted). Timestamps are UTC. Enumerated columns are String(32) wide on purpose (the My Day
lesson) and an introspection test checks every value we write against its width.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, _now

TS = DateTime(timezone=True)


class GcSession(Base):
    """One analysed stretch of English speech (a Face-to-Face talk, an interview, a Practice attempt, a Job Interview Practice session).
    The numbers are a pure fold over `units` (scoring.fold_units), so every surface shares one idempotent path."""
    __tablename__ = "gc_sessions"
    __table_args__ = (
        Index("uq_gc_session_client", "user_id", "client_key", unique=True, postgresql_where=text("client_key IS NOT NULL")),
        Index("ix_gc_session_user_created", "user_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))                       # talk | interview | practice | job_interview
    kind: Mapped[str] = mapped_column(String(32), default="")             # presentation / speech / seminar / viva / discussion / custom
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)   # ws:<gref> | pa:<attemptId> | ri:<sessionId>
    lang: Mapped[str] = mapped_column(String(8), default="en")
    level: Mapped[str] = mapped_column(String(8), default="")
    state: Mapped[str] = mapped_column(String(32), default="pending")     # pending | done | partial | failed
    claimed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    text_saved: Mapped[bool] = mapped_column(Boolean, default=False)      # sentence rows exist (the learner chose to keep them)
    units: Mapped[list] = mapped_column(JSONB, default=list)
    timeline: Mapped[str] = mapped_column(String(600), default="")        # one char per sentence: o n x ~ - ?
    words: Mapped[int] = mapped_column(Integer, default=0)
    words_checked: Mapped[int] = mapped_column(Integer, default=0)
    sentences: Mapped[int] = mapped_column(Integer, default=0)
    checked: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    clean: Mapped[int] = mapped_column(Integer, default=0)
    marks_error: Mapped[int] = mapped_column(Integer, default=0)
    marks_natural: Mapped[int] = mapped_column(Integer, default=0)
    per100: Mapped[float | None] = mapped_column(Float, nullable=True)    # NULL when the minimum evidence is not met
    rule_counts: Mapped[dict] = mapped_column(JSONB, default=dict)        # {rule or rule#entry: {hits, opp}}
    family_counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    flow: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    top: Mapped[list] = mapped_column(JSONB, default=list)
    best_run: Mapped[int] = mapped_column(Integer, default=0)
    duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    rules_version: Mapped[int] = mapped_column(Integer, default=1)
    engine: Mapped[dict] = mapped_column(JSONB, default=dict)             # source chrome|whisper|gemini, calls, dropped, quick, degraded, tally
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class GcSentence(Base):
    """ONLY a sentence that had a mistake or a tip, and only after the learner chose to keep them (redact_light applied). Correct sentences
    exist only as timeline codes in gc_sessions."""
    __tablename__ = "gc_sentences"
    __table_args__ = (Index("ix_gc_sentence_user_created", "user_id", "created_at"), Index("ix_gc_sentence_session", "session_id", "pos"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[int] = mapped_column(Integer)
    unit: Mapped[int] = mapped_column(Integer, default=0)
    pos: Mapped[int] = mapped_column(Integer, default=0)
    said: Mapped[str] = mapped_column(String(320), default="")
    fixed: Mapped[str] = mapped_column(String(480), default="")
    status: Mapped[str] = mapped_column(String(32), default="fix")        # fix | natural | unsure
    contest: Mapped[str] = mapped_column(String(32), default="none")      # none | not_said | is_correct
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class GcMark(Base):
    """One verified finding. With "counts only" (or before the learner's choice) a row still exists - rule + family + severity + date - but
    sentence_id is NULL and quote / fix / why are empty, so per-rule counts and trends keep working without any text."""
    __tablename__ = "gc_marks"
    __table_args__ = (Index("ix_gc_mark_user_rule", "user_id", "rule", "created_at"), Index("ix_gc_mark_session", "session_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[int] = mapped_column(Integer)
    sentence_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rule: Mapped[str] = mapped_column(String(64))
    family: Mapped[str] = mapped_column(String(32), default="")
    severity: Mapped[str] = mapped_column(String(32), default="error")
    conf: Mapped[str] = mapped_column(String(32), default="sure")         # sure | likely
    src: Mapped[str] = mapped_column(String(32), default="model")         # model | rule | both
    quote: Mapped[str] = mapped_column(String(160), default="")
    fix: Mapped[str] = mapped_column(String(200), default="")
    why: Mapped[str] = mapped_column(String(200), default="")
    contest: Mapped[str] = mapped_column(String(32), default="none")      # none | not_said | is_correct
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class GcDrill(Base):
    """Drill progress per learner and rule. A result batch carries a client_key; a rule's row skips a batch whose key equals its last_key."""
    __tablename__ = "gc_drills"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    rule: Mapped[str] = mapped_column(String(64), primary_key=True)
    right: Mapped[int] = mapped_column(Integer, default=0)
    wrong: Mapped[int] = mapped_column(Integer, default=0)
    streak: Mapped[int] = mapped_column(Integer, default=0)
    last_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    last_key: Mapped[str] = mapped_column(String(64), default="")


GC_TABLES = (GcSession, GcSentence, GcMark, GcDrill)
