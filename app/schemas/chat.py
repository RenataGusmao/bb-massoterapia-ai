from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.recepcao.intents import Intencao


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = None
    colaborador_id: UUID | None = None
    mensagem: str = Field(..., min_length=1, max_length=1000)

    @field_validator("mensagem")
    @classmethod
    def mensagem_nao_vazia(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("Informe uma mensagem.")
        return valor.strip()

    @field_validator("session_id")
    @classmethod
    def sessao_uuid(cls, valor: str | None) -> str | None:
        return str(UUID(valor)) if valor is not None else None


class ChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    sucesso: bool
    intencao: Intencao
    acao: str | None
    resposta: str
    dados_extraidos: dict[str, str]
    dados_faltantes: list[str]
    status: str
    opcoes: list[dict[str, Any]] = Field(default_factory=list)
    opcao_selecionada: dict[str, Any] | None = None
    agendamento: dict[str, Any] | None = None
    detalhes: dict[str, Any] | None = None
