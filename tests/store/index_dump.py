"""Dump every index a tree declares, as JSON: [{table, cols, unique, partial}]. Runs inside EITHER tree (mounted at /app): the OLD one (SQLAlchemy models) or the NEW one
(the store's models) - whichever imports. `tests/store/index_parity.sh` runs both and diffs them: no index may be lost in the translation."""
import json
import os
import re
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("SESSION_SECRET", "x")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("MONGODB_URI", None)

from app import main as _main                                           # noqa: E402,F401  (imports every model module)
from app import db                                                      # noqa: E402

out = []
try:                                                                    # ---- the NEW tree: app.store models
    models = db.Base.models()
    for M in models:
        seen = set()
        for ix in M.__indexes__:
            key = (tuple(ix.cols), bool(ix.unique))
            if key in seen:
                continue
            seen.add(key)
            out.append({"table": M.__tablename__, "cols": list(ix.cols), "unique": bool(ix.unique), "partial": bool(ix.where), "name": ix.name})
except AttributeError:                                                  # ---- the OLD tree: SQLAlchemy metadata
    from sqlalchemy import Column, UniqueConstraint

    def colname(e):
        if isinstance(e, Column):
            return e.name
        s = re.sub(r"\s+", " ", str(e).strip().lower())
        m = re.match(r"^(?:\w+\.)?(\w+) desc$", s)
        return ("-" + m.group(1)) if m else s

    for t in db.Base.metadata.tables.values():
        seen = set()
        for ix in t.indexes:
            cols = [colname(e) for e in ix.expressions]
            key = (tuple(cols), bool(ix.unique))
            if key in seen:
                continue
            seen.add(key)
            out.append({"table": t.name, "cols": cols, "unique": bool(ix.unique), "partial": bool(ix.dialect_options["postgresql"].get("where") is not None), "name": ix.name})
        for c in t.constraints:
            if isinstance(c, UniqueConstraint):
                cols = [x.name for x in c.columns]
                key = (tuple(cols), True)
                if key not in seen:
                    seen.add(key)
                    out.append({"table": t.name, "cols": cols, "unique": True, "partial": False, "name": c.name or "uq"})
        pk = [c.name for c in t.primary_key.columns]
        out.append({"table": t.name, "cols": pk, "unique": True, "partial": False, "name": "PRIMARY KEY", "pk": True})
print(json.dumps(out))
