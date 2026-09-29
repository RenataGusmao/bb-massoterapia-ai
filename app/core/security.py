from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def verificar_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()

    if not settings.auth_habilitada:
        return

    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida ou ausente.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
