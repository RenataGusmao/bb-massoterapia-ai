from typing import TypedDict

from app.agents.recepcao.intents import Intencao


class OrchestratorState(TypedDict, total=False):
    mensagem: str
    intencao: Intencao
    acao: str | None
    dados_extraidos: dict[str, str]
    dados_faltantes: list[str]
    encaminhar_para: str
    resposta: str
    status: str
    sucesso: bool
    session_id: str
    opcao_selecionada: dict | None
    agendamento: dict | None
