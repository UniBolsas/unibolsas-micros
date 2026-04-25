import time
from unittest.mock import MagicMock, patch

import pytest

from scrapers.funcap.scraper import run
from shared.pdf import extract_end_date_from_pdf

# TODO: adicionar testes com PDFs reais da FUNCAP como fixtures para medir:
# - precisão: data retornada está certa?
# - recall: encontra a data quando existe?


@pytest.mark.integration
def test_tempo_scraping_funcap(tmp_path):
    output = tmp_path / "editais.json"
    start = time.time()
    total = run(output)
    elapsed = time.time() - start
    print(f"\nEditais coletados: {total} | Tempo: {elapsed:.1f}s")
    assert elapsed < 120, f"scraping esta demorando/mal otimizado: {elapsed:.1f}s"


def _fake_pdf(lines: list[str]) -> bytes:
    page = MagicMock()
    page.extract_text.return_value = "\n".join(lines)
    with patch("shared.pdf.PdfReader") as mock_reader:
        mock_reader.return_value.pages = [page]
        return mock_reader


def _run(lines: list[str]):
    page = MagicMock()
    page.extract_text.return_value = "\n".join(lines)
    with patch("shared.pdf.PdfReader") as mock_reader:
        mock_reader.return_value.pages = [page]
        return extract_end_date_from_pdf(b"fake")


def test_extrai_data_de_inscricao():
    date, context = _run(["Prazo de inscrições: 31/12/2030"])
    assert date == "2030-12-31"
    assert "31/12/2030" in context


def test_ignora_data_passada():
    date, context = _run(["Data limite de inscrições: 01/01/2020"])
    assert date is None
    assert context is None


def test_ignora_linha_com_negative_hint():
    date, context = _run(["Resultado das inscrições: 31/12/2030"])
    assert date is None


def test_fallback_para_keyword_baixa():
    date, context = _run(["Prazo final: 15/06/2030"])
    assert date == "2030-06-15"


def test_pdf_ilegivel_retorna_none():
    with patch("scrapers.funcap.scraper.PdfReader", side_effect=Exception("corrompido")):
        date, context = extract_end_date_from_pdf(b"lixo")
    assert date is None
    assert context is None
