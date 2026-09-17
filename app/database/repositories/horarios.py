from datetime import date
from uuid import UUID

from app.database.supabase import get_supabase_client
from app.schemas.horario import HorarioCreate


def listar_horarios(
    apenas_disponiveis: bool | None = None,
    massoterapeuta_id: UUID | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> list[dict]:
    query = get_supabase_client().table("horarios_disponiveis").select("*")

    if apenas_disponiveis is True:
        query = query.eq("disponivel", True)
    elif apenas_disponiveis is False:
        query = query.eq("disponivel", False)

    if massoterapeuta_id is not None:
        query = query.eq("massoterapeuta_id", str(massoterapeuta_id))

    if data_inicio is not None:
        query = query.gte("data", data_inicio.isoformat())

    if data_fim is not None:
        query = query.lte("data", data_fim.isoformat())

    response = query.order("data").order("hora_inicio").execute()

    return response.data or []


def listar_horarios_disponiveis(a_partir_de: date | None = None) -> list[dict]:
    return listar_horarios(
        apenas_disponiveis=True,
        data_inicio=a_partir_de or date.today(),
    )


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
    """Mantido apenas como fallback.

    O caminho oficial de reserva passou a ser a RPC transacional
    criar_agendamento_transacional (ver database/rpc_agendamentos.sql).
    """
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
