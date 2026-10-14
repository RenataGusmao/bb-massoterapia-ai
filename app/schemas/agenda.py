from datetime import date, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.schemas.agendamento import AgendamentoStatus


class TerceirizadaContaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    senha: SecretStr = Field(
        min_length=12, max_length=256,
        json_schema_extra={"writeOnly": True, "format": "password"},
    )
    disponibilidade_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("email", mode="before")
    @classmethod
    def normalizar_email(cls, valor: object) -> object:
        return valor.strip().lower() if isinstance(valor, str) else valor

    @field_validator("senha", mode="before")
    @classmethod
    def senha_forte(cls, valor: str | SecretStr) -> str:
        if isinstance(valor, SecretStr):
            valor = valor.get_secret_value()
        if not isinstance(valor, str):
            raise ValueError("Senha deve ser texto.")
        if not (
            any(c.isupper() for c in valor) and any(c.islower() for c in valor)
            and any(c.isdigit() for c in valor)
            and any(not c.isalnum() and not c.isspace() for c in valor)
        ):
            raise ValueError("Senha deve conter maiuscula, minuscula, numero e simbolo.")
        return valor

    @field_validator("disponibilidade_ids")
    @classmethod
    def lotes_distintos(cls, valor: list[UUID]) -> list[UUID]:
        if len(set(valor)) != len(valor):
            raise ValueError("Informe lotes distintos.")
        return valor


class AtendimentoOperacional(BaseModel):
    id: UUID
    data: date
    hora_inicio: time
    hora_fim: time
    status: AgendamentoStatus
    horario_id: UUID
    disponibilidade_id: UUID


class AgendaResponse(BaseModel):
    itens: list[AtendimentoOperacional]
    total: int = Field(ge=0)
    pagina: int = Field(ge=1, le=10000)
    tamanho_pagina: int = Field(ge=1, le=100)
