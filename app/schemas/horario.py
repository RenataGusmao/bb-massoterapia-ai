from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HorarioCreate(BaseModel):
    massoterapeuta_id: UUID
    data: date
    hora_inicio: time
    hora_fim: time
    disponivel: bool = True

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
    massoterapeuta_id: UUID
    data: date
    hora_inicio: time
    hora_fim: time
    disponivel: bool
    criado_em: datetime
