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
from app.schemas.agenda import BloqueioCreate, BloqueioResponse
from app.schemas.auth import UsuarioAutenticado
from app.database.repositories.agenda import criar_bloqueio, desativar_bloqueio, listar_bloqueios, AgendaConflitoError
from app.services.agenda_automatica import sincronizar_agenda, exigir_prontidao_http

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
    responses={200: {"description": "Repetição idempotente."}, 409: {"description": "Intervalo, chave ou horário em conflito."},
               503: {"description": "Agenda ainda nao pronta ou banco indisponivel."}},
)
def cadastrar_horario(horario: HorarioCreate, response: Response) -> DisponibilidadeResponse:
    exigir_prontidao_http()
    try:
        resultado = criar_horario(horario)
        response.status_code = 201 if resultado.criado else 200
        return resultado.disponibilidade
    except DisponibilidadeError as exc:
        erros = {
            "calendario_indisponivel": (409, "Intervalo fora do calendario ou bloqueado."),
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


@router.post("/sincronizar", dependencies=[Depends(require_admin)])
def atualizar_janela() -> dict:
    try:
        return sincronizar_agenda()
    except Exception as exc:
        raise HTTPException(503, "Falha ao sincronizar agenda.") from exc


@router.post("/bloqueios", response_model=BloqueioResponse, status_code=201)
def bloquear(payload: BloqueioCreate, admin: UsuarioAutenticado = Depends(require_admin)):
    try:
        return criar_bloqueio(admin.id, payload)
    except AgendaConflitoError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "Falha ao registrar bloqueio.") from exc


@router.get("/bloqueios", response_model=list[BloqueioResponse], dependencies=[Depends(require_admin)])
def obter_bloqueios(data_inicio: date, data_fim: date):
    if not 0 <= (data_fim-data_inicio).days <= 30:
        raise HTTPException(422, "Consulte ate 31 dias.")
    try:
        return listar_bloqueios(data_inicio, data_fim)
    except Exception as exc:
        raise HTTPException(503, "Falha ao consultar bloqueios.") from exc


@router.delete("/bloqueios/{bloqueio_id}", status_code=204)
def desbloquear(bloqueio_id: UUID, admin: UsuarioAutenticado = Depends(require_admin)):
    try:
        encontrado = desativar_bloqueio(admin.id, bloqueio_id)
    except Exception as exc:
        raise HTTPException(503, "Falha ao desativar bloqueio.") from exc
    if not encontrado:
        raise HTTPException(404, "Bloqueio nao encontrado.")


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
