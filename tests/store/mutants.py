"""Planted bugs for app/store: each is an exact-text replacement in a COPY of the layer. tests/store/mutants.sh applies one at a time and runs the tiers - a mutant the tests do not
fail on SURVIVED, and that is a hole in the tests, not a pass.   python3 mutants.py --check | --ids | --apply <ID> <app dir>"""

import sys

M = {}


def mut(id_, desc, file, old, new):
    M[id_] = (desc, file, old, new)


# ---------------------------------------------------------------- NULL / SQL semantics (expr.py)
mut("S1", "!= compiled as plain $ne: NULL rows leak into `col != v`", "store/expr.py",
    '"!=": {f: {"$nin": [v, None]}}', '"!=": {f: {"$ne": v}}')
mut("S2", "NULL placement flipped in Python sorts", "store/expr.py",
    "null_rank = 1 if null_is_largest else -1", "null_rank = -1 if null_is_largest else 1")
mut("S3", "IN keeps None in its list", "store/expr.py",
    "self.values = [col.type.to_bind(v) for v in values if v is not None]", "self.values = [col.type.to_bind(v) for v in values]")
mut("S4", "sort pushed down to Mongo for a NULLABLE column", "store/expr.py",
    "if not isinstance(expr, ColumnOps) or expr.nullable or nulls is not None:", "if not isinstance(expr, ColumnOps) or nulls is not None:")
mut("S5", "LIKE not anchored", "store/expr.py",
    'return "^" + "".join(out) + "$"', 'return "".join(out)')
mut("S6", "IS NOT TRUE excludes NULL", "store/expr.py",
    'return {f: {"$ne": node.value}} if node.negate else {f: node.value}', 'return {f: {"$nin": [node.value, None]}} if node.negate else {f: node.value}')

# ---------------------------------------------------------------- the session (session.py)
mut("S7", "no autoflush before a SELECT", "store/session.py",
    "        flt = to_filter(and_(*st._where))\n        await self._autoflush()\n        if st._group", "        flt = to_filter(and_(*st._where))\n        if st._group")
mut("S8", "flush takes no row locks", "store/session.py",
    "            await self._lock_keys([(type(i).__tablename__, type(i).pk_id(i._pk())) for i, _ in dirty] + [(type(i).__tablename__, type(i).pk_id(i._pk())) for i in dele])",
    "            pass")
mut("S9", "get(with_for_update=True) does not lock", "store/session.py",
    "            await self._lock_keys([(model.__tablename__, model.pk_id(pk))])", "            pass")
mut("S10", "a replay does not compare what it affected with the first run", "store/session.py",
    '                if n != op.expect:\n                    raise ConcurrencyError(f"replay of', '                if False:\n                    raise ConcurrencyError(f"replay of')
mut("S11", "locks released at flush instead of at commit", "store/session.py",
    "        for inst, st in prepared:\n            inst._snap = copy.deepcopy(st)", "        self._release_locks()\n        for inst, st in prepared:\n            inst._snap = copy.deepcopy(st)")
mut("S12", "commit() never commits the transaction", "store/session.py",
    "                    await self._ms.commit_transaction()\n                    break", "                    break")
mut("S13", "no identity map: the same row loads as a new object every time", "store/session.py",
    "        have = self._ident.get(key)\n        if have is not None:\n            if populate:", "        have = None\n        if have is not None:\n            if populate:")
mut("S14", "a bulk UPDATE does not refresh instances already loaded", "store/session.py",
    "        by_field = {c.field: c for c in model.__columns__.values()}\n        for key, inst in self._ident.items():", "        return\n        by_field = {c.field: c for c in model.__columns__.values()}\n        for key, inst in self._ident.items():")
mut("S15", "claim_one is find-then-update (not atomic)", "store/session.py",
    '        doc = await core.coll(model.__tablename__).find_one_and_update(flt, upd, sort=(sort or [("_id", 1)]), return_document=ReturnDocument.AFTER)',
    '        doc = await core.coll(model.__tablename__).find_one(flt, sort=(sort or [("_id", 1)]))\n'
    '        if doc is not None:\n'
    '            await asyncio.sleep(0)\n'
    '            await core.coll(model.__tablename__).update_one({"_id": doc["_id"]}, upd)\n'
    '            doc = await core.coll(model.__tablename__).find_one({"_id": doc["_id"]})')
mut("S16", "a duplicate inside insert_many is not an IntegrityError", "store/session.py",
    '    if isinstance(e, DuplicateKeyError) or (isinstance(e, BulkWriteError) and any(w.get("code") == 11000 for w in (e.details or {}).get("writeErrors", []))):',
    "    if isinstance(e, DuplicateKeyError):")
mut("S17", "SUM of only NULLs is 0 instead of NULL", "store/session.py",
    '                    if acc[0] == "sum" and not g.get(name + "n"):\n                        return None\n', "")
mut("S18", "count(col) counts NULLs", "store/session.py",
    '"count": {"$sum": {"$cond": [{"$in": [{"$type": f}, ["null", "missing"]]}, 0, 1]}} if f else None,', '"count": {"$sum": 1} if f else None,')
mut("S19", "a replay does not re-run the log (writes are lost after an abort)", "store/session.py",
    "            for op in self._log:                                  # replay what this session already wrote, in a fresh snapshot",
    "            for op in []:                                         # replay what this session already wrote, in a fresh snapshot")
mut("S20", "a locked SELECT does not take the locks", "store/session.py",
    "                await self._lock_keys(new)\n                locked.update(new)", "                locked.update(new)")
mut("S21", "a bulk UPDATE does not lock the rows it changes", "store/session.py",
    "        ids = await self._matching_ids(model, flt)\n        await self._lock_keys([(model.__tablename__, i) for i in ids])\n        if st._returning:", "        ids = await self._matching_ids(model, flt)\n        if st._returning:")
mut("S22", "rollback() leaves the transaction open", "store/session.py",
    "    async def rollback(self):\n        await self._abort_txn()\n        self._log.clear()", "    async def rollback(self):\n        self._log.clear()")
mut("S23", "no tie-break on _id in a pushed-down sort", "store/session.py",
    'cur = cur.sort(push if any(f == "_id" for f, _ in push) else push + [("_id", 1)])     # the tie-break must not repeat a key already sorted on', "cur = cur.sort(push)")

# ---------------------------------------------------------------- types / model / core
mut("S24", "datetimes keep microseconds in memory but the stored value is cut (no truncation at all)", "store/types.py",
    "        v = v.replace(tzinfo=_UTC) if v.tzinfo is None else v.astimezone(_UTC)\n        return trunc_ms(v)", "        v = v.replace(tzinfo=_UTC) if v.tzinfo is None else v.astimezone(_UTC)\n        return v")
mut("S25", "a date reads back as a string", "store/types.py",
    "        if isinstance(v, str):\n            return dt.date.fromisoformat(v)", "        if isinstance(v, str):\n            return v")
mut("S26", "partial unique indexes lose their filter", "store/core.py",
    '            if ix.where:\n                kw["partialFilterExpression"] = ix.where', '            if False:\n                kw["partialFilterExpression"] = ix.where')
mut("S27", "the id counter hands out 1 forever", "store/core.py",
    'd = await coll("counters").find_one_and_update({"_id": collection}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)\n    return int(d["seq"])\n\n\nasync def raise_counter',
    'd = await coll("counters").find_one_and_update({"_id": collection}, {"$set": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)\n    return int(d["seq"])\n\n\nasync def raise_counter')
mut("S28", "an in-place edit of a JSON column is not detected", "store/model.py",
    "            if now[name] != self._snap.get(name):\n                out[c.field] = now[name]", "            if now[name] != self._snap.get(name) and not c.type.json:\n                out[c.field] = now[name]")
mut("S29", "an update writes every column, not just the changed ones", "store/model.py",
    "            if now[name] != self._snap.get(name):\n                out[c.field] = now[name]", "            out[c.field] = now[name]")


# ---------------------------------------------------------------- referential integrity and the idioms
mut("S30", "no parent-exists check on insert", "store/session.py",
    '                if await self._run(fetch) is None:\n                    raise IntegrityError(f"{model.__tablename__}.{col.name}={v!r} references',
    '                if False:\n                    raise IntegrityError(f"{model.__tablename__}.{col.name}={v!r} references')
mut("S31", "deleting a parent that has children is allowed", "store/session.py",
    '            if await self._run(count):\n                raise IntegrityError(f"cannot delete from',
    '            if False:\n                raise IntegrityError(f"cannot delete from')
mut("S32", "children may be inserted before their parents", "store/session.py",
    "            new = sorted(new, key=lambda i: type(i).fk_rank())      # parents before children (stable: add order otherwise)", "            pass")
mut("S33", "insert_if_absent always says it inserted", "store/session.py",
    "        if upserted is None:\n            return False\n        inst._snap = copy.deepcopy(stored)\n        inst._deleted = False",
    "        if False:\n            return False\n        inst._snap = copy.deepcopy(stored)\n        inst._deleted = False")
mut("S34", "advisory_lock locks nothing", "store/session.py",
    '        await self._lock_keys([("advisory", (key,))])', "        pass")
mut("S35", "a deleted parent is still remembered as existing", "store/session.py",
    "        for v in vals:\n            self._fk_known.discard((model.__tablename__, v))", "        pass")


def apply(id_, app_dir):
    desc, file, old, new = M[id_]
    path = f"{app_dir}/{file}"
    src = open(path).read()
    if src.count(old) != 1:
        raise SystemExit(f"{id_}: pattern found {src.count(old)} times in {file}: {old[:70]!r}")
    open(path, "w").write(src.replace(old, new))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--ids"]:
        print(" ".join(M))
    elif a[:1] == ["--desc"]:
        print(M[a[1]][0])
    elif a[:1] == ["--check"]:
        bad = 0
        for i, (d, f, old, new) in M.items():
            n = open(f"backend/app/{f}").read().count(old)
            if n != 1:
                bad += 1
                print(f"{i}: pattern matches {n} times in {f}")
        print("all patterns apply once" if not bad else f"{bad} bad pattern(s)")
        sys.exit(1 if bad else 0)
    elif a[:1] == ["--apply"]:
        apply(a[1], a[2])
    else:
        raise SystemExit(__doc__)
