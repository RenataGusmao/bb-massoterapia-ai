from uuid import UUID

from app.database.supabase import get_supabase_client
from app.schemas.auth import UsuarioCreate


def buscar_usuario_por_email(email: str) -> dict | None:
    response = (
        get_supabase_client()
        .table("usuarios")
        .select("*")
        .ilike("email", email.strip())
        .limit(1)
        .execute()
    )

    usuarios = response.data or []
    return usuarios[0] if usuarios else None


def buscar_usuario_por_id(usuario_id: UUID) -> dict | None:
    response = (
        get_supabase_client()
        .table("usuarios")
        .select("*")
        .eq("id", str(usuario_id))
        .limit(1)
        .execute()
    )

    usuarios = response.data or []
    return usuarios[0] if usuarios else None


def buscar_usuario_por_colaborador_id(colaborador_id: UUID) -> dict | None:
    response = (
        get_supabase_client()
        .table("usuarios")
        .select("*")
        .eq("colaborador_id", str(colaborador_id))
        .limit(1)
        .execute()
    )

    usuarios = response.data or []
    return usuarios[0] if usuarios else None


def criar_usuario(usuario: UsuarioCreate) -> dict:
    payload = usuario.model_dump(mode="json")
    response = get_supabase_client().table("usuarios").insert(payload).execute()
    return response.data[0]
