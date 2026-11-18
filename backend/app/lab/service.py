"""Grammar Lab - every read and write, scoped to the learner.

Rules of the road (the Grammar Coach / My Day ones): every query filters on user_id; a foreign id is a 404, never a 403; a result can only be claimed for an item the SERVER served in a set it
holds; an answer is graded by pure code (checker.py) - there is no model call anywhere in this module; no learner text is ever stored; error messages never contain the learner's words.
A set is serialised by a row lock, so two quick taps on "Check" can never count one item twice.
"""

from __future__ import annotations

import datetime as dt
import random
import time
from collections import Counter

from ..store import delete, func, select
from ..store import pg_insert

from .. import db
from ..db import _now
from . import bank, catalog, checker, explain
from .models import GL_TABLES, GlAttempt, GlProgress, GlReview, GlSet

_S = lambda: db._Session()          # noqa: E731 - resolved at call time so tests can swap the engine

MAX_TRIES = 3                       # wrong answers on one item before the answer is shown
SET_SIZE = 10
SET_TTL_H = 6                       # an open set older than this is abandoned, not resumed
MAX_SETS_PER_DAY = 80
STAR_MIN_GRADED = 6                 # stars need at least this many graded items in the set (an "unsure" is not graded)
STAR_PCT = (60, 80, 90)             # 1, 2, 3 stars
KEEP_DAYS = 90
MAX_SAID = 400
_ITEMS: dict | None = None
_VARIANTS: dict = {}
_last_prune = 0.0
_rng = random.SystemRandom()


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


def items() -> dict:
    global _ITEMS
    if _ITEMS is None:
        _ITEMS = bank.load()
    return _ITEMS


def reset_cache() -> None:
    global _ITEMS, _VARIANTS
    _ITEMS, _VARIANTS = None, {}
    bank.reset()


def _variants(it) -> list:
    v = _VARIANTS.get(it.id)
    if v is None:
        v = _VARIANTS[it.id] = bank.variants(it.en)
    return v


def _utc() -> dt.datetime:
    return _now()


def _iso(d) -> str | None:
    return d.isoformat() if d else None


# ----------------------------------------------------------------------------- the hub
def catalog_payload() -> dict:
    return {"units": {u: {"name": m["name"], "gist": m["gist"], "formula": m["formula"], "marker": m["marker"], "example": m["example"], "family": m["family"], "type": m["type"], "code": m["code"]}
                      for u, m in catalog.UNIT_META.items()},
            "order": list(catalog.UNITS), "levels": {l: {"name": catalog.LEVEL_NAME[l], "gist": catalog.LEVEL_GIST[l]} for l in catalog.LEVELS},
            "families": catalog.FAMILY_NAME, "types": catalog.TYPE_NAME, "reviewed": catalog.REVIEWED, "version": catalog.VERSION}


async def state(uid: str) -> dict:
    its = items()
    counts: Counter = Counter((i.unit, i.level) for i in its.values())
    async with _S() as s:
        prog = (await s.execute(select(GlProgress).where(GlProgress.user_id == uid))).scalars().all()
        n_review = (await s.execute(select(func.count()).select_from(GlReview).where(GlReview.user_id == uid))).scalar() or 0
        open_sets = (await s.execute(select(GlSet).where(GlSet.user_id == uid, GlSet.state == "open").order_by(GlSet.id.desc()).limit(3))).scalars().all()
        await s.commit()
    by = {(p.unit, p.level): p for p in prog}
    units = []
    stars_total = 0
    for u in catalog.UNITS:
        lv = {}
        for l in catalog.LEVELS:
            p = by.get((u, l))
            lv[l] = {"items": counts.get((u, l), 0), "stars": p.stars if p else 0, "best": p.best_pct if p else 0, "sets": p.sets if p else 0}
            stars_total += lv[l]["stars"]
        units.append({"unit": u, "levels": lv, "stars": sum(x["stars"] for x in lv.values())})
    now = _utc()
    open_set = None
    for r in open_sets:
        if r.created_at and (now - r.created_at) < dt.timedelta(hours=SET_TTL_H):
            done = sum(1 for v in (r.results or {}).values() if v.get("done"))
            if done < len(r.items or []):
                open_set = {"id": r.id, "unit": r.unit, "level": r.level, "answered": done, "total": len(r.items or [])}
                break
    await _maybe_prune()
    return {"units": units, "stars": stars_total, "stars_max": len(catalog.UNITS) * len(catalog.LEVELS) * 3, "review_due": n_review, "open_set": open_set,
            "ready": bool(its), "items": len(its), "catalog": catalog_payload()}


# ----------------------------------------------------------------------------- a set
def _set_payload(row: GlSet) -> dict:
    its = items()
    res = row.results or {}
    return {"set": row.id, "unit": row.unit, "level": row.level, "total": len(row.items or []),
            "answered": sum(1 for v in res.values() if v.get("done")),
            "items": [{"id": i, "hi": its[i].hi, "done": bool(res.get(i, {}).get("done")), "tries": int(res.get(i, {}).get("tries", 0))} for i in (row.items or []) if i in its]}


async def make_set(uid: str, unit: str, level: str) -> dict:
    """Open (or resume) a set of up to 10 items.  `unit` "mixed" + `level` "review" = the items the learner missed before."""
    its = items()
    review = (unit, level) == ("mixed", "review")
    if not review and (unit not in catalog.UNITS or level not in catalog.LEVELS):
        raise Invalid("unit_level")
    now = _utc()
    async with _S() as s:
        await s.advisory_lock("gl:" + uid)                                       # two quick taps on "start" must not make two sets (there is no row to lock yet when none is open)
        n_today = (await s.execute(select(func.count()).select_from(GlSet).where(GlSet.user_id == uid, GlSet.created_at >= now - dt.timedelta(hours=24)))).scalar() or 0
        olds = (await s.execute(select(GlSet).where(GlSet.user_id == uid, GlSet.state == "open").order_by(GlSet.id.desc()).with_for_update())).scalars().all()
        resume = None
        for r in olds:
            fresh = r.created_at and (now - r.created_at) < dt.timedelta(hours=SET_TTL_H)
            unanswered = len(r.items or []) - sum(1 for v in (r.results or {}).values() if v.get("done"))
            if resume is None and fresh and r.unit == unit and r.level == level and unanswered > 0:
                resume = r
            else:
                r.state = "abandoned"
        if resume is not None:
            await s.commit()
            return _set_payload(resume)
        if n_today >= MAX_SETS_PER_DAY:
            await s.commit()
            raise Invalid("too_many")
        if review:
            rows = (await s.execute(select(GlReview).where(GlReview.user_id == uid, GlReview.misses > 0).order_by(GlReview.last_at))).scalars().all()
            chosen = [its[r.item_id] for r in rows if r.item_id in its][:SET_SIZE]
            if not chosen:
                await s.commit()
                raise Invalid("nothing_to_review")
            _rng.shuffle(chosen)
            prog = None
        else:
            pool = sorted((i for i in its.values() if i.unit == unit and i.level == level), key=lambda i: i.id)
            if not pool:
                await s.commit()
                raise Invalid("empty")
            await s.execute(pg_insert(GlProgress).values(user_id=uid, unit=unit, level=level, sets=0, stars=0, best_pct=0, best_right=0, best_graded=0, recent=[]).on_conflict_do_nothing(index_elements=["user_id", "unit", "level"]))
            prog = (await s.execute(select(GlProgress).where(GlProgress.user_id == uid, GlProgress.unit == unit, GlProgress.level == level).with_for_update())).scalars().first()
            recent = list(prog.recent or []) if prog else []
            miss = {r.item_id for r in (await s.execute(select(GlReview).where(GlReview.user_id == uid, GlReview.unit == unit, GlReview.level == level, GlReview.misses > 0))).scalars().all()}
            n = min(SET_SIZE, len(pool))
            due = [i for i in pool if i.id in miss]
            _rng.shuffle(due)
            chosen = due[:3]
            fresh_items = [i for i in pool if i.id not in recent and i not in chosen]
            _rng.shuffle(fresh_items)
            chosen += fresh_items[:n - len(chosen)]
            if len(chosen) < n:                                              # the pool is small: take the ones served longest ago
                rest = sorted((i for i in pool if i not in chosen), key=lambda i: recent.index(i.id) if i.id in recent else -1)
                chosen += rest[:n - len(chosen)]
            _rng.shuffle(chosen)
            if prog is not None:
                prog.recent = (recent + [i.id for i in chosen])[-40:]
        row = GlSet(user_id=uid, unit=unit, level=level, items=[i.id for i in chosen], results={}, state="open", summary={}, created_at=now)
        s.add(row)
        await s.flush()
        await s.commit()
        return _set_payload(row)


async def get_set(uid: str, sid: int) -> dict:
    async with _S() as s:
        row = (await s.execute(select(GlSet).where(GlSet.id == sid, GlSet.user_id == uid))).scalars().first()
        await s.commit()
    if row is None:
        raise NotFound()
    out = _set_payload(row)
    if row.state == "done":
        out["summary"] = row.summary
    return out


# ----------------------------------------------------------------------------- checking an answer
def _reveal(it, kind: str, tries: int, expl: dict, done: bool) -> dict:
    """How much of the explanation a learner gets: the rule first, the exact change after a second miss, the answer after the third (or when they ask)."""
    out = {lg: {"headline": d.get("headline", ""), "rules": list(d.get("rules", [])), "changes": [], "formula": d.get("formula", ""), "marker": d.get("marker", ""),
                "gist": d.get("gist", ""), "trap": d.get("trap", "")} for lg, d in expl.items()}
    if kind == "wrong" and (tries >= 2 or done):
        for lg in out:
            out[lg]["changes"] = list(expl[lg].get("changes", []))
    if kind == "unsure":
        for lg in out:
            out[lg]["changes"] = list(expl[lg].get("changes", []))
    return out


async def _finish_item(s, uid: str, row: GlSet, it, res: dict, codes: list) -> None:
    now = _utc()
    s.add(GlAttempt(user_id=uid, set_id=row.id, item_id=it.id, unit=it.unit, level=it.level, verdict=res["v"], tries=int(res["tries"]), codes=list(codes)[:3], created_at=now))
    v = res["v"]
    if v in ("wrong", "shown"):
        await s.execute(pg_insert(GlReview).values(user_id=uid, item_id=it.id, unit=it.unit, level=it.level, misses=0, last_at=now).on_conflict_do_nothing(index_elements=["user_id", "item_id"]))
        rv = (await s.execute(select(GlReview).where(GlReview.user_id == uid, GlReview.item_id == it.id).with_for_update())).scalars().first()
        if rv is not None:
            rv.misses = min(5, int(rv.misses or 0) + 1)
            rv.last_at = now
    elif v == "ok":
        rv = (await s.execute(select(GlReview).where(GlReview.user_id == uid, GlReview.item_id == it.id).with_for_update())).scalars().first()
        if rv is not None:
            rv.misses = int(rv.misses or 0) - 1
            if rv.misses <= 0:
                await s.delete(rv)
            else:
                rv.last_at = now


def _stars(right: int, graded: int) -> int:
    if graded < STAR_MIN_GRADED:
        return 0
    pct = 100 * right / graded
    return sum(1 for p in STAR_PCT if pct >= p)


def _next_step(unit: str, level: str, stars: int, pct: int) -> dict:
    if unit == "mixed":
        return {"unit": "mixed", "level": "review", "reason": "review"}
    if stars < 2:
        return {"unit": unit, "level": level, "reason": "again"}
    li = catalog.LEVELS.index(level)
    if li + 1 < len(catalog.LEVELS):
        return {"unit": unit, "level": catalog.LEVELS[li + 1], "reason": "next_level"}
    ui = catalog.UNITS.index(unit)
    if ui + 1 >= len(catalog.UNITS):                                   # the last level of the last unit: nothing comes after it (never wrap to the first unit)
        return {"unit": unit, "level": level, "reason": "path_end"}
    return {"unit": catalog.UNITS[ui + 1], "level": "easy", "reason": "next_unit"}


async def _finalize(s, uid: str, row: GlSet) -> dict:
    its = items()
    res = row.results or {}
    right = sum(1 for v in res.values() if v.get("v") == "ok")
    wrong = sum(1 for v in res.values() if v.get("v") in ("wrong", "shown"))
    unsure = sum(1 for v in res.values() if v.get("v") == "unsure")
    first = sum(1 for v in res.values() if v.get("v") == "ok" and v.get("first"))
    graded = right + wrong
    pct = round(100 * right / graded) if graded else 0
    stars = _stars(right, graded)
    codes = Counter(c[0] for v in res.values() if v.get("v") in ("wrong", "shown") for c in [v.get("codes") or []] if c)
    weak = [{"code": c, "n": n, "rule": explain.rule_text(c, row.unit)} for c, n in codes.most_common(2)]
    missed = [{"id": i, "hi": its[i].hi, "en": its[i].en[0]} for i in row.items if i in its and res.get(i, {}).get("v") in ("wrong", "shown")]
    summary = {"right": right, "wrong": wrong, "unsure": unsure, "first_try": first, "total": len(row.items), "graded": graded, "pct": pct, "stars": stars,
               "weak": weak, "missed": missed, "new_best": False, "best_stars": stars, "best_pct": pct}
    now = _utc()
    if row.unit in catalog.UNITS and row.level in catalog.LEVELS:
        prog = (await s.execute(select(GlProgress).where(GlProgress.user_id == uid, GlProgress.unit == row.unit, GlProgress.level == row.level).with_for_update())).scalars().first()
        if prog is None:
            prog = GlProgress(user_id=uid, unit=row.unit, level=row.level, sets=0, stars=0, best_pct=0, best_right=0, best_graded=0, recent=[])
            s.add(prog)
        prog.sets = int(prog.sets or 0) + 1
        prog.last_at = now
        if graded and (stars, pct) > (int(prog.stars or 0), int(prog.best_pct or 0)):
            prog.stars, prog.best_pct, prog.best_right, prog.best_graded = stars, pct, right, graded
            summary["new_best"] = True
        summary["best_stars"], summary["best_pct"] = int(prog.stars or 0), int(prog.best_pct or 0)
    summary["next"] = _next_step(row.unit, row.level, stars, pct)
    row.state, row.done_at, row.summary = "done", now, summary
    return summary


async def check(uid: str, sid: int, item_id: str, said) -> dict:
    its = items()
    it = its.get(str(item_id))
    if it is None:
        raise NotFound()
    said = str(said or "")[:MAX_SAID]
    async with _S() as s:
        row = (await s.execute(select(GlSet).where(GlSet.id == sid, GlSet.user_id == uid).with_for_update())).scalars().first()
        if row is None or it.id not in (row.items or []):
            await s.commit()
            raise NotFound()
        results = dict(row.results or {})
        cur = dict(results.get(it.id) or {"tries": 0, "done": False})
        if cur.get("done"):                                            # a repeated request: the stored outcome, never a second grading
            out = _stored_result(row, it, cur)
            await s.commit()
            return out
        if row.state != "open":
            await s.commit()
            raise Invalid("closed")
        r = checker.check(said, _variants(it), it.unit)
        verdict = r["verdict"]
        if verdict in ("empty", "lang"):                               # not an attempt: nothing is counted
            expl = explain.build(r, it.unit)
            await s.commit()
            return {"verdict": verdict, "tries": int(cur["tries"]), "left": MAX_TRIES - int(cur["tries"]), "done": False, "explain": _reveal(it, verdict, 0, expl, False),
                    "answered": sum(1 for v in results.values() if v.get("done")), "total": len(row.items)}
        cur["tries"] = int(cur["tries"]) + 1
        if verdict == "ok":
            cur.update(done=True, v="ok", first=cur["tries"] == 1)
        elif verdict == "unsure":
            cur.update(done=True, v="unsure", first=False)
        else:
            cur["codes"] = r.get("codes", [])[:3]
            if cur["tries"] >= MAX_TRIES:
                cur.update(done=True, v="wrong", first=False)
        results[it.id] = cur
        row.results = results
        if cur.get("done"):
            await _finish_item(s, uid, row, it, cur, cur.get("codes") or [])
        summary = None
        if len(row.items) and all(results.get(i, {}).get("done") for i in row.items):
            summary = await _finalize(s, uid, row)
        expl = explain.build(r, it.unit, it.trap) if verdict != "ok" else {}
        out = {"verdict": verdict if not (verdict == "wrong" and cur.get("done")) else "wrong", "tries": cur["tries"], "left": max(0, MAX_TRIES - cur["tries"]), "done": bool(cur.get("done")),
               "answered": sum(1 for v in results.values() if v.get("done")), "total": len(row.items)}
        if expl:
            out["explain"] = _reveal(it, verdict, cur["tries"], expl, bool(cur.get("done")))
        if cur.get("done"):
            out["target"] = r.get("target") if verdict == "ok" else it.en[0]
            out["model"] = it.en[0]
            out["also"] = list(it.en[1:])
            out["first_try"] = bool(cur.get("first"))
        if summary is not None:
            out["summary"] = summary
        await s.commit()
        return out


def _stored_result(row: GlSet, it, cur: dict) -> dict:
    results = row.results or {}
    out = {"verdict": cur.get("v", "ok"), "tries": int(cur.get("tries", 1)), "left": 0, "done": True, "repeat": True, "target": it.en[0], "model": it.en[0], "also": list(it.en[1:]),
           "first_try": bool(cur.get("first")), "answered": sum(1 for v in results.values() if v.get("done")), "total": len(row.items)}
    if row.state == "done":
        out["summary"] = row.summary
    return out


async def show(uid: str, sid: int, item_id: str) -> dict:
    """The learner asks to see the answer: the item is finished as 'shown' (it counts as a miss and goes to review)."""
    its = items()
    it = its.get(str(item_id))
    if it is None:
        raise NotFound()
    async with _S() as s:
        row = (await s.execute(select(GlSet).where(GlSet.id == sid, GlSet.user_id == uid).with_for_update())).scalars().first()
        if row is None or it.id not in (row.items or []):
            await s.commit()
            raise NotFound()
        results = dict(row.results or {})
        cur = dict(results.get(it.id) or {"tries": 0, "done": False})
        if cur.get("done"):
            out = _stored_result(row, it, cur)
            await s.commit()
            return out
        if row.state != "open":
            await s.commit()
            raise Invalid("closed")
        cur.update(done=True, v="shown", first=False)
        results[it.id] = cur
        row.results = results
        await _finish_item(s, uid, row, it, cur, cur.get("codes") or [])
        summary = None
        if all(results.get(i, {}).get("done") for i in row.items):
            summary = await _finalize(s, uid, row)
        out = {"verdict": "shown", "tries": int(cur["tries"]), "left": 0, "done": True, "target": it.en[0], "model": it.en[0], "also": list(it.en[1:]), "explain": explain.static_help(it.unit, it.trap, it.en[0]),
               "answered": sum(1 for v in results.values() if v.get("done")), "total": len(row.items)}
        if summary is not None:
            out["summary"] = summary
        await s.commit()
        return out


# ----------------------------------------------------------------------------- housekeeping + data rights
async def _maybe_prune() -> None:
    global _last_prune
    if time.time() - _last_prune < 3600:
        return
    _last_prune = time.time()
    cut = _utc() - dt.timedelta(days=KEEP_DAYS)
    try:
        async with _S() as s:
            await s.execute(delete(GlAttempt).where(GlAttempt.created_at < cut))
            await s.execute(delete(GlSet).where(GlSet.created_at < cut))
            await s.commit()
    except Exception as e:
        print(f"[lab] prune: {type(e).__name__}")


async def delete_rows(s, uids: list) -> None:
    """FK-safe delete of every Grammar Lab row for these users, inside the caller's transaction (db.delete_user / admin_wipe_users call it)."""
    for M in GL_TABLES:
        await s.execute(delete(M).where(M.user_id.in_(uids)))


async def delete_all(uid: str) -> dict:
    async with _S() as s:
        await delete_rows(s, [uid])
        await s.commit()
    return {"ok": True}


async def export_all(uid: str) -> dict:
    async with _S() as s:
        prog = (await s.execute(select(GlProgress).where(GlProgress.user_id == uid))).scalars().all()
        sets = (await s.execute(select(GlSet).where(GlSet.user_id == uid).order_by(GlSet.id))).scalars().all()
        att = (await s.execute(select(GlAttempt).where(GlAttempt.user_id == uid).order_by(GlAttempt.id))).scalars().all()
        rev = (await s.execute(select(GlReview).where(GlReview.user_id == uid))).scalars().all()
        await s.commit()
    return {"progress": [{"unit": p.unit, "level": p.level, "sets": p.sets, "stars": p.stars, "best_pct": p.best_pct, "last_at": _iso(p.last_at)} for p in prog],
            "sets": [{"id": r.id, "unit": r.unit, "level": r.level, "items": r.items, "results": r.results, "state": r.state, "summary": r.summary, "created_at": _iso(r.created_at), "done_at": _iso(r.done_at)} for r in sets],
            "attempts": [{"set_id": a.set_id, "item_id": a.item_id, "unit": a.unit, "level": a.level, "verdict": a.verdict, "tries": a.tries, "codes": a.codes, "created_at": _iso(a.created_at)} for a in att],
            "review": [{"item_id": r.item_id, "unit": r.unit, "level": r.level, "misses": r.misses, "last_at": _iso(r.last_at)} for r in rev]}


async def health() -> dict:
    try:
        async with _S() as s:
            sets = (await s.execute(select(func.count()).select_from(GlSet))).scalar() or 0
            att = (await s.execute(select(func.count()).select_from(GlAttempt))).scalar() or 0
            await s.commit()
        return {"sets": sets, "attempts": att, "items": len(items())}
    except Exception as e:
        return {"error": type(e).__name__}
