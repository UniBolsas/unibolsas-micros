from __future__ import annotations

import argparse
from pathlib import Path

from scrapers.cnpq.scraper import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper de chamadas abertas - CNPq")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/cnpq_chamadas_abertas.json"),
        help="Caminho do arquivo JSON de saida",
    )
    args = parser.parse_args()
    total = run(args.output)
    print(f"Chamadas coletadas: {total}")


if __name__ == "__main__":
    main()
