"""Utilitários compartilhados entre scrapers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx

from shared.models import Edital


def build_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def fetch_html(url: str) -> str:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text


def listing_hash(editais: list[Edital]) -> str:
    joined = "\n".join(sorted(e.id for e in editais))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class RunResult:
    status: str
    total_found: int
    new_inserted: int
    updated: int
    skipped_cached: int
    listing_hash: str
