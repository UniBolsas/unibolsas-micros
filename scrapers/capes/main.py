from __future__ import annotations

import argparse
from pathlib import Path

from scrapers.capes.scraper import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper de editais abertos - CAPES")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/capes_editais_abertos.json"),
        help="Caminho do arquivo JSON de saida",
    )
    args = parser.parse_args()
    total = run(args.output)
    print(f"Editais coletados: {total}")


if __name__ == "__main__":
    main()
