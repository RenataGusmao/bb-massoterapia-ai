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
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "colaborador_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "horario_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }]})

    colaborador_id: UUID
    horario_id: UUID


class AgendamentoStatusUpdate(BaseModel):
    status: AgendamentoStatus


class AgendamentoGraphRequest(BaseModel):
    """Criacao estruturada/textual e cancelamento de reservas proprias.

    Estruturado: colaborador_id + horario_id (vaga).
    Com IA:      colaborador_id + mensagem em texto livre.
    Cancelar:    mensagem ou agendamento_id; identidade vem do JWT.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [
        {"colaborador_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
         "horario_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
        {"colaborador_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
         "mensagem": "Quero massagem quinta de manha."},
        {"mensagem": "Quero cancelar meu agendamento."},
        {"mensagem": "Cancela minha massagem do dia 26/10."},
    ]})

    colaborador_id: UUID | None = Field(default=None, description="Para colaborador, omitido usa o vinculo do JWT. Admin informa o alvo da criacao.")
    horario_id: UUID | None = None
    agendamento_id: UUID | None = Field(default=None, description="Reserva propria a cancelar; nao e o horario_id. Util para esclarecer ou repetir um cancelamento.")
    mensagem: str | None = Field(
        default=None,
        max_length=500,
        description="Pedido de criacao ou cancelamento, ex.: 'quero massagem quinta de manha' ou 'quero desmarcar minha massagem de amanha'.",
    )

    @model_validator(mode="after")
    def validar_caminho(self) -> "AgendamentoGraphRequest":
        estruturado = self.horario_id is not None
        texto = bool(self.mensagem and self.mensagem.strip())

        if estruturado and self.agendamento_id:
            raise ValueError("Nao combine horario_id de criacao e agendamento_id de cancelamento.")
        if not estruturado and not texto and self.agendamento_id is None:
            raise ValueError(
                "Envie horario_id, mensagem em texto livre ou agendamento_id para cancelar."
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
