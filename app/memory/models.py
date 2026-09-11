from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SessionContext:
    session_id: str
    updated_at: datetime
    ultima_intencao: str | None = None
    ultima_acao: str | None = None
    opcoes_horarios: list[dict] = field(default_factory=list)
    horario_selecionado: dict | None = None
    dados_extraidos: dict[str, str] = field(default_factory=dict)
    colaborador_id: str | None = None
