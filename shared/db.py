"""Acesso ao MongoDB e repositórios."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from shared.models import Edital

STATUS_CLOSED = "fechado"
_DEADLINE_FIELDS = ("registration_deadline", "registration_deadline_context")

_client: MongoClient | None = None
_db: Database | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(os.environ["MONGO_URI"])
    return _client


def get_db() -> Database:
    global _db
    if _db is None:
        _db = get_client().get_default_database()
    return _db


def ensure_indexes() -> None:
    db = get_db()
    db["scrape_runs"].create_index(
        [("institution", ASCENDING), ("started_at", DESCENDING)]
    )


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class UpsertStats:
    inserted: int = 0
    updated: int = 0


class EditaisRepository:
    def __init__(self, institution: str, db: Database | None = None) -> None:
        self.institution = institution
        self.collection: Collection = (db or get_db())[institution.lower()]

    def get_existing_ids(self, ids: Iterable[str]) -> set[str]:
        ids = list(ids)
        if not ids:
            return set()
        cursor = self.collection.find({"_id": {"$in": ids}}, {"_id": 1})
        return {doc["_id"] for doc in cursor}

    def get_existing_complete_ids(self, ids: Iterable[str]) -> set[str]:
        """IDs já no banco e com `registration_deadline` preenchido."""
        ids = list(ids)
        if not ids:
            return set()
        cursor = self.collection.find(
            {"_id": {"$in": ids}, "registration_deadline": {"$ne": None}},
            {"_id": 1},
        )
        return {doc["_id"] for doc in cursor}

    def upsert_many(self, editais: list[Edital]) -> UpsertStats:
        """Insere ou atualiza. Sem prazo novo, preserva o prazo já salvo."""
        stats = UpsertStats()
        now = _now().isoformat(timespec="seconds").replace("+00:00", "Z")
        for edital in editais:
            fields = {k: v for k, v in asdict(edital).items() if k != "id"}
            # prazo e contexto andam juntos: ou atualiza os dois, ou nenhum
            insert_only = (
                _DEADLINE_FIELDS if edital.registration_deadline is None else ()
            )
            on_update = {k: v for k, v in fields.items() if k not in insert_only}
            on_insert = {k: fields[k] for k in insert_only}
            result = self.collection.update_one(
                {"_id": edital.id},
                {
                    "$set": {**on_update, "last_seen_at": now},
                    "$setOnInsert": {**on_insert, "first_seen_at": now},
                },
                upsert=True,
            )
            if result.upserted_id is not None:
                stats.inserted += 1
            elif result.modified_count:
                stats.updated += 1
        return stats

    def close_missing(self, open_ids: Iterable[str]) -> int:
        """Marca como fechado todo edital fora da listagem de abertos."""
        result = self.collection.update_many(
            {"_id": {"$nin": list(open_ids)}, "status": {"$ne": STATUS_CLOSED}},
            {"$set": {"status": STATUS_CLOSED}},
        )
        return result.modified_count

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(
            self.collection.find().sort("last_seen_at", DESCENDING).limit(limit)
        )


@dataclass(slots=True)
class ScrapeRun:
    institution: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str = "running"  # running | ok | unchanged | error
    listing_hash: str | None = None
    total_found: int = 0
    new_inserted: int = 0
    updated: int = 0
    skipped_cached: int = 0
    duration_ms: int | None = None
    error: dict[str, str] | None = None


class ScrapeRunsRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.collection: Collection = (db or get_db())["scrape_runs"]

    def start(self, institution: str) -> Any:
        run = ScrapeRun(institution=institution, started_at=_now())
        doc = asdict(run)
        result = self.collection.insert_one(doc)
        return result.inserted_id

    def finish(self, run_id: Any, **fields: Any) -> None:
        finished_at = _now()
        update: dict[str, Any] = {"finished_at": finished_at, **fields}
        started = self.collection.find_one({"_id": run_id}, {"started_at": 1})
        if started and started.get("started_at"):
            delta = finished_at - started["started_at"].replace(tzinfo=UTC)
            update["duration_ms"] = int(delta.total_seconds() * 1000)
        self.collection.update_one({"_id": run_id}, {"$set": update})

    def get_last(self, institution: str) -> dict[str, Any] | None:
        return self.collection.find_one(
            {"institution": institution},
            sort=[("started_at", DESCENDING)],
        )

    def list_recent(
        self, limit: int = 20, institution: str | None = None
    ) -> list[dict[str, Any]]:
        query = {"institution": institution.lower()} if institution else {}
        return list(
            self.collection.find(query).sort("started_at", DESCENDING).limit(limit)
        )
