import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "segredo-de-teste-com-tamanho-adequado")

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.routes import auth, graph_agendamentos
from app.core import security
from app.core.config import get_settings
from app.main import app
from app.schemas.auth import UsuarioAutenticado

ID, COL, VAGA = [uuid4() for _ in range(3)]


def test_005_escopo_sem_defaults_ou_revogacoes_globais():
    sql = (Path(__file__).resolve().parents[1] / "database/migrations/005_seguranca_permissoes.sql").read_text(encoding="utf-8").lower()
    assert "alter default privileges" not in sql
    assert "on all tables" not in sql and "on all routines" not in sql
    assert "on all sequences" not in sql and "revoke all on schema" not in sql
    assert "alter role" not in sql and "alter event trigger" not in sql
    assert "grant usage on schema public to service_role" in sql


@pytest.fixture(autouse=True)
def limpar():
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def usuario(role="admin"):
    return dict(id=str(ID), email="audit@example.com", role=role, ativo=True,
                colaborador_id=str(COL) if role=="colaborador" else None)


@pytest.mark.parametrize("email", [None, 12, {}, [], True, "email-invalido"])
def test_login_email_invalido_422(client, monkeypatch, email):
    consultar = Mock(side_effect=AssertionError("nao consultar banco"))
    monkeypatch.setattr(auth, "buscar_usuario_por_email", consultar)
    assert client.post("/auth/login", json={"email": email, "senha": "ficticia"}).status_code == 422
    consultar.assert_not_called()


@pytest.mark.parametrize("role", ["admin","colaborador","terceirizada"])
def test_login_normalizado_roles_preservadas(client, monkeypatch, role):
    dados = {**usuario(role), "senha_hash": security.gerar_hash_senha("senha-ficticia")}
    buscar = Mock(return_value=dados)
    monkeypatch.setattr(auth, "buscar_usuario_por_email", buscar)
    monkeypatch.setattr(auth, "validar_vinculo_colaborador", lambda _: True)
    resposta=client.post("/auth/login", json={"email": " AUDIT@EXAMPLE.COM ", "senha": "senha-ficticia"})
    assert resposta.status_code == 200
    buscar.assert_called_once_with("audit@example.com")


@pytest.mark.parametrize("hash_invalido", ["", "hash-ficticio", "$argon2id$corrompido", None, 123])
def test_hash_invalido_falha_fechada(client, monkeypatch, hash_invalido):
    monkeypatch.setattr(auth, "buscar_usuario_por_email", lambda _: {**usuario(), "senha_hash": hash_invalido})
    resposta=client.post("/auth/login", json={"email": "audit@example.com", "senha": "senha-ficticia"})
    assert resposta.status_code == 401
    assert resposta.json()["detail"] == "E-mail ou senha inválidos."
    assert "senha_hash" not in resposta.text


def claims():
    return {"sub": str(ID), "role": "admin", "exp": int((datetime.now(timezone.utc)+timedelta(minutes=5)).timestamp())}


@pytest.mark.parametrize("mudanca", [
    {"sub": None}, {"sub": 123}, {"sub": "nao-uuid"}, {"sub": {}},
    {"exp": None}, {"exp": "9999999999"}, {"exp": True}, {"exp": 9999999999.5},
    {"exp": 0}, {"role": None}, {"role": "gestor"}, {"role": {}},
    {"remover": "exp"}, {"remover": "sub"}, {"remover": "role"},
])
def test_jwt_claims_obrigatorias_e_tipos(client, monkeypatch, mudanca):
    dados=claims()
    mudanca=dict(mudanca)
    remover=mudanca.pop("remover", None)
    dados.update(mudanca)
    if remover:
        dados.pop(remover)
    token=jwt.encode(dados,get_settings().require_jwt_secret(),algorithm=get_settings().jwt_algorithm)
    consultar=Mock(side_effect=AssertionError("nao consultar banco"))
    monkeypatch.setattr(security,"buscar_usuario_por_id",consultar)
    assert client.get("/auth/me",headers={"Authorization":"Bearer "+token}).status_code == 401
    consultar.assert_not_called()


@pytest.mark.parametrize("caso", ["valido","assinatura_invalida","malformado"])
def test_validacao_token(client, monkeypatch, caso):
    monkeypatch.setattr(security,"buscar_usuario_por_id",lambda _:usuario())
    segredo = "segredo-ficticio-incorreto-com-mais-de-32-caracteres" if caso=="assinatura_invalida" else get_settings().require_jwt_secret()
    token = "nao-e-jwt" if caso=="malformado" else jwt.encode(claims(),segredo,algorithm=get_settings().jwt_algorithm)
    resposta=client.get("/auth/me",headers={"Authorization":"Bearer "+token})
    assert resposta.status_code == (200 if caso=="valido" else 401)


def agendamento():
    return dict(id=str(uuid4()),colaborador_id=str(COL),horario_id=str(VAGA),
                massoterapeuta_id=None,data_agendamento="2099-01-01",hora_inicio="09:00",
                hora_fim="09:30",status="AGENDADO",criado_em="2026-01-01T00:00:00Z",
                atualizado_em="2026-01-01T00:00:00Z")


@pytest.mark.parametrize("payload", [
    {"colaborador_id":str(COL),"horario_id":str(VAGA)},
    {"colaborador_id":str(COL),"mensagem":"Pedido ficticio"},
])
def test_graph_contrato_sucesso(client, monkeypatch, payload):
    app.dependency_overrides[security.get_current_user]=lambda:UsuarioAutenticado(**usuario("colaborador"))
    monkeypatch.setattr(graph_agendamentos.agendamento_graph,"invoke",lambda _:dict(
        sucesso=True,mensagem_resposta="Sucesso",interpretacao=None,agendamento=agendamento()))
    resposta=client.post("/graph/agendamentos",json=payload)
    assert resposta.status_code == 201
    assert set(resposta.json())=={"sucesso","mensagem","interpretacao","agendamento"}
    assert resposta.json()["agendamento"]["massoterapeuta_id"] is None


def test_graph_openapi_tipado(client, monkeypatch):
    schema=client.get("/openapi.json").json()
    respostas=schema["paths"]["/graph/agendamentos"]["post"]["responses"]
    assert respostas["201"]["content"]["application/json"]["schema"]["$ref"].endswith("AgendamentoGraphResponse")
    for codigo in ("404","409","500","502","503"):
        assert respostas[codigo]["content"]["application/json"]["schema"]["$ref"].endswith("AgendamentoGraphErrorResponse")
    modelos=respostas["422"]["content"]["application/json"]["schema"]["anyOf"]
    assert {modelo["$ref"].split("/")[-1] for modelo in modelos} == {
        "AgendamentoGraphErrorResponse","AgendamentoGraphValidationErrorResponse"}


def test_graph_validacao_422_documentada(client):
    app.dependency_overrides[security.get_current_user]=lambda:UsuarioAutenticado(**usuario("colaborador"))
    resposta=client.post("/graph/agendamentos",json={"colaborador_id":str(COL)})
    assert resposta.status_code == 422 and "detail" in resposta.json()


def test_graph_erro_preserva_status_e_campos(client, monkeypatch):
    app.dependency_overrides[security.get_current_user]=lambda:UsuarioAutenticado(**usuario("colaborador"))
    monkeypatch.setattr(graph_agendamentos.agendamento_graph,"invoke",lambda _:dict(
        sucesso=False,status_http=409,mensagem_resposta="Conflito",erro="intervalo_minimo"))
    resposta=client.post("/graph/agendamentos",json={"colaborador_id":str(COL),"horario_id":str(VAGA)})
    assert resposta.status_code == 409
    assert resposta.json()=={"sucesso":False,"mensagem":"Conflito","erro":"intervalo_minimo"}


@pytest.mark.parametrize("textual", [False,True])
def test_graph_real_estruturado_e_textual_sem_profissional(client, monkeypatch, textual):
    from datetime import date
    from app.agents.interpretador import Interpretacao
    from app.graphs.agendamento import nodes
    from app.services.agendamentos import AgendamentoContexto
    app.dependency_overrides[security.get_current_user]=lambda:UsuarioAutenticado(**usuario("colaborador"))
    interpretar=Mock(return_value=Interpretacao(
        escolhido=True,horario_id=str(VAGA),massoterapeuta_id=None,justificativa="Interpretacao ficticia"))
    monkeypatch.setattr(nodes,"interpretar_mensagem",interpretar)
    monkeypatch.setattr(nodes,"validar_entidades_agendamento",lambda _:AgendamentoContexto(
        colaborador={"id":str(COL)},massoterapeuta={},horario={"id":str(VAGA)},
        data_agendamento=date(2099,1,1)))
    monkeypatch.setattr(nodes,"validar_intervalo_agendamento",lambda *_:None)
    monkeypatch.setattr(nodes,"executar_criacao_agendamento",lambda *_:agendamento())
    payload={"colaborador_id":str(COL)}
    payload.update({"mensagem":"Pedido ficticio"} if textual else {"horario_id":str(VAGA)})
    resposta=client.post("/graph/agendamentos",json=payload)
    assert resposta.status_code == 201
    assert resposta.json()["agendamento"]["massoterapeuta_id"] is None
    assert resposta.json()["interpretacao"] == ("Interpretacao ficticia" if textual else None)
    assert interpretar.call_count == int(textual)
