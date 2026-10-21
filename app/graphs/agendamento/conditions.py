from app.graphs.agendamento.state import AgendamentoState


def decidir_apos_interpretacao(state: AgendamentoState) -> str:
    if state.get("erro") is None:
        return "continuar"

    return "erro"


def decidir_apos_validacao_entidades(state: AgendamentoState) -> str:
    if state.get("entidades_validas") is True:
        return "continuar"

    return "erro"


def decidir_apos_intervalo(state: AgendamentoState) -> str:
    if state.get("intervalo_permitido") is True:
        return "continuar"

    return "bloqueio"


def decidir_apos_execucao(state: AgendamentoState) -> str:
    if state.get("sucesso") is True:
        return "sucesso"

    return "erro"