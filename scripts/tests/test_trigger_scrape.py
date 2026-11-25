import http.client

import pytest

from scripts import trigger_scrape as ts


def _run(id_, status="ok", **kw):
    return {
        "_id": id_,
        "status": status,
        "total_found": 3,
        "new_inserted": 1,
        "updated": 2,
        "duration_ms": 2500,
        **kw,
    }


OLD = {"funcap": _run("f1"), "capes": _run("c1")}
NEW_CAPES = _run("c2")


class FakeApi:
    """`statuses` são as respostas de /scrape/status; a primeira é a linha de base."""

    def __init__(self, statuses, health_failures=0, post_error=None):
        self.statuses = list(statuses)
        self.health_failures = health_failures
        self.post_error = post_error
        self.posts = 0

    def __call__(self, method, url, headers=None):
        assert "//" not in url.removeprefix("http://")
        if url.endswith("/health"):
            if self.health_failures:
                self.health_failures -= 1
                raise ts.RequestError("timeout")
            return {}
        if method == "POST":
            self.posts += 1
            assert headers == {"X-Scrape-Token": "tok"}
            if self.post_error:
                raise self.post_error
            return {"status": "scheduled", "institutions": ["funcap", "capes"]}
        item = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if isinstance(item, Exception):
            raise item
        return {"institutions": item}


def _go(api, summary_path=None):
    lines = []
    env = {"SCRAPE_URL": "http://srv/", "SCRAPE_TOKEN": "tok"}
    if summary_path:
        env["GITHUB_STEP_SUMMARY"] = str(summary_path)
    code = ts.main(env, request=api, sleep=lambda s: None, write=lines.append, max_polls=5)
    return code, "\n".join(lines)


def test_sucesso_espera_execucoes_novas_e_monta_tabela():
    api = FakeApi(
        [
            OLD,
            OLD,
            {"funcap": _run("f2", "running"), "capes": NEW_CAPES},
            {"funcap": _run("f2", "unchanged"), "capes": NEW_CAPES},
        ]
    )
    code, out = _go(api)
    assert code == 0
    assert api.posts == 1
    assert "| funcap | unchanged | 3 | 1 | 2 | 2.5s |" in out


def test_grava_tabela_no_resumo_do_action(tmp_path):
    summary = tmp_path / "summary.md"
    _go(FakeApi([OLD, {"funcap": _run("f2"), "capes": NEW_CAPES}]), summary)
    assert "| capes | ok |" in summary.read_text(encoding="utf-8")


def test_resultado_antigo_nao_conta_como_novo():
    code, out = _go(FakeApi([OLD, OLD]))
    assert code == 1
    assert "| funcap | não terminou |" in out


def test_primeira_execucao_da_instituicao():
    code, _ = _go(
        FakeApi(
            [
                {"funcap": None, "capes": None},
                {"funcap": _run("f1"), "capes": _run("c1")},
            ]
        )
    )
    assert code == 0


def test_erro_falha_e_mostra_so_o_tipo():
    err = {"type": "ReadTimeout", "message": "mongodb://user:senha@host"}
    api = FakeApi([OLD, {"funcap": _run("f2", "error", error=err), "capes": NEW_CAPES}])
    code, out = _go(api)
    assert code == 1
    assert "error (ReadTimeout)" in out
    assert "senha" not in out


def test_zero_editais_avisa_sem_falhar():
    api = FakeApi([OLD, {"funcap": _run("f2", total_found=0), "capes": NEW_CAPES}])
    code, out = _go(api)
    assert code == 0
    assert "::warning::funcap" in out


def test_health_tenta_de_novo():
    api = FakeApi([OLD, {"funcap": _run("f2"), "capes": NEW_CAPES}], health_failures=2)
    assert _go(api)[0] == 0
    assert api.posts == 1


def test_post_nao_e_repetido():
    api = FakeApi([OLD], post_error=ts.RequestError("timeout"))
    code, out = _go(api)
    assert code == 1
    assert api.posts == 1
    assert "::error::" in out


def test_servidor_fora_do_ar_nao_dispara():
    api = FakeApi([OLD], health_failures=99)
    code, out = _go(api)
    assert code == 1
    assert api.posts == 0
    assert "::error::" in out


def test_falha_passageira_na_consulta_nao_derruba():
    done = {"funcap": _run("f2"), "capes": NEW_CAPES}
    code, _ = _go(FakeApi([OLD, ts.RequestError("502"), done]))
    assert code == 0


@pytest.mark.parametrize("env", [{}, {"SCRAPE_URL": "http://s"}, {"SCRAPE_TOKEN": "x"}])
def test_configuracao_ausente_falha(env):
    lines = []
    assert ts.main(env, write=lines.append) == 1
    assert "SCRAPE_URL" in lines[0]


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b"{}"


def test_http_request_se_identifica(monkeypatch):
    """O User-Agent padrao do urllib costuma ser bloqueado por proxies."""
    sent = []

    def fake_urlopen(req, timeout):
        sent.append(req)
        return _FakeResponse()

    monkeypatch.setattr(ts.urllib.request, "urlopen", fake_urlopen)
    ts.http_request("POST", "http://srv/x", {"X-Scrape-Token": "t"})
    assert sent[0].get_header("User-agent") == ts.USER_AGENT
    assert sent[0].get_header("X-scrape-token") == "t"


def test_resposta_interrompida_vira_request_error(monkeypatch):
    def broken(req, timeout):
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(ts.urllib.request, "urlopen", broken)
    with pytest.raises(ts.RequestError, match="IncompleteRead"):
        ts.http_request("GET", "http://srv/health")
