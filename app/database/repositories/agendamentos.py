from uuid import UUID
from datetime import date

from app.database.supabase import get_supabase_client


def listar_agendamentos() -> list[dict]:
    response = (
        get_supabase_client()
        .table("agendamentos")
        .select("*")
        .order("data_agendamento", desc=True)
        .order("hora_inicio", desc=True)
        .execute()
    )

    return response.data or []


def buscar_agendamento_por_id(agendamento_id: UUID) -> dict | None:
    response = (
        get_supabase_client()
        .table("agendamentos")
        .select("*")
        .eq("id", str(agendamento_id))
        .limit(1)
        .execute()
    )

    agendamentos = response.data or []
    return agendamentos[0] if agendamentos else None


def buscar_ultimo_agendamento_valido(colaborador_id: UUID) -> dict | None:
    response = (
        get_supabase_client()
        .table("agendamentos")
        .select("*")
        .eq("colaborador_id", str(colaborador_id))
        .in_("status", ["AGENDADO", "CONCLUIDO"])
        .order("data_agendamento", desc=True)
        .limit(1)
        .execute()
    )

    agendamentos = response.data or []
    return agendamentos[0] if agendamentos else None


def buscar_agendamentos_validos_no_intervalo(
    colaborador_id: UUID,
    data_inicio: date,
    data_fim: date,
) -> list[dict]:
    response = (
        get_supabase_client()
        .table("agendamentos")
        .select("*")
        .eq("colaborador_id", str(colaborador_id))
        .in_("status", ["AGENDADO", "CONCLUIDO"])
        .gte("data_agendamento", data_inicio.isoformat())
        .lte("data_agendamento", data_fim.isoformat())
        .order("data_agendamento")
        .execute()
    )

    return response.data or []


def criar_agendamento(payload: dict) -> dict:
    response = (
        get_supabase_client()
        .table("agendamentos")
        .insert(payload)
        .execute()
    )

    return response.data[0]


def criar_agendamento_transacional(
    colaborador_id: UUID,
    massoterapeuta_id: UUID,
    horario_id: UUID,
) -> dict:
    """Chama a funcao RPC do Postgres.

    Validacao, reserva do horario e insert acontecem em uma unica transacao,
    entao nao existe mais a janela em que o horario fica travado sem agendamento.
    """
    response = (
        get_supabase_client()
        .rpc(
            "criar_agendamento_transacional",
            {
                "p_colaborador_id": str(colaborador_id),
                "p_massoterapeuta_id": str(massoterapeuta_id),
                "p_horario_id": str(horario_id),
            },
        )
        .execute()
    )

    return response.data or {}


def atualizar_status_agendamento(agendamento_id: UUID, status: str) -> dict:
    """Muda o status e, no caso de CANCELADO, devolve o horario para a agenda."""
    response = (
        get_supabase_client()
        .rpc(
            "atualizar_status_agendamento",
            {
                "p_agendamento_id": str(agendamento_id),
                "p_status": status,
            },
        )
        .execute()
    )

    return response.data or {}
