from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import (
    criar_access_token,
    get_current_user,
    require_admin,
    validar_vinculo_colaborador,
    verificar_senha,
)
from app.database.repositories.usuarios import UsuarioDuplicadoError, buscar_usuario_por_email
from app.database.supabase import SupabaseConfigurationError
from app.schemas.auth import (
    ColaboradorContaCreate,
    LoginRequest,
    TokenResponse,
    UsuarioAutenticado,
)
from app.services.auth import (
    ColaboradorContaInativoError,
    ColaboradorContaNaoEncontradoError,
    provisionar_conta_colaborador,
)


router = APIRouter(prefix="/auth", tags=["autenticação"])


def _login_invalido() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="E-mail ou senha inválidos.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/login", response_model=TokenResponse)
def login(credenciais: LoginRequest) -> TokenResponse:
    try:
        usuario = buscar_usuario_por_email(str(credenciais.email))
    except SupabaseConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Banco de dados não configurado.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao autenticar usuário.",
        ) from exc

    if (
        usuario is None
        or not usuario.get("ativo", False)
        or usuario.get("role") not in {"admin", "colaborador"}
        or not verificar_senha(credenciais.senha, usuario["senha_hash"])
    ):
        raise _login_invalido()

    try:
        vinculo_valido = validar_vinculo_colaborador(usuario)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Falha ao consultar usuário.") from exc
    if not vinculo_valido:
        raise _login_invalido()

    token = criar_access_token(usuario["id"], usuario["role"])
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UsuarioAutenticado)
def obter_usuario_autenticado(
    usuario: UsuarioAutenticado = Depends(get_current_user),
) -> UsuarioAutenticado:
    return usuario


@router.post(
    "/colaboradores",
    response_model=UsuarioAutenticado,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def provisionar_colaborador(payload: ColaboradorContaCreate) -> dict:
    try:
        return provisionar_conta_colaborador(payload)
    except ColaboradorContaNaoEncontradoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ColaboradorContaInativoError, UsuarioDuplicadoError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupabaseConfigurationError as exc:
        raise HTTPException(status_code=503, detail="Banco de dados não configurado.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Erro ao provisionar conta.") from exc
