from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date as date_type
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from shared.db import EditaisRepository, ScrapeRunsRepository
from shared.models import Edital
from shared.pdf import fetch_pdf_bytes, extract_end_date_from_pdf
from shared.scraping import RunResult, build_id, fetch_html, listing_hash
from shared.urls import FUNCAP_URL

logger = logging.getLogger("unibolsas.scraper.funcap")
INSTITUTION = "funcap"
PDF_WORKERS = 8


def parse_funcap_open_editais(html: str) -> list[Edital]:
    soup = BeautifulSoup(html, "lxml")
    start_header = soup.find(string=lambda s: isinstance(s, str)
                             and "Editais Abertos" in s)
    if start_header is None:
        return []

    panel = start_header.parent.find_next("div", class_="ui-tabs-panel")
    if panel is None:
        return []

    captured_at = Edital.now_iso()
    seen_urls: set[str] = set()
    editais: list[Edital] = []
    skip_terms = ("resultado", "adendo", "anexo")

    for node in panel.find_all("a"):
        raw_url = (node.get("href") or "").strip()
        abs_url = urljoin(FUNCAP_URL, raw_url)
        link_text = " ".join(node.get_text(" ", strip=True).split())
        low_link = link_text.lower()

        if (
            not raw_url
            or not link_text
            or ".pdf" not in abs_url.lower()
            or any(term in low_link for term in skip_terms)
            or not abs_url.startswith("http")
            or abs_url in seen_urls
        ):
            continue

        header_tag = node.find_previous("b")
        header_text = " ".join(header_tag.get_text(
            " ", strip=True).split()) if header_tag else ""
        title = (header_text or link_text).upper()

        seen_urls.add(abs_url)
        editais.append(
            Edital(
                id=build_id(abs_url),
                title=title,
                pdf_url=abs_url,
                institution="FUNCAP",
                status="aberto",
                captured_at=captured_at,
            )
        )

    return editais


def _enrich_edital(edital: Edital) -> Edital:
    try:
        pdf_bytes = fetch_pdf_bytes(edital.pdf_url)
        deadline, context = extract_end_date_from_pdf(pdf_bytes)
        edital.registration_deadline = deadline
        edital.registration_deadline_context = context
    except Exception as exc:
        logger.warning("Falha ao baixar/parsear PDF %s: %s", edital.pdf_url, exc)
        edital.registration_deadline = None
        edital.registration_deadline_context = None
    return edital


def run_and_persist() -> RunResult:
    """Executa o scraping da FUNCAP e persiste no MongoDB de forma idempotente."""
    runs_repo = ScrapeRunsRepository()
    editais_repo = EditaisRepository(INSTITUTION)
    run_id = runs_repo.start(INSTITUTION)
    logger.info("FUNCAP scrape iniciado run_id=%s", run_id)

    try:
        html = fetch_html(FUNCAP_URL)
        editais = parse_funcap_open_editais(html)
        total_found = len(editais)
        lhash = listing_hash(editais)
        logger.info("FUNCAP encontrou %d editais (hash=%s)", total_found, lhash[:8])

        last = runs_repo.get_last(INSTITUTION)
        all_ids = [e.id for e in editais]
        existing_complete = editais_repo.get_existing_complete_ids(all_ids)

        unchanged = (
            last is not None
            and last.get("listing_hash") == lhash
            and len(existing_complete) == total_found
        )

        if unchanged:
            logger.info("FUNCAP sem mudanças, pulando download de PDFs")
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

        to_fetch = [e for e in editais if e.id not in existing_complete]
        logger.info("FUNCAP baixando %d PDFs (cache: %d)", len(to_fetch), len(existing_complete))

        with ThreadPoolExecutor(max_workers=PDF_WORKERS) as pool:
            futures = {pool.submit(_enrich_edital, e): e for e in to_fetch}
            for future in as_completed(futures):
                future.result()

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
            "FUNCAP run_id=%s ok inserted=%d updated=%d cached=%d",
            run_id, stats.inserted, stats.updated, len(existing_complete),
        )
        return RunResult(
            "ok", total_found, stats.inserted, stats.updated,
            len(existing_complete), lhash,
        )
    except Exception as exc:
        logger.exception("FUNCAP run_id=%s falhou", run_id)
        runs_repo.finish(
            run_id,
            status="error",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise


def run(output_path: Path) -> int:
    html = fetch_html(FUNCAP_URL)
    editais = parse_funcap_open_editais(html)
    for edital in editais:
        try:
            pdf_bytes = fetch_pdf_bytes(edital.pdf_url)
            registration_deadline, context = extract_end_date_from_pdf(pdf_bytes)
            edital.registration_deadline = registration_deadline
            edital.registration_deadline_context = context
        except Exception:
            edital.registration_deadline = None
            edital.registration_deadline_context = None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(e) for e in editais], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(editais)
