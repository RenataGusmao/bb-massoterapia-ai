import re

from app.agents.bem_estar import processar_orientacao
from app.agents.bem_estar.categories import CategoriaBemEstar
from app.agents.orchestrator.state import OrchestratorState
from app.agents.recepcao import processar_mensagem_recepcao
from app.agents.recepcao.classifier import normalizar_mensagem
from app.agents.recepcao.intents import Intencao
from app.graphs.agendamento.graph import agendamento_graph
from app.graphs.agendamento.state import AgendamentoState
from app.memory import get_or_create_session, save_session
from app.memory.models import SessionContext
from app.services.disponibilidade import consultar_disponibilidade_chat


RESPOSTA_COLETAR_DADOS = (
    "Para continuar, me informe a data ou se prefere manhã, tarde ou noite."
)

RESPOSTA_FORA_DE_ESCOPO = "Essa funcionalidade ainda não está disponível neste MVP."

RESPOSTA_NAO_ENTENDIDO = (
    "Não consegui identificar sua solicitação. Você pode reformular ou informar se "
    "deseja agendar uma sessão ou receber uma orientação de bem-estar?"
)

RESPOSTA_SAUDE_SENSIVEL = (
    "Essa situação requer avaliação por profissional de saúde habilitado. Posso "
    "compartilhar orientações gerais de bem-estar, mas não diagnosticar, prescrever "
    "ou indicar tratamento."
)

RESPOSTA_SEM_CONTEXTO = (
    "Não tenho opções de horário recentes nesta sessão. Consulte a disponibilidade primeiro."
)

RESPOSTA_HORARIO_AMBIGUO = (
    "Encontrei mais de uma opção nesse horário. Informe o número da opção desejada."
)

RESPOSTA_COLABORADOR_NECESSARIO = (
    "Para confirmar o agendamento, preciso do colaborador_id nesta sessão."
)

ORDINAIS = {
    "primeiro": 1,
    "primeira": 1,
    "segundo": 2,
    "segunda": 2,
    "terceiro": 3,
    "terceira": 3,
    "quarto": 4,
    "quarta": 4,
    "quinto": 5,
    "quinta": 5,
}

CONFIRMACOES = ("sim", "confirmo", "pode confirmar", "confirmar")
NEGACOES = ("nao", "cancelar escolha")


def processar_chat(
    mensagem: str,
    session_id: str | None = None,
    colaborador_id: str | None = None,
) -> dict:
    session, _, expirou = get_or_create_session(session_id)

    if colaborador_id is not None:
        session.colaborador_id = colaborador_id

    texto = normalizar_mensagem(mensagem)

    if _eh_negacao(texto) and session.horario_selecionado is not None:
        return _cancelar_selecao(session, expirou)

    if _eh_confirmacao(texto) and session.horario_selecionado is not None:
        return _confirmar_agendamento(session, expirou)

    if _parece_selecao(texto):
        return _selecionar_opcao(session, texto, expirou)

    recepcao = processar_mensagem_recepcao(mensagem)
    estado: OrchestratorState = {
        "session_id": session.session_id,
        "mensagem": mensagem,
        "intencao": recepcao["intencao"],
        "acao": recepcao["acao"],
        "dados_extraidos": recepcao["dados_extraidos"],
        "dados_faltantes": recepcao["dados_faltantes"],
        "encaminhar_para": recepcao["encaminhar_para"],
    }

    intencao = estado["intencao"]

    if intencao == Intencao.ORIENTACAO_BEM_ESTAR:
        return _responder_bem_estar(session, estado, expirou)

    if intencao == Intencao.AGENDAMENTO:
        return _responder_agendamento(session, estado, expirou)

    if intencao == Intencao.SAUDE_SENSIVEL:
        return _responder_saude_sensivel(session, estado, expirou)

    if intencao == Intencao.FORA_DE_ESCOPO:
        _atualizar_session(session, estado, opcoes=[], selecao=None)
        return _montar_resposta(
            estado=estado,
            sucesso=False,
            resposta=RESPOSTA_FORA_DE_ESCOPO,
            status="fora_de_escopo",
            expirou=expirou,
        )

    _atualizar_session(session, estado, opcoes=[], selecao=None)
    return _montar_resposta(
        estado=estado,
        sucesso=False,
        resposta=RESPOSTA_NAO_ENTENDIDO,
        status="nao_entendido",
        expirou=expirou,
    )


def _responder_bem_estar(
    session: SessionContext,
    estado: OrchestratorState,
    expirou: bool,
) -> dict:
    orientacao = processar_orientacao(estado["mensagem"])
    _atualizar_session(session, estado, opcoes=[], selecao=None)

    return _montar_resposta(
        estado=estado,
        sucesso=orientacao["permitido"],
        resposta=orientacao["mensagem"],
        status="respondido" if orientacao["permitido"] else "bloqueado",
        detalhes={
            "categoria": orientacao["categoria"],
            "encaminhamento": orientacao["encaminhamento"],
        },
        expirou=expirou,
    )


def _responder_agendamento(
    session: SessionContext,
    estado: OrchestratorState,
    expirou: bool,
) -> dict:
    if estado["acao"] == "CONSULTAR_DISPONIBILIDADE":
        disponibilidade = consultar_disponibilidade_chat(estado["dados_extraidos"])
        dados_extraidos = {
            **estado["dados_extraidos"],
            "data_resolvida": disponibilidade["data_resolvida"],
        }
        estado = {**estado, "dados_extraidos": dados_extraidos}
        opcoes = disponibilidade["opcoes"]
        descricao_consulta = _descrever_consulta(dados_extraidos)
        _atualizar_session(session, estado, opcoes=opcoes, selecao=None)

        if not opcoes:
            return _montar_resposta(
                estado=estado,
                sucesso=True,
                resposta=f"Não encontrei horários disponíveis para {descricao_consulta}.",
                status="sem_disponibilidade",
                acao="SEM_DISPONIBILIDADE",
                opcoes=[],
                expirou=expirou,
            )

        return _montar_resposta(
            estado=estado,
            sucesso=True,
            resposta=f"Encontrei horários disponíveis para {descricao_consulta}.",
            status="aguardando_selecao_horario",
            acao="SELECIONAR_HORARIO",
            opcoes=opcoes,
            expirou=expirou,
        )

    _atualizar_session(session, estado, opcoes=[], selecao=None)
    return _montar_resposta(
        estado=estado,
        sucesso=True,
        resposta=RESPOSTA_COLETAR_DADOS,
        status="coletando_dados",
        expirou=expirou,
    )


def _responder_saude_sensivel(
    session: SessionContext,
    estado: OrchestratorState,
    expirou: bool,
) -> dict:
    orientacao = processar_orientacao(estado["mensagem"])
    _atualizar_session(session, estado, opcoes=[], selecao=None)

    if orientacao["categoria"] == CategoriaBemEstar.SINAL_DE_ALERTA:
        resposta = orientacao["mensagem"]
        detalhes = {
            "categoria": orientacao["categoria"],
            "encaminhamento": orientacao["encaminhamento"],
        }
    else:
        resposta = RESPOSTA_SAUDE_SENSIVEL
        detalhes = {
            "categoria": CategoriaBemEstar.FORA_DO_LIMITE_PROFISSIONAL,
            "encaminhamento": "PROFISSIONAL_HABILITADO",
        }

    return _montar_resposta(
        estado=estado,
        sucesso=False,
        resposta=resposta,
        status="bloqueado",
        detalhes=detalhes,
        expirou=expirou,
    )


def _selecionar_opcao(session: SessionContext, texto: str, expirou: bool) -> dict:
    estado = _estado_de_session(session)

    if not session.opcoes_horarios:
        return _montar_resposta(
            estado=estado,
            sucesso=False,
            resposta=RESPOSTA_SEM_CONTEXTO,
            status="sem_contexto",
            acao="CONSULTAR_DISPONIBILIDADE",
            expirou=expirou,
        )

    selecao = _buscar_opcao_por_ordinal(session.opcoes_horarios, texto)
    if selecao is None:
        selecao = _buscar_opcao_por_horario(session.opcoes_horarios, texto)

    if selecao == "AMBIGUA":
        return _montar_resposta(
            estado=estado,
            sucesso=False,
            resposta=RESPOSTA_HORARIO_AMBIGUO,
            status="selecao_ambigua",
            acao="SELECIONAR_OPCAO",
            opcoes=session.opcoes_horarios,
            expirou=expirou,
        )

    if selecao is None:
        return _montar_resposta(
            estado=estado,
            sucesso=False,
            resposta="Não consegui identificar a opção escolhida. Informe o número da opção desejada.",
            status="selecao_nao_entendida",
            acao="SELECIONAR_OPCAO",
            opcoes=session.opcoes_horarios,
            expirou=expirou,
        )

    session.horario_selecionado = selecao
    session.ultima_acao = "CONFIRMAR_AGENDAMENTO"
    save_session(session)

    return _montar_resposta(
        estado=estado,
        sucesso=True,
        resposta=_descrever_selecao(selecao),
        status="aguardando_confirmacao",
        acao="CONFIRMAR_AGENDAMENTO",
        opcoes=session.opcoes_horarios,
        opcao_selecionada=selecao,
        expirou=expirou,
    )


def _confirmar_agendamento(session: SessionContext, expirou: bool) -> dict:
    estado = _estado_de_session(session)

    if session.colaborador_id is None:
        return _montar_resposta(
            estado=estado,
            sucesso=False,
            resposta=RESPOSTA_COLABORADOR_NECESSARIO,
            status="aguardando_colaborador",
            acao="INFORMAR_COLABORADOR",
            opcao_selecionada=session.horario_selecionado,
            expirou=expirou,
        )

    opcao = session.horario_selecionado or {}
    state_inicial: AgendamentoState = {
        "colaborador_id": session.colaborador_id,
        "massoterapeuta_id": str(opcao["massoterapeuta_id"]),
        "horario_id": str(opcao["horario_id"]),
    }

    resultado = agendamento_graph.invoke(state_inicial)

    if resultado.get("sucesso") is True:
        session.opcoes_horarios = []
        session.horario_selecionado = None
        session.ultima_acao = "AGENDAMENTO_CONFIRMADO"
        save_session(session)

        return _montar_resposta(
            estado=estado,
            sucesso=True,
            resposta="Agendamento confirmado com sucesso.",
            status="agendamento_confirmado",
            acao="AGENDAMENTO_CONFIRMADO",
            agendamento=resultado["agendamento"],
            status_http=201,
            expirou=expirou,
        )

    if resultado.get("status_http") == 409:
        session.horario_selecionado = None
        session.ultima_acao = "CONSULTAR_DISPONIBILIDADE"
        save_session(session)

    return _montar_resposta(
        estado=estado,
        sucesso=False,
        resposta=resultado.get("mensagem", "Não foi possível confirmar o agendamento."),
        status="erro_confirmacao",
        acao="CONFIRMAR_AGENDAMENTO",
        opcao_selecionada=session.horario_selecionado,
        status_http=resultado.get("status_http", 500),
        expirou=expirou,
    )


def _cancelar_selecao(session: SessionContext, expirou: bool) -> dict:
    estado = _estado_de_session(session)
    session.horario_selecionado = None
    session.ultima_acao = "SELECIONAR_OPCAO"
    save_session(session)

    return _montar_resposta(
        estado=estado,
        sucesso=True,
        resposta="Seleção cancelada. Nenhum agendamento foi criado.",
        status="selecao_cancelada",
        acao="SELECAO_CANCELADA",
        opcoes=session.opcoes_horarios,
        expirou=expirou,
    )


def _atualizar_session(
    session: SessionContext,
    estado: OrchestratorState,
    opcoes: list[dict],
    selecao: dict | None,
) -> None:
    session.ultima_intencao = str(estado["intencao"])
    session.ultima_acao = estado["acao"]
    session.dados_extraidos = estado["dados_extraidos"]
    session.opcoes_horarios = opcoes
    session.horario_selecionado = selecao
    save_session(session)


def _estado_de_session(session: SessionContext) -> OrchestratorState:
    return {
        "session_id": session.session_id,
        "mensagem": "",
        "intencao": Intencao.AGENDAMENTO,
        "acao": session.ultima_acao or "SELECIONAR_OPCAO",
        "dados_extraidos": session.dados_extraidos,
        "dados_faltantes": [],
        "encaminhar_para": "agendamento",
    }


def _buscar_opcao_por_ordinal(opcoes: list[dict], texto: str) -> dict | None:
    indice = _extrair_ordinal(texto)

    if indice is None:
        return None

    return next((opcao for opcao in opcoes if opcao.get("indice") == indice), None)


def _buscar_opcao_por_horario(opcoes: list[dict], texto: str) -> dict | str | None:
    horario = _extrair_horario(texto)
    if horario is None:
        return None

    correspondencias = [
        opcao for opcao in opcoes if str(opcao.get("hora_inicio", "")).startswith(horario)
    ]

    if len(correspondencias) > 1:
        return "AMBIGUA"

    return correspondencias[0] if correspondencias else None


def _extrair_horario(texto: str) -> str | None:
    match = re.search(r"\b([01]?\d|2[0-3])h(?:([0-5]\d))?\b", texto)
    if match:
        hora = int(match.group(1))
        minuto = int(match.group(2) or "00")
        return f"{hora:02d}:{minuto:02d}"

    match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", texto)
    if match:
        hora = int(match.group(1))
        minuto = int(match.group(2))
        return f"{hora:02d}:{minuto:02d}"

    return None


def _parece_selecao(texto: str) -> bool:
    return _extrair_ordinal(texto) is not None or _extrair_horario(texto) is not None


def _extrair_ordinal(texto: str) -> int | None:
    match = re.search(r"\bopcao\s*(\d+)\b", texto)
    if match:
        return int(match.group(1))

    for ordinal, valor in ORDINAIS.items():
        if re.search(rf"\b{ordinal}\b", texto):
            return valor

    return None


def _eh_confirmacao(texto: str) -> bool:
    return texto in CONFIRMACOES


def _eh_negacao(texto: str) -> bool:
    return texto in NEGACOES


def _descrever_consulta(dados_extraidos: dict[str, str]) -> str:
    datas = {
        "HOJE": "hoje",
        "AMANHA": "amanhã",
    }
    periodos = {
        "MANHA": "de manhã",
        "TARDE": "à tarde",
        "NOITE": "à noite",
    }

    data = datas.get(dados_extraidos.get("referencia_data"), "a data informada")
    periodo = periodos.get(dados_extraidos.get("periodo"))

    if periodo is None:
        return data

    return f"{data} {periodo}"


def _descrever_selecao(opcao: dict) -> str:
    nome = opcao.get("massoterapeuta_nome") or "o massoterapeuta selecionado"
    return (
        f"Você selecionou {opcao.get('hora_inicio')} com {nome} em "
        f"{opcao.get('data')}. Deseja confirmar o agendamento?"
    )


def _montar_resposta(
    estado: OrchestratorState,
    sucesso: bool,
    resposta: str,
    status: str,
    acao: str | None = None,
    opcoes: list[dict] | None = None,
    opcao_selecionada: dict | None = None,
    agendamento: dict | None = None,
    status_http: int = 200,
    detalhes: dict | None = None,
    expirou: bool = False,
) -> dict:
    payload = {
        "session_id": estado["session_id"],
        "sucesso": sucesso,
        "intencao": estado["intencao"],
        "acao": acao if acao is not None else estado["acao"],
        "resposta": resposta,
        "dados_extraidos": estado["dados_extraidos"],
        "dados_faltantes": estado["dados_faltantes"],
        "status": status,
        "opcoes": opcoes or [],
        "opcao_selecionada": opcao_selecionada,
        "agendamento": agendamento,
        "status_http": status_http,
    }

    if detalhes is not None:
        payload["detalhes"] = detalhes

    if expirou:
        payload["detalhes"] = {
            **(payload.get("detalhes") or {}),
            "contexto_expirado": True,
        }

    return payload
