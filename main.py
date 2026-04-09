import logging
import os
from datetime import datetime
from html import escape

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pymongo.errors import ConnectionFailure

from scrapers.registry import SCRAPERS, get_scraper, institutions
from shared.db import EditaisRepository, ScrapeRunsRepository, ensure_indexes, get_client, get_db

load_dotenv()
logging.basicConfig(level=logging.INFO)

mongo_client = get_client()
db = get_db()

app = FastAPI()


@app.on_event("startup")
def _startup() -> None:
    ensure_indexes()


def _check_token(token: str | None) -> None:
    expected = os.environ.get("SCRAPE_TOKEN")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="invalid or missing token")


@app.get("/health")
def health():
    """Verifica o status da aplicação e da conexão com o MongoDB."""
    try:
        server_info = mongo_client.server_info()
        collections = db.list_collection_names()
        db_status = "connected"
    except ConnectionFailure:
        server_info = None
        collections = []
        db_status = "disconnected"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": {
            "connection": db_status,
            "name": db.name,
            "collections": collections,
        },
        "server": {"version": server_info.get("version") if server_info else None},
        "scrapers": institutions(),
    }


# --------------------------------------------------------------------------
# Scrape: disparo
# --------------------------------------------------------------------------


def _run_all() -> None:
    """Executa todos os scrapers sequencialmente, capturando erros por item."""
    for name, fn in SCRAPERS.items():
        try:
            fn()
        except Exception:
            logging.getLogger("unibolsas").exception("scraper %s falhou", name)


@app.post("/scrape/run")
def scrape_run_all(
    background_tasks: BackgroundTasks,
    x_scrape_token: str | None = Header(default=None),
):
    """Dispara todos os scrapers registrados em background."""
    _check_token(x_scrape_token)
    background_tasks.add_task(_run_all)
    return {"status": "scheduled", "institutions": institutions()}


@app.post("/scrape/run/{institution}")
def scrape_run_one(
    institution: str,
    background_tasks: BackgroundTasks,
    x_scrape_token: str | None = Header(default=None),
):
    """Dispara um scraper específico."""
    _check_token(x_scrape_token)
    try:
        fn = get_scraper(institution)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown institution: {institution}")
    background_tasks.add_task(fn)
    return {"status": "scheduled", "institution": institution.lower()}


# --------------------------------------------------------------------------
# Scrape: status (JSON)
# --------------------------------------------------------------------------


def _serialize_run(run: dict | None) -> dict | None:
    if run is None:
        return None
    run = dict(run)
    run["_id"] = str(run["_id"])
    return run


@app.get("/scrape/status")
def scrape_status_all():
    repo = ScrapeRunsRepository()
    return {
        "institutions": {
            name: _serialize_run(repo.get_last(name)) for name in institutions()
        }
    }


@app.get("/scrape/status/{institution}")
def scrape_status_one(institution: str):
    if institution.lower() not in SCRAPERS:
        raise HTTPException(status_code=404, detail=f"unknown institution: {institution}")
    last = ScrapeRunsRepository().get_last(institution.lower())
    return {"institution": institution.lower(), "last_run": _serialize_run(last)}


# --------------------------------------------------------------------------
# Scrape: dashboard HTML
# --------------------------------------------------------------------------


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def _render_section(name: str) -> str:
    last = ScrapeRunsRepository().get_last(name) or {}
    editais = EditaisRepository(name).list_recent(limit=50)

    rows = "".join(
        f"<tr>"
        f"<td>{escape(str(e.get('title', '')))}</td>"
        f"<td>{escape(str(e.get('registration_deadline') or '—'))}</td>"
        f"<td><a href='{escape(str(e.get('pdf_url', '')))}' target='_blank'>PDF</a></td>"
        f"<td>{escape(str(e.get('first_seen_at', '—')))}</td>"
        f"</tr>"
        for e in editais
    )

    status = escape(str(last.get("status", "—")))
    started = _fmt(last.get("started_at"))
    finished = _fmt(last.get("finished_at"))
    duration = last.get("duration_ms")
    duration_s = f"{duration/1000:.1f}s" if duration else "—"
    new_inserted = last.get("new_inserted", 0)
    total_found = last.get("total_found", 0)
    error = last.get("error")
    error_html = (
        f"<p style='color:#b00'>Erro: {escape(str(error))}</p>" if error else ""
    )

    return f"""
<section>
  <h2>{name.upper()}</h2>
  <div class="card">
    <dl class="kv">
      <dt>Status</dt><dd><strong>{status}</strong></dd>
      <dt>Início</dt><dd>{started}</dd>
      <dt>Fim</dt><dd>{finished}</dd>
      <dt>Duração</dt><dd>{duration_s}</dd>
      <dt>Encontrados</dt><dd>{total_found}</dd>
      <dt>Novos inseridos</dt><dd>{new_inserted}</dd>
    </dl>
    {error_html}
  </div>
  <table>
    <thead><tr><th>Título</th><th>Prazo inscrição</th><th>PDF</th><th>Visto em</th></tr></thead>
    <tbody>{rows or '<tr><td colspan=4>Nenhum edital ainda.</td></tr>'}</tbody>
  </table>
</section>
"""


@app.get("/scrape", response_class=HTMLResponse)
def scrape_dashboard():
    sections = "\n".join(_render_section(name) for name in institutions())
    html = f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8"><title>unibolsas — scrapers</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#222}}
h1{{margin-bottom:0}}
section{{margin-top:2rem}}
table{{width:100%;border-collapse:collapse;margin-top:1rem}}
th,td{{text-align:left;padding:.5rem;border-bottom:1px solid #ddd;font-size:.9rem}}
th{{background:#f4f4f4}}
.card{{background:#f9f9f9;border:1px solid #e3e3e3;border-radius:6px;padding:1rem;margin-top:.5rem}}
.kv{{display:grid;grid-template-columns:max-content 1fr;gap:.25rem 1rem;margin:0}}
.kv dt{{color:#666}}.kv dd{{margin:0}}
</style></head><body>
<h1>unibolsas — scrapers</h1>
<p>Instituições registradas: {", ".join(institutions()) or "nenhuma"}</p>
{sections}
</body></html>"""
    return HTMLResponse(html)
