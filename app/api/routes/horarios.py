from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import verificar_api_key
from app.database.repositories.horarios import (
    buscar_horario_por_id,
    criar_horario,
    listar_horarios,
)
from app.database.supabase import SupabaseConfigurationError
from app.schemas.horario import HorarioCreate, HorarioResponse

router = APIRouter(prefix="/horarios", tags=["horarios"])


@router.get("", response_model=list[HorarioResponse])
def obter_horarios(
    disponivel: bool | None = Query(
        default=None,
        description="true lista só os livres, false só os ocupados, omitido lista todos.",
    ),
    massoterapeuta_id: UUID | None = Query(default=None),
    data_inicio: date | None = Query(default=None, description="Formato AAAA-MM-DD."),
    data_fim: date | None = Query(default=None, description="Formato AAAA-MM-DD."),
) -> list[dict]:
    try:
        return listar_horarios(
            apenas_disponiveis=disponivel,
            massoterapeuta_id=massoterapeuta_id,
            data_inicio=data_inicio,
            data_fim=data_fim,
        )
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao acessar horários.",
        ) from exc


@router.post(
    "",
    response_model=HorarioResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verificar_api_key)],
)
def cadastrar_horario(horario: HorarioCreate) -> dict:
    try:
        return criar_horario(horario)
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar horário.",
        ) from exc


@router.get("/{horario_id}", response_model=HorarioResponse)
def obter_horario_por_id(horario_id: UUID) -> dict:
    try:
        horario = buscar_horario_por_id(horario_id)
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao acessar horário.",
        ) from exc

    if horario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Horário não encontrado.",
        )

    return horario
