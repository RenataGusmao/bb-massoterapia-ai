import hashlib
import hmac
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, Security
from fastapi.security import APIKeyHeader

from app.core.config import get_settings
from app.core.datas import data_local
from app.database.repositories.agenda import consultar_agenda
from app.schemas.agenda import AgendaResponse

router = APIRouter(prefix="/agenda", tags=["agenda de leitura"])
agenda_key = APIKeyHeader(name="X-Agenda-Key", auto_error=False, scheme_name="AgendaLeitura")


def autorizar_agenda(chave: str | None = Security(agenda_key)) -> None:
    esperado = get_settings().agenda_leitura_token_sha256
    if not esperado or len(esperado) != 64 or any(c not in "0123456789abcdef" for c in esperado):
        raise HTTPException(503, "Acesso de leitura nao configurado.")
    if chave is None or not hmac.compare_digest(hashlib.sha256(chave.encode()).hexdigest(), esperado):
        raise HTTPException(401, "Chave de leitura invalida.")


@router.get("/atendimentos", response_model=AgendaResponse, dependencies=[Depends(autorizar_agenda)])
def agenda_atendimentos(
    response: Response,
    data_inicio: date | None = None,
    data_fim: date | None = None,
) -> AgendaResponse:
    hoje = data_local()
    inicio, fim = data_inicio or hoje, data_fim or (data_inicio or hoje)
    if not hoje <= inicio <= fim <= hoje + timedelta(days=30):
        raise HTTPException(422, "Consulte somente a janela dos proximos 31 dias.")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        return consultar_agenda(inicio, fim)
    except Exception as exc:
        raise HTTPException(503, "Agenda temporariamente indisponivel.") from exc
