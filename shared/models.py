"""Modelo de dados para editais de bolsas."""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class Edital:
    """Representa um edital capturado de uma instituição.

    Attributes:
        id: Identificador único do edital.
        nome: Nome ou título do edital.
        url_pdf: URL para o PDF do edital.
        instituicao: Nome da instituição responsável.
        status: Status atual do edital (e.g. "aberto", "encerrado").
        capturado_em: Data e hora em que o edital foi capturado.
        data_encerramento: Data limite para inscrições, se disponível.
        contexto_data_encerramento: Trecho ou contexto de onde a data de
            encerramento foi extraída.
    """

    id: str
    nome: str
    url_pdf: str
    instituicao: str
    status: str
    capturado_em: datetime
    data_encerramento: datetime | None = None
    contexto_data_encerramento: str | None = None

    @staticmethod
    def now_iso() -> str:
        """Retorna o timestamp atual em formato ISO 8601 com sufixo 'Z'."""
        return datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
