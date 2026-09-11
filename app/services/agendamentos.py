from app.database.repositories.colaboradores import buscar_colaborador_por_id
from app.database.repositories.agendamentos import criar_agendamento
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
