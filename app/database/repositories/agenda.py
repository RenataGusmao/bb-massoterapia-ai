from datetime import date
from uuid import UUID

from postgrest.exceptions import APIError

from app.database.supabase import get_supabase_client
from app.schemas.agenda import AgendaResponse, BloqueioCreate, BloqueioResponse


class AgendaConflitoError(ValueError):
    pass


def listar_bloqueios(inicio: date, fim: date) -> list[BloqueioResponse]:
    dados = get_supabase_client().table("bloqueios_agenda").select(
        "id,data,hora_inicio,hora_fim,motivo,ativo"
    ).gte("data", inicio.isoformat()).lte("data", fim.isoformat()).order("data").execute().data
    return [BloqueioResponse.model_validate(item) for item in (dados or [])]


def consultar_agenda(inicio: date, fim: date) -> AgendaResponse:
    dados = get_supabase_client().rpc("consultar_agenda_leitura", {
        "p_inicio": inicio.isoformat(), "p_fim": fim.isoformat(),
    }).execute().data
    return AgendaResponse.model_validate(dados)


def criar_bloqueio(admin_id: UUID, payload: BloqueioCreate) -> BloqueioResponse:
    try:
        dados = get_supabase_client().rpc("registrar_bloqueio_agenda", {
            "p_admin_id": str(admin_id), "p_id": str(payload.chave_idempotencia),
            "p_data": payload.data.isoformat(), "p_inicio": payload.hora_inicio.isoformat() if payload.hora_inicio else None,
            "p_fim": payload.hora_fim.isoformat() if payload.hora_fim else None, "p_motivo": payload.motivo,
        }).execute().data
    except APIError as exc:
        if exc.code in {"22023", "23505"}:
            raise AgendaConflitoError("Chave ou dados do bloqueio em conflito.") from exc
        raise
    return BloqueioResponse.model_validate(dados)


def desativar_bloqueio(admin_id: UUID, bloqueio_id: UUID) -> bool:
    return bool(get_supabase_client().rpc("desativar_bloqueio_agenda", {
        "p_admin_id": str(admin_id), "p_id": str(bloqueio_id),
    }).execute().data)
