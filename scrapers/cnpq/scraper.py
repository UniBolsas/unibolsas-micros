from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path

from datetime import datetime

from bs4 import BeautifulSoup

from shared.db import EditaisRepository, ScrapeRunsRepository
from shared.models import Edital
from shared.scraping import RunResult, build_id, fetch_html, listing_hash
from shared.urls import CNPQ_URL

logger = logging.getLogger("unibolsas.scraper.cnpq")
INSTITUTION = "cnpq"

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")


def _parse_deadline(inscricao_text: str) -> str | None:
    dates = DATE_RE.findall(inscricao_text)
    if not dates:
        return None
    try:
        return datetime.strptime(dates[-1], "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def parse_cnpq_open_chamadas(html: str) -> list[Edital]:
    soup = BeautifulSoup(html, "lxml")

    ol = soup.find("ol", class_="list-chamadas")
    if ol is None:
        return []

    captured_at = Edital.now_iso()
    chamadas: list[Edital] = []
    seen_ids: set[str] = set()

    for li in ol.find_all("li", recursive=False):
        h4 = li.find("h4")
        if not h4:
            continue
        title = " ".join(h4.get_text(" ", strip=True).split()).upper()

        btn = li.find("a", class_="btn", alt="Chamada")
        if not btn or not btn.get("href"):
            continue
        pdf_url = btn["href"].strip()

        edital_id = build_id(pdf_url)
        if edital_id in seen_ids:
            continue
        seen_ids.add(edital_id)

        inscricao_div = li.find("div", class_="inscricao")
        inscricao_text = inscricao_div.get_text(" ", strip=True) if inscricao_div else ""

        chamadas.append(
            Edital(
                id=edital_id,
                title=title,
                pdf_url=pdf_url,
                institution="CNPq",
                status="aberto",
                captured_at=captured_at,
                registration_deadline=_parse_deadline(inscricao_text) if inscricao_text else None,
                registration_deadline_context=inscricao_text or None,
            )
        )

    return chamadas


def run_and_persist() -> RunResult:
    """Executa o scraping do CNPq e persiste no MongoDB de forma idempotente."""
    runs_repo = ScrapeRunsRepository()
    editais_repo = EditaisRepository(INSTITUTION)
    run_id = runs_repo.start(INSTITUTION)
    logger.info("CNPq scrape iniciado run_id=%s", run_id)

    try:
        html = fetch_html(CNPQ_URL)
        chamadas = parse_cnpq_open_chamadas(html)
        total_found = len(chamadas)
        lhash = listing_hash(chamadas)
        logger.info("CNPq encontrou %d chamadas (hash=%s)", total_found, lhash[:8])

        last = runs_repo.get_last(INSTITUTION)
        all_ids = [e.id for e in chamadas]
        existing_complete = editais_repo.get_existing_complete_ids(all_ids)

        unchanged = (
            last is not None
            and last.get("listing_hash") == lhash
            and len(existing_complete) == total_found
        )

        if unchanged:
            logger.info("CNPq sem mudanças, pulando persistência")
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

        stats = editais_repo.upsert_many(chamadas)
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
            "CNPq run_id=%s ok inserted=%d updated=%d cached=%d",
            run_id, stats.inserted, stats.updated, len(existing_complete),
        )
        return RunResult(
            "ok", total_found, stats.inserted, stats.updated,
            len(existing_complete), lhash,
        )
    except Exception as exc:
        logger.exception("CNPq run_id=%s falhou", run_id)
        runs_repo.finish(
            run_id,
            status="error",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise


def run(output_path: Path) -> int:
    html = fetch_html(CNPQ_URL)
    chamadas = parse_cnpq_open_chamadas(html)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(e) for e in chamadas], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(chamadas)
