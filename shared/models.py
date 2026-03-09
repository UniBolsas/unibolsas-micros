from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class Edital:
    id: str
    nome: str
    url_pdf: str
    fonte: str
    status: str
    capturado_em: str
    data_encerramento: str | None = None
    contexto_data_encerramento: str | None = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
