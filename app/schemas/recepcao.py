from pydantic import BaseModel, ConfigDict, Field

from app.agents.recepcao.intents import Intencao


class RecepcaoRequest(BaseModel):
    mensagem: str = Field(..., min_length=1)


class RecepcaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    intencao: Intencao
    mensagem_recebida: str
    dados_extraidos: dict[str, str]
    dados_faltantes: list[str]
    acao: str
    encaminhar_para: str
