from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import date as date_type
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from shared.models import Edital
from shared.urls import FUNCAP_URL

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
KEYWORDS = ("encerr", "prazo", "final", "inscri", "submiss", "data limite")
NEGATIVE_HINTS = (
    "anteriores",
    "meses anteriores",
    "últimos 12 meses",
    "ultimos 12 meses")


def _build_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def fetch_html(url: str) -> str:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text


def fetch_pdf_bytes(url: str) -> bytes:
    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return response.content


def _normalize_date(raw: str) -> str | None:
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def extract_end_date_from_pdf(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception:
        return None, None

    today = datetime.utcnow().date()

    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(line.strip() for line in text.splitlines() if line.strip())

    # First pass: prefer earliest future date from a keyword-matching line.
    # Second pass: fall back to the latest past date if no future date found.
    best_future: tuple[str, str] | None = None
    best_past: tuple[str, str] | None = None

    for line in lines:
        low = line.lower()
        if any(h in low for h in NEGATIVE_HINTS):
            continue
        if not any(k in low for k in KEYWORDS):
            continue
        # When a table row has Início/Término columns, take the last date (Término)
        all_dates = DATE_RE.findall(line)
        if not all_dates:
            continue
        iso = _normalize_date(all_dates[-1])
        if not iso:
            continue
        parsed = date_type.fromisoformat(iso)
        if parsed >= today:
            if best_future is None or iso < best_future[0]:
                best_future = (iso, line[:240])
        else:
            if best_past is None or iso > best_past[0]:
                best_past = (iso, line[:240])

    result = best_future or best_past
    return (result[0], result[1]) if result else (None, None)


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

        # Section <b> header is always more complete than the link text
        header_tag = node.find_previous("b")
        header_text = " ".join(header_tag.get_text(
            " ", strip=True).split()) if header_tag else ""
        nome = (header_text or link_text).upper()

        seen_urls.add(abs_url)
        editais.append(
            Edital(
                id=_build_id(abs_url),
                nome=nome,
                url_pdf=abs_url,
                fonte=FUNCAP_URL,
                status="aberto",
                capturado_em=captured_at,
            )
        )

    return editais


def run(output_path: Path) -> int:
    html = fetch_html(FUNCAP_URL)
    editais = parse_funcap_open_editais(html)
    # TODO: extração de data_encerramento via PDF está retornando datas incorretas
    # (ex: "resultado final" e "prazo de recursos" em vez do prazo de inscrição).
    # Desabilitado até definir estratégia de extração mais confiável.
    # for edital in editais:
    #     try:
    #         pdf_bytes = fetch_pdf_bytes(edital.url_pdf)
    #         data_encerramento, contexto = extract_end_date_from_pdf(pdf_bytes)
    #         edital.data_encerramento = data_encerramento
    #         edital.contexto_data_encerramento = contexto
    #     except Exception:
    #         edital.data_encerramento = None
    #         edital.contexto_data_encerramento = None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(e) for e in editais], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(editais)
