from typing import Any, NotRequired, TypedDict


class AgendamentoState(TypedDict):
    # State representa os dados compartilhados entre os nós durante a execução do grafo.
    colaborador_id: str
    massoterapeuta_id: str
    horario_id: str
    colaborador: NotRequired[dict[str, Any] | None]
    massoterapeuta: NotRequired[dict[str, Any] | None]
    horario: NotRequired[dict[str, Any] | None]
    data_agendamento: NotRequired[str | None]
    entidades_validas: NotRequired[bool]
    intervalo_permitido: NotRequired[bool]
    sucesso: NotRequired[bool]
    status_http: NotRequired[int]
    mensagem: NotRequired[str]
    agendamento: NotRequired[dict[str, Any] | None]
    erro: NotRequired[str | None]
