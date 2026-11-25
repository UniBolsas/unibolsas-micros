"""Banco em memória que cobre só o que os repositórios usam."""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

_OPERATORS = {
    "$in": lambda value, arg: value in arg,
    "$nin": lambda value, arg: value not in arg,
    "$ne": lambda value, arg: value != arg,
}


def _matches(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        value = doc.get(key)
        if not isinstance(cond, dict):
            if value != cond:
                return False
        elif not all(_OPERATORS[op](value, arg) for op, arg in cond.items()):
            return False
    return True


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict = {}

    def insert_one(self, doc: dict):
        new_id = len(self.docs) + 1
        self.docs[new_id] = {**doc, "_id": new_id}
        return SimpleNamespace(inserted_id=new_id)

    def find(self, query=None, projection=None):
        return [dict(d) for d in self.docs.values() if _matches(d, query or {})]

    def find_one(self, query, projection=None, sort=None):
        found = self.find(query)
        for field, direction in reversed(sort or []):
            found = sorted(found, key=lambda d: d[field], reverse=direction < 0)
        return found[0] if found else None

    def update_one(self, query, update, upsert=False):
        overlap = set(update.get("$set", {})) & set(update.get("$setOnInsert", {}))
        assert not overlap, f"Mongo rejeita o mesmo campo nos dois: {overlap}"
        key = query["_id"]
        is_new = key not in self.docs
        if is_new and not upsert:
            return SimpleNamespace(upserted_id=None, modified_count=0)
        before = self.docs.get(key, {"_id": key})
        on_insert = update.get("$setOnInsert", {}) if is_new else {}
        after = {**before, **on_insert, **update.get("$set", {})}
        self.docs[key] = after
        return SimpleNamespace(
            upserted_id=key if is_new else None,
            modified_count=int(not is_new and after != before),
        )

    def update_many(self, query, update):
        hits = [d["_id"] for d in self.find(query)]
        for key in hits:
            self.docs[key] = {**self.docs[key], **update["$set"]}
        return SimpleNamespace(modified_count=len(hits))


def fake_db() -> dict:
    """Não vazio de propósito: os repositórios fazem `db or get_db()`."""
    return defaultdict(FakeCollection, scrape_runs=FakeCollection())
