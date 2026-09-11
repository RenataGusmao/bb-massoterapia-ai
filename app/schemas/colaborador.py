from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ColaboradorCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=160)
    matricula: str = Field(..., min_length=1, max_length=80)
    email: EmailStr
    setor: str | None = Field(default=None, max_length=120)


class ColaboradorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    matricula: str
    email: EmailStr
    setor: str | None = None
    ativo: bool
    criado_em: datetime
