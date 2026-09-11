from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.database.repositories.massoterapeutas import (
    buscar_massoterapeuta_por_id,
    criar_massoterapeuta,
    listar_massoterapeutas,
)
from app.database.supabase import SupabaseConfigurationError
from app.schemas.massoterapeuta import MassoterapeutaCreate, MassoterapeutaResponse

router = APIRouter(prefix="/massoterapeutas", tags=["massoterapeutas"])


@router.get("", response_model=list[MassoterapeutaResponse])
def obter_massoterapeutas() -> list[dict]:
    try:
        return listar_massoterapeutas()
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao acessar massoterapeutas.",
        ) from exc


@router.post("", response_model=MassoterapeutaResponse, status_code=status.HTTP_201_CREATED)
def cadastrar_massoterapeuta(massoterapeuta: MassoterapeutaCreate) -> dict:
    try:
        return criar_massoterapeuta(massoterapeuta)
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar massoterapeuta.",
        ) from exc


@router.get("/{massoterapeuta_id}", response_model=MassoterapeutaResponse)
def obter_massoterapeuta_por_id(massoterapeuta_id: UUID) -> dict:
    try:
        massoterapeuta = buscar_massoterapeuta_por_id(massoterapeuta_id)
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao acessar massoterapeuta.",
        ) from exc

    if massoterapeuta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Massoterapeuta não encontrado.",
        )

    return massoterapeuta
