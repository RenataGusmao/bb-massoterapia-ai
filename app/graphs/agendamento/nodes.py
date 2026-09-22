from datetime import date

from pydantic import ValidationError

from app.agents.interpretador import InterpretacaoError, interpretar_mensagem
from app.database.supabase import SupabaseConfigurationError
from app.graphs.agendamento.state import AgendamentoState
from app.schemas.agendamento import AgendamentoCreate
from app.services.agendamentos import (
    AgendamentoContexto,
    ColaboradorNaoEncontradoError,
    HorarioIndisponivelError,
    HorarioMassoterapeutaInvalidoError,
    HorarioNaoEncontradoError,
    IntervaloAgendamentoError,
    MassoterapeutaInativoError,
    MassoterapeutaNaoEncontradoError,
    executar_criacao_agendamento,
    validar_entidades_agendamento,
    validar_intervalo_agendamento,
)


def receber_solicitacao(state: AgendamentoState) -> AgendamentoState:
    return {
        **state,
        "colaborador": None,
        "massoterapeuta": None,
        "horario": None,
        "data_agendamento": None,
        "entidades_validas": False,
        "intervalo_permitido": False,
        "sucesso": False,
        "status_http": 202,
        "mensagem_resposta": "Solicitação recebida.",
        "agendamento": None,
        "erro": None,
        "sugestoes": None,
    }


def interpretar_solicitacao(state: AgendamentoState) -> AgendamentoState:
    """Node de IA.

    So entra em acao quando o cliente NAO mandou os ids. Se eles ja vieram
    prontos, o node apenas repassa o estado e nenhuma chamada ao modelo
    acontece, o que economiza cota do free tier.
    """
    if state.get("horario_id") and state.get("massoterapeuta_id"):
        return {
            **state,
            "mensagem_resposta": "Solicitação estruturada, interpretação dispensada.",
        }

    mensagem = (state.get("mensagem") or "").strip()

    if not mensagem:
        return _erro(
            state,
            422,
            "Informe horario_id e massoterapeuta_id ou uma mensagem em texto.",
            "solicitacao_incompleta",
        )

    try:
        interpretacao = interpretar_mensagem(mensagem)
    except InterpretacaoError as exc:
        return _erro(state, 503, str(exc), "interpretador_indisponivel")
    except SupabaseConfigurationError:
        return _erro(state, 503, "Banco de dados não configurado.", "banco_nao_configurado")
    except Exception:
        return _erro(state, 502, "Falha ao consultar o modelo de linguagem.", "erro_llm")

    if not interpretacao.escolhido:
        return _erro(
            state,
            422,
            interpretacao.motivo or "Não foi possível entender o pedido.",
            "interpretacao_inconclusiva",
            sugestoes=interpretacao.sugestoes,
        )

    return {
        **state,
        "horario_id": interpretacao.horario_id,
        "massoterapeuta_id": interpretacao.massoterapeuta_id,
        "interpretacao": interpretacao.justificativa,
        "status_http": 200,
        "mensagem_resposta": "Pedido interpretado.",
        "erro": None,
    }


def validar_entidades(state: AgendamentoState) -> AgendamentoState:
    try:
        agendamento = _criar_schema(state)
        contexto = validar_entidades_agendamento(agendamento)
    except ValidationError:
        return _erro(state, 422, "Dados inválidos para agendamento.", "payload_invalido")
    except ColaboradorNaoEncontradoError:
        return _erro(state, 404, "Colaborador não encontrado.", "colaborador_nao_encontrado")
    except MassoterapeutaNaoEncontradoError:
        return _erro(
            state,
            404,
            "Massoterapeuta não encontrado.",
            "massoterapeuta_nao_encontrado",
        )
    except MassoterapeutaInativoError:
        return _erro(state, 409, "Massoterapeuta está inativo.", "massoterapeuta_inativo")
    except HorarioNaoEncontradoError:
        return _erro(state, 404, "Horário não encontrado.", "horario_nao_encontrado")
    except HorarioIndisponivelError:
        return _erro(state, 409, "Horário já está ocupado.", "horario_indisponivel")
    except HorarioMassoterapeutaInvalidoError:
        return _erro(
            state,
            422,
            "Horário não pertence ao massoterapeuta informado.",
            "horario_massoterapeuta_invalido",
        )
    except SupabaseConfigurationError:
        return _erro(state, 503, "Banco de dados não configurado.", "banco_nao_configurado")
    except Exception:
        return _erro(state, 500, "Erro ao validar agendamento.", "erro_interno")

    return {
        **state,
        "colaborador": contexto.colaborador,
        "massoterapeuta": contexto.massoterapeuta,
        "horario": contexto.horario,
        "data_agendamento": contexto.data_agendamento.isoformat(),
        "entidades_validas": True,
        "status_http": 200,
        "mensagem_resposta": "Entidades validadas.",
        "erro": None,
    }


def validar_intervalo(state: AgendamentoState) -> AgendamentoState:
    try:
        agendamento = _criar_schema(state)
        contexto = _criar_contexto(state)
        validar_intervalo_agendamento(agendamento, contexto)
    except IntervaloAgendamentoError as exc:
        return _erro(state, 409, exc.detail, "intervalo_minimo")
    except SupabaseConfigurationError:
        return _erro(state, 503, "Banco de dados não configurado.", "banco_nao_configurado")
    except Exception:
        return _erro(state, 500, "Erro ao validar intervalo.", "erro_interno")

    return {
        **state,
        "intervalo_permitido": True,
        "status_http": 200,
        "mensagem_resposta": "Intervalo permitido.",
        "erro": None,
    }


def executar_agendamento(state: AgendamentoState) -> AgendamentoState:
    try:
        agendamento = _criar_schema(state)
        contexto = _criar_contexto(state)
        resultado = executar_criacao_agendamento(agendamento, contexto)
    except IntervaloAgendamentoError as exc:
        return _erro(state, 409, exc.detail, "intervalo_minimo")
    except HorarioIndisponivelError:
        return _erro(state, 409, "Horário já está ocupado.", "horario_indisponivel")
    except SupabaseConfigurationError:
        return _erro(state, 503, "Banco de dados não configurado.", "banco_nao_configurado")
    except Exception:
        return _erro(state, 500, "Erro ao criar agendamento.", "erro_interno")

    return {
        **state,
        "sucesso": True,
        "status_http": 201,
        "mensagem_resposta": "Agendamento realizado com sucesso.",
        "agendamento": resultado,
        "erro": None,
    }


def responder_sucesso(state: AgendamentoState) -> AgendamentoState:
    return {
        **state,
        "sucesso": True,
        "status_http": 201,
        "mensagem_resposta": "Agendamento realizado com sucesso.",
    }


def responder_erro(state: AgendamentoState) -> AgendamentoState:
    return {
        **state,
        "sucesso": False,
        "status_http": state.get("status_http", 500),
        "mensagem_resposta": state.get("mensagem_resposta")
        or "Não foi possível realizar o agendamento.",
        "agendamento": None,
    }


def _criar_schema(state: AgendamentoState) -> AgendamentoCreate:
    return AgendamentoCreate(
        colaborador_id=state["colaborador_id"],
        massoterapeuta_id=state.get("massoterapeuta_id"),
        horario_id=state.get("horario_id"),
    )


def _criar_contexto(state: AgendamentoState) -> AgendamentoContexto:
    return AgendamentoContexto(
        colaborador=state.get("colaborador") or {},
        massoterapeuta=state.get("massoterapeuta") or {},
        horario=state.get("horario") or {},
        data_agendamento=date.fromisoformat(state.get("data_agendamento") or ""),
    )


def _erro(
    state: AgendamentoState,
    status_http: int,
    mensagem: str,
    erro: str,
    sugestoes: list[dict] | None = None,
) -> AgendamentoState:
    return {
        **state,
        "sucesso": False,
        "status_http": status_http,
        "mensagem_resposta": mensagem,
        "agendamento": None,
        "erro": erro,
        "sugestoes": sugestoes,
    }