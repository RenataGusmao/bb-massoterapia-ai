from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings


settings = get_settings()
settings.require_jwt_secret()

app = FastAPI(
    title="BB Massoterapia AI",
    description="API REST do MVP BB Massoterapia AI, preparada para deploy em nuvem.",
    version="0.3.0",
)

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
