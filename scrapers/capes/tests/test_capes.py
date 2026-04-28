from scrapers.capes.scraper import _find_edital_pdf_candidates, parse_capes_open_editais


# ---------------------------------------------------------------------------
# HTML helpers — estrutura real da página gov.br/capes
# ---------------------------------------------------------------------------

def _make_row(content: str) -> str:
    return f'<div class="row"><div class="row-content"><div class="column col-md-12">{content}</div></div></div>'


def _make_header_row() -> str:
    tile = '<div class="tile tile-default"><div class="outstanding-header tile-content"><h2 class="outstanding-title">Editais Abertos</h2></div></div>'
    return _make_row(tile)


def _make_links_row(items: list[dict]) -> str:
    lis = ""
    for item in items:
        href = item.get("href", "")
        title = item.get("title", "")
        cls = f' class="{item["class"]}"' if item.get("class") else ""
        lis += f"<li><span><a{cls} href=\"{href}\">{title}</a></span></li>"
    tile = f'<div class="tile tile-default"><div class="cover-richtext-tile tile-content"><ul>{lis}</ul></div></div>'
    return _make_row(tile)


def _make_html(items: list[dict], extra_rows: str = "") -> str:
    return (
        "<html><body>"
        + _make_header_row()
        + _make_links_row(items)
        + extra_rows
        + "</body></html>"
    )


SAMPLE_ITEMS = [
    {
        "href": "https://www.gov.br/capes/pt-br/acesso-a-informacao/acoes-e-programas/bolsas/bolsas-e-auxilios-internacionais/encontre-aqui/paises/alemanha/probral",
        "title": "Probral",
        "class": "external-link",
    },
    {
        "href": "https://www.gov.br/capes/pt-br/acesso-a-informacao/acoes-e-programas/bolsas/bolsas-e-auxilios-internacionais/encontre-aqui/paises/franca/cofecub",
        "title": "Programa CAPES/Cofecub",
        "class": "external-link",
    },
    {
        # link sem class — caso real: Programa CAPES/Purdue
        "href": "https://www.gov.br/capes/pt-br/acesso-a-informacao/acoes-e-programas/bolsas/bolsas-e-auxilios-internacionais/encontre-aqui/paises/estados-unidos/purdue",
        "title": "Programa CAPES/Purdue para Projetos Conjuntos de Pesquisa",
    },
]

SAMPLE_HTML = _make_html(SAMPLE_ITEMS)


# ---------------------------------------------------------------------------
# parse_capes_open_editais — casos normais
# ---------------------------------------------------------------------------

def test_retorna_lista_vazia_sem_header():
    assert parse_capes_open_editais("<html><body></body></html>") == []


def test_retorna_lista_vazia_sem_content_row():
    html = "<html><body>" + _make_header_row() + "</body></html>"
    assert parse_capes_open_editais(html) == []


def test_retorna_lista_vazia_sem_richtext():
    tile = '<div class="tile tile-default"><div class="tile-content"><ul><li><a href="https://example.com">X</a></li></ul></div></div>'
    html = "<html><body>" + _make_header_row() + _make_row(tile) + "</body></html>"
    assert parse_capes_open_editais(html) == []


def test_retorna_lista_vazia_sem_links():
    html = "<html><body>" + _make_header_row() + _make_links_row([]) + "</body></html>"
    assert parse_capes_open_editais(html) == []


def test_parse_quantidade_correta():
    assert len(parse_capes_open_editais(SAMPLE_HTML)) == 3


def test_parse_titulo_em_maiusculo():
    result = parse_capes_open_editais(SAMPLE_HTML)
    assert result[0].title == "PROBRAL"
    assert result[1].title == "PROGRAMA CAPES/COFECUB"


def test_parse_institution():
    result = parse_capes_open_editais(SAMPLE_HTML)
    assert all(e.institution == "CAPES" for e in result)


def test_parse_status_aberto():
    result = parse_capes_open_editais(SAMPLE_HTML)
    assert all(e.status == "aberto" for e in result)


def test_parse_url():
    result = parse_capes_open_editais(SAMPLE_HTML)
    assert "probral" in result[0].pdf_url
    assert "cofecub" in result[1].pdf_url
    assert "purdue" in result[2].pdf_url


def test_captura_link_sem_class():
    """Link sem class="external-link" deve ser capturado (caso real: CAPES/Purdue)."""
    result = parse_capes_open_editais(SAMPLE_HTML)
    titles = [e.title for e in result]
    assert "PROGRAMA CAPES/PURDUE PARA PROJETOS CONJUNTOS DE PESQUISA" in titles


def test_parse_id_deterministico():
    r1 = parse_capes_open_editais(SAMPLE_HTML)
    r2 = parse_capes_open_editais(SAMPLE_HTML)
    assert r1[0].id == r2[0].id


def test_deadline_nulo():
    result = parse_capes_open_editais(SAMPLE_HTML)
    assert all(e.registration_deadline is None for e in result)


def test_sem_duplicatas():
    html = _make_html([
        {"href": "https://www.gov.br/capes/probral", "title": "Probral", "class": "external-link"},
        {"href": "https://www.gov.br/capes/probral", "title": "Probral duplicado", "class": "external-link"},
    ])
    assert len(parse_capes_open_editais(html)) == 1


def test_ignora_li_sem_a():
    lis = "<li>Texto sem link</li>"
    tile = f'<div class="tile tile-default"><div class="cover-richtext-tile tile-content"><ul>{lis}</ul></div></div>'
    html = "<html><body>" + _make_header_row() + _make_row(tile) + "</body></html>"
    assert parse_capes_open_editais(html) == []


def test_ignora_a_sem_href():
    html = _make_html([{"title": "Sem href"}])
    assert parse_capes_open_editais(html) == []


def test_ignora_a_com_href_relativo():
    html = _make_html([{"href": "/capes/relativo", "title": "Relativo"}])
    assert parse_capes_open_editais(html) == []


def test_nao_captura_links_de_outras_secoes():
    """Links em rows após "Resultados de editais" não devem aparecer."""
    encerrado_row = (
        _make_row(
            '<div class="tile tile-default"><div class="outstanding-header tile-content">'
            '<h2 class="outstanding-title">Resultados de editais</h2></div></div>'
        )
        + _make_links_row([{"href": "https://www.gov.br/capes/resultado", "title": "Resultado 2024"}])
    )
    html = "<html><body>" + _make_header_row() + _make_links_row(SAMPLE_ITEMS) + encerrado_row + "</body></html>"
    result = parse_capes_open_editais(html)
    assert len(result) == 3
    assert all("resultado" not in e.pdf_url for e in result)


def test_titulo_normaliza_espacos():
    html = _make_html([{"href": "https://www.gov.br/capes/teste", "title": "  Título   com   espaços  "}])
    result = parse_capes_open_editais(html)
    assert result[0].title == "TÍTULO COM ESPAÇOS"


# ---------------------------------------------------------------------------
# _find_edital_pdf_candidates
# ---------------------------------------------------------------------------

def _pdf_link(href: str, text: str) -> str:
    return f'<a href="{href}">{text}</a>'


def _page_html(*links: str) -> str:
    body = "".join(links)
    return f"<html><body>{body}</body></html>"


_EDITAL_HREF = "https://www.gov.br/capes/pt-br/centrais-de-conteudo/editais/13042026_Edital_001.pdf"
_EDITAL_HREF_OLD = "https://www.gov.br/capes/pt-br/centrais-de-conteudo/editais/01042026_Edital_002.pdf"
_RESULT_HREF = "https://www.gov.br/capes/pt-br/centrais-de-conteudo/resultados-dos-editais/13042026_Resultado.pdf"
_MANUAL_HREF = "https://www.gov.br/capes/pt-br/centrais-de-conteudo/documentos/manual-cartao.pdf"


def test_find_pdf_retorna_vazio_sem_links():
    assert _find_edital_pdf_candidates("<html><body></body></html>") == []


def test_find_pdf_retorna_vazio_sem_candidatos():
    html = _page_html(
        _pdf_link(_RESULT_HREF, "Resultado Final do Edital nº 09/2025"),
        _pdf_link(_MANUAL_HREF, "Manual Cartão Pesquisador"),
    )
    assert _find_edital_pdf_candidates(html) == []


def test_find_pdf_ignora_resultados_dos_editais():
    html = _page_html(_pdf_link(_RESULT_HREF, "Edital nº 09/2025 - resultado"))
    assert _find_edital_pdf_candidates(html) == []


def test_find_pdf_ignora_negativo_resultado():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Resultado Final do Edital nº 09/2025"))
    assert _find_edital_pdf_candidates(html) == []


def test_find_pdf_ignora_negativo_lista():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Lista de inscritos do Edital nº 9/2025"))
    assert _find_edital_pdf_candidates(html) == []


def test_find_pdf_ignora_negativo_anexo():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Anexo I - Termo de Outorga"))
    assert _find_edital_pdf_candidates(html) == []


def test_find_pdf_ignora_negativo_modelo():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Modelo de Projeto do Edital nº 9/2025"))
    assert _find_edital_pdf_candidates(html) == []


def test_find_pdf_ignora_sem_texto_relevante():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Relatório de Atividades nº 01/2026"))
    assert _find_edital_pdf_candidates(html) == []


def test_find_pdf_retorna_edital_simples():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Edital nº 08/2026 - CAPES/DAAD Probral"))
    assert _find_edital_pdf_candidates(html) == [_EDITAL_HREF]


def test_find_pdf_retorna_alteracao_de_edital():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Alteração do Edital nº 08/2026"))
    assert _find_edital_pdf_candidates(html) == [_EDITAL_HREF]


def test_find_pdf_retorna_mais_recente_primeiro():
    """Lista deve ter o mais recente primeiro (data de arquivo desc)."""
    html = _page_html(
        _pdf_link(_EDITAL_HREF_OLD, "Edital nº 08/2026 - CAPES/DAAD Probral, pdf"),
        _pdf_link(_EDITAL_HREF, "Alteração do Edital nº 08/2026, pdf"),
    )
    result = _find_edital_pdf_candidates(html)
    assert result[0] == _EDITAL_HREF
    assert result[1] == _EDITAL_HREF_OLD


def test_find_pdf_desduplicar_href():
    """Link duplicado não deve duplicar candidatos."""
    html = _page_html(
        _pdf_link(_EDITAL_HREF, "Edital nº 08/2026"),
        _pdf_link(_EDITAL_HREF, "Edital nº 08/2026 (cópia)"),
    )
    assert _find_edital_pdf_candidates(html) == [_EDITAL_HREF]


def test_find_pdf_ignora_nao_pdf():
    html = _page_html('<a href="https://www.gov.br/capes/pagina">Edital nº 08/2026</a>')
    assert _find_edital_pdf_candidates(html) == []


def test_find_pdf_aceita_chamamento():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Chamamento Público nº 01/2026"))
    assert _find_edital_pdf_candidates(html) == [_EDITAL_HREF]


def test_find_pdf_aceita_premio():
    html = _page_html(_pdf_link(_EDITAL_HREF, "Prêmio CAPES de Tese 2026"))
    assert _find_edital_pdf_candidates(html) == [_EDITAL_HREF]


# ---------------------------------------------------------------------------
# Smoke test com HTML real baixado (requer rede)
# ---------------------------------------------------------------------------

def test_parse_html_real():
    """Valida o parser contra o HTML real da CAPES (requer rede)."""
    import pytest
    try:
        from shared.scraping import fetch_html
        from shared.urls import CAPES_URL
        html = fetch_html(CAPES_URL)
    except Exception:
        pytest.skip("sem rede ou URL indisponível")

    result = parse_capes_open_editais(html)
    assert len(result) > 0, "esperava pelo menos 1 edital aberto na CAPES"
    for e in result:
        assert e.id, "id não pode ser vazio"
        assert e.title, "título não pode ser vazio"
        assert e.pdf_url.startswith("http"), f"url inválida: {e.pdf_url}"
        assert e.institution == "CAPES"
        assert e.status == "aberto"
