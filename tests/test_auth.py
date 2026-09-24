import os
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


os.environ.setdefault("JWT_SECRET_KEY", "segredo-de-teste-com-tamanho-adequado")

from app.api.routes import auth as auth_routes
from app.core import security
from app.core.config import get_settings
from app.core.security import criar_access_token, gerar_hash_senha, get_current_user
from app.main import app
from app.schemas.auth import UsuarioAutenticado, UsuarioRole


USUARIO_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
COLABORADOR_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


@pytest.fixture(scope="module")
def usuario() -> dict:
    return {
        "id": str(USUARIO_ID),
        "colaborador_id": str(COLABORADOR_ID),
        "email": "usuario@example.com",
        "senha_hash": gerar_hash_senha("senha-correta"),
        "role": "colaborador",
        "ativo": True,
    }


@pytest.fixture(autouse=True)
def limpar_overrides():
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_login_correto_retorna_token(client, monkeypatch, usuario):
    monkeypatch.setattr(auth_routes, "buscar_usuario_por_email", lambda email: usuario)

    response = client.post(
        "/auth/login",
        json={"email": "usuario@example.com", "senha": "senha-correta"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_com_senha_errada_retorna_401(client, monkeypatch, usuario):
    monkeypatch.setattr(auth_routes, "buscar_usuario_por_email", lambda email: usuario)

    response = client.post(
        "/auth/login",
        json={"email": "usuario@example.com", "senha": "senha-errada"},
    )

    assert response.status_code == 401


def test_auth_me_sem_token_retorna_401(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_auth_me_com_token_valido_retorna_usuario(
    client, monkeypatch, usuario
):
    monkeypatch.setattr(security, "buscar_usuario_por_id", lambda usuario_id: usuario)
    token = criar_access_token(USUARIO_ID, UsuarioRole.COLABORADOR)

    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(USUARIO_ID)
    assert "senha_hash" not in response.json()


def test_token_invalido_retorna_401(client):
    response = client.get(
        "/auth/me", headers={"Authorization": "Bearer token-invalido"}
    )
    assert response.status_code == 401


def test_token_expirado_retorna_401(client):
    token = criar_access_token(
        USUARIO_ID,
        UsuarioRole.COLABORADOR,
        expires_delta=timedelta(seconds=-1),
    )

    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_rota_admin_com_colaborador_retorna_403(client):
    usuario_comum = UsuarioAutenticado(
        id=USUARIO_ID,
        colaborador_id=COLABORADOR_ID,
        email="usuario@example.com",
        role=UsuarioRole.COLABORADOR,
        ativo=True,
    )
    app.dependency_overrides[get_current_user] = lambda: usuario_comum

    response = client.get("/agendamentos")
    assert response.status_code == 403
