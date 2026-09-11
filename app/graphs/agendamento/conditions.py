from app.graphs.agendamento.state import AgendamentoState


def decidir_apos_validacao_entidades(state: AgendamentoState) -> str:
    # Conditional Edge escolhe o próximo nó com base no estado atual do fluxo.
    if state.get("entidades_validas") is True:
        return "continuar"

    return "erro"


def decidir_apos_intervalo(state: AgendamentoState) -> str:
    # Conditional Edge escolhe o próximo nó com base no estado atual do fluxo.
    if state.get("intervalo_permitido") is True:
        return "continuar"

    return "bloqueio"


def decidir_apos_execucao(state: AgendamentoState) -> str:
    # Conditional Edge escolhe o próximo nó com base no estado atual do fluxo.
    if state.get("sucesso") is True:
        return "sucesso"

    return "erro"
