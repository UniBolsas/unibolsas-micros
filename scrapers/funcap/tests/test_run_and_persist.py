from urllib.parse import urljoin

import pytest

import scrapers.funcap.scraper as funcap
from scrapers.funcap.scraper import ListingNotFoundError, parse_funcap_open_editais
from shared.scraping import build_id, listing_hash
from shared.tests.fakes import fake_db


def _page(*pdfs: str) -> str:
    links = "".join(
        f"<b>{p}</b><a href='../edital/{p}.pdf'>Edital {p}</a>" for p in pdfs
    )
    return (
        "<h5>Editais Abertos</h5>"
        f"<div class='ui-tabs-panel'>{links}</div>"
        "<h5>Editais Encerrados</h5>"
        "<div class='ui-tabs-panel'><a href='../edital/1.pdf'>Edital velho</a></div>"
    )


@pytest.fixture
def env(monkeypatch):
    db = fake_db()
    state = {"html": _page("768", "800")}
    monkeypatch.setattr("shared.db.get_db", lambda: db)
    monkeypatch.setattr(funcap, "fetch_html", lambda url: state["html"])
    monkeypatch.setattr(funcap, "fetch_pdf_bytes", lambda url: url)
    monkeypatch.setattr(
        funcap,
        "extract_end_date_from_pdf",
        lambda b: ("2030-01-01", "ctx") if "800" in b else (None, None),
    )
    return state, db


def _by_pdf(db, number: str) -> dict:
    docs = db["funcap"].docs.values()
    return next(d for d in docs if f"/{number}.pdf" in d["pdf_url"])


def _statuses(db) -> set[str]:
    return {d["status"] for d in db["funcap"].docs.values()}


def test_edital_que_sai_da_aba_de_abertos_e_fechado(env) -> None:
    state, db = env
    funcap.run_and_persist()
    state["html"] = _page("800")
    funcap.run_and_persist()
    assert _by_pdf(db, "768")["status"] == "fechado"
    assert _by_pdf(db, "800")["status"] == "aberto"


def test_aba_vazia_fecha_todos(env) -> None:
    state, db = env
    funcap.run_and_persist()
    state["html"] = _page()
    funcap.run_and_persist()
    assert _statuses(db) == {"fechado"}


def test_fecha_mesmo_quando_a_lista_nao_mudou(env, monkeypatch) -> None:
    """O atalho `unchanged` não pode pular o fechamento."""
    state, db = env
    funcap.run_and_persist()
    state["html"] = _page()
    monkeypatch.setattr(
        funcap.ScrapeRunsRepository,
        "get_last",
        lambda self, inst: {"listing_hash": listing_hash([])},
    )
    assert funcap.run_and_persist().status == "unchanged"
    assert _statuses(db) == {"fechado"}


@pytest.mark.parametrize(
    "html",
    [
        "<html>manutenção</html>",
        "<h5>Editais Abertos</h5><p>sem painel</p>",
        # sem o painel de abertos, o próximo painel é o de encerrados
        "<h5>Editais Abertos</h5><h5>Editais Encerrados</h5>"
        "<div class='ui-tabs-panel'><a href='../edital/1.pdf'>Edital velho</a></div>",
    ],
)
def test_pagina_inesperada_falha_e_nao_fecha_nada(env, html) -> None:
    state, db = env
    funcap.run_and_persist()
    state["html"] = html
    with pytest.raises(ListingNotFoundError):
        funcap.run_and_persist()
    assert _statuses(db) == {"aberto"}
    assert len(db["funcap"].docs) == 2
    assert any(r["status"] == "error" for r in db["scrape_runs"].docs.values())


def test_prazo_sobrevive_a_execucoes_seguidas(env) -> None:
    _, db = env
    for _ in range(4):
        funcap.run_and_persist()
        assert _by_pdf(db, "800")["registration_deadline"] == "2030-01-01"


def test_parser_aceita_painel_de_abertos_vazio() -> None:
    assert parse_funcap_open_editais(_page()) == []


def test_parser_ignora_painel_de_encerrados() -> None:
    ids = [e.id for e in parse_funcap_open_editais(_page("768"))]
    assert ids == [build_id(urljoin(funcap.FUNCAP_URL, "../edital/768.pdf"))]
