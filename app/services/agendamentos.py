from datetime import date, timedelta

from app.database.repositories.colaboradores import buscar_colaborador_por_id
from app.database.repositories.agendamentos import (
    buscar_agendamentos_validos_no_intervalo,
    criar_agendamento,
)
from app.database.repositories.massoterapeutas import buscar_massoterapeuta_por_id
from app.database.repositories.horarios import (
    atualizar_disponibilidade_horario,
    buscar_horario_por_id,
    reservar_horario_disponivel,
)
from app.schemas.agendamento import AgendamentoCreate, AgendamentoStatus


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


class IntervaloAgendamentoError(ValueError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def _parse_data_agendamento(data_agendamento: date | str) -> date:
    if isinstance(data_agendamento, date):
        return data_agendamento

    return date.fromisoformat(data_agendamento)


def _validar_intervalo_minimo(colaborador_id, nova_data: date) -> None:
    data_inicio = nova_data - timedelta(days=14)
    data_fim = nova_data + timedelta(days=14)
    conflitos = buscar_agendamentos_validos_no_intervalo(
        colaborador_id=colaborador_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
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
        proxima_data_permitida = conflito_anterior + timedelta(days=15)
        raise IntervaloAgendamentoError(
            f"Novo agendamento permitido somente a partir de {proxima_data_permitida.isoformat()}."
        )

    conflito_futuro = min(datas_conflitantes)
    data_limite_anterior = conflito_futuro - timedelta(days=15)
    proxima_data_permitida = conflito_futuro + timedelta(days=15)
    raise IntervaloAgendamentoError(
        "Já existe sessão válida em intervalo inferior a 15 dias. "
        f"Escolha uma data até {data_limite_anterior.isoformat()} "
        f"ou a partir de {proxima_data_permitida.isoformat()}."
    )


def criar_agendamento_para_horario(agendamento: AgendamentoCreate) -> dict:
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
    _validar_intervalo_minimo(agendamento.colaborador_id, data_agendamento)

    horario_reservado = reservar_horario_disponivel(agendamento.horario_id)
    if horario_reservado is None:
        raise HorarioIndisponivelError("Horário indisponível.")

    payload = {
        "colaborador_id": str(agendamento.colaborador_id),
        "massoterapeuta_id": str(agendamento.massoterapeuta_id),
        "horario_id": str(agendamento.horario_id),
        "data_agendamento": horario_reservado["data"],
        "hora_inicio": horario_reservado["hora_inicio"],
        "hora_fim": horario_reservado["hora_fim"],
        "status": AgendamentoStatus.AGENDADO.value,
    }

    try:
        return criar_agendamento(payload)
    except Exception:
        try:
            atualizar_disponibilidade_horario(agendamento.horario_id, True)
        except Exception:
            pass
        raise
