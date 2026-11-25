from shared.db import EditaisRepository
from shared.models import Edital
from shared.tests.fakes import fake_db


def _edital(id_: str, deadline: str | None = None, context: str | None = None) -> Edital:
    return Edital(
        id=id_,
        title=id_,
        pdf_url=f"http://x/{id_}.pdf",
        institution="FUNCAP",
        status="aberto",
        captured_at="2026-01-01T00:00:00Z",
        registration_deadline=deadline,
        registration_deadline_context=context,
    )


def _repo():
    db = fake_db()
    return EditaisRepository("funcap", db), db["funcap"].docs


def test_upsert_nao_apaga_prazo_salvo() -> None:
    repo, docs = _repo()
    repo.upsert_many([_edital("a", "2030-01-01", "ctx")])
    repo.upsert_many([_edital("a")])
    assert docs["a"]["registration_deadline"] == "2030-01-01"
    assert docs["a"]["registration_deadline_context"] == "ctx"


def test_upsert_nao_mistura_prazo_antigo_com_contexto_novo() -> None:
    repo, docs = _repo()
    repo.upsert_many([_edital("a", "2030-01-01", "ctx")])
    repo.upsert_many([_edital("a", None, "outro texto")])
    assert docs["a"]["registration_deadline_context"] == "ctx"


def test_upsert_atualiza_prazo_quando_ha_novo() -> None:
    repo, docs = _repo()
    repo.upsert_many([_edital("a", "2030-01-01", "ctx")])
    repo.upsert_many([_edital("a", "2030-02-02", "novo")])
    assert docs["a"]["registration_deadline"] == "2030-02-02"
    assert docs["a"]["registration_deadline_context"] == "novo"


def test_upsert_grava_campos_nulos_em_edital_novo() -> None:
    repo, docs = _repo()
    repo.upsert_many([_edital("a")])
    assert docs["a"]["registration_deadline"] is None
    assert docs["a"]["registration_deadline_context"] is None


def test_close_missing_fecha_so_o_que_saiu_da_lista() -> None:
    repo, docs = _repo()
    repo.upsert_many([_edital("a"), _edital("b")])
    assert repo.close_missing(["a"]) == 1
    assert docs["a"]["status"] == "aberto"
    assert docs["b"]["status"] == "fechado"
    assert repo.close_missing(["a"]) == 0


def test_close_missing_com_lista_vazia_fecha_todos() -> None:
    repo, _ = _repo()
    repo.upsert_many([_edital("a"), _edital("b")])
    assert repo.close_missing([]) == 2


def test_edital_que_volta_para_a_lista_reabre() -> None:
    repo, docs = _repo()
    repo.upsert_many([_edital("a")])
    repo.close_missing([])
    repo.upsert_many([_edital("a")])
    assert docs["a"]["status"] == "aberto"
