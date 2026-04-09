import pytest

from scrapers.cnpq.scraper import _parse_deadline, parse_cnpq_open_chamadas

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _make_html(items: list[dict]) -> str:
    """Gera HTML mínimo com a estrutura real do CNPq."""
    lis = ""
    for item in items:
        btn = (
            f'<a class="btn" alt="Chamada" href="{item["btn_href"]}">Chamada</a>'
            if item.get("btn_href") else ""
        )
        inscricao = (
            f'<div class="inscricao"><strong>Inscrições:</strong>'
            f'<ul class="datas"><li>{item["datas"]}</li></ul></div>'
            if item.get("datas") else ""
        )
        h4 = f'<h4>{item["title"]}</h4>' if item.get("title") else ""
        lis += f'<li><div class="content">{h4}{inscricao}</div>'
        lis += f'<div class="bottom-content">{btn}</div></li>'

    return f'<html><body><ol class="list-chamadas">{lis}</ol></body></html>'


SAMPLE_HTML = _make_html([
    {
        "title": "Chamada CNPq/MCTI Nº 1/2026 Programa Exemplo",
        "btn_href": "http://resultado.cnpq.br/0634870311591204",
        "datas": "25/02/2026  a  13/04/2026",
    },
    {
        "title": "Chamada CNPq Nº 2/2026 Cooperação Internacional",
        "btn_href": "http://resultado.cnpq.br/5170965351053941",
        "datas": "28/01/2026  a  30/04/2026",
    },
])


# ---------------------------------------------------------------------------
# parse_cnpq_open_chamadas
# ---------------------------------------------------------------------------

def test_retorna_lista_vazia_sem_ol():
    assert parse_cnpq_open_chamadas("<html><body></body></html>") == []


def test_retorna_lista_vazia_com_ol_vazia():
    html = '<html><body><ol class="list-chamadas"></ol></body></html>'
    assert parse_cnpq_open_chamadas(html) == []


def test_parse_quantidade_correta():
    result = parse_cnpq_open_chamadas(SAMPLE_HTML)
    assert len(result) == 2


def test_parse_titulo_em_maiusculo():
    result = parse_cnpq_open_chamadas(SAMPLE_HTML)
    assert result[0].title == "CHAMADA CNPQ/MCTI Nº 1/2026 PROGRAMA EXEMPLO"


def test_parse_institution():
    result = parse_cnpq_open_chamadas(SAMPLE_HTML)
    assert all(e.institution == "CNPq" for e in result)


def test_parse_status_aberto():
    result = parse_cnpq_open_chamadas(SAMPLE_HTML)
    assert all(e.status == "aberto" for e in result)


def test_parse_pdf_url():
    result = parse_cnpq_open_chamadas(SAMPLE_HTML)
    assert result[0].pdf_url == "http://resultado.cnpq.br/0634870311591204"
    assert result[1].pdf_url == "http://resultado.cnpq.br/5170965351053941"


def test_parse_registration_deadline():
    result = parse_cnpq_open_chamadas(SAMPLE_HTML)
    assert result[0].registration_deadline == "2026-04-13"
    assert result[1].registration_deadline == "2026-04-30"


def test_parse_registration_deadline_context_contem_datas():
    result = parse_cnpq_open_chamadas(SAMPLE_HTML)
    assert "25/02/2026" in result[0].registration_deadline_context
    assert "13/04/2026" in result[0].registration_deadline_context


def test_parse_id_deterministico():
    result1 = parse_cnpq_open_chamadas(SAMPLE_HTML)
    result2 = parse_cnpq_open_chamadas(SAMPLE_HTML)
    assert result1[0].id == result2[0].id


def test_ignora_item_sem_h4():
    html = _make_html([
        {"btn_href": "http://resultado.cnpq.br/111", "datas": "01/01/2030  a  01/06/2030"},
    ])
    assert parse_cnpq_open_chamadas(html) == []


def test_ignora_item_sem_btn_chamada():
    html = _make_html([
        {"title": "Chamada sem botão", "datas": "01/01/2030  a  01/06/2030"},
    ])
    assert parse_cnpq_open_chamadas(html) == []


def test_deadline_none_quando_sem_datas():
    html = _make_html([
        {
            "title": "Chamada sem data",
            "btn_href": "http://resultado.cnpq.br/999",
        },
    ])
    result = parse_cnpq_open_chamadas(html)
    assert len(result) == 1
    assert result[0].registration_deadline is None
    assert result[0].registration_deadline_context is None


def test_sem_duplicatas():
    html = _make_html([
        {
            "title": "Chamada repetida",
            "btn_href": "http://resultado.cnpq.br/0634870311591204",
            "datas": "01/01/2026  a  01/06/2026",
        },
        {
            "title": "Chamada repetida 2",
            "btn_href": "http://resultado.cnpq.br/0634870311591204",  # mesmo link
            "datas": "01/01/2026  a  01/06/2026",
        },
    ])
    result = parse_cnpq_open_chamadas(html)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# _parse_deadline
# ---------------------------------------------------------------------------

def test_parse_deadline_formato_padrao():
    assert _parse_deadline("Inscrições: 25/02/2026  a  13/04/2026") == "2026-04-13"


def test_parse_deadline_retorna_ultima_data():
    assert _parse_deadline("01/01/2026 a 30/06/2030") == "2030-06-30"


def test_parse_deadline_sem_data_retorna_none():
    assert _parse_deadline("Inscrições abertas") is None


def test_parse_deadline_data_unica():
    assert _parse_deadline("Prazo: 15/08/2027") == "2027-08-15"
