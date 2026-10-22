import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.services.agenda_automatica import iniciar_agenda, reiniciar_prontidao, exigir_prontidao_http


settings = get_settings()
settings.require_jwt_secret()


@asynccontextmanager
async def lifespan(app: FastAPI):
    tarefa = None
    reiniciar_prontidao()
    if get_settings().agenda_geracao_automatica:
        tarefa = asyncio.create_task(iniciar_agenda())
    try:
        yield
    finally:
        if tarefa is not None:
            tarefa.cancel()
            with suppress(asyncio.CancelledError):
                await tarefa

app = FastAPI(
    title="BB Massoterapia AI",
    description="API REST do MVP BB Massoterapia AI, preparada para deploy em nuvem.",
    version="0.3.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def ocultar_credenciais_invalidas(request: Request, exc: RequestValidationError):
    erros = []
    for erro in exc.errors():
        erro = dict(erro)
        if any(campo in {"senha", "senha_hash"} for campo in erro.get("loc", ())):
            erro.pop("input", None)
        erros.append(erro)
    return await request_validation_exception_handler(request, RequestValidationError(erros))

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "API BB Massoterapia AI funcionando"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"], responses={503: {"description": "Agenda ainda nao pronta."}})
def readiness_check(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    exigir_prontidao_http()
    return {"status": "ready"}
