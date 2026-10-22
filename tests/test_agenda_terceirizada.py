"""The retired profile cannot login; shared agenda access is not a user role."""
import hashlib
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth, agenda
from app.core import security
from app.core.config import get_settings
from app.core.datas import data_local
from app.main import app

KEY = "chave-de-leitura-ficticia-com-entropia-de-teste"
USER = str(uuid4())


@pytest.fixture(autouse=True)
def limpar(monkeypatch):
    app.dependency_overrides.clear()
    monkeypatch.setenv("AGENDA_LEITURA_TOKEN_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_endpoints_terceirizada_removidos(client):
    assert client.post("/auth/terceirizadas", json={}).status_code == 404
    assert client.get("/agenda/terceirizada").status_code == 404
    schema = client.get("/openapi.json").json()
    assert schema["components"]["schemas"]["UsuarioRole"]["enum"] == ["colaborador", "admin"]
    assert schema["paths"]["/agenda/atendimentos"]["get"]["security"] == [{"AgendaLeitura": []}]


@pytest.mark.parametrize("ativo", [False, True])
def test_login_legacy_recusado_mesmo_antes_da_migration(client, monkeypatch, ativo):
    monkeypatch.setattr(auth, "buscar_usuario_por_email", lambda _: {
        "id": USER, "email": "legacy@example.com", "role": "terceirizada",
        "ativo": ativo, "senha_hash": "nao-expor",
    })
    verificar = Mock(side_effect=AssertionError("Nao verificar hash legado"))
    monkeypatch.setattr(auth, "verificar_senha", verificar)
    assert client.post("/auth/login", json={"email": "legacy@example.com", "senha": "teste"}).status_code == 401
    verificar.assert_not_called()


def test_jwt_antigo_nao_autoriza(client, monkeypatch):
    token = jwt.encode({"sub": USER, "role": "terceirizada", "exp": 9999999999},
                       get_settings().require_jwt_secret(), algorithm="HS256")
    buscar = Mock(side_effect=AssertionError("Nao consultar perfil removido"))
    monkeypatch.setattr(security, "buscar_usuario_por_id", buscar)
    assert client.get("/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401
    buscar.assert_not_called()
    with pytest.raises(ValueError):
        security.criar_access_token(USER, "terceirizada")


@pytest.mark.parametrize("key", [None, "errada"])
def test_agenda_nao_anonima_irrestrita(client, key):
    headers = {"X-Agenda-Key": key} if key else {}
    assert client.get("/agenda/atendimentos", headers=headers).status_code == 401


def test_agenda_falha_fechada_sem_chave_configurada(client, monkeypatch):
    monkeypatch.delenv("AGENDA_LEITURA_TOKEN_SHA256")
    get_settings.cache_clear()
    assert client.get("/agenda/atendimentos", headers={"X-Agenda-Key": KEY}).status_code == 503


def test_agenda_minimizada_sem_jwt(client, monkeypatch):
    hoje = data_local()
    consultar = Mock(return_value={"itens": [{
        "data": hoje.isoformat(), "hora_inicio": "09:40", "hora_fim": "10:10",
        "capacidade": 2, "agendados": 1, "disponiveis": 1,
    }]})
    monkeypatch.setattr(agenda, "consultar_agenda", consultar)
    response = client.get("/agenda/atendimentos", headers={"X-Agenda-Key": KEY})
    assert response.status_code == 200
    assert set(response.json()["itens"][0]) == {"data", "hora_inicio", "hora_fim", "capacidade", "agendados", "disponiveis"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("dias", [-1, 31])
def test_agenda_limita_periodo(client, dias):
    dia = data_local() + timedelta(days=dias)
    assert client.get("/agenda/atendimentos", params={"data_inicio": dia.isoformat()},
                      headers={"X-Agenda-Key": KEY}).status_code == 422


def test_chave_leitura_nao_autoriza_escrita(client):
    assert client.post("/horarios", json={}, headers={"X-Agenda-Key": KEY}).status_code == 401
