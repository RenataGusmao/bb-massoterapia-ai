from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class MassoterapeutaCreate(BaseModel):
    nome: str = Field(..., min_length=2, max_length=160)
    email: EmailStr | None = None
    ativo: bool = True


class MassoterapeutaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    email: EmailStr | None = None
    ativo: bool
    criado_em: datetime
