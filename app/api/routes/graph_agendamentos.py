from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from app.core.security import autorizar_colaborador, get_current_user
from app.schemas.auth import UsuarioAutenticado
from app.agents.cancelamento import acao_solicitada
from app.services.agenda_automatica import exigir_prontidao_http
from app.graphs.agendamento.graph import agendamento_graph
from app.graphs.agendamento.state import AgendamentoState
from app.schemas.agendamento import (
    AgendamentoGraphRequest, AgendamentoGraphResponse, AgendamentoGraphErrorResponse,
    AgendamentoGraphValidationErrorResponse,
)

router = APIRouter(prefix="/graph", tags=["langgraph"])

AGENDAMENTO_GRAPH_RESPONSES = {
    200: {"description": "Agendamento cancelado ou cancelamento repetido.", "model": AgendamentoGraphResponse},
    201: {"description": "Agendamento criado pelo fluxo LangGraph."},
    404: {"description": "Colaborador, massoterapeuta ou horário não encontrado."},
    409: {"description": "Pedido ambiguo, transicao invalida ou conflito de negocio."},
    422: {"description": "Dados inválidos, pedido incompreensível ou horário incompatível."},
    500: {"description": "Erro interno controlado."},
    502: {"description": "Falha na chamada ao modelo de linguagem."},
    503: {"description": "Agenda ainda nao pronta, falha de infraestrutura, banco ou IA nao configurados."},
}
for codigo, contrato in AGENDAMENTO_GRAPH_RESPONSES.items():
    if codigo not in (200, 201):
        contrato["model"] = AgendamentoGraphErrorResponse
AGENDAMENTO_GRAPH_RESPONSES[422]["model"] = (
    AgendamentoGraphErrorResponse | AgendamentoGraphValidationErrorResponse
)


@router.post(
    "/agendamentos",
    summary="Criar ou cancelar agendamento com LangGraph",
    response_model=AgendamentoGraphResponse,
    status_code=status.HTTP_201_CREATED,
    responses=AGENDAMENTO_GRAPH_RESPONSES,
)
def cadastrar_agendamento_com_grafo(
    requisicao: AgendamentoGraphRequest,
    usuario: UsuarioAutenticado = Depends(get_current_user),
):
    """Cria uma reserva ou cancela uma reserva propria usando a identidade do JWT.

    Cancelamento nao depende da prontidao da agenda. Pedidos ambiguos retornam
    409 e devem ser reenviados com data/horario ou agendamento_id.
    """
    colaborador_id = requisicao.colaborador_id or usuario.colaborador_id
    if colaborador_id is None:
        raise HTTPException(422, "Informe colaborador_id para criar; para cancelar use uma conta vinculada ao colaborador.")
    autorizar_colaborador(usuario, colaborador_id)
    if acao_solicitada(requisicao.mensagem, requisicao.agendamento_id) == "criar":
        try:
            exigir_prontidao_http()
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, headers=exc.headers, content={
                "sucesso": False, "mensagem": exc.detail, "erro": "agenda_nao_pronta",
            })
    state_inicial: AgendamentoState = {
        "colaborador_id": str(colaborador_id),
        "colaborador_autenticado_id": str(usuario.colaborador_id) if usuario.colaborador_id else None,
        "agendamento_id": str(requisicao.agendamento_id) if requisicao.agendamento_id else None,
        "horario_id": str(requisicao.horario_id) if requisicao.horario_id else None,
        "mensagem": requisicao.mensagem,
    }

    resultado = agendamento_graph.invoke(state_inicial)

    if resultado.get("sucesso") is True:
        conteudo = AgendamentoGraphResponse.model_validate({
            "sucesso": True,
            "mensagem": resultado["mensagem_resposta"],
            "interpretacao": resultado.get("interpretacao"),
            "agendamento": resultado["agendamento"],
        })
        if resultado.get("acao") == "cancelar":
            return JSONResponse(status_code=200, content=jsonable_encoder(conteudo),
                                headers={"Cache-Control": "no-store"})
        return conteudo

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
        headers={"Cache-Control": "no-store"},
    )
