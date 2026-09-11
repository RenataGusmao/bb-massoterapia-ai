from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agents.recepcao.intents import Intencao


class ChatRequest(BaseModel):
    session_id: str | None = None
    colaborador_id: UUID | None = None
    mensagem: str = Field(..., min_length=1)


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
