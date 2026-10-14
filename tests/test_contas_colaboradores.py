import os
from uuid import UUID
from unittest.mock import Mock

os.environ.setdefault("JWT_SECRET_KEY", "segredo-de-teste-com-tamanho-adequado")

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.api.routes import agendamentos, auth, colaboradores, graph_agendamentos
from app.core import security
from app.core.config import get_settings
from app.database.repositories import usuarios as usuario_repo
from app.database.repositories import agendamentos as agendamento_repo
from app.main import app
from app.schemas.auth import UsuarioAutenticado, UsuarioCreate, UsuarioRole
from app.services import auth as conta_service


COLABORADOR = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OUTRO = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
USUARIO = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
AGENDAMENTO = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
SENHA = "senha-ficticia-de-teste"


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


def identidade(role="colaborador", colaborador_id=COLABORADOR):
    return UsuarioAutenticado(
        id=USUARIO, colaborador_id=colaborador_id,
        email="usuario@example.com", role=role, ativo=True,
    )


def autenticar(role="colaborador", colaborador_id=COLABORADOR):
    app.dependency_overrides[security.get_current_user] = lambda: identidade(role, colaborador_id)


def cadastro():
    return {
        "id": str(COLABORADOR), "nome": "Colaborador Teste",
        "matricula": "TESTE", "email": "usuario@example.com", "setor": None,
        "ativo": True, "criado_em": "2026-01-01T00:00:00Z",
    }


def agendamento(colaborador_id=COLABORADOR):
    return {
        "id": str(AGENDAMENTO), "colaborador_id": str(colaborador_id),
        "massoterapeuta_id": str(OUTRO), "horario_id": str(USUARIO),
        "data_agendamento": "2026-12-01", "hora_inicio": "10:00:00",
        "hora_fim": "10:30:00", "status": "AGENDADO",
        "criado_em": "2026-01-01T00:00:00Z", "atualizado_em": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def provisionamento(monkeypatch):
    monkeypatch.setattr(conta_service, "buscar_colaborador_por_id", lambda _: cadastro())
    monkeypatch.setattr(conta_service, "buscar_usuario_por_colaborador_id", lambda _: None)
    monkeypatch.setattr(conta_service, "buscar_usuario_por_email", lambda _: None)
    salvar = Mock(side_effect=lambda usuario: {"id": str(USUARIO), **usuario.model_dump(mode="json")})
    monkeypatch.setattr(conta_service, "criar_usuario", salvar)
    return salvar


def payload_conta():
    return {"colaborador_id": str(COLABORADOR), "senha": SENHA}


def test_fluxo_provisionar_login_me_sem_expor_hash(client, monkeypatch, provisionamento):
    autenticar("admin", None)
    response = client.post("/auth/colaboradores", json=payload_conta())
    assert response.status_code == 201
    assert response.json()["role"] == "colaborador"
    assert set(response.json()) == {"id", "colaborador_id", "email", "role", "ativo"}
    persistido = provisionamento.call_args.args[0]
    assert persistido.senha_hash != SENHA
    assert persistido.senha_hash.startswith("$argon2")
    assert security.verificar_senha(SENHA, persistido.senha_hash)
    usuario = {"id": str(USUARIO), **persistido.model_dump(mode="json")}
    app.dependency_overrides.clear()
    monkeypatch.setattr(auth, "buscar_usuario_por_email", lambda _: usuario)
    monkeypatch.setattr(security, "buscar_usuario_por_id", lambda _: usuario)
    monkeypatch.setattr(security, "buscar_colaborador_por_id", lambda _: cadastro())
    login = client.post("/auth/login", json={"email": "usuario@example.com", "senha": SENHA})
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["colaborador_id"] == str(COLABORADOR)
    assert "senha_hash" not in me.json()
    monkeypatch.setattr(agendamentos, "buscar_agendamento_por_id", lambda _: agendamento(OUTRO))
    assert client.get(f"/agendamentos/{AGENDAMENTO}", headers=headers).status_code == 404
    assert client.get("/agendamentos", headers=headers).status_code == 403
    monkeypatch.setattr(security, "buscar_colaborador_por_id", lambda _: {**cadastro(), "ativo": False})
    assert client.get("/auth/me", headers=headers).status_code == 401


@pytest.mark.parametrize("role,esperado", [(None, 401), ("colaborador", 403)])
def test_provisionamento_exige_admin(client, provisionamento, role, esperado):
    if role:
        autenticar(role)
    assert client.post("/auth/colaboradores", json=payload_conta()).status_code == esperado
    provisionamento.assert_not_called()


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"email": "outro@example.com"}, {"ativo": True}])
def test_provisionamento_nao_aceita_escolha_de_role_ou_email(client, provisionamento, extra):
    autenticar("admin", None)
    assert client.post("/auth/colaboradores", json={**payload_conta(), **extra}).status_code == 422
    provisionamento.assert_not_called()


def test_senha_curta_rejeitada(client, provisionamento):
    autenticar("admin", None)
    assert client.post("/auth/colaboradores", json={**payload_conta(), "senha": "curta"}).status_code == 422
    provisionamento.assert_not_called()


@pytest.mark.parametrize("registro,status", [(None, 404), ({"ativo": False}, 409)])
def test_provisionamento_exige_colaborador_valido(client, monkeypatch, provisionamento, registro, status):
    autenticar("admin", None)
    monkeypatch.setattr(conta_service, "buscar_colaborador_por_id", lambda _: registro)
    assert client.post("/auth/colaboradores", json=payload_conta()).status_code == status
    provisionamento.assert_not_called()


@pytest.mark.parametrize("busca", ["buscar_usuario_por_colaborador_id", "buscar_usuario_por_email"])
def test_conta_ou_email_duplicado(client, monkeypatch, provisionamento, busca):
    autenticar("admin", None)
    monkeypatch.setattr(conta_service, busca, lambda _: {"id": str(USUARIO)})
    assert client.post("/auth/colaboradores", json=payload_conta()).status_code == 409
    provisionamento.assert_not_called()


def test_conflito_concorrente_traduzido_para_409(client, provisionamento):
    autenticar("admin", None)
    provisionamento.side_effect = usuario_repo.UsuarioDuplicadoError("Conta ou e-mail já cadastrado.")
    assert client.post("/auth/colaboradores", json=payload_conta()).status_code == 409


def test_repository_traduz_constraint_unica(monkeypatch):
    client = Mock()
    client.table.return_value.insert.return_value.execute.side_effect = APIError(
        {"code": "23505", "message": "duplicate", "details": "", "hint": ""}
    )
    monkeypatch.setattr(usuario_repo, "get_supabase_client", lambda: client)
    with pytest.raises(usuario_repo.UsuarioDuplicadoError):
        usuario_repo.criar_usuario(UsuarioCreate(
            colaborador_id=COLABORADOR, email="usuario@example.com", senha_hash="hash-ficticio",
        ))


def test_busca_email_escapa_curingas(monkeypatch):
    client = Mock()
    query = client.table.return_value.select.return_value
    query.ilike.return_value.limit.return_value.execute.return_value.data = []
    monkeypatch.setattr(usuario_repo, "get_supabase_client", lambda: client)
    assert usuario_repo.buscar_usuario_por_email("conta_%@example.com") is None
    query.ilike.assert_called_once_with("email", "conta\\_\\%@example.com")


@pytest.mark.parametrize("vinculo,registro", [(None, None), (COLABORADOR, None), (COLABORADOR, {"ativo": False})])
def test_login_e_token_rejeitam_vinculo_invalido(client, monkeypatch, vinculo, registro):
    usuario = {
        "id": str(USUARIO), "email": "usuario@example.com",
        "colaborador_id": str(vinculo) if vinculo else None,
        "role": "colaborador", "ativo": True, "senha_hash": security.gerar_hash_senha(SENHA),
    }
    monkeypatch.setattr(auth, "buscar_usuario_por_email", lambda _: usuario)
    monkeypatch.setattr(security, "buscar_usuario_por_id", lambda _: usuario)
    monkeypatch.setattr(security, "buscar_colaborador_por_id", lambda _: registro)
    assert client.post("/auth/login", json={"email": usuario["email"], "senha": SENHA}).status_code == 401
    token = security.criar_access_token(USUARIO, "colaborador")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_admin_sem_vinculo_preservado(client, monkeypatch):
    usuario = {
        **identidade("admin", None).model_dump(mode="json"),
        "senha_hash": security.gerar_hash_senha(SENHA),
    }
    monkeypatch.setattr(auth, "buscar_usuario_por_email", lambda _: usuario)
    monkeypatch.setattr(security, "buscar_usuario_por_id", lambda _: usuario)
    monkeypatch.setattr(security, "buscar_colaborador_por_id", Mock(side_effect=AssertionError("admin não precisa de vínculo")))
    response = client.post("/auth/login", json={"email": usuario["email"], "senha": SENHA})
    assert response.status_code == 200
    assert client.get("/auth/me", headers={"Authorization": "Bearer " + response.json()["access_token"]}).status_code == 200


def test_role_do_banco_prevalece_sobre_token(client, monkeypatch):
    usuario = identidade().model_dump(mode="json")
    monkeypatch.setattr(security, "buscar_usuario_por_id", lambda _: usuario)
    monkeypatch.setattr(security, "buscar_colaborador_por_id", lambda _: cadastro())
    token = security.criar_access_token(USUARIO, UsuarioRole.ADMIN)
    assert client.get("/agendamentos", headers={"Authorization": f"Bearer {token}"}).status_code == 403


@pytest.mark.parametrize("role,dono,status", [
    ("colaborador", COLABORADOR, 201), ("colaborador", OUTRO, 403), ("admin", OUTRO, 201),
])
@pytest.mark.parametrize("rota", ["/agendamentos", "/graph/agendamentos"])
def test_criacao_confere_proprietario(client, monkeypatch, role, dono, status, rota):
    autenticar(role)
    executar = Mock(return_value=agendamento(dono))
    monkeypatch.setattr(agendamentos, "criar_agendamento_para_horario", executar)
    invocar = Mock(return_value={
        "sucesso": True, "mensagem_resposta": "Criado", "agendamento": agendamento(dono),
    })
    monkeypatch.setattr(graph_agendamentos.agendamento_graph, "invoke", invocar)
    response = client.post(rota, json={
        "colaborador_id": str(dono), "massoterapeuta_id": str(OUTRO), "horario_id": str(USUARIO),
    })
    assert response.status_code == status
    alvo = executar if rota == "/agendamentos" else invocar
    if status == 403:
        alvo.assert_not_called()
    else:
        alvo.assert_called_once()


@pytest.mark.parametrize("role,dono,status", [
    ("colaborador", COLABORADOR, 200), ("colaborador", OUTRO, 404), ("admin", OUTRO, 200),
])
def test_leitura_confere_proprietario(client, monkeypatch, role, dono, status):
    autenticar(role)
    monkeypatch.setattr(agendamentos, "buscar_agendamento_por_id", lambda _: agendamento(dono))
    response = client.get(f"/agendamentos/{AGENDAMENTO}")
    assert response.status_code == status
    if status == 404:
        assert response.json() == {"detail": "Agendamento não encontrado."}


def test_meus_agendamentos_usa_identidade_nao_query(client, monkeypatch):
    autenticar()
    listar = Mock(return_value=[agendamento()])
    monkeypatch.setattr(agendamentos, "listar_agendamentos_por_colaborador", listar)
    response = client.get(f"/agendamentos/me?colaborador_id={OUTRO}")
    assert response.status_code == 200
    assert response.json()[0]["colaborador_id"] == str(COLABORADOR)
    listar.assert_called_once_with(COLABORADOR)


def test_repository_filtra_meus_agendamentos(monkeypatch):
    client = Mock()
    query = client.table.return_value.select.return_value
    query.eq.return_value.order.return_value.order.return_value.execute.return_value.data = []
    monkeypatch.setattr(agendamento_repo, "get_supabase_client", lambda: client)
    assert agendamento_repo.listar_agendamentos_por_colaborador(COLABORADOR) == []
    query.eq.assert_called_once_with("colaborador_id", str(COLABORADOR))


@pytest.mark.parametrize("role,dono,status", [
    ("colaborador", COLABORADOR, 200), ("colaborador", OUTRO, 403), ("admin", OUTRO, 200),
])
def test_dados_cadastrais_restritos(client, monkeypatch, role, dono, status):
    autenticar(role)
    buscar = Mock(return_value={**cadastro(), "id": str(dono)})
    monkeypatch.setattr(colaboradores, "buscar_colaborador_por_id", buscar)
    assert client.get(f"/colaboradores/{dono}").status_code == status
    if status == 403:
        buscar.assert_not_called()


@pytest.mark.parametrize("rota", ["/colaboradores", "/agendamentos"])
def test_listagens_gerais_restritas(client, rota):
    autenticar()
    assert client.get(rota).status_code == 403


def test_cadastro_colaborador_exige_admin(client):
    payload = {"nome": "Teste", "matricula": "MTESTE", "email": "teste@example.com"}
    assert client.post("/colaboradores", json=payload).status_code == 401
    autenticar()
    assert client.post("/colaboradores", json=payload).status_code == 403


@pytest.mark.parametrize("rota", ["/agendamentos/me", f"/colaboradores/{COLABORADOR}", f"/agendamentos/{AGENDAMENTO}"])
def test_consultas_sem_token(client, rota):
    assert client.get(rota).status_code == 401


def test_erro_banco_nao_expoe_credencial(client, monkeypatch, provisionamento):
    autenticar("admin", None)
    provisionamento.side_effect = RuntimeError("credencial-ficticia-nao-expor")
    response = client.post("/auth/colaboradores", json=payload_conta())
    assert response.status_code == 500
    assert "credencial-ficticia" not in response.text
