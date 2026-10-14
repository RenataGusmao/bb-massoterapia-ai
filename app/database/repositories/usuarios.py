from uuid import UUID

from postgrest.exceptions import APIError

from app.database.supabase import get_supabase_client
from app.schemas.auth import UsuarioCreate


class UsuarioDuplicadoError(ValueError):
    pass


def buscar_usuario_por_email(email: str) -> dict | None:
    # ILIKE must treat valid email characters as literals, not wildcard patterns.
    email_literal = email.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    response = (
        get_supabase_client()
        .table("usuarios")
        .select("*")
        .ilike("email", email_literal)
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
    try:
        response = get_supabase_client().table("usuarios").insert(payload).execute()
    except APIError as exc:
        if exc.code == "23505":
            raise UsuarioDuplicadoError("Conta ou e-mail já cadastrado.") from exc
        raise
    return response.data[0]
