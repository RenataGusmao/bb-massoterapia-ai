from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from app.database.repositories.colaboradores import buscar_colaborador_por_id
from app.database.repositories.agendamentos import (
    atualizar_status_agendamento,
    buscar_agendamento_por_id,
    buscar_agendamentos_validos_no_intervalo,
    criar_agendamento_transacional,
)
from app.database.repositories.massoterapeutas import buscar_massoterapeuta_por_id
from app.database.repositories.horarios import buscar_horario_por_id
from app.schemas.agendamento import AgendamentoCreate, AgendamentoStatus

INTERVALO_MINIMO_DIAS = 15


@dataclass(frozen=True)
class AgendamentoContexto:
    colaborador: dict
    massoterapeuta: dict
    horario: dict
    data_agendamento: date


class ColaboradorNaoEncontradoError(ValueError):
    pass


class MassoterapeutaNaoEncontradoError(ValueError):
    pass


class MassoterapeutaInativoError(ValueError):
    pass


class HorarioNaoEncontradoError(ValueError):
    pass


class HorarioIndisponivelError(ValueError):
    pass


class HorarioMassoterapeutaInvalidoError(ValueError):
    pass


class AgendamentoNaoEncontradoError(ValueError):
    pass


class StatusInvalidoError(ValueError):
    pass


class IntervaloAgendamentoError(ValueError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


ERROS_RPC: dict[str, type[ValueError]] = {
    "colaborador_nao_encontrado": ColaboradorNaoEncontradoError,
    "massoterapeuta_nao_encontrado": MassoterapeutaNaoEncontradoError,
    "massoterapeuta_inativo": MassoterapeutaInativoError,
    "horario_nao_encontrado": HorarioNaoEncontradoError,
    "horario_indisponivel": HorarioIndisponivelError,
    "horario_massoterapeuta_invalido": HorarioMassoterapeutaInvalidoError,
    "agendamento_nao_encontrado": AgendamentoNaoEncontradoError,
    "status_invalido": StatusInvalidoError,
}


def _parse_data_agendamento(data_agendamento: date | str) -> date:
    if isinstance(data_agendamento, date):
        return data_agendamento

    return date.fromisoformat(data_agendamento)


def _levantar_erro_rpc(resultado: dict) -> None:
    erro = resultado.get("erro")

    if erro == "intervalo_minimo":
        raise IntervaloAgendamentoError(
            resultado.get("detalhe") or "Intervalo mínimo entre sessões não respeitado."
        )

    excecao = ERROS_RPC.get(erro or "")
    if excecao is not None:
        raise excecao(erro)

    raise RuntimeError(f"Falha não mapeada na RPC: {erro!r}")


def _validar_intervalo_minimo(colaborador_id: UUID, nova_data: date) -> None:
    janela = INTERVALO_MINIMO_DIAS - 1
    conflitos = buscar_agendamentos_validos_no_intervalo(
        colaborador_id=colaborador_id,
        data_inicio=nova_data - timedelta(days=janela),
        data_fim=nova_data + timedelta(days=janela),
    )

    if not conflitos:
        return

    datas_conflitantes = [
        _parse_data_agendamento(conflito["data_agendamento"]) for conflito in conflitos
    ]

    conflito_anterior = max(
        (data_conflito for data_conflito in datas_conflitantes if data_conflito <= nova_data),
        default=None,
    )

    if conflito_anterior is not None:
        proxima_data_permitida = conflito_anterior + timedelta(days=INTERVALO_MINIMO_DIAS)
        raise IntervaloAgendamentoError(
            f"Novo agendamento permitido somente a partir de {proxima_data_permitida.isoformat()}."
        )

    conflito_futuro = min(datas_conflitantes)
    data_limite_anterior = conflito_futuro - timedelta(days=INTERVALO_MINIMO_DIAS)
    proxima_data_permitida = conflito_futuro + timedelta(days=INTERVALO_MINIMO_DIAS)
    raise IntervaloAgendamentoError(
        "Já existe sessão válida em intervalo inferior a 15 dias. "
        f"Escolha uma data até {data_limite_anterior.isoformat()} "
        f"ou a partir de {proxima_data_permitida.isoformat()}."
    )


def validar_entidades_agendamento(agendamento: AgendamentoCreate) -> AgendamentoContexto:
    colaborador = buscar_colaborador_por_id(agendamento.colaborador_id)
    if colaborador is None:
        raise ColaboradorNaoEncontradoError("Colaborador não encontrado.")

    massoterapeuta = buscar_massoterapeuta_por_id(agendamento.massoterapeuta_id)
    if massoterapeuta is None:
        raise MassoterapeutaNaoEncontradoError("Massoterapeuta não encontrado.")

    if massoterapeuta.get("ativo") is False:
        raise MassoterapeutaInativoError("Massoterapeuta inativo.")

    horario = buscar_horario_por_id(agendamento.horario_id)

    if horario is None:
        raise HorarioNaoEncontradoError("Horário não encontrado.")

    if not horario.get("disponivel"):
        raise HorarioIndisponivelError("Horário indisponível.")

    if str(horario.get("massoterapeuta_id")) != str(agendamento.massoterapeuta_id):
        raise HorarioMassoterapeutaInvalidoError(
            "Horário não pertence ao massoterapeuta informado."
        )

    data_agendamento = _parse_data_agendamento(horario["data"])

    return AgendamentoContexto(
        colaborador=colaborador,
        massoterapeuta=massoterapeuta,
        horario=horario,
        data_agendamento=data_agendamento,
    )


def validar_intervalo_agendamento(
    agendamento: AgendamentoCreate,
    contexto: AgendamentoContexto,
) -> None:
    _validar_intervalo_minimo(agendamento.colaborador_id, contexto.data_agendamento)


def executar_criacao_agendamento(
    agendamento: AgendamentoCreate,
    contexto: AgendamentoContexto | None = None,
) -> dict:
    resultado = criar_agendamento_transacional(
        colaborador_id=agendamento.colaborador_id,
        massoterapeuta_id=agendamento.massoterapeuta_id,
        horario_id=agendamento.horario_id,
    )

    if resultado.get("sucesso") is not True:
        _levantar_erro_rpc(resultado)

    return resultado["agendamento"]


def criar_agendamento_para_horario(agendamento: AgendamentoCreate) -> dict:
    contexto = validar_entidades_agendamento(agendamento)
    validar_intervalo_agendamento(agendamento, contexto)
    return executar_criacao_agendamento(agendamento, contexto)


def alterar_status_agendamento(agendamento_id: UUID, status: AgendamentoStatus) -> dict:
    if buscar_agendamento_por_id(agendamento_id) is None:
        raise AgendamentoNaoEncontradoError("Agendamento não encontrado.")

    resultado = atualizar_status_agendamento(agendamento_id, status.value)

    if resultado.get("sucesso") is not True:
        _levantar_erro_rpc(resultado)

    return resultado["agendamento"]
