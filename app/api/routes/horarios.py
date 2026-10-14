from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.security import require_admin, require_agendamento_user
from app.database.repositories.horarios import (
    buscar_horario_por_id,
    DisponibilidadeError,
    criar_horario,
    listar_horarios,
)
from app.database.supabase import SupabaseConfigurationError
from app.schemas.horario import DisponibilidadeResponse, HorarioCreate, HorarioResponse

router = APIRouter(prefix="/horarios", tags=["horarios"])


@router.get("", response_model=list[HorarioResponse], dependencies=[Depends(require_agendamento_user)])
def obter_horarios(
    disponivel: bool | None = Query(
        default=None,
        description="true lista só os livres, false só os ocupados, omitido lista todos.",
    ),
    massoterapeuta_id: UUID | None = Query(default=None),
    data_inicio: date | None = Query(default=None, description="Formato AAAA-MM-DD."),
    data_fim: date | None = Query(default=None, description="Formato AAAA-MM-DD."),
    dia: date | None = Query(default=None, alias="data"),
) -> list[dict]:
    if data_inicio and data_fim and data_fim < data_inicio:
        raise HTTPException(status_code=422, detail="data_fim deve ser igual ou posterior a data_inicio.")
    try:
        return listar_horarios(
            apenas_disponiveis=disponivel,
            massoterapeuta_id=massoterapeuta_id,
            data_inicio=data_inicio,
            data_fim=data_fim,
            dia=dia,
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
    response_model=DisponibilidadeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    responses={200: {"description": "Repetição idempotente."}, 409: {"description": "Intervalo, chave ou horário em conflito."}},
)
def cadastrar_horario(horario: HorarioCreate, response: Response) -> DisponibilidadeResponse:
    try:
        resultado = criar_horario(horario)
        response.status_code = 201 if resultado.criado else 200
        return resultado.disponibilidade
    except DisponibilidadeError as exc:
        erros = {
            "capacidade_invalida": (422, "Capacidade deve ser um inteiro entre 1 e 500."),
            "periodo_invalido": (422, "Intervalo inválido."),
            "horario_passado": (409, "Não é permitido cadastrar intervalo já iniciado."),
            "idempotencia_conflitante": (409, "Chave de idempotência já utilizada com outro conteúdo."),
            "intervalo_existente": (409, "Intervalo já cadastrado."),
            "intervalo_sobreposto": (409, "Intervalo sobreposto à disponibilidade existente."),
            "massoterapeuta_nao_encontrado": (404, "Massoterapeuta não encontrado."),
            "massoterapeuta_inativo": (409, "Massoterapeuta inativo."),
            "conflito_disponibilidade": (409, "Conflito concorrente. Consulte a disponibilidade e tente novamente."),
        }
        codigo, mensagem = erros.get(exc.codigo, (500, "Erro ao criar disponibilidade."))
        raise HTTPException(status_code=codigo, detail=mensagem) from exc
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


@router.get("/{horario_id}", response_model=HorarioResponse, dependencies=[Depends(require_agendamento_user)])
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
