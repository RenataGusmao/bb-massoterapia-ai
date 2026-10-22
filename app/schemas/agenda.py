from datetime import date, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BloqueioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chave_idempotencia: UUID
    data: date
    hora_inicio: time | None = None
    hora_fim: time | None = None
    motivo: str = Field(min_length=1, max_length=200)

    @field_validator("motivo")
    @classmethod
    def motivo_nao_vazio(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("Informe um motivo.")
        return valor.strip()

    @field_validator("hora_inicio", "hora_fim")
    @classmethod
    def hora_local(cls, valor: time | None) -> time | None:
        if valor is not None and valor.tzinfo is not None:
            raise ValueError("Informe hora local sem offset.")
        return valor

    @model_validator(mode="after")
    def intervalo(self):
        if (self.hora_inicio is None) != (self.hora_fim is None):
            raise ValueError("Informe ambas as horas ou nenhuma para bloquear o dia.")
        if self.hora_inicio is not None and self.hora_fim <= self.hora_inicio:
            raise ValueError("Intervalo invalido.")
        return self


class BloqueioResponse(BaseModel):
    id: UUID
    data: date
    hora_inicio: time | None
    hora_fim: time | None
    motivo: str
    ativo: bool


class AtendimentoOperacional(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: date
    hora_inicio: time
    hora_fim: time
    capacidade: int = Field(ge=1)
    agendados: int = Field(ge=0)
    disponiveis: int = Field(ge=0)


class AgendaResponse(BaseModel):
    itens: list[AtendimentoOperacional] = Field(max_length=310)
