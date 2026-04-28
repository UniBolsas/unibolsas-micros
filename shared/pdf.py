"""Utilitários compartilhados para download e extração de datas em PDFs."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from datetime import date as date_type
from io import BytesIO

import httpx
from pypdf import PdfReader

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")

# "28 de maio de 2026" ou "30 novembro de 2026" (sem "de" entre dia e mês)
_DATE_EXTENSO_RE = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?"
    r"(janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
    r"\s+de\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_MAP = {
    "janeiro": "01", "fevereiro": "02", "março": "03", "marco": "03",
    "abril": "04", "maio": "05", "junho": "06",
    "julho": "07", "agosto": "08", "setembro": "09",
    "outubro": "10", "novembro": "11", "dezembro": "12",
}

KEYWORDS_HIGH = ("inscri", "submiss", "data limite", "encerr")
KEYWORDS_LOW = ("prazo", "final")

NEGATIVE_HINTS = (
    "anteriores",
    "meses anteriores",
    "últimos 12 meses",
    "ultimos 12 meses",
    "resultado",
    "recurso",
    "homologaç",
    "divulgaç",
    "publicaç",
    "julgament",
)

_LOOKAHEAD = 5


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


def _parse_extenso(m: re.Match) -> str | None:
    day = m.group(1).zfill(2)
    month_raw = m.group(2).lower().replace("ç", "c")
    month = _MONTH_MAP.get(month_raw)
    if not month:
        return None
    try:
        return date_type(int(m.group(3)), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _find_dates(text: str) -> list[str]:
    results = []
    for raw in DATE_RE.findall(text):
        iso = _normalize_date(raw)
        if iso:
            results.append(iso)
    for m in _DATE_EXTENSO_RE.finditer(text):
        iso = _parse_extenso(m)
        if iso:
            results.append(iso)
    return results


def extract_end_date_from_pdf(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception:
        return None, None

    today = datetime.now(UTC).date()

    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(line.strip() for line in text.splitlines() if line.strip())

    def _scan(keyword_set: tuple[str, ...]) -> tuple[str, str] | None:
        earliest_future: tuple[str, str] | None = None
        for keyword_idx, line in enumerate(lines):
            low = line.lower()
            if any(hint in low for hint in NEGATIVE_HINTS):
                continue
            if not any(keyword in low for keyword in keyword_set):
                continue
            lookahead_end = min(keyword_idx + _LOOKAHEAD + 1, len(lines))
            for date_idx in range(keyword_idx, lookahead_end):
                for iso in _find_dates(lines[date_idx]):
                    parsed = date_type.fromisoformat(iso)
                    if parsed >= today:
                        if earliest_future is None or iso < earliest_future[0]:
                            ctx = " ".join(lines[keyword_idx: date_idx + 2])
                            earliest_future = (iso, ctx[:240])
        return earliest_future

    found = _scan(KEYWORDS_HIGH) or _scan(KEYWORDS_LOW)
    return (found[0], found[1]) if found else (None, None)
