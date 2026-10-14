from datetime import date, datetime, time
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class AgendamentoStatus(StrEnum):
    AGENDADO = "AGENDADO"
    CANCELADO = "CANCELADO"
    CONCLUIDO = "CONCLUIDO"
    FALTOU = "FALTOU"


class AgendamentoCreate(BaseModel):
    colaborador_id: UUID
    massoterapeuta_id: UUID | None = None
    horario_id: UUID


class AgendamentoStatusUpdate(BaseModel):
    status: AgendamentoStatus


class AgendamentoGraphRequest(BaseModel):
    """Aceita os dois caminhos do grafo.

    Estruturado: colaborador_id + horario_id (vaga).
    Com IA:      colaborador_id + mensagem em texto livre.
    """

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
        estruturado = self.horario_id is not None
        texto = bool(self.mensagem and self.mensagem.strip())

        if not estruturado and not texto:
            raise ValueError(
                "Envie horario_id, ou uma mensagem em texto livre."
            )

        return self


class AgendamentoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    colaborador_id: UUID
    massoterapeuta_id: UUID | None = None
    horario_id: UUID
    data_agendamento: date
    hora_inicio: time
    hora_fim: time
    status: AgendamentoStatus
    criado_em: datetime
    atualizado_em: datetime


class AgendamentoGraphResponse(BaseModel):
    sucesso: bool
    mensagem: str
    interpretacao: str | None
    agendamento: AgendamentoResponse


class AgendamentoGraphErrorResponse(BaseModel):
    sucesso: bool
    mensagem: str
    erro: str | None
    sugestoes: list[dict[str, Any]] | None = None


class AgendamentoGraphValidationErrorResponse(BaseModel):
    detail: list[dict[str, Any]]


class AgendamentoRPCResponse(BaseModel):
    sucesso: StrictBool
    agendamento: AgendamentoResponse | None = None
    erro: str | None = None
    detalhe: str | None = None

    @model_validator(mode="after")
    def validar_resultado(self) -> "AgendamentoRPCResponse":
        if self.sucesso and self.agendamento is None:
            raise ValueError("RPC não retornou o agendamento.")
        if not self.sucesso and not self.erro:
            raise ValueError("RPC não retornou o código do erro.")
        return self
