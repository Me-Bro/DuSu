"""Grammar Lab - tables (all new, prefix `gl_`).

Brand-new collections only: `create_all` makes them and no existing table is altered.  Every row carries `user_id` (FK to users) and every query in service.py filters on it.  NO learner text is
stored anywhere: an attempt keeps the item id, the verdict, the number of tries and the error codes - never what the learner typed or said (the Grammar Coach rule: a transcript is never stored).
Column widths are checked against every value the code writes (tests/lab/selftest.py introspection).
"""

from __future__ import annotations

import datetime as dt

from ..store import DateTime, ForeignKey, Index, Integer, String
from ..store import JSONB
from ..store import Mapped, mapped_column

from ..db import Base, _now

TS = DateTime(timezone=True)


class GlSet(Base):
    """One practice set (up to 10 items).  The set is held on the SERVER: the items and the learner's per-item state live here, so a result can never be claimed for an item that was not served."""
    __tablename__ = "gl_sets"
    __table_args__ = (Index("ix_gl_set_user_state", "user_id", "state"), Index("ix_gl_set_user_created", "user_id", "created_at"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    unit: Mapped[str] = mapped_column(String(32))                         # a unit id, or "mixed" for a review set
    level: Mapped[str] = mapped_column(String(8))                         # easy | medium | hard | extra | review
    items: Mapped[list] = mapped_column(JSONB, default=list)              # item ids, in the order served
    results: Mapped[dict] = mapped_column(JSONB, default=dict)            # {item id: {"tries": n, "done": bool, "v": ok|wrong|unsure|shown, "first": bool}}
    state: Mapped[str] = mapped_column(String(10), default="open")        # open | done | abandoned
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)
    done_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class GlProgress(Base):
    """Best result per unit and level (stars) and the ids served lately (so the next set does not repeat them)."""
    __tablename__ = "gl_progress"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    unit: Mapped[str] = mapped_column(String(32), primary_key=True)
    level: Mapped[str] = mapped_column(String(8), primary_key=True)
    sets: Mapped[int] = mapped_column(Integer, default=0)
    stars: Mapped[int] = mapped_column(Integer, default=0)                # best stars, 0-3
    best_pct: Mapped[int] = mapped_column(Integer, default=0)
    best_right: Mapped[int] = mapped_column(Integer, default=0)
    best_graded: Mapped[int] = mapped_column(Integer, default=0)
    recent: Mapped[list] = mapped_column(JSONB, default=list)
    last_at: Mapped[dt.datetime | None] = mapped_column(TS, nullable=True)


class GlAttempt(Base):
    """One FINISHED item (one row per item per set): the server-graded evidence the Path will read.  No text."""
    __tablename__ = "gl_attempts"
    __table_args__ = (Index("ix_gl_attempt_user_created", "user_id", "created_at"), Index("ix_gl_attempt_set", "set_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    set_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(String(16))
    unit: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(8))
    verdict: Mapped[str] = mapped_column(String(10))                      # ok | wrong | unsure | shown
    tries: Mapped[int] = mapped_column(Integer, default=1)
    codes: Mapped[list] = mapped_column(JSONB, default=list)              # the error codes of the last wrong answer (<= 3), e.g. ["vf:base>s"]
    created_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


class GlReview(Base):
    """An item the learner missed (answered wrong or looked up).  A later correct answer takes a miss off; at zero the row goes."""
    __tablename__ = "gl_review"
    __table_args__ = (Index("ix_gl_review_user_last", "user_id", "last_at"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    unit: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(8))
    misses: Mapped[int] = mapped_column(Integer, default=1)
    last_at: Mapped[dt.datetime] = mapped_column(TS, default=_now)


GL_TABLES = (GlReview, GlAttempt, GlSet, GlProgress)           # child-first: the order a delete walks them
