from datetime import date
from uuid import UUID

from postgrest.exceptions import APIError

from app.database.repositories.usuarios import UsuarioDuplicadoError
from app.database.supabase import get_supabase_client
from app.schemas.agenda import AgendaResponse, TerceirizadaContaCreate
from app.schemas.auth import UsuarioAutenticado
from app.schemas.agendamento import AgendamentoStatus


class EscopoInvalidoError(ValueError):
    pass


class AcessoInstitucionalNegadoError(PermissionError):
    pass


def provisionar_terceirizada(
    admin_id: UUID, payload: TerceirizadaContaCreate, senha_hash: str,
) -> dict:
    try:
        resposta = get_supabase_client().rpc("provisionar_terceirizada", {
            "p_admin_id": str(admin_id), "p_email": str(payload.email),
            "p_senha_hash": senha_hash,
            "p_disponibilidade_ids": [str(i) for i in payload.disponibilidade_ids],
        }).execute()
    except APIError as exc:
        if exc.code == "23505":
            raise UsuarioDuplicadoError("Conta ou e-mail ja cadastrado.") from exc
        if exc.code == "22023":
            raise EscopoInvalidoError("Lotes autorizados inexistentes ou invalidos.") from exc
        if exc.code == "42501":
            raise AcessoInstitucionalNegadoError("Acesso institucional negado.") from exc
        raise
    return UsuarioAutenticado.model_validate(resposta.data).model_dump(mode="json")


def consultar_agenda(
    usuario_id: UUID, inicio: date, fim: date,
    statuses: list[AgendamentoStatus] | None, pagina: int, tamanho: int,
) -> AgendaResponse:
    try:
        resposta = get_supabase_client().rpc("consultar_agenda_terceirizada", {
            "p_usuario_id": str(usuario_id), "p_inicio": inicio.isoformat(),
            "p_fim": fim.isoformat(), "p_statuses": [str(s) for s in statuses] if statuses else None,
            "p_pagina": pagina, "p_tamanho": tamanho,
        }).execute()
    except APIError as exc:
        if exc.code == "42501":
            raise AcessoInstitucionalNegadoError("Acesso institucional negado.") from exc
        raise
    return AgendaResponse.model_validate(resposta.data)
