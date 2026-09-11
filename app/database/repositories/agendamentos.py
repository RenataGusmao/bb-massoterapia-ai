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
