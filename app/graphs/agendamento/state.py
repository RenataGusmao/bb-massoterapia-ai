from typing import Any, NotRequired, TypedDict


class AgendamentoState(TypedDict):
    colaborador_id: str

    massoterapeuta_id: NotRequired[str | None]
    horario_id: NotRequired[str | None]

    mensagem: NotRequired[str | None]
    interpretacao: NotRequired[str | None]

    colaborador: NotRequired[dict[str, Any] | None]
    massoterapeuta: NotRequired[dict[str, Any] | None]
    horario: NotRequired[dict[str, Any] | None]
    data_agendamento: NotRequired[str | None]
    entidades_validas: NotRequired[bool]
    intervalo_permitido: NotRequired[bool]
    sucesso: NotRequired[bool]
    status_http: NotRequired[int]
    mensagem_resposta: NotRequired[str]
    agendamento: NotRequired[dict[str, Any] | None]
    erro: NotRequired[str | None]
