from langgraph.graph import END, START, StateGraph

from app.graphs.agendamento.conditions import (
    decidir_apos_execucao,
    decidir_apos_interpretacao,
    decidir_apos_intervalo,
    decidir_apos_validacao_entidades,
)
from app.graphs.agendamento.nodes import (
    executar_agendamento,
    interpretar_solicitacao,
    receber_solicitacao,
    responder_erro,
    responder_sucesso,
    validar_entidades,
    validar_intervalo,
)
from app.graphs.agendamento.state import AgendamentoState


graph_builder = StateGraph(AgendamentoState)
graph_builder.add_node("receber_solicitacao", receber_solicitacao)
graph_builder.add_node("interpretar_solicitacao", interpretar_solicitacao)
graph_builder.add_node("validar_entidades", validar_entidades)
graph_builder.add_node("validar_intervalo", validar_intervalo)
graph_builder.add_node("executar_agendamento", executar_agendamento)
graph_builder.add_node("responder_sucesso", responder_sucesso)
graph_builder.add_node("responder_erro", responder_erro)

graph_builder.add_edge(START, "receber_solicitacao")
graph_builder.add_edge("receber_solicitacao", "interpretar_solicitacao")

graph_builder.add_conditional_edges(
    "interpretar_solicitacao",
    decidir_apos_interpretacao,
    {
        "continuar": "validar_entidades",
        "erro": "responder_erro",
    },
)
graph_builder.add_conditional_edges(
    "validar_entidades",
    decidir_apos_validacao_entidades,
    {
        "continuar": "validar_intervalo",
        "erro": "responder_erro",
    },
)
graph_builder.add_conditional_edges(
    "validar_intervalo",
    decidir_apos_intervalo,
    {
        "continuar": "executar_agendamento",
        "bloqueio": "responder_erro",
    },
)
graph_builder.add_conditional_edges(
    "executar_agendamento",
    decidir_apos_execucao,
    {
        "sucesso": "responder_sucesso",
        "erro": "responder_erro",
    },
)
graph_builder.add_edge("responder_sucesso", END)
graph_builder.add_edge("responder_erro", END)

agendamento_graph = graph_builder.compile()
