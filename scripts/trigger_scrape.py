"""Dispara os scrapers pelo GitHub Actions, espera o fim e relata o resultado.

Usa só a biblioteca padrão, para o workflow não precisar instalar nada.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

USER_AGENT = "unibolsas-scrape-action"
REQUEST_TIMEOUT_S = 60
HEALTH_ATTEMPTS = 5
HEALTH_WAIT_S = 10
POLL_INTERVAL_S = 15
MAX_POLLS = 40  # 40 x 15s = 10 min
SUCCESS_STATUSES = ("ok", "unchanged")

Request = Callable[..., Any]
Runs = dict[str, dict[str, Any] | None]


class RequestError(Exception):
    """Falha de rede, HTTP ou resposta que não é JSON."""


def http_request(
    method: str, url: str, headers: Mapping[str, str] | None = None
) -> Any:
    all_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    req = urllib.request.Request(url, method=method, headers=all_headers)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RequestError(f"HTTP {exc.code}") from exc
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise RequestError(type(exc).__name__) from exc


def wake_server(base: str, request: Request, sleep: Callable, write: Callable) -> None:
    """O Render dorme sem tráfego. Repetir GET é seguro; repetir POST, não."""
    for attempt in range(1, HEALTH_ATTEMPTS + 1):
        try:
            request("GET", f"{base}/health")
            return
        except RequestError as exc:
            write(f"servidor não respondeu ({exc}), tentativa {attempt}/{HEALTH_ATTEMPTS}")
            if attempt == HEALTH_ATTEMPTS:
                raise
            sleep(HEALTH_WAIT_S)


def fetch_runs(base: str, request: Request) -> Runs:
    return request("GET", f"{base}/scrape/status")["institutions"]


def finished_runs(current: Runs, previous: Runs) -> dict[str, dict[str, Any]]:
    """Execuções novas (id diferente do anterior) que já terminaram."""
    return {
        name: run
        for name, run in current.items()
        if run
        and run["status"] != "running"
        and run["_id"] != (previous.get(name) or {}).get("_id")
    }


def wait_for_runs(
    base: str,
    names: list[str],
    previous: Runs,
    request: Request,
    sleep: Callable,
    write: Callable,
    max_polls: int,
) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    for _ in range(max_polls):
        sleep(POLL_INTERVAL_S)
        try:
            done = finished_runs(fetch_runs(base, request), previous)
        except RequestError as exc:
            write(f"falha ao consultar status: {exc}")
            continue
        write(f"concluídos {sum(n in done for n in names)}/{len(names)}")
        if all(name in done for name in names):
            break
    return done


def status_label(run: Mapping[str, Any]) -> str:
    # só o tipo do erro: a mensagem pode conter dados internos
    error_type = (run.get("error") or {}).get("type")
    return f"{run['status']} ({error_type})" if error_type else run["status"]


def table_row(name: str, run: Mapping[str, Any] | None) -> str:
    if run is None:
        return f"| {name} | não terminou | – | – | – | – |"
    seconds = (run.get("duration_ms") or 0) / 1000
    return (
        f"| {name} | {status_label(run)} | {run['total_found']} "
        f"| {run['new_inserted']} | {run['updated']} | {seconds:.1f}s |"
    )


def report(
    names: list[str], done: Mapping[str, dict[str, Any]], write: Callable
) -> tuple[int, str]:
    header = "| Instituição | Status | Encontrados | Novos | Atualizados | Duração |"
    rows = [table_row(name, done.get(name)) for name in names]
    table = "\n".join([header, "|---|---|---|---|---|---|", *rows])
    write(table)

    exit_code = 0
    for name in names:
        run = done.get(name)
        if run is None or run["status"] not in SUCCESS_STATUSES:
            label = status_label(run) if run else "não terminou"
            write(f"::error::{name}: {label}")
            exit_code = 1
        elif run["total_found"] == 0:
            write(f"::warning::{name}: nenhum edital encontrado, confira a página")
    return exit_code, table


def main(
    env: Mapping[str, str],
    request: Request = http_request,
    sleep: Callable = time.sleep,
    write: Callable = print,
    max_polls: int = MAX_POLLS,
) -> int:
    base, token = env.get("SCRAPE_URL", "").rstrip("/"), env.get("SCRAPE_TOKEN")
    if not base or not token:
        write("::error::configure SCRAPE_URL (variable) e SCRAPE_TOKEN (secret)")
        return 1

    try:
        wake_server(base, request, sleep, write)
        previous = fetch_runs(base, request)
        scheduled = request(
            "POST", f"{base}/scrape/run", headers={"X-Scrape-Token": token}
        )
    except RequestError as exc:
        write(f"::error::falha ao disparar o scraping: {exc}")
        return 1

    names = scheduled["institutions"]
    write(f"disparado: {', '.join(names)}")
    done = wait_for_runs(base, names, previous, request, sleep, write, max_polls)
    exit_code, table = report(names, done, write)

    summary_path = env.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f"{table}\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main(os.environ))
