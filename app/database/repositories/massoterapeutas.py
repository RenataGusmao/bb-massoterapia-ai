from app.database.supabase import get_supabase_client


def listar_massoterapeutas() -> list[dict]:
    response = (
        get_supabase_client()
        .table("massoterapeutas")
        .select("*")
        .eq("ativo", True)
        .order("nome")
        .execute()
    )

    return response.data or []
