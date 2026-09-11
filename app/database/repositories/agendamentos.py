from uuid import UUID

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


def criar_agendamento(payload: dict) -> dict:
    response = (
        get_supabase_client()
        .table("agendamentos")
        .insert(payload)
        .execute()
    )

    return response.data[0]
