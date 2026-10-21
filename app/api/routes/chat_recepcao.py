from fastapi import APIRouter

from app.agents.recepcao import processar_mensagem_recepcao
from app.schemas.recepcao import RecepcaoRequest, RecepcaoResponse

router = APIRouter(prefix="/chat", tags=["recepcao"])


@router.post("/recepcao", response_model=RecepcaoResponse)
def receber_mensagem_recepcao(payload: RecepcaoRequest) -> dict:
    return processar_mensagem_recepcao(payload.mensagem)
