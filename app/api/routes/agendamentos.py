from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import verificar_api_key
from app.database.repositories.agendamentos import (
    buscar_agendamento_por_id,
    listar_agendamentos,
)
from app.database.supabase import SupabaseConfigurationError
from app.schemas.agendamento import (
    AgendamentoCreate,
    AgendamentoResponse,
    AgendamentoStatusUpdate,
)
from app.services.agendamentos import (
    AgendamentoNaoEncontradoError,
    ColaboradorNaoEncontradoError,
    HorarioIndisponivelError,
    HorarioMassoterapeutaInvalidoError,
    HorarioNaoEncontradoError,
    IntervaloAgendamentoError,
    MassoterapeutaInativoError,
    MassoterapeutaNaoEncontradoError,
    StatusInvalidoError,
    alterar_status_agendamento,
    criar_agendamento_para_horario,
)

router = APIRouter(prefix="/agendamentos", tags=["agendamentos"])

AGENDAMENTO_POST_RESPONSES = {
    201: {"description": "Agendamento criado."},
    404: {"description": "Colaborador, massoterapeuta ou horário não encontrado."},
    409: {"description": "Conflito de negócio, como intervalo mínimo, horário ocupado ou massoterapeuta inativo."},
    422: {"description": "Dados inválidos ou horário incompatível com o massoterapeuta informado."},
    500: {"description": "Erro interno controlado."},
    503: {"description": "Falha de infraestrutura ou banco não configurado."},
}


@router.get("", response_model=list[AgendamentoResponse])
def obter_agendamentos() -> list[dict]:
    try:
        return listar_agendamentos()
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao acessar agendamentos.",
        ) from exc


@router.post(
    "",
    response_model=AgendamentoResponse,
    status_code=status.HTTP_201_CREATED,
    responses=AGENDAMENTO_POST_RESPONSES,
    dependencies=[Depends(verificar_api_key)],
)
def cadastrar_agendamento(agendamento: AgendamentoCreate) -> dict:
    try:
        return criar_agendamento_para_horario(agendamento)
    except ColaboradorNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Colaborador não encontrado.",
        ) from exc
    except MassoterapeutaNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Massoterapeuta não encontrado.",
        ) from exc
    except MassoterapeutaInativoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Massoterapeuta está inativo.",
        ) from exc
    except HorarioNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Horário não encontrado.",
        ) from exc
    except HorarioMassoterapeutaInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Horário não pertence ao massoterapeuta informado.",
        ) from exc
    except IntervaloAgendamentoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.detail,
        ) from exc
    except HorarioIndisponivelError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Horário já está ocupado.",
        ) from exc
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar agendamento.",
        ) from exc


@router.patch(
    "/{agendamento_id}/status",
    response_model=AgendamentoResponse,
    dependencies=[Depends(verificar_api_key)],
    responses={
        404: {"description": "Agendamento não encontrado."},
        422: {"description": "Status inválido."},
    },
)
def alterar_status(agendamento_id: UUID, payload: AgendamentoStatusUpdate) -> dict:
    """Cancela, conclui ou marca falta.

    Cancelamento devolve o horário para a agenda dentro da mesma transação.
    """
    try:
        return alterar_status_agendamento(agendamento_id, payload.status)
    except AgendamentoNaoEncontradoError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado.",
        ) from exc
    except StatusInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Status inválido.",
        ) from exc
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao atualizar agendamento.",
        ) from exc


@router.get("/{agendamento_id}", response_model=AgendamentoResponse)
def obter_agendamento_por_id(agendamento_id: UUID) -> dict:
    try:
        agendamento = buscar_agendamento_por_id(agendamento_id)
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao acessar agendamento.",
        ) from exc

    if agendamento is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado.",
        )

    return agendamento
