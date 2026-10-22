from uuid import UUID

from app.agents.cancelamento import acao_solicitada, filtrar_reservas, EsclarecimentoCancelamento
from app.database.repositories import agendamentos as repository
from app.graphs.agendamento.nodes import _erro
from app.graphs.agendamento.state import AgendamentoState
from app.services.agendamentos import AgendamentoRegraError, cancelar_agendamento_do_colaborador


def classificar_solicitacao(state: AgendamentoState) -> AgendamentoState:
    acao = acao_solicitada(state.get("mensagem"), state.get("agendamento_id"))
    state = {**state, "acao": acao}
    if acao == "esclarecer":
        return _erro(state, 409, "Voce deseja cancelar uma reserva? Confirme o pedido e informe a data ou o agendamento_id.",
                     "esclarecimento_necessario")
    if acao == "cancelar" and state.get("horario_id"):
        return _erro(state, 422, "Para cancelar, informe agendamento_id, nao horario_id.", "payload_invalido")
    return state


def decidir_solicitacao(state: AgendamentoState) -> str:
    return "erro" if state.get("erro") else state["acao"]


def executar_cancelamento(state: AgendamentoState) -> AgendamentoState:
    identidade = state.get("colaborador_autenticado_id")
    if not identidade or identidade != state["colaborador_id"]:
        return _erro(state, 403, "Cancelamento pelo grafo exige o proprio vinculo autenticado.", "acesso_negado")
    colaborador_id = UUID(identidade)
    try:
        identificador = state.get("agendamento_id")
        if identificador:
            reserva = repository.buscar_agendamento_do_colaborador(UUID(identificador), colaborador_id)
            reservas = [reserva] if reserva else []
        else:
            reservas = repository.listar_agendamentos_para_cancelamento(colaborador_id)
        # Defense in depth: neither a model nor a malformed repository result may change ownership.
        reservas = [r for r in reservas if str(r["colaborador_id"]) == identidade]
        candidatas = filtrar_reservas(state.get("mensagem"), reservas, por_id=bool(identificador))
        if not candidatas:
            return _erro(state, 404, "Nao encontrei um agendamento seu correspondente ao pedido.", "agendamento_nao_encontrado")
        if len(candidatas) > 1:
            opcoes = [{"agendamento_id": str(r["id"]), "data": str(r["data_agendamento"]),
                       "hora_inicio": str(r["hora_inicio"]), "status": str(r["status"])}
                      for r in candidatas[:10]]
            return _erro(state, 409, "Encontrei mais de uma reserva possivel. Informe a data e horario ou o agendamento_id.",
                         "esclarecimento_necessario", sugestoes=opcoes)
        resultado = cancelar_agendamento_do_colaborador(UUID(str(candidatas[0]["id"])), colaborador_id)
    except repository.ConsultaAgendamentosIncompletaError:
        return _erro(state, 409, "Informe o agendamento_id para localizar a reserva com seguranca.",
                     "esclarecimento_necessario")
    except EsclarecimentoCancelamento as exc:
        return _erro(state, 409, str(exc), "esclarecimento_necessario")
    except AgendamentoRegraError as exc:
        return _erro(state, exc.status_http, str(exc), exc.codigo)
    except Exception:
        return _erro(state, 503, "Nao foi possivel consultar ou cancelar sua reserva agora. Tente novamente.",
                     "cancelamento_indisponivel")
    return {**state, "sucesso": True, "status_http": 200, "agendamento": resultado, "erro": None,
            "mensagem_resposta": "Seu agendamento foi cancelado. A vaga segue as regras de disponibilidade da agenda."}
