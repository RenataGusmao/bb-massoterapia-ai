from datetime import date, datetime, time
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AgendamentoStatus(StrEnum):
    AGENDADO = "AGENDADO"
    CANCELADO = "CANCELADO"
    CONCLUIDO = "CONCLUIDO"
    FALTOU = "FALTOU"


class AgendamentoCreate(BaseModel):
    colaborador_id: UUID
    massoterapeuta_id: UUID
    horario_id: UUID


class AgendamentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    colaborador_id: UUID
    massoterapeuta_id: UUID
    horario_id: UUID
    data_agendamento: date
    hora_inicio: time
    hora_fim: time
    status: AgendamentoStatus
    criado_em: datetime
    atualizado_em: datetime
