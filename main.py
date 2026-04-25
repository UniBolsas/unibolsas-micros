import logging
import os
from datetime import UTC, datetime
from html import escape
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pymongo.errors import PyMongoError

from scrapers.registry import SCRAPERS, get_scraper, institutions
from shared.db import ScrapeRunsRepository, ensure_indexes, get_client, get_db

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


def _health_snapshot() -> dict[str, Any]:
    repo = ScrapeRunsRepository()
    names = institutions()

    try:
        server_info = mongo_client.server_info()
        collections = db.list_collection_names()
        recent_runs = repo.list_recent(limit=12)
        db_status = "connected"
        db_error = None
    except PyMongoError as exc:
        server_info = None
        collections = []
        recent_runs = []
        db_status = "disconnected"
        db_error = f"{type(exc).__name__}: {exc}"

    serialized_recent = [_serialize_run(run) for run in recent_runs]
    completed_runs = [
        run for run in serialized_recent if run and run.get("status") != "running"
    ]
    last_run = serialized_recent[0] if serialized_recent else None

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "app": {
            "status": "healthy" if db_status == "connected" else "degraded",
            "scrapers_registered": len(names),
            "last_run_at": (last_run or {}).get("finished_at") or (last_run or {}).get("started_at"),
            "recent_failures": sum(
                1 for run in completed_runs if run.get("status") == "error"
            ),
        },
        "database": {
            "connection": db_status,
            "name": db.name,
            "collections": collections,
            "collections_count": len(collections),
            "error": db_error,
        },
        "server": {"version": server_info.get("version") if server_info else None},
        "scrapers": names,
        "recent_runs": serialized_recent,
    }


@app.get("/health")
def health():
    """Verifica o status da aplicação e da conexão com o MongoDB."""
    return _health_snapshot()


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
        raise HTTPException(
            status_code=404, detail=f"unknown institution: {institution}")
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
        raise HTTPException(
            status_code=404, detail=f"unknown institution: {institution}")
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


def _fmt_duration(duration_ms: int | None) -> str:
    if not duration_ms:
        return "—"
    return f"{duration_ms / 1000:.1f}s"


def _fmt_error(error: dict[str, str] | None) -> str:
    if not error:
        return "—"
    error_type = error.get("type")
    message = error.get("message")
    if error_type and message:
        return f"{error_type}: {message}"
    return error_type or message or "erro"


def _status_class(status: str | None) -> str:
    mapping = {
        "ok": "s-ok",
        "unchanged": "s-unchanged",
        "running": "s-running",
        "error": "s-error",
        "connected": "s-ok",
        "disconnected": "s-error",
        "healthy": "s-ok",
        "degraded": "s-unchanged",
    }
    return mapping.get((status or "").lower(), "s-neutral")


def _status_text(label: str | None) -> str:
    text = escape((label or "unknown").replace("_", " ").lower())
    return f"<span class='s {_status_class(label)}'>{text}</span>"


def _num_cell(value: int, highlight: bool = False) -> str:
    n = int(value or 0)
    if n == 0:
        cls = "num num-zero"
    elif highlight:
        cls = "num num-hi"
    else:
        cls = "num"
    return f'<td class="{cls}">{n}</td>'


def _render_recent_runs(runs: list[dict[str, Any]]) -> str:
    if not runs:
        return "<p class='empty'>nenhuma execução registrada</p>"

    rows = "".join(
        f"""<tr>
  <td class="src">{escape(str(run.get("institution", "—")).lower())}</td>
  <td>{_status_text(run.get("status"))}</td>
  <td class="ts">{_fmt(run.get("started_at"))}</td>
  <td class="num">{_fmt_duration(run.get("duration_ms"))}</td>
</tr>"""
        for run in runs
    )
    return f"""<div class="table-shell">
  <table class="data">
    <thead>
      <tr>
        <th>Scraper</th>
        <th>Resultado</th>
        <th>Início</th>
        <th class="num">Duração</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def _render_dashboard() -> str:
    snapshot = _health_snapshot()
    app_status = snapshot["app"]
    database = snapshot["database"]
    recent_runs = snapshot["recent_runs"]

    sources_str = ", ".join(snapshot["scrapers"]) or "—"
    db_error_block = (
        f"<p class='err-line'>{escape(database['error'])}</p>"
        if database["error"]
        else ""
    )

    return f"""<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Healthcheck</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">
  <style>
    :root {{
      --bg: #09111d;
      --bg-soft: #0f1a2c;
      --panel: rgba(11, 20, 34, 0.9);
      --panel-strong: rgba(16, 28, 46, 0.96);
      --ink: #edf4ff;
      --soft: #c8d4e8;
      --dim: #90a0ba;
      --line: rgba(144, 160, 186, 0.18);
      --line-strong: rgba(118, 211, 255, 0.2);
      --accent: #76d3ff;
      --ok: #92e6a7;
      --warn: #f3c46b;
      --run: #85b7ff;
      --err: #ff8f8f;
      --shadow: 0 18px 54px rgba(3, 8, 18, 0.34);
      --sans: "IBM Plex Sans", "Segoe UI", sans-serif;
      --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      padding: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: var(--sans);
      font-size: 15px;
      line-height: 1.55;
    }}
    body {{
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(118, 211, 255, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(243, 196, 107, 0.14), transparent 24%),
        linear-gradient(180deg, #0b1523 0%, var(--bg) 52%, #08101a 100%);
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(255, 255, 255, 0.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.025) 1px, transparent 1px);
      background-size: 36px 36px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.55), transparent 92%);
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 28px 24px 72px;
      position: relative;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 18px;
      padding: 18px 22px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(15, 26, 44, 0.92), rgba(10, 18, 30, 0.94));
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }}
    header h1 {{
      margin: 0;
      font-size: 17px;
      font-weight: 700;
      letter-spacing: 0.01em;
      color: var(--ink);
      font-family: var(--mono);
    }}
    header h1 .slash {{ color: var(--accent); font-weight: 400; }}
    header .meta {{
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--dim);
      font-size: 13px;
      font-family: var(--mono);
    }}
    header .meta > span:first-child {{
      color: var(--soft);
    }}
    section {{
      margin-bottom: 18px;
      padding: 18px 22px 16px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: linear-gradient(180deg, var(--panel-strong), var(--panel));
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
    }}
    section h2 {{
      margin: 0 0 16px;
      font-size: 12px;
      font-weight: 500;
      letter-spacing: 0.24em;
      text-transform: uppercase;
      color: var(--accent);
      font-family: var(--mono);
    }}
    .kv {{
      display: grid;
      grid-template-columns: 200px 1fr;
      gap: 10px 24px;
    }}
    .kv dt {{
      color: var(--dim);
      font-family: var(--mono);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .kv dd {{
      margin: 0;
      color: var(--ink);
      word-break: break-word;
      font-family: var(--mono);
      font-size: 14px;
    }}
    .table-shell {{
      overflow-x: auto;
      border-top: 1px solid var(--line);
      padding-top: 4px;
      scrollbar-color: var(--line-strong) transparent;
    }}
    table.data {{
      width: 100%;
      min-width: 780px;
      border-collapse: collapse;
      font-size: 14px;
    }}
    table.data th,
    table.data td {{
      text-align: left;
      padding: 11px 14px 11px 0;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      white-space: nowrap;
      font-family: var(--mono);
    }}
    table.data th {{
      font-weight: 500;
      color: var(--dim);
      text-transform: lowercase;
      letter-spacing: 0.04em;
      padding-bottom: 12px;
      font-size: 13px;
    }}
    table.data tbody tr {{
      transition: background-color 120ms ease;
    }}
    table.data tbody tr:hover {{
      background: rgba(118, 211, 255, 0.045);
    }}
    table.data td.num,
    table.data th.num {{
      text-align: right;
      font-variant-numeric: tabular-nums;
    }}
    table.data td.src {{
      color: var(--soft);
      font-weight: 600;
    }}
    table.data td.ts,
    table.data td.err {{
      color: var(--dim);
    }}
    table.data td.err {{
      white-space: normal;
      max-width: 280px;
    }}
    table.data tr.err-row td {{
      padding-top: 0;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--line);
      color: var(--err);
      font-size: 13px;
      white-space: normal;
      background: rgba(255, 143, 143, 0.04);
    }}
    .s {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 2px 9px;
      border: 1px solid currentColor;
      border-radius: 999px;
      font-weight: 500;
      line-height: 1.25;
    }}
    .s::before {{
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: currentColor;
    }}
    .s-ok {{ color: var(--ok); background: rgba(146, 230, 167, 0.08); }}
    .s-unchanged {{ color: var(--warn); background: rgba(243, 196, 107, 0.08); }}
    .s-running {{ color: var(--run); background: rgba(133, 183, 255, 0.08); }}
    .s-error {{ color: var(--err); background: rgba(255, 143, 143, 0.08); }}
    .s-neutral {{ color: var(--dim); background: rgba(144, 160, 186, 0.08); }}
    .num-hi {{ color: var(--ok); font-weight: 700; }}
    .num-zero {{ color: var(--dim); }}
    .empty {{
      color: var(--dim);
      margin: 0;
      font-size: 14px;
      font-family: var(--mono);
    }}
    .err-line {{
      margin: 14px 0 0;
      padding-top: 14px;
      border-top: 1px solid rgba(255, 143, 143, 0.18);
      color: var(--err);
      font-size: 14px;
      font-family: var(--mono);
    }}
    @media (max-width: 720px) {{
      html, body {{ font-size: 14px; }}
      main {{ padding: 16px 14px 42px; }}
      .kv {{ grid-template-columns: 1fr; gap: 0; font-size: 14px; }}
      .kv dd {{ margin-bottom: 10px; }}
      header,
      section {{
        padding-left: 16px;
        padding-right: 16px;
        border-radius: 16px;
      }}
      header {{ flex-direction: column; align-items: flex-start; gap: 10px; }}
      table.data td.err {{ max-width: none; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Editais Agoras - Scrappers</h1>
      <div class="meta">
        <span>{_fmt(datetime.now(UTC))}</span>
        {_status_text(app_status["status"])}
      </div>
    </header>

    <section>
      <h2>system</h2>
      <dl class="kv">
        <dt>database</dt><dd>{_status_text(database["connection"])} · {escape(database["name"])}</dd>
        <dt>mongo</dt><dd>{escape(str(snapshot["server"]["version"] or "unknown"))}</dd>
        <dt>collections</dt><dd>{database["collections_count"]}</dd>
        <dt>scrapers</dt><dd>{app_status["scrapers_registered"]} · {escape(sources_str)}</dd>
        <dt>last activity</dt><dd>{_fmt(app_status["last_run_at"])}</dd>
        <dt>recent failures</dt><dd>{app_status["recent_failures"]} / {len(recent_runs)}</dd>
      </dl>
      {db_error_block}
    </section>

    <section>
      <h2>recent runs</h2>
      {_render_recent_runs(recent_runs)}
    </section>
  </main>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
@app.get("/scrape", response_class=HTMLResponse)
def scrape_dashboard():
    return HTMLResponse(_render_dashboard())
