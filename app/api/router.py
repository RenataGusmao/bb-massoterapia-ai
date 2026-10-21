from fastapi import APIRouter, HTTPException, status

from app.api.routes import (
    agendamentos,
    colaboradores,
    graph_agendamentos,
    horarios,
    massoterapeutas,
)
from app.database.supabase import SupabaseConfigurationError, check_database_connection

api_router = APIRouter()
api_router.include_router(colaboradores.router)
api_router.include_router(massoterapeutas.router)
api_router.include_router(horarios.router)
api_router.include_router(agendamentos.router)
api_router.include_router(graph_agendamentos.router)


@api_router.get("/health/db", tags=["health"])
def database_health_check() -> dict[str, str]:
    try:
        check_database_connection()
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados indisponível.",
        ) from exc

    return {"status": "ok", "database": "connected"}
