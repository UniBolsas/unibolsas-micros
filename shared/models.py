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
        captured_at: Timestamp ISO 8601 de quando o edital foi capturado (e.g. "2026-04-25T20:39:40Z").
        registration_deadline: Data limite para inscrições no formato ISO 8601 (e.g. "2026-05-12"), se encontrada.
        registration_deadline_context: Trecho do PDF de onde a data limite foi extraída.
    """

    id: str
    title: str
    pdf_url: str
    institution: str
    status: str
    captured_at: str
    registration_deadline: str | None = None
    registration_deadline_context: str | None = None

    @staticmethod
    def now_iso() -> str:
        """Retorna o timestamp atual em formato ISO 8601 com sufixo 'Z'."""
        return datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
