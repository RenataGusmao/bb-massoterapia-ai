from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UsuarioRole(StrEnum):
    COLABORADOR = "colaborador"
    ADMIN = "admin"


class LoginRequest(BaseModel):
    email: EmailStr
    senha: str = Field(..., min_length=1, max_length=256)

    @field_validator("email", mode="before")
    @classmethod
    def normalizar_email(cls, valor: object) -> object:
        return valor.strip().lower() if isinstance(valor, str) else valor


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ColaboradorContaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colaborador_id: UUID
    senha: str = Field(..., min_length=12, max_length=256)


class UsuarioCreate(BaseModel):
    colaborador_id: UUID | None = None
    email: EmailStr
    senha_hash: str
    role: UsuarioRole = UsuarioRole.COLABORADOR
    ativo: bool = True

    @field_validator("email", mode="before")
    @classmethod
    def normalizar_email(cls, valor: object) -> object:
        return valor.strip().lower() if isinstance(valor, str) else valor


class UsuarioAutenticado(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    colaborador_id: UUID | None = None
    email: EmailStr
    role: UsuarioRole
    ativo: bool


class UsuarioResponse(UsuarioAutenticado):
    created_at: datetime
    updated_at: datetime
