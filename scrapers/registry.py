"""Registro central de scrapers por instituição.

Para adicionar um novo scraper, importe sua função `run_and_persist` e
registre-a em `SCRAPERS` com a chave da instituição (lowercase). Todas as
rotas em `main.py` descobrem instituições automaticamente a partir daqui —
nada mais precisa ser alterado.
"""

from __future__ import annotations

from typing import Callable

from scrapers.cnpq.scraper import run_and_persist as cnpq_run
from scrapers.funcap.scraper import run_and_persist as funcap_run

ScraperFn = Callable[[], object]

SCRAPERS: dict[str, ScraperFn] = {
    "funcap": funcap_run,
    "cnpq": cnpq_run,
    # "capes": capes_run,
}


def get_scraper(institution: str) -> ScraperFn:
    try:
        return SCRAPERS[institution.lower()]
    except KeyError as exc:
        raise KeyError(f"Scraper não registrado: {institution}") from exc


def institutions() -> list[str]:
    return sorted(SCRAPERS.keys())
