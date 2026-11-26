from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.agents.orchestrator import processar_chat
from app.core.security import autorizar_colaborador, require_agendamento_user
from app.memory.session_store import SessionNotFoundError, SessionTargetError, SessionCapacityError
from app.schemas.auth import UsuarioAutenticado
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse, responses={
    201: {"model": ChatResponse, "description": "Reserva confirmada ou confirmacao repetida."},
    409: {"model": ChatResponse, "description": "Conflito na reserva."},
    503: {"description": "Infraestrutura ou agenda indisponivel."},
})
def conversar(payload: ChatRequest, usuario: UsuarioAutenticado = Depends(require_agendamento_user)):
    colaborador_id = payload.colaborador_id or usuario.colaborador_id
    if colaborador_id is not None:
        autorizar_colaborador(usuario, colaborador_id)
    try:
        resultado = processar_chat(
            mensagem=payload.mensagem,
            session_id=payload.session_id,
            colaborador_id=str(colaborador_id) if colaborador_id else None,
            usuario_id=str(usuario.id),
        )
    except SessionNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except SessionTargetError as exc:
        raise HTTPException(403, str(exc)) from exc
    except SessionCapacityError as exc:
        raise HTTPException(503, "Chat temporariamente ocupado.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Chat temporariamente indisponivel.") from exc
    codigo = resultado.pop("status_http", 200)
    conteudo = ChatResponse.model_validate(resultado)
    return JSONResponse(status_code=codigo, content=jsonable_encoder(conteudo),
                        headers={"Cache-Control": "no-store"})
