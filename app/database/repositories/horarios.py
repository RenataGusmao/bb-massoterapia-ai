from app.database.supabase import get_supabase_client


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
