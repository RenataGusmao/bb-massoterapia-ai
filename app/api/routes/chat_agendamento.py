from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.graphs.agendamento.graph import agendamento_graph
from app.graphs.agendamento.state import AgendamentoState
from app.schemas.chat_agendamento import (
    ChatAgendamentoConfirmarRequest,
    ChatAgendamentoConfirmarResponse,
)

router = APIRouter(prefix="/chat/agendamento", tags=["chat"])

CHAT_AGENDAMENTO_CONFIRMAR_RESPONSES = {
    201: {"description": "Agendamento confirmado com sucesso."},
    404: {"description": "Colaborador, massoterapeuta ou horário não encontrado."},
    409: {"description": "Conflito de negócio, como intervalo mínimo, horário ocupado ou massoterapeuta inativo."},
    422: {"description": "Dados inválidos ou horário incompatível com o massoterapeuta informado."},
    500: {"description": "Erro interno controlado."},
    503: {"description": "Falha de infraestrutura ou banco não configurado."},
}


@router.post(
    "/confirmar",
    response_model=ChatAgendamentoConfirmarResponse,
    status_code=status.HTTP_201_CREATED,
    responses=CHAT_AGENDAMENTO_CONFIRMAR_RESPONSES,
)
def confirmar_agendamento_chat(payload: ChatAgendamentoConfirmarRequest):
    state_inicial: AgendamentoState = {
        "colaborador_id": str(payload.colaborador_id),
        "massoterapeuta_id": str(payload.massoterapeuta_id),
        "horario_id": str(payload.horario_id),
    }

    resultado = agendamento_graph.invoke(state_inicial)

    if resultado.get("sucesso") is True:
        return {
            "sucesso": True,
            "mensagem": "Agendamento confirmado com sucesso.",
            "agendamento": resultado["agendamento"],
        }

    return JSONResponse(
        status_code=resultado.get("status_http", status.HTTP_500_INTERNAL_SERVER_ERROR),
        content={
            "sucesso": False,
            "mensagem": resultado.get("mensagem", "Não foi possível confirmar o agendamento."),
        },
    )
