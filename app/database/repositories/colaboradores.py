from uuid import UUID

from app.database.supabase import get_supabase_client
from app.schemas.colaborador import ColaboradorCreate


def listar_colaboradores() -> list[dict]:
    response = (
        get_supabase_client()
        .table("colaboradores")
        .select("*")
        .order("criado_em", desc=True)
        .execute()
    )

    return response.data or []


def buscar_colaborador_por_id(colaborador_id: UUID) -> dict | None:
    response = (
        get_supabase_client()
        .table("colaboradores")
        .select("*")
        .eq("id", str(colaborador_id))
        .limit(1)
        .execute()
    )

    colaboradores = response.data or []
    return colaboradores[0] if colaboradores else None


def criar_colaborador(colaborador: ColaboradorCreate) -> dict:
    payload = colaborador.model_dump(exclude_none=True)
    response = (
        get_supabase_client()
        .table("colaboradores")
        .insert(payload)
        .execute()
    )

    return response.data[0]
