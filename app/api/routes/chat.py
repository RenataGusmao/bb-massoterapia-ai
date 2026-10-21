from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.agents.orchestrator import processar_chat
from app.database.supabase import SupabaseConfigurationError
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def conversar(payload: ChatRequest) -> dict:
    try:
        resultado = processar_chat(
            mensagem=payload.mensagem,
            session_id=payload.session_id,
            colaborador_id=str(payload.colaborador_id) if payload.colaborador_id else None,
        )
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível consultar disponibilidade.",
        ) from exc

    status_http = resultado.pop("status_http", status.HTTP_200_OK)

    if status_http != status.HTTP_200_OK:
        return JSONResponse(status_code=status_http, content=resultado)

    return resultado
