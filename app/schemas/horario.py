from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class HorarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "chave_idempotencia": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "data": "2099-01-01", "hora_inicio": "09:00", "hora_fim": "09:30",
        "capacidade": 2, "disponivel": True,
    }]})

    chave_idempotencia: UUID
    capacidade: int = Field(default=1, strict=True, ge=1, le=500)
    data: date
    hora_inicio: time
    hora_fim: time
    disponivel: bool = True

    @field_validator("hora_inicio", "hora_fim")
    @classmethod
    def validar_hora_local(cls, valor: time) -> time:
        if valor.tzinfo is not None:
            raise ValueError("Informe horários locais sem offset; fuso America/Sao_Paulo.")
        return valor

    @field_validator("hora_fim")
    @classmethod
    def validar_periodo(cls, hora_fim: time, info) -> time:
        hora_inicio = info.data.get("hora_inicio")
        if hora_inicio is not None and hora_fim <= hora_inicio:
            raise ValueError("hora_fim deve ser posterior a hora_inicio.")

        return hora_fim


class HorarioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    massoterapeuta_id: UUID | None = None
    disponibilidade_id: UUID
    numero_vaga: int
    data: date
    hora_inicio: time
    hora_fim: time
    disponivel: bool
    criado_em: datetime


class DisponibilidadeResponse(BaseModel):
    id: UUID
    data: date
    hora_inicio: time
    hora_fim: time
    capacidade: int = Field(gt=0)
    vagas: list[HorarioResponse]

    @model_validator(mode="after")
    def validar_vagas(self) -> "DisponibilidadeResponse":
        if (
            len(self.vagas) != self.capacidade
            or len({v.id for v in self.vagas}) != self.capacidade
            or {v.numero_vaga for v in self.vagas} != set(range(1, self.capacidade + 1))
            or any(
                v.disponibilidade_id != self.id or v.data != self.data
                or v.hora_inicio != self.hora_inicio or v.hora_fim != self.hora_fim
                for v in self.vagas
            )
        ):
            raise ValueError("Vagas incompatíveis com o lote.")
        return self


class DisponibilidadeRPCResponse(BaseModel):
    sucesso: StrictBool
    criado: StrictBool | None = None
    disponibilidade: DisponibilidadeResponse | None = None
    erro: str | None = None

    @model_validator(mode="after")
    def validar_resultado(self) -> "DisponibilidadeRPCResponse":
        if self.sucesso and (self.disponibilidade is None or self.criado is None):
            raise ValueError("RPC não retornou a disponibilidade.")
        if not self.sucesso and not self.erro:
            raise ValueError("RPC não retornou o erro.")
        return self
