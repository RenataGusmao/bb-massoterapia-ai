from app.core.security import gerar_hash_senha
from app.database.repositories.colaboradores import buscar_colaborador_por_id
from app.database.repositories.usuarios import (
    UsuarioDuplicadoError,
    buscar_usuario_por_colaborador_id,
    buscar_usuario_por_email,
    criar_usuario,
)
from app.schemas.auth import ColaboradorContaCreate, UsuarioCreate, UsuarioRole


class ColaboradorContaNaoEncontradoError(ValueError):
    pass


class ColaboradorContaInativoError(ValueError):
    pass


def provisionar_conta_colaborador(payload: ColaboradorContaCreate) -> dict:
    colaborador = buscar_colaborador_por_id(payload.colaborador_id)
    if colaborador is None:
        raise ColaboradorContaNaoEncontradoError("Colaborador não encontrado.")
    if not colaborador.get("ativo", False):
        raise ColaboradorContaInativoError("Colaborador inativo.")

    email = colaborador["email"].strip().lower()
    if (
        buscar_usuario_por_colaborador_id(payload.colaborador_id) is not None
        or buscar_usuario_por_email(email) is not None
    ):
        raise UsuarioDuplicadoError("Conta ou e-mail já cadastrado.")

    return criar_usuario(
        UsuarioCreate(
            colaborador_id=payload.colaborador_id,
            email=email,
            senha_hash=gerar_hash_senha(payload.senha),
            role=UsuarioRole.COLABORADOR,
        )
    )
