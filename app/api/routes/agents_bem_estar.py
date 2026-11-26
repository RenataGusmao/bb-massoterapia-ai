from fastapi import APIRouter, Depends, Response

from app.core.security import require_agendamento_user

from app.agents.bem_estar import processar_orientacao
from app.schemas.bem_estar import BemEstarRequest, BemEstarResponse

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/bem-estar", response_model=BemEstarResponse, dependencies=[Depends(require_agendamento_user)])
def orientar_bem_estar(payload: BemEstarRequest, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return processar_orientacao(payload.mensagem)
