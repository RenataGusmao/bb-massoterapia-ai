from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.database.repositories.colaboradores import (
    buscar_colaborador_por_id,
    criar_colaborador,
    listar_colaboradores,
)
from app.database.supabase import SupabaseConfigurationError
from app.schemas.colaborador import ColaboradorCreate, ColaboradorResponse

router = APIRouter(prefix="/colaboradores", tags=["colaboradores"])


@router.get("", response_model=list[ColaboradorResponse])
def obter_colaboradores() -> list[dict]:
    try:
        return listar_colaboradores()
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao acessar colaboradores.",
        ) from exc


@router.post("", response_model=ColaboradorResponse, status_code=status.HTTP_201_CREATED)
def cadastrar_colaborador(colaborador: ColaboradorCreate) -> dict:
    try:
        return criar_colaborador(colaborador)
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar colaborador.",
        ) from exc


@router.get("/{colaborador_id}", response_model=ColaboradorResponse)
def obter_colaborador_por_id(colaborador_id: UUID) -> dict:
    try:
        colaborador = buscar_colaborador_por_id(colaborador_id)
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao acessar colaborador.",
        ) from exc

    if colaborador is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Colaborador não encontrado.",
        )

    return colaborador
