from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.core.security import verificar_api_key
from app.graphs.agendamento.graph import agendamento_graph
from app.graphs.agendamento.state import AgendamentoState
from app.schemas.agendamento import AgendamentoGraphRequest

router = APIRouter(prefix="/graph", tags=["langgraph"])

AGENDAMENTO_GRAPH_RESPONSES = {
    201: {"description": "Agendamento criado pelo fluxo LangGraph."},
    404: {"description": "Colaborador, massoterapeuta ou horário não encontrado."},
    409: {"description": "Conflito de negócio, como intervalo mínimo, horário ocupado ou massoterapeuta inativo."},
    422: {"description": "Dados inválidos, pedido incompreensível ou horário incompatível."},
    500: {"description": "Erro interno controlado."},
    502: {"description": "Falha na chamada ao modelo de linguagem."},
    503: {"description": "Falha de infraestrutura, banco ou IA não configurados."},
}


@router.post(
    "/agendamentos",
    response_model=None,
    status_code=status.HTTP_201_CREATED,
    responses=AGENDAMENTO_GRAPH_RESPONSES,
    dependencies=[Depends(verificar_api_key)],
)
def cadastrar_agendamento_com_grafo(requisicao: AgendamentoGraphRequest):
    state_inicial: AgendamentoState = {
        "colaborador_id": str(requisicao.colaborador_id),
        "massoterapeuta_id": (
            str(requisicao.massoterapeuta_id) if requisicao.massoterapeuta_id else None
        ),
        "horario_id": str(requisicao.horario_id) if requisicao.horario_id else None,
        "mensagem": requisicao.mensagem,
    }

    resultado = agendamento_graph.invoke(state_inicial)

    if resultado.get("sucesso") is True:
        return {
            "sucesso": True,
            "mensagem": resultado["mensagem_resposta"],
            "interpretacao": resultado.get("interpretacao"),
            "agendamento": resultado["agendamento"],
        }

    conteudo = {
        "sucesso": False,
        "mensagem": resultado.get(
            "mensagem_resposta", "Não foi possível realizar o agendamento."
        ),
        "erro": resultado.get("erro"),
    }

    sugestoes = resultado.get("sugestoes")
    if sugestoes:
        conteudo["sugestoes"] = sugestoes

    return JSONResponse(
        status_code=resultado.get("status_http", status.HTTP_500_INTERNAL_SERVER_ERROR),
        content=conteudo,
    )