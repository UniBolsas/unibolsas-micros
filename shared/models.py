"""Modelo de dados para editais de bolsas."""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class Edital:
    """Representa um edital capturado de uma instituição.

    Attributes:
        id: Identificador único do edital.
        title: Nome ou título do edital.
        pdf_url: URL para o PDF do edital.
        institution: Nome da instituição responsável.
        status: Status atual do edital (e.g. "aberto", "encerrado").
        captured_at: Data e hora em que o edital foi capturado.
        registration_deadline: Data limite para inscrições, se disponível.
        registration_deadline_context: Trecho ou contexto de onde a data de
            encerramento foi extraída.
    """

    id: str
    title: str
    pdf_url: str
    institution: str
    status: str
    captured_at: datetime
    registration_deadline: datetime | None = None
    registration_deadline_context: str | None = None

    @staticmethod
    def now_iso() -> str:
        """Retorna o timestamp atual em formato ISO 8601 com sufixo 'Z'."""
        return datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
