from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from shared.db import EditaisRepository, ScrapeRunsRepository
from shared.models import Edital
from shared.scraping import RunResult, build_id, fetch_html, listing_hash
from shared.urls import CAPES_URL

logger = logging.getLogger("unibolsas.scraper.capes")
INSTITUTION = "capes"


def _find_row(tag: Tag) -> Tag | None:
    """Sobe na árvore até encontrar o div.row imediato (não div.row-content)."""
    node = tag.parent
    while node and node.name != "body":
        classes = node.get("class") or []
        if node.name == "div" and "row" in classes and "row-content" not in classes:
            return node
        node = node.parent
    return None


def parse_capes_open_editais(html: str) -> list[Edital]:
    soup = BeautifulSoup(html, "lxml")

    header = soup.find(
        lambda tag: tag.name == "h2"
        and "outstanding-title" in (tag.get("class") or [])
        and "Editais Abertos" in tag.get_text(),
    )
    if header is None:
        return []

    header_row = _find_row(header)
    if header_row is None:
        return []

    content_row = header_row.find_next_sibling("div", class_="row")
    if content_row is None:
        return []

    richtext = content_row.find("div", class_="cover-richtext-tile")
    if richtext is None:
        return []

    captured_at = Edital.now_iso()
    seen_ids: set[str] = set()
    editais: list[Edital] = []

    for li in richtext.find_all("li"):
        a = li.find("a")
        if not a:
            continue
        href = (a.get("href") or "").strip()
        title = " ".join(a.get_text(" ", strip=True).split()).upper()
        if not href or not title or not href.startswith("http"):
            continue
        edital_id = build_id(href)
        if edital_id in seen_ids:
            continue
        seen_ids.add(edital_id)
        editais.append(
            Edital(
                id=edital_id,
                title=title,
                pdf_url=href,
                institution="CAPES",
                status="aberto",
                captured_at=captured_at,
            )
        )

    return editais


def run_and_persist() -> RunResult:
    """Executa o scraping da CAPES e persiste no MongoDB de forma idempotente."""
    runs_repo = ScrapeRunsRepository()
    editais_repo = EditaisRepository(INSTITUTION)
    run_id = runs_repo.start(INSTITUTION)
    logger.info("CAPES scrape iniciado run_id=%s", run_id)

    try:
        html = fetch_html(CAPES_URL)
        editais = parse_capes_open_editais(html)
        total_found = len(editais)
        lhash = listing_hash(editais)
        logger.info("CAPES encontrou %d editais (hash=%s)", total_found, lhash[:8])

        last = runs_repo.get_last(INSTITUTION)
        all_ids = [e.id for e in editais]
        existing_complete = editais_repo.get_existing_complete_ids(all_ids)

        unchanged = (
            last is not None
            and last.get("listing_hash") == lhash
            and len(existing_complete) == total_found
        )

        if unchanged:
            logger.info("CAPES sem mudanças, pulando persistência")
            runs_repo.finish(
                run_id,
                status="unchanged",
                listing_hash=lhash,
                total_found=total_found,
                new_inserted=0,
                updated=0,
                skipped_cached=total_found,
            )
            return RunResult("unchanged", total_found, 0, 0, total_found, lhash)

        stats = editais_repo.upsert_many(editais)
        runs_repo.finish(
            run_id,
            status="ok",
            listing_hash=lhash,
            total_found=total_found,
            new_inserted=stats.inserted,
            updated=stats.updated,
            skipped_cached=len(existing_complete),
        )
        logger.info(
            "CAPES run_id=%s ok inserted=%d updated=%d cached=%d",
            run_id, stats.inserted, stats.updated, len(existing_complete),
        )
        return RunResult(
            "ok", total_found, stats.inserted, stats.updated,
            len(existing_complete), lhash,
        )
    except Exception as exc:
        logger.exception("CAPES run_id=%s falhou", run_id)
        runs_repo.finish(
            run_id,
            status="error",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise


def run(output_path: Path) -> int:
    html = fetch_html(CAPES_URL)
    editais = parse_capes_open_editais(html)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(e) for e in editais], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(editais)
