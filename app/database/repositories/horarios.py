from uuid import UUID

from app.database.supabase import get_supabase_client
from app.schemas.horario import HorarioCreate


def listar_horarios() -> list[dict]:
    response = (
        get_supabase_client()
        .table("horarios_disponiveis")
        .select("*")
        .order("data")
        .order("hora_inicio")
        .execute()
    )

    return response.data or []


def listar_horarios_disponiveis() -> list[dict]:
    response = (
        get_supabase_client()
        .table("horarios_disponiveis")
        .select("*")
        .eq("disponivel", True)
        .order("data")
        .order("hora_inicio")
        .execute()
    )

    return response.data or []


def buscar_horario_por_id(horario_id: UUID) -> dict | None:
    response = (
        get_supabase_client()
        .table("horarios_disponiveis")
        .select("*")
        .eq("id", str(horario_id))
        .limit(1)
        .execute()
    )

    horarios = response.data or []
    return horarios[0] if horarios else None


def criar_horario(horario: HorarioCreate) -> dict:
    payload = horario.model_dump(mode="json", exclude_none=True)
    response = (
        get_supabase_client()
        .table("horarios_disponiveis")
        .insert(payload)
        .execute()
    )

    return response.data[0]


def atualizar_disponibilidade_horario(horario_id: UUID, disponivel: bool) -> dict:
    response = (
        get_supabase_client()
        .table("horarios_disponiveis")
        .update({"disponivel": disponivel})
        .eq("id", str(horario_id))
        .execute()
    )

    return response.data[0]


def reservar_horario_disponivel(horario_id: UUID) -> dict | None:
    response = (
        get_supabase_client()
        .table("horarios_disponiveis")
        .update({"disponivel": False})
        .eq("id", str(horario_id))
        .eq("disponivel", True)
        .execute()
    )

    horarios = response.data or []
    return horarios[0] if horarios else None
