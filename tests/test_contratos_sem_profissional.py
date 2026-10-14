"""HTTP inputs identify slots only; historical professional metadata stays in outputs."""
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.routes import graph_agendamentos
from app.core.security import get_current_user
from app.database.repositories import agendamentos, horarios
from app.main import app
from app.schemas.agendamento import AgendamentoCreate, AgendamentoGraphRequest
from app.schemas.auth import UsuarioAutenticado
from app.schemas.horario import HorarioCreate
from app.services import agendamentos as service

COL = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
VAGA = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
RESERVA = {"colaborador_id": COL, "horario_id": VAGA}
HORARIO = {"chave_idempotencia": VAGA, "data": "2099-01-01",
           "hora_inicio": "09:00", "hora_fim": "09:30", "capacidade": 2}


@pytest.fixture
def client():
    app.dependency_overrides.clear()
    app.dependency_overrides[get_current_user] = lambda: UsuarioAutenticado(
        id=UUID(COL), email="teste@example.com", role="admin", ativo=True,
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize("rota,modelo", [
    ("/horarios", HorarioCreate),
    ("/agendamentos", AgendamentoCreate),
    ("/graph/agendamentos", AgendamentoGraphRequest),
])
def test_openapi_entrada_sem_profissional(client, rota, modelo):
    spec = client.get("/openapi.json").json()
    ref = spec["paths"][rota]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    schema = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert "massoterapeuta_id" not in schema["properties"]
    assert "massoterapeuta_id" not in schema.get("required", [])
    assert schema["additionalProperties"] is False
    if rota == "/agendamentos":
        assert set(schema["properties"]) == {"colaborador_id", "horario_id"}
    for example in schema["examples"]:
        assert "massoterapeuta_id" not in example
        modelo.model_validate(example)


@pytest.mark.parametrize("modelo", ["AgendamentoResponse", "HorarioResponse"])
def test_openapi_resposta_preserva_profissional_nullable(client, modelo):
    campo = client.get("/openapi.json").json()["components"]["schemas"][modelo]["properties"]["massoterapeuta_id"]
    assert any(tipo.get("type") == "null" for tipo in campo["anyOf"])


@pytest.mark.parametrize("rota,payload", [
    ("/horarios", HORARIO),
    ("/agendamentos", RESERVA),
    ("/graph/agendamentos", RESERVA),
    ("/graph/agendamentos", {"colaborador_id": COL, "mensagem": "Quinta de manha"}),
])
@pytest.mark.parametrize("profissional", [None, PROF])
def test_http_rejeita_profissional_antes_de_rpc_ou_grafo(client, monkeypatch, rota, payload, profissional):
    banco = Mock(side_effect=AssertionError("Nao acessar o banco"))
    grafo = Mock(side_effect=AssertionError("Nao executar o grafo"))
    monkeypatch.setattr(horarios, "get_supabase_client", banco)
    monkeypatch.setattr(agendamentos, "get_supabase_client", banco)
    monkeypatch.setattr(graph_agendamentos.agendamento_graph, "invoke", grafo)
    response = client.post(rota, json={**payload, "massoterapeuta_id": profissional})
    assert response.status_code == 422
    assert any(erro["type"] == "extra_forbidden" for erro in response.json()["detail"])
    banco.assert_not_called()
    grafo.assert_not_called()


def test_prevalidacao_preserva_profissional_historico_da_vaga(monkeypatch):
    monkeypatch.setattr(service, "buscar_colaborador_por_id", lambda _: {"ativo": True})
    monkeypatch.setattr(service, "buscar_horario_por_id", lambda _: {
        "disponivel": True, "data": "2099-01-01", "massoterapeuta_id": PROF,
    })
    consultar = Mock(return_value={"id": PROF, "ativo": True})
    monkeypatch.setattr(service, "buscar_massoterapeuta_por_id", consultar)
    contexto = service.validar_entidades_agendamento(AgendamentoCreate(**RESERVA))
    consultar.assert_called_once_with(UUID(PROF))
    assert contexto.massoterapeuta["id"] == PROF


@pytest.mark.parametrize("pedido", [RESERVA, {"colaborador_id": COL, "mensagem": "Quinta de manha"}])
def test_http_grafo_nao_encaminha_profissional(client, monkeypatch, pedido):
    registro = {**RESERVA, "id": VAGA, "massoterapeuta_id": None,
                "data_agendamento": "2099-01-01", "hora_inicio": "09:00",
                "hora_fim": "09:30", "status": "AGENDADO",
                "criado_em": "2026-01-01T00:00:00Z", "atualizado_em": "2026-01-01T00:00:00Z"}
    executar = Mock(return_value={"sucesso": True, "mensagem_resposta": "Criado", "agendamento": registro})
    monkeypatch.setattr(graph_agendamentos.agendamento_graph, "invoke", executar)
    assert client.post("/graph/agendamentos", json=pedido).status_code == 201
    assert "massoterapeuta_id" not in executar.call_args.args[0]


def test_gemini_nao_escolhe_profissional_mesmo_se_inventar_id(monkeypatch):
    from app.agents import interpretador
    monkeypatch.setattr(interpretador, "listar_horarios_disponiveis", lambda *_: [{
        "id": VAGA, "data": "2099-01-01", "hora_inicio": "09:00", "hora_fim": "09:30",
        "massoterapeuta_id": None,
    }])
    llm = Mock()
    llm.invoke.return_value.content = '{"escolhido":true,"horario_id":"' + VAGA + '","massoterapeuta_id":"' + PROF + '"}'
    monkeypatch.setattr(interpretador, "get_llm", lambda: llm)
    resultado = interpretador.interpretar_mensagem("Quinta de manha")
    assert resultado.horario_id == VAGA and resultado.massoterapeuta_id is None
    assert "Não escolha profissionais" in interpretador.SYSTEM_PROMPT
