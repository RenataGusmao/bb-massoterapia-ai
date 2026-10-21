from fastapi import APIRouter

from app.agents.bem_estar import processar_orientacao
from app.schemas.bem_estar import BemEstarRequest, BemEstarResponse

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/bem-estar", response_model=BemEstarResponse)
def orientar_bem_estar(payload: BemEstarRequest) -> dict:
    return processar_orientacao(payload.mensagem)
