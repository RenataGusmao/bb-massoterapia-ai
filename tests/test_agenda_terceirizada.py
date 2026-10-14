import os
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "segredo-de-teste-com-tamanho-adequado")

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.api.routes import agenda, auth
from app.core import security
from app.core.config import get_settings
from app.database.repositories import agenda as repo
from app.main import app
from app.schemas.agenda import AgendaResponse, TerceirizadaContaCreate
from app.schemas.auth import UsuarioAutenticado

USER, LOTE, COL, VAGA = [uuid4() for _ in range(4)]
SENHA = "Senha-Ficticia123!"


def usuario(role="terceirizada", ativo=True):
    return dict(id=str(USER), colaborador_id=None, email="institucional@example.com",
                role=role, ativo=ativo)


def payload():
    return dict(email="institucional@example.com", senha=SENHA, disponibilidade_ids=[str(LOTE)])


@pytest.fixture(autouse=True)
def isolamento():
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def autenticar(role="terceirizada"):
    app.dependency_overrides[security.get_current_user] = lambda: UsuarioAutenticado(**usuario(role))


def pagina():
    return AgendaResponse.model_validate(dict(
        itens=[dict(id=str(uuid4()), data="2026-12-01", hora_inicio="10:00",
                    hora_fim="10:30", status="AGENDADO", horario_id=str(VAGA),
                    disponibilidade_id=str(LOTE))],
        total=1, pagina=1, tamanho_pagina=50,
    ))


def test_admin_provisiona_hash_role_fixa(client, monkeypatch):
    autenticar("admin")
    salvar = Mock(return_value=usuario())
    monkeypatch.setattr(auth, "provisionar_terceirizada", salvar)
    resposta = client.post("/auth/terceirizadas", json=payload())
    assert resposta.status_code == 201
    assert resposta.json() == usuario()
    admin_id, dados, senha_hash = salvar.call_args.args
    assert admin_id == USER
    assert dados.disponibilidade_ids == [LOTE]
    assert senha_hash.startswith("$argon2")
    assert security.verificar_senha(SENHA, senha_hash)
    assert SENHA not in resposta.text and "senha_hash" not in resposta.text


@pytest.mark.parametrize("role", ["colaborador", "terceirizada"])
def test_provisionamento_restrito(client, role):
    autenticar(role)
    assert client.post("/auth/terceirizadas", json=payload()).status_code == 403


@pytest.mark.parametrize("mudanca", [
    {"role": "admin"}, {"colaborador_id": str(COL)}, {"senha": "senha-fraca"},
    {"email": {"valor": "invalido"}}, {"senha": {"valor": "invalido"}},
    {"disponibilidade_ids": []}, {"disponibilidade_ids": [str(LOTE), str(LOTE)]},
    {"disponibilidade_ids": [str(uuid4()) for _ in range(101)]},
])
def test_provisionamento_validacao(client, mudanca):
    autenticar("admin")
    assert client.post("/auth/terceirizadas", json={**payload(), **mudanca}).status_code == 422


@pytest.mark.parametrize("erro,codigo", [
    (repo.UsuarioDuplicadoError("Conta existente"), 409),
    (repo.EscopoInvalidoError("Escopo invalido"), 422),
    (RuntimeError("informacao sensivel"), 503),
    (repo.AcessoInstitucionalNegadoError("Acesso negado"), 403),
])
def test_provisionamento_erros_controlados(client, monkeypatch, erro, codigo):
    autenticar("admin")
    monkeypatch.setattr(auth, "provisionar_terceirizada", Mock(side_effect=erro))
    resposta = client.post("/auth/terceirizadas", json=payload())
    assert resposta.status_code == codigo
    assert "informacao sensivel" not in resposta.text


def test_login_jwt_me_agenda(client, monkeypatch):
    dados = {**usuario(), "senha_hash": security.gerar_hash_senha(SENHA)}
    monkeypatch.setattr(auth, "buscar_usuario_por_email", lambda _: dados)
    monkeypatch.setattr(security, "buscar_usuario_por_id", lambda _: dados)
    monkeypatch.setattr(security, "buscar_colaborador_por_id", Mock(side_effect=AssertionError("sem vinculo")))
    consulta = Mock(return_value=pagina())
    monkeypatch.setattr(agenda, "consultar_agenda", consulta)
    resposta = client.post("/auth/login", json={"email": dados["email"], "senha": SENHA})
    assert resposta.status_code == 200
    headers = {"Authorization": "Bearer " + resposta.json()["access_token"]}
    assert client.get("/auth/me", headers=headers).json() == usuario()
    resposta = client.get("/agenda/terceirizada?data=2026-12-01", headers=headers)
    assert resposta.status_code == 200
    assert set(resposta.json()["itens"][0]) == {
        "id", "data", "hora_inicio", "hora_fim", "status", "horario_id", "disponibilidade_id"}
    assert consulta.call_args.args[0] == USER
    for path in ["/horarios", "/horarios/" + str(VAGA), "/massoterapeutas"]:
        assert client.get(path, headers=headers).status_code == 403


@pytest.mark.parametrize("caso", ["inativo", "expirado", "invalido", "sem_token"])
def test_credenciais_rejeitadas(client, monkeypatch, caso):
    monkeypatch.setattr(security, "buscar_usuario_por_id", lambda _: usuario(ativo=caso != "inativo"))
    token = security.criar_access_token(USER, "terceirizada",
        expires_delta=timedelta(seconds=-1) if caso == "expirado" else None)
    if caso == "invalido":
        token = "token-invalido"
    headers = {} if caso == "sem_token" else {"Authorization": "Bearer " + token}
    assert client.get("/agenda/terceirizada", headers=headers).status_code == 401


@pytest.mark.parametrize("role", ["admin", "colaborador"])
def test_agenda_exige_role_institucional(client, role):
    autenticar(role)
    assert client.get("/agenda/terceirizada").status_code == 403


@pytest.mark.parametrize("method,path,body", [
    ("get", "/agendamentos", None), ("get", "/agendamentos/me", None),
    ("get", "/agendamentos/" + str(VAGA), None),
    ("post", "/agendamentos", {"colaborador_id": str(COL), "horario_id": str(VAGA)}),
    ("patch", "/agendamentos/" + str(VAGA) + "/status", {"status": "CANCELADO"}),
    ("get", "/colaboradores", None), ("get", "/colaboradores/" + str(COL), None),
    ("post", "/auth/colaboradores", {"colaborador_id": str(COL), "senha": SENHA}),
    ("post", "/horarios", {}),
    ("post", "/massoterapeutas", {}),
    ("get", "/horarios", None),
    ("get", "/horarios/" + str(VAGA), None),
    ("get", "/massoterapeutas", None),
    ("get", "/massoterapeutas/" + str(VAGA), None),
    ("post", "/graph/agendamentos", {"colaborador_id": str(COL), "horario_id": str(VAGA)}),
])
def test_institucional_nao_acessa_outros_recursos(client, method, path, body):
    autenticar()
    resposta = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert resposta.status_code == 403


@pytest.mark.parametrize("query", [
    "data_inicio=2026-12-01", "data_fim=2026-12-01",
    "data=2026-12-01&data_inicio=2026-12-01&data_fim=2026-12-02",
    "data_inicio=2026-12-02&data_fim=2026-12-01",
    "data_inicio=2026-12-01&data_fim=2027-01-01",
    "pagina=0", "pagina=10001", "tamanho_pagina=101", "tamanho_pagina=0",
    "status=INVALIDO", "data=invalida",
])
def test_filtros_invalidos(client, monkeypatch, query):
    autenticar()
    consultar = Mock(side_effect=AssertionError("nao consultar"))
    monkeypatch.setattr(agenda, "consultar_agenda", consultar)
    assert client.get("/agenda/terceirizada?" + query).status_code == 422
    consultar.assert_not_called()


@pytest.mark.parametrize("query", [
    "data=2026-12-01",
    "data_inicio=2026-12-01&data_fim=2026-12-31&status=CANCELADO&status=AGENDADO&pagina=2&tamanho_pagina=1",
    "",
])
def test_filtros_paginacao_encaminhados(client, monkeypatch, query):
    autenticar()
    consultar = Mock(return_value=pagina())
    monkeypatch.setattr(agenda, "consultar_agenda", consultar)
    assert client.get("/agenda/terceirizada?" + query).status_code == 200
    args = consultar.call_args.args
    assert args[0] == USER
    if "pagina=2" in query:
        assert args[1].isoformat() == "2026-12-01"
        assert args[2].isoformat() == "2026-12-31"
        assert args[3] == ["CANCELADO", "AGENDADO"]
        assert args[4:] == (2, 1)


def test_repositorio_parametros_e_resposta_minima(monkeypatch):
    cliente = Mock()
    cliente.rpc.return_value.execute.return_value.data = pagina().model_dump(mode="json")
    monkeypatch.setattr(repo, "get_supabase_client", lambda: cliente)
    from datetime import date
    assert repo.consultar_agenda(USER, date(2026,12,1), date(2026,12,1), None, 1, 50).total == 1
    assert cliente.rpc.call_args.args[1]["p_usuario_id"] == str(USER)
    cliente.rpc.return_value.execute.return_value.data = {**usuario(), "senha_hash": "sensivel"}
    assert repo.provisionar_terceirizada(USER, TerceirizadaContaCreate(**payload()), "$argon2test") == usuario()


@pytest.mark.parametrize("code,erro", [
    ("23505", repo.UsuarioDuplicadoError), ("22023", repo.EscopoInvalidoError),
    ("42501", repo.AcessoInstitucionalNegadoError),
])
def test_repositorio_erros_pg(monkeypatch, code, erro):
    cliente = Mock()
    cliente.rpc.return_value.execute.side_effect = APIError({"code": code, "message": "sensivel", "details": None, "hint": None})
    monkeypatch.setattr(repo, "get_supabase_client", lambda: cliente)
    with pytest.raises(erro):
        repo.provisionar_terceirizada(USER, TerceirizadaContaCreate(**payload()), "$argon2test")


@pytest.mark.parametrize("path", ["/horarios", "/massoterapeutas", "/auth/terceirizadas", "/agenda/terceirizada"])
def test_sem_token_nao_contorna_escopo(client, path):
    resposta = client.post(path, json=payload()) if path.startswith("/auth") else client.get(path)
    assert resposta.status_code == 401


def test_role_no_token_nao_eleva_permissao(client, monkeypatch):
    monkeypatch.setattr(security, "buscar_usuario_por_id", lambda _: usuario())
    token = security.criar_access_token(USER, "admin")
    assert client.get("/agendamentos", headers={"Authorization": "Bearer " + token}).status_code == 403


def test_login_conta_inativa(client, monkeypatch):
    monkeypatch.setattr(auth, "buscar_usuario_por_email",
        lambda _: {**usuario(ativo=False), "senha_hash": security.gerar_hash_senha(SENHA)})
    assert client.post("/auth/login", json={"email": usuario()["email"], "senha": SENHA}).status_code == 401


def test_falha_agenda_sem_expor_infraestrutura(client, monkeypatch):
    autenticar()
    monkeypatch.setattr(agenda, "consultar_agenda", Mock(side_effect=RuntimeError("segredo")))
    resposta = client.get("/agenda/terceirizada")
    assert resposta.status_code == 503 and "segredo" not in resposta.text


def test_validacao_nao_ecoa_senha(client):
    autenticar("admin")
    resposta = client.post("/auth/terceirizadas", json={**payload(), "senha": "senha-fraca"})
    assert resposta.status_code == 422
    assert "senha-fraca" not in resposta.text
    assert "input" not in resposta.json()["detail"][0]
    assert SENHA not in repr(TerceirizadaContaCreate(**payload()))


def test_acesso_revogado_na_rpc(client, monkeypatch):
    autenticar()
    monkeypatch.setattr(agenda, "consultar_agenda",
        Mock(side_effect=repo.AcessoInstitucionalNegadoError("negado")))
    assert client.get("/agenda/terceirizada").status_code == 403
