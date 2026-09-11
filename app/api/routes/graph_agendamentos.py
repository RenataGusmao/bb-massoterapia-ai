from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.graphs.agendamento.graph import agendamento_graph
from app.graphs.agendamento.state import AgendamentoState
from app.schemas.agendamento import AgendamentoCreate

router = APIRouter(prefix="/graph", tags=["langgraph"])

AGENDAMENTO_GRAPH_RESPONSES = {
    201: {"description": "Agendamento criado pelo fluxo LangGraph."},
    404: {"description": "Colaborador, massoterapeuta ou horário não encontrado."},
    409: {"description": "Conflito de negócio, como intervalo mínimo, horário ocupado ou massoterapeuta inativo."},
    422: {"description": "Dados inválidos ou horário incompatível com o massoterapeuta informado."},
    500: {"description": "Erro interno controlado."},
    503: {"description": "Falha de infraestrutura ou banco não configurado."},
}


@router.post(
    "/agendamentos",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    responses=AGENDAMENTO_GRAPH_RESPONSES,
)
def cadastrar_agendamento_com_grafo(agendamento: AgendamentoCreate):
    state_inicial: AgendamentoState = {
        "colaborador_id": str(agendamento.colaborador_id),
        "massoterapeuta_id": str(agendamento.massoterapeuta_id),
        "horario_id": str(agendamento.horario_id),
    }

    resultado = agendamento_graph.invoke(state_inicial)

    if resultado.get("sucesso") is True:
        return {
            "sucesso": True,
            "mensagem": resultado["mensagem"],
            "agendamento": resultado["agendamento"],
        }

    return JSONResponse(
        status_code=resultado.get("status_http", status.HTTP_500_INTERNAL_SERVER_ERROR),
        content={
            "sucesso": False,
            "mensagem": resultado.get("mensagem", "Não foi possível realizar o agendamento."),
        },
    )
