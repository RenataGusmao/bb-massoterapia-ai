from datetime import date, time
from uuid import UUID

from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.database.supabase import get_supabase_client
from app.core.datas import agora_local, data_local
from app.schemas.horario import DisponibilidadeRPCResponse, HorarioCreate


class DisponibilidadeError(ValueError):
    def __init__(self, codigo: str) -> None:
        self.codigo = codigo
        super().__init__(codigo)


def listar_horarios(
    apenas_disponiveis: bool | None = None,
    massoterapeuta_id: UUID | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    dia: date | None = None,
) -> list[dict]:
    query = get_supabase_client().table("horarios_disponiveis").select("*")

    if apenas_disponiveis is True:
        query = query.eq("disponivel", True)
        agora = agora_local()
        hoje = agora.date().isoformat()
        hora = agora.time().isoformat()
        query = query.or_(f"data.gt.{hoje},and(data.eq.{hoje},hora_inicio.gt.{hora})")
    elif apenas_disponiveis is False:
        query = query.eq("disponivel", False)

    if massoterapeuta_id is not None:
        query = query.eq("massoterapeuta_id", str(massoterapeuta_id))

    if data_inicio is not None:
        query = query.gte("data", data_inicio.isoformat())

    if data_fim is not None:
        query = query.lte("data", data_fim.isoformat())
    if dia is not None:
        query = query.eq("data", dia.isoformat())

    response = query.order("data").order("hora_inicio").execute()

    return response.data or []


def listar_horarios_disponiveis(a_partir_de: date | None = None) -> list[dict]:
    return listar_horarios(
        apenas_disponiveis=True,
        data_inicio=a_partir_de or data_local(),
    )


def buscar_horarios_disponiveis(
    data_consulta: date,
    hora_inicio: time | None = None,
    hora_fim: time | None = None,
) -> list[dict]:
    query = (
        get_supabase_client()
        .table("horarios_disponiveis")
        .select("*")
        .eq("disponivel", True)
        .eq("data", data_consulta.isoformat())
    )

    if hora_inicio is not None:
        query = query.gte("hora_inicio", hora_inicio.isoformat())

    if hora_fim is not None:
        query = query.lte("hora_inicio", hora_fim.isoformat())

    response = query.order("hora_inicio").execute()

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


def criar_horario(horario: HorarioCreate) -> DisponibilidadeRPCResponse:
    parametros = {
        "p_chave_idempotencia": str(horario.chave_idempotencia),
        "p_data": horario.data.isoformat(),
        "p_hora_inicio": horario.hora_inicio.isoformat(),
        "p_hora_fim": horario.hora_fim.isoformat(),
        "p_capacidade": horario.capacidade,
        "p_massoterapeuta_id": None,
        "p_disponivel": horario.disponivel,
    }
    try:
        response = get_supabase_client().rpc("criar_disponibilidade_transacional", parametros).execute()
    except APIError as exc:
        if exc.code in {"23505", "23P01", "40001", "40P01", "55P03"}:
            raise DisponibilidadeError("conflito_disponibilidade") from exc
        raise
    try:
        resultado = DisponibilidadeRPCResponse.model_validate(response.data)
    except ValidationError as exc:
        raise RuntimeError("Contrato inválido da RPC de disponibilidade.") from exc
    if not resultado.sucesso:
        raise DisponibilidadeError(resultado.erro)
    return resultado


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
