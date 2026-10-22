from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from app.database.repositories.colaboradores import buscar_colaborador_por_id
from app.database.repositories.agendamentos import (
    AgendamentoRPCError,
    atualizar_status_agendamento,
    buscar_agendamentos_validos_no_intervalo,
    criar_agendamento_transacional,
)
from app.database.repositories.massoterapeutas import buscar_massoterapeuta_por_id
from app.database.repositories.horarios import (
    buscar_horario_por_id,
)
from app.schemas.agendamento import AgendamentoCreate, AgendamentoStatus
from app.services import agenda_automatica


@dataclass(frozen=True)
class AgendamentoContexto:
    colaborador: dict
    massoterapeuta: dict
    horario: dict
    data_agendamento: date


class AgendamentoRegraError(ValueError):
    status_http = 409
    codigo = "conflito_agendamento"


class AgendaNaoSincronizadaError(AgendamentoRegraError):
    status_http = 503
    codigo = "agenda_nao_pronta"


class ColaboradorNaoEncontradoError(AgendamentoRegraError):
    status_http = 404
    codigo = "colaborador_nao_encontrado"


class ColaboradorInativoError(AgendamentoRegraError):
    codigo = "colaborador_inativo"


class MassoterapeutaNaoEncontradoError(AgendamentoRegraError):
    status_http = 404
    codigo = "massoterapeuta_nao_encontrado"


class MassoterapeutaInativoError(AgendamentoRegraError):
    codigo = "massoterapeuta_inativo"


class HorarioNaoEncontradoError(AgendamentoRegraError):
    status_http = 404
    codigo = "horario_nao_encontrado"


class HorarioIndisponivelError(AgendamentoRegraError):
    codigo = "horario_indisponivel"


class HorarioPassadoError(AgendamentoRegraError):
    codigo = "horario_passado"


class HorarioMassoterapeutaInvalidoError(AgendamentoRegraError):
    status_http = 422
    codigo = "horario_massoterapeuta_invalido"


class AgendamentoNaoEncontradoError(AgendamentoRegraError):
    status_http = 404
    codigo = "agendamento_nao_encontrado"


class StatusInvalidoError(AgendamentoRegraError):
    status_http = 422
    codigo = "status_invalido"


class TransicaoStatusInvalidaError(AgendamentoRegraError):
    codigo = "transicao_invalida"


class AgendamentoConcorrenteError(AgendamentoRegraError):
    codigo = "conflito_concorrente"


class IntervaloAgendamentoError(AgendamentoRegraError):
    codigo = "intervalo_minimo"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def _traduzir_erro_rpc(erro: AgendamentoRPCError) -> AgendamentoRegraError:
    erros = {
        "colaborador_nao_encontrado": (ColaboradorNaoEncontradoError, "Colaborador não encontrado."),
        "colaborador_inativo": (ColaboradorInativoError, "Colaborador está inativo."),
        "massoterapeuta_nao_encontrado": (MassoterapeutaNaoEncontradoError, "Massoterapeuta não encontrado."),
        "massoterapeuta_inativo": (MassoterapeutaInativoError, "Massoterapeuta está inativo."),
        "horario_nao_encontrado": (HorarioNaoEncontradoError, "Horário não encontrado."),
        "horario_indisponivel": (HorarioIndisponivelError, "Horário já está ocupado."),
        "horario_passado": (HorarioPassadoError, "Horário já passou."),
        "horario_massoterapeuta_invalido": (HorarioMassoterapeutaInvalidoError, "Horário não pertence ao massoterapeuta informado."),
        "intervalo_minimo": (IntervaloAgendamentoError, "Já existe sessão válida em intervalo inferior a 15 dias."),
        "agendamento_nao_encontrado": (AgendamentoNaoEncontradoError, "Agendamento não encontrado."),
        "status_invalido": (StatusInvalidoError, "Status inválido."),
        "transicao_invalida": (TransicaoStatusInvalidaError, "Transição de status não permitida."),
        "conflito_concorrente": (AgendamentoConcorrenteError, "Conflito concorrente. Atualize a agenda e tente novamente."),
    }
    if erro.codigo not in erros:
        raise RuntimeError("Código de erro inesperado da RPC.") from erro
    classe, mensagem = erros[erro.codigo]
    return classe(erro.detalhe or mensagem)


def _parse_data_agendamento(data_agendamento: date | str) -> date:
    if isinstance(data_agendamento, date):
        return data_agendamento

    return date.fromisoformat(data_agendamento)


def _validar_intervalo_minimo(colaborador_id: UUID, nova_data: date) -> None:
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


def validar_entidades_agendamento(agendamento: AgendamentoCreate) -> AgendamentoContexto:
    colaborador = buscar_colaborador_por_id(agendamento.colaborador_id)
    if colaborador is None:
        raise ColaboradorNaoEncontradoError("Colaborador não encontrado.")
    if not colaborador.get("ativo", False):
        raise ColaboradorInativoError("Colaborador está inativo.")

    horario = buscar_horario_por_id(agendamento.horario_id)

    if horario is None:
        raise HorarioNaoEncontradoError("Horário não encontrado.")

    if not horario.get("disponivel"):
        raise HorarioIndisponivelError("Horário indisponível.")

    profissional_id = horario.get("massoterapeuta_id")
    massoterapeuta = {}
    if profissional_id:
        massoterapeuta = buscar_massoterapeuta_por_id(UUID(str(profissional_id)))
        if massoterapeuta is None:
            raise MassoterapeutaNaoEncontradoError("Massoterapeuta não encontrado.")
        if massoterapeuta.get("ativo") is False:
            raise MassoterapeutaInativoError("Massoterapeuta inativo.")

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
    # The graph's context is advisory; the RPC revalidates under database locks.
    try:
        agenda_automatica.exigir_agenda_pronta()
    except agenda_automatica.AgendaNaoProntaError as exc:
        raise AgendaNaoSincronizadaError(str(exc)) from exc
    try:
        return criar_agendamento_transacional(
            agendamento.colaborador_id, None, agendamento.horario_id
        )

    except AgendamentoRPCError as exc:
        raise _traduzir_erro_rpc(exc) from exc


def criar_agendamento_para_horario(agendamento: AgendamentoCreate) -> dict:
    return executar_criacao_agendamento(agendamento)


def alterar_status_agendamento(agendamento_id: UUID, novo_status: AgendamentoStatus) -> dict:
    """Muda o status de um agendamento (ex.: cancelar, concluir, marcar falta).

    A validação definitiva e a liberação do horário (no caso de cancelamento)
    acontecem dentro da RPC do Postgres, de forma transacional.
    """
    status_valor = (
        novo_status.value if isinstance(novo_status, AgendamentoStatus) else str(novo_status)
    )

    valores_validos = {item.value for item in AgendamentoStatus}
    if status_valor not in valores_validos:
        raise StatusInvalidoError(f"Status inválido: {status_valor}.")

    try:
        return atualizar_status_agendamento(agendamento_id, status_valor)
    except AgendamentoRPCError as exc:
        raise _traduzir_erro_rpc(exc) from exc
