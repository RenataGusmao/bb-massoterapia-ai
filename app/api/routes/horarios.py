from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.database.repositories.horarios import (
    buscar_horario_por_id,
    criar_horario,
    listar_horarios,
)
from app.database.supabase import SupabaseConfigurationError
from app.schemas.horario import HorarioCreate, HorarioResponse

router = APIRouter(prefix="/horarios", tags=["horarios"])


@router.get("", response_model=list[HorarioResponse])
def obter_horarios() -> list[dict]:
    try:
        return listar_horarios()
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


@router.post("", response_model=HorarioResponse, status_code=status.HTTP_201_CREATED)
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
