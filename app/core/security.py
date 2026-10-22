from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import get_settings
from app.database.repositories.usuarios import buscar_usuario_por_id
from app.database.repositories.colaboradores import buscar_colaborador_por_id
from app.schemas.auth import UsuarioAutenticado, UsuarioRole


password_hash = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)


def gerar_hash_senha(senha: str) -> str:
    return password_hash.hash(senha)


def verificar_senha(senha: str, senha_hash: str) -> bool:
    try:
        return password_hash.verify(senha, senha_hash)
    except (UnknownHashError, ValueError, TypeError):
        return False


def criar_access_token(
    usuario_id: UUID | str,
    role: UsuarioRole | str,
    expires_delta: timedelta | None = None,
) -> str:
    if str(role) not in {role.value for role in UsuarioRole}:
        raise ValueError("Perfil nao suportado.")
    settings = get_settings()
    expiracao = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    payload = {
        "sub": str(usuario_id),
        "role": str(role),
        "exp": expiracao,
    }
    return jwt.encode(
        payload,
        settings.require_jwt_secret(),
        algorithm=settings.jwt_algorithm,
    )


def _credenciais_invalidas() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido ou expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def validar_vinculo_colaborador(usuario: dict) -> bool:
    if usuario.get("role") != UsuarioRole.COLABORADOR:
        return True
    if not usuario.get("colaborador_id"):
        return False
    colaborador = buscar_colaborador_por_id(UUID(str(usuario["colaborador_id"])))
    return colaborador is not None and bool(colaborador.get("ativo", False))


def autorizar_colaborador(usuario: UsuarioAutenticado, colaborador_id: UUID) -> None:
    if usuario.role == UsuarioRole.ADMIN:
        return
    if usuario.role != UsuarioRole.COLABORADOR or usuario.colaborador_id != colaborador_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito ao próprio colaborador.",
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UsuarioAutenticado:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _credenciais_invalidas()

    settings = get_settings()
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.require_jwt_secret(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "role"]},
        )
        if (
            not isinstance(payload["sub"], str)
            or type(payload["exp"]) is not int
            or not isinstance(payload["role"], str)
            or payload["role"] not in {role.value for role in UsuarioRole}
        ):
            raise ValueError("Claims invalidas.")
        usuario_id = UUID(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise _credenciais_invalidas() from exc

    try:
        usuario = buscar_usuario_por_id(usuario_id)
        permitido = (
            usuario is not None
            and usuario.get("ativo", False)
            and usuario.get("role") in {role.value for role in UsuarioRole}
            and validar_vinculo_colaborador(usuario)
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Falha ao consultar usuário.") from exc
    if not permitido:
        raise _credenciais_invalidas()

    return UsuarioAutenticado.model_validate(usuario)


def require_admin(
    usuario: UsuarioAutenticado = Depends(get_current_user),
) -> UsuarioAutenticado:
    if usuario.role != UsuarioRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a administradores.",
        )

    return usuario


def require_agendamento_user(
    usuario: UsuarioAutenticado = Depends(get_current_user),
) -> UsuarioAutenticado:
    if usuario.role not in {UsuarioRole.ADMIN, UsuarioRole.COLABORADOR}:
        raise HTTPException(status_code=403, detail="Perfil sem acesso a este recurso.")
    return usuario


def verificar_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Compatibilidade temporária com integrações legadas que usam x-api-key."""
    settings = get_settings()

    if not settings.auth_habilitada:
        return

    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida ou ausente.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
