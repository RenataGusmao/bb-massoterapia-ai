from datetime import date

from pydantic import ValidationError

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
        "mensagem": "Solicitação recebida.",
        "agendamento": None,
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
        "mensagem": "Entidades validadas.",
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
        "mensagem": "Intervalo permitido.",
        "erro": None,
    }


def executar_agendamento(state: AgendamentoState) -> AgendamentoState:
    try:
        agendamento = _criar_schema(state)
        contexto = _criar_contexto(state)
        resultado = executar_criacao_agendamento(agendamento, contexto)
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
        "mensagem": "Agendamento realizado com sucesso.",
        "agendamento": resultado,
        "erro": None,
    }


def responder_sucesso(state: AgendamentoState) -> AgendamentoState:
    return {
        **state,
        "sucesso": True,
        "status_http": 201,
        "mensagem": "Agendamento realizado com sucesso.",
    }


def responder_erro(state: AgendamentoState) -> AgendamentoState:
    return {
        **state,
        "sucesso": False,
        "status_http": state.get("status_http", 500),
        "mensagem": state.get("mensagem") or "Não foi possível realizar o agendamento.",
        "agendamento": None,
    }


def _criar_schema(state: AgendamentoState) -> AgendamentoCreate:
    return AgendamentoCreate(
        colaborador_id=state["colaborador_id"],
        massoterapeuta_id=state["massoterapeuta_id"],
        horario_id=state["horario_id"],
    )


def _criar_contexto(state: AgendamentoState) -> AgendamentoContexto:
    return AgendamentoContexto(
        colaborador=state["colaborador"] or {},
        massoterapeuta=state["massoterapeuta"] or {},
        horario=state["horario"] or {},
        data_agendamento=date.fromisoformat(state["data_agendamento"] or ""),
    )


def _erro(
    state: AgendamentoState,
    status_http: int,
    mensagem: str,
    erro: str,
) -> AgendamentoState:
    return {
        **state,
        "sucesso": False,
        "status_http": status_http,
        "mensagem": mensagem,
        "agendamento": None,
        "erro": erro,
    }
