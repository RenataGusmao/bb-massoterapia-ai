from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.datas import data_local
from app.core.security import require_terceirizada
from app.database.repositories.agenda import AcessoInstitucionalNegadoError, consultar_agenda
from app.schemas.agenda import AgendaResponse
from app.schemas.agendamento import AgendamentoStatus
from app.schemas.auth import UsuarioAutenticado

router = APIRouter(prefix="/agenda", tags=["agenda institucional"])


@router.get("/terceirizada", response_model=AgendaResponse)
def agenda_terceirizada(
    dia: date | None = Query(None, alias="data"),
    data_inicio: date | None = None,
    data_fim: date | None = None,
    statuses: list[AgendamentoStatus] | None = Query(None, alias="status", max_length=4),
    pagina: int = Query(1, ge=1, le=10000),
    tamanho_pagina: int = Query(50, ge=1, le=100),
    usuario: UsuarioAutenticado = Depends(require_terceirizada),
) -> AgendaResponse:
    if dia is not None and (data_inicio is not None or data_fim is not None):
        raise HTTPException(422, "Use data ou periodo, nao ambos.")
    if (data_inicio is None) != (data_fim is None):
        raise HTTPException(422, "Informe data_inicio e data_fim juntos.")
    inicio = dia or data_inicio or data_local()
    fim = dia or data_fim or inicio
    if not 0 <= (fim - inicio).days <= 30:
        raise HTTPException(422, "Periodo deve conter entre 1 e 31 dias inclusivos.")
    try:
        return consultar_agenda(usuario.id, inicio, fim, statuses, pagina, tamanho_pagina)
    except AcessoInstitucionalNegadoError as exc:
        raise HTTPException(403, "Acesso institucional negado.") from exc
    except Exception as exc:
        raise HTTPException(503, "Agenda temporariamente indisponivel.") from exc
