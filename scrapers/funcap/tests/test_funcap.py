from scrapers.funcap.scraper import parse_funcap_open_editais


def test_parse_funcap_open_editais_filters_only_open_edital_pdfs() -> None:
    html = """
    <html><body>
      <h3>Editais Abertos</h3>
      <div class='ui-tabs-panel'>
        <ul>
          <li><a href='../edital/768.pdf'>Edital No 08/2025</a></li>
          <li><a href='../edital/resultados/777.pdf'>Resultado definitivo</a></li>
        </ul>
      </div>
    </body></html>
    """
    result = parse_funcap_open_editais(html)

    assert len(result) == 1
    assert result[0].nome == "EDITAL NO 08/2025"
    assert result[0].status == "aberto"
    assert result[0].url_pdf.endswith("/edital/768.pdf")
