from uuid import UUID

from app.database.supabase import get_supabase_client
from app.schemas.massoterapeuta import MassoterapeutaCreate


def listar_massoterapeutas() -> list[dict]:
    response = (
        get_supabase_client()
        .table("massoterapeutas")
        .select("*")
        .order("nome")
        .execute()
    )

    return response.data or []


def buscar_massoterapeuta_por_id(massoterapeuta_id: UUID) -> dict | None:
    response = (
        get_supabase_client()
        .table("massoterapeutas")
        .select("*")
        .eq("id", str(massoterapeuta_id))
        .limit(1)
        .execute()
    )

    massoterapeutas = response.data or []
    return massoterapeutas[0] if massoterapeutas else None


def criar_massoterapeuta(massoterapeuta: MassoterapeutaCreate) -> dict:
    payload = massoterapeuta.model_dump(exclude_none=True)
    response = (
        get_supabase_client()
        .table("massoterapeutas")
        .insert(payload)
        .execute()
    )

    return response.data[0]
