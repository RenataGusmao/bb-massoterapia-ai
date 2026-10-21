from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChatAgendamentoConfirmarRequest(BaseModel):
    colaborador_id: UUID
    massoterapeuta_id: UUID
    horario_id: UUID


class ChatAgendamentoConfirmarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sucesso: bool
    mensagem: str
    agendamento: dict[str, Any]
