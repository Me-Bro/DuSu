"""Resume Interview - tables (all new, prefix `ri_`; DUSU_RESUME_INTERVIEW_PLAN.md §7).

Brand-new tables only: `create_all` makes them and no existing table is altered - so the columns stay stable and anything that may evolve
lives in JSONB next to a `rules_version`. Every row carries `user_id` (FK to users) and every query in service.py filters on it. Links between
these tables are plain indexed integers (like planner.goal_id): deletion order is explicit in `service.delete_rows`, which `db.delete_user`
and `db.admin_wipe_users` call first. Timestamps are UTC. Enumerated columns are String(32) wide on purpose (the My Day lesson: a 15-character
value in a String(14) column failed only on a real database) and an introspection test checks every value we write against its width.
There is deliberately NO audio table: recordings stay on the learner's phone.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, _now

TS = DateTime(timezone=True)


class RiDocument(Base):
    """A resume or a job description, as the learner confirmed it: REDACTED text (no contact / personal details), immutable - an edit is a new
    version (parent_id). No file name is stored (it usually contains the learner's name). For a JD, `meta` holds its extracted requirements."""
    __tablename__ = "ri_documents"
    __table_args__ = (
        Index("uq_ri_doc_sha", "user_id", "kind", "text_sha", unique=True),
        Index("uq_ri_doc_client", "user_id", "client_key", unique=True, postgresql_where=text("client_key IS NOT NULL")),
        Index("ix_ri_doc_user_kind", "user_id", "kind", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))                       # resume | jd
    title: Mapped[str] = mapped_column(String(160), default="")
    company: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(32), default="paste")    # pdf | docx | txt | paste
    chars: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    text_sha: Mapped[str] = mapped_column(String(64), default="")
    redactions: Mapped[dict] = mapped_column(JSONB, default=dict)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class RiAnalysis(Base):
    """The match of ONE resume version against ONE job. Cached: an identical pair + rules_version is never analysed twice."""
    __tablename__ = "ri_analyses"
    __table_args__ = (Index("uq_ri_analysis_pair", "user_id", "resume_id", "jd_id", unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resume_id: Mapped[int] = mapped_column(Integer, index=True)
    jd_id: Mapped[int] = mapped_column(Integer, index=True)
    prev_id: Mapped[int | None] = mapped_column(Integer, nullable=True)         # the analysis this one improves on (a re-uploaded resume)
    state: Mapped[str] = mapped_column(String(32), default="pending")           # pending | done | failed
    claimed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    match_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    band: Mapped[str] = mapped_column(String(32), default="unknown")
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    picked: Mapped[list] = mapped_column(JSONB, default=list)                   # the edit ids the learner ticked
    rules_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class RiSession(Base):
    """One mock interview. No stored counters: asked / answered / real are GROUP BYs over ri_turns under the session lock, so they cannot drift."""
    __tablename__ = "ri_sessions"
    __table_args__ = (
        Index("uq_ri_session_client", "user_id", "client_key", unique=True, postgresql_where=text("client_key IS NOT NULL")),
        Index("ix_ri_session_user_created", "user_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    resume_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jd_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")            # draft | matched | active | finished
    plan_state: Mapped[str] = mapped_column(String(32), default="none")         # none | pending | done
    plan_claimed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    brief: Mapped[dict] = mapped_column(JSONB, default=dict)
    overall: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    awarded_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)    # compare-and-set: XP is paid exactly once
    rev: Mapped[int] = mapped_column(Integer, default=0)
    client_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    started_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    last_activity_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class RiTurn(Base):
    """One question. The plan is ROWS (status 'queued', idx NULL): the first non-terminal turn is the pointer, idx is assigned when it is asked."""
    __tablename__ = "ri_turns"
    __table_args__ = (
        Index("uq_ri_turn_idx", "session_id", "idx", unique=True, postgresql_where=text("idx IS NOT NULL")),
        Index("uq_ri_turn_pos", "session_id", "plan_pos", unique=True, postgresql_where=text("plan_pos IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="resume")
    source: Mapped[str] = mapped_column(String(32), default="plan")             # plan | followup | bank
    question: Mapped[str] = mapped_column(Text, default="")
    why: Mapped[str] = mapped_column(Text, default="")
    req_ids: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(32), default="queued")           # queued | asked | answered | skipped | dropped
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_words: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine: Mapped[str | None] = mapped_column(String(32), nullable=True)       # groq | gemini
    audio_device: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    scores: Mapped[dict] = mapped_column(JSONB, default=dict)
    feedback: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    feedback_state: Mapped[str] = mapped_column(String(32), default="none")     # none | pending | done | failed
    feedback_claimed_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    feedback_attempts: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    real: Mapped[bool] = mapped_column(Boolean, default=False)
    asked_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    answered_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


RI_TABLES = (RiDocument, RiAnalysis, RiSession, RiTurn)
