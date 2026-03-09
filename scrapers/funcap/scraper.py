from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from shared.models import Edital

FUNCAP_EDITAIS_URL = "http://montenegro.funcap.ce.gov.br/sugba/editais/"
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
KEYWORDS = ("encerr", "prazo", "final", "inscri", "submiss", "data limite")
NEGATIVE_HINTS = ("anteriores", "meses anteriores", "últimos 12 meses", "ultimos 12 meses")


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

    lines: list[str] = []
    for page in reader.pages[:4]:
        text = page.extract_text() or ""
        lines.extend(line.strip() for line in text.splitlines() if line.strip())

    for line in lines:
        low = line.lower()
        if any(h in low for h in NEGATIVE_HINTS):
            continue
        if not any(k in low for k in KEYWORDS):
            continue
        match = DATE_RE.search(line)
        if not match:
            continue
        iso = _normalize_date(match.group(1))
        if iso:
            return iso, line[:240]

    return None, None


def parse_funcap_open_editais(html: str) -> list[Edital]:
    soup = BeautifulSoup(html, "lxml")
    start_header = soup.find(string=lambda s: isinstance(s, str) and "Editais Abertos" in s)
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
        title = " ".join(node.get_text(" ", strip=True).split())
        low_title = title.lower()
        abs_url = urljoin(FUNCAP_EDITAIS_URL, raw_url)

        if (
            not raw_url
            or not title
            or ".pdf" not in abs_url.lower()
            or "edital" not in low_title
            or any(term in low_title for term in skip_terms)
            or not abs_url.startswith("http")
            or abs_url in seen_urls
        ):
            continue

        seen_urls.add(abs_url)
        editais.append(
            Edital(
                id=_build_id(abs_url),
                nome=title,
                url_pdf=abs_url,
                fonte=FUNCAP_EDITAIS_URL,
                status="aberto",
                capturado_em=captured_at,
            )
        )

    return editais


def run(output_path: Path) -> int:
    html = fetch_html(FUNCAP_EDITAIS_URL)
    editais = parse_funcap_open_editais(html)
    for edital in editais:
        try:
            pdf_bytes = fetch_pdf_bytes(edital.url_pdf)
            data_encerramento, contexto = extract_end_date_from_pdf(pdf_bytes)
            edital.data_encerramento = data_encerramento
            edital.contexto_data_encerramento = contexto
        except Exception:
            edital.data_encerramento = None
            edital.contexto_data_encerramento = None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(e) for e in editais], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(editais)
