from datetime import date, datetime, time
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgendamentoStatus(StrEnum):
    AGENDADO = "AGENDADO"
    CANCELADO = "CANCELADO"
    CONCLUIDO = "CONCLUIDO"
    FALTOU = "FALTOU"


class AgendamentoCreate(BaseModel):
    colaborador_id: UUID
    massoterapeuta_id: UUID
    horario_id: UUID


class AgendamentoStatusUpdate(BaseModel):
    status: AgendamentoStatus


class AgendamentoGraphRequest(BaseModel):
    colaborador_id: UUID
    massoterapeuta_id: UUID | None = None
    horario_id: UUID | None = None
    mensagem: str | None = Field(
        default=None,
        max_length=500,
        description="Pedido em linguagem natural, ex.: 'quero massagem quinta de manhã'.",
    )

    @model_validator(mode="after")
    def validar_caminho(self) -> "AgendamentoGraphRequest":
        estruturado = self.massoterapeuta_id is not None and self.horario_id is not None
        texto = bool(self.mensagem and self.mensagem.strip())

        if not estruturado and not texto:
            raise ValueError(
                "Envie massoterapeuta_id + horario_id, ou uma mensagem em texto livre."
            )

        return self


class AgendamentoGraphResponse(BaseModel):
    sucesso: bool
    mensagem: str
    interpretacao: str | None = None
    agendamento: dict[str, Any] | None = None


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
