import os
from datetime import date, datetime
from unittest.mock import Mock
from uuid import UUID

os.environ.setdefault("JWT_SECRET_KEY", "segredo-de-teste-com-tamanho-adequado")

import pytest
from fastapi.testclient import TestClient

from app.agents import interpretador
from app.api.routes import horarios, agendamentos, graph_agendamentos
from app.core.security import get_current_user
from app.database.repositories import horarios as repo, agendamentos as agendamento_repo
from app.graphs.agendamento import nodes
from app.graphs.agendamento.graph import agendamento_graph
from app.main import app
from app.schemas.auth import UsuarioAutenticado
from app.schemas.agendamento import AgendamentoCreate
from app.services import agendamentos as service


COLABORADOR = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
GRUPO = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
VAGA = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
CHAVE = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


def vaga(numero=1):
    return {
        "id": str(VAGA if numero == 1 else CHAVE), "disponibilidade_id": str(GRUPO),
        "numero_vaga": numero, "massoterapeuta_id": None,
        "data": "2099-01-01", "hora_inicio": "09:00:00", "hora_fim": "09:30:00",
        "disponivel": True, "criado_em": "2026-01-01T00:00:00Z",
    }


def disponibilidade():
    return {
        "id": str(GRUPO), "data": "2099-01-01", "hora_inicio": "09:00:00",
        "hora_fim": "09:30:00", "capacidade": 2, "vagas": [vaga(), vaga(2)],
    }


def payload():
    return {
        "chave_idempotencia": str(CHAVE), "data": "2099-01-01",
        "hora_inicio": "09:00", "hora_fim": "09:30", "capacidade": 2,
    }


def reserva():
    return {
        "id": str(CHAVE), "colaborador_id": str(COLABORADOR),
        "horario_id": str(VAGA), "massoterapeuta_id": None,
        "data_agendamento": "2099-01-01", "hora_inicio": "09:00",
        "hora_fim": "09:30", "status": "AGENDADO",
        "criado_em": "2026-01-01T00:00:00Z", "atualizado_em": "2026-01-01T00:00:00Z",
    }


def autenticar(role="admin"):
    app.dependency_overrides[get_current_user] = lambda: UsuarioAutenticado(
        id=CHAVE, colaborador_id=COLABORADOR, email="teste@example.com", role=role, ativo=True,
    )


@pytest.fixture(autouse=True)
def limpar():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def rpc_mock(monkeypatch, dados):
    banco = Mock()
    banco.rpc.return_value.execute.return_value.data = dados
    monkeypatch.setattr(repo, "get_supabase_client", lambda: banco)
    return banco


@pytest.mark.parametrize("criado,codigo", [(True, 201), (False, 200)])
def test_cadastro_sem_profissional_e_retry(client, monkeypatch, criado, codigo):
    autenticar()
    banco = rpc_mock(monkeypatch, {"sucesso": True, "criado": criado, "disponibilidade": disponibilidade()})
    response = client.post("/horarios", json=payload())
    assert response.status_code == codigo
    assert len(response.json()["vagas"]) == 2
    assert response.json()["vagas"][0]["massoterapeuta_id"] is None
    assert banco.rpc.call_args.args[1]["p_massoterapeuta_id"] is None
    assert banco.rpc.call_args.args[1]["p_capacidade"] == 2
    banco.table.assert_not_called()


@pytest.mark.parametrize("valor", [0, -1, 501, 1.5, "2", True, None])
def test_capacidade_invalida(client, monkeypatch, valor):
    autenticar()
    banco = rpc_mock(monkeypatch, {})
    assert client.post("/horarios", json={**payload(), "capacidade": valor}).status_code == 422
    banco.rpc.assert_not_called()


@pytest.mark.parametrize("inicio,fim", [("10:00", "09:00"), ("09:00", "09:00"), ("09:00+03:00", "10:00+03:00")])
def test_intervalo_invalido(client, inicio, fim):
    autenticar()
    assert client.post("/horarios", json={**payload(), "hora_inicio": inicio, "hora_fim": fim}).status_code == 422


def test_chave_idempotencia_obrigatoria(client):
    autenticar()
    dados = payload()
    dados.pop("chave_idempotencia")
    assert client.post("/horarios", json=dados).status_code == 422


@pytest.mark.parametrize("role,esperado", [(None, 401), ("colaborador", 403)])
def test_cadastro_exige_admin(client, role, esperado):
    if role:
        autenticar(role)
    assert client.post("/horarios", json=payload()).status_code == esperado


@pytest.mark.parametrize("erro,status", [
    ("horario_passado", 409), ("intervalo_existente", 409),
    ("intervalo_sobreposto", 409), ("idempotencia_conflitante", 409),
    ("capacidade_invalida", 422), ("periodo_invalido", 422), ("conflito_disponibilidade", 409),
    ("calendario_indisponivel", 409),
])
def test_conflitos_cadastro(client, monkeypatch, erro, status):
    autenticar()
    rpc_mock(monkeypatch, {"sucesso": False, "erro": erro})
    assert client.post("/horarios", json=payload()).status_code == status


@pytest.mark.parametrize("malformado", [
    {"sucesso": True},
    {"sucesso": True, "disponibilidade": disponibilidade()},
    {"sucesso": True, "criado": True, "disponibilidade": {**disponibilidade(), "vagas": [vaga()]}},
    {"sucesso": True, "criado": True, "disponibilidade": {**disponibilidade(), "vagas": [vaga(), vaga()]}},
])
def test_contrato_invalido_nao_simula_capacidade(client, monkeypatch, malformado):
    autenticar()
    rpc_mock(monkeypatch, malformado)
    assert client.post("/horarios", json=payload()).status_code == 500


def test_consulta_duas_vagas_por_data(client, monkeypatch):
    autenticar("colaborador")
    listar = Mock(return_value=[vaga(), {**vaga(2), "disponivel": False}])
    monkeypatch.setattr(horarios, "listar_horarios", listar)
    response = client.get("/horarios?data=2099-01-01")
    assert response.status_code == 200
    assert [r["disponivel"] for r in response.json()] == [True, False]
    assert listar.call_args.kwargs["dia"] == date(2099, 1, 1)


def test_consulta_periodo_invertido(client):
    autenticar("colaborador")
    assert client.get("/horarios?data_inicio=2099-02-01&data_fim=2099-01-01").status_code == 422


def test_repository_filtra_data_disponibilidade_profissional(monkeypatch):
    banco = Mock()
    query = banco.table.return_value.select.return_value
    query.eq.return_value = query
    query.or_.return_value = query
    query.gte.return_value = query
    query.lte.return_value = query
    query.order.return_value = query
    query.execute.return_value.data = [vaga()]
    monkeypatch.setattr(repo, "get_supabase_client", lambda: banco)
    result = repo.listar_horarios(True, GRUPO, date(2099, 1, 1), date(2099, 1, 2), date(2099, 1, 1))
    assert result == [vaga()]
    assert query.eq.call_args_list[0].args == ("disponivel", True)
    assert query.eq.call_args_list[-1].args == ("data", "2099-01-01")
    query.gte.assert_called_once_with("data", "2099-01-01")


def test_repository_livres_exclui_vagas_ja_iniciadas(monkeypatch):
    banco = Mock()
    query = banco.table.return_value.select.return_value
    query.eq.return_value = query
    query.or_.return_value = query
    query.order.return_value = query
    query.execute.return_value.data = []
    monkeypatch.setattr(repo, "get_supabase_client", lambda: banco)
    monkeypatch.setattr(repo, "agora_local", lambda: datetime(2026, 10, 13, 15, 30))
    assert repo.listar_horarios(apenas_disponiveis=True) == []
    query.or_.assert_called_once_with("data.gt.2026-10-13,and(data.eq.2026-10-13,hora_inicio.gt.15:30:00)")


def test_prevalidacao_nao_exige_profissional(monkeypatch):
    monkeypatch.setattr(service, "buscar_colaborador_por_id", lambda _: {"ativo": True})
    monkeypatch.setattr(service, "buscar_horario_por_id", lambda _: vaga())
    profissional = Mock(side_effect=AssertionError("Não deve consultar profissional"))
    monkeypatch.setattr(service, "buscar_massoterapeuta_por_id", profissional)
    contexto = service.validar_entidades_agendamento(AgendamentoCreate(colaborador_id=COLABORADOR, horario_id=VAGA))
    assert contexto.massoterapeuta == {}
    profissional.assert_not_called()


def test_reserva_http_sem_profissional(client, monkeypatch):
    autenticar("colaborador")
    banco = Mock()
    banco.rpc.return_value.execute.return_value.data = {"sucesso": True, "agendamento": reserva()}
    monkeypatch.setattr(agendamento_repo, "get_supabase_client", lambda: banco)
    response = client.post("/agendamentos", json={"colaborador_id": str(COLABORADOR), "horario_id": str(VAGA)})
    assert response.status_code == 201
    assert response.json()["massoterapeuta_id"] is None
    assert banco.rpc.call_args.args[1]["p_massoterapeuta_id"] is None


def test_grafo_estruturado_nao_chama_llm(client, monkeypatch):
    autenticar("colaborador")
    llm = Mock(side_effect=AssertionError("Não deve interpretar vaga informada"))
    monkeypatch.setattr(nodes, "interpretar_mensagem", llm)
    monkeypatch.setattr(service, "buscar_colaborador_por_id", lambda _: {"ativo": True})
    monkeypatch.setattr(service, "buscar_horario_por_id", lambda _: vaga())
    monkeypatch.setattr(service, "buscar_agendamentos_validos_no_intervalo", lambda **_: [])
    monkeypatch.setattr(service, "criar_agendamento_transacional", lambda *args: reserva())
    response = client.post("/graph/agendamentos", json={"colaborador_id": str(COLABORADOR), "horario_id": str(VAGA)})
    assert response.status_code == 201
    assert response.json()["agendamento"]["massoterapeuta_id"] is None
    llm.assert_not_called()


def test_interpretador_escolhe_vaga_sem_profissional(monkeypatch):
    monkeypatch.setattr(interpretador, "listar_horarios_disponiveis", lambda *_: [vaga(), vaga(2)])
    llm = Mock()
    llm.invoke.return_value.content = '{"escolhido":true,"horario_id":"' + str(VAGA) + '"}'
    monkeypatch.setattr(interpretador, "get_llm", lambda: llm)
    resultado = interpretador.interpretar_mensagem("Quero massagem na sexta à tarde.")
    assert resultado.horario_id == str(VAGA)
    assert resultado.massoterapeuta_id is None
    assert "massoterapeuta_id=" not in llm.invoke.call_args.args[0][1]["content"]


def test_interpretador_usa_mesma_data_no_filtro_e_prompt(monkeypatch):
    consultar = Mock(return_value=[vaga()])
    monkeypatch.setattr(interpretador, "listar_horarios_disponiveis", consultar)
    llm = Mock()
    llm.invoke.return_value.content = '{"escolhido":false}'
    monkeypatch.setattr(interpretador, "get_llm", lambda: llm)
    referencia = date(2099, 1, 1)
    interpretador.interpretar_mensagem("Sexta à tarde", hoje=referencia)
    consultar.assert_called_once_with(referencia)
    assert "2099-01-01" in llm.invoke.call_args.args[0][1]["content"]


def test_sugestoes_sem_profissional_e_sem_ids_inventados():
    result = interpretador._validar_sugestoes(
        [{"horario_id": str(VAGA)}, {"horario_id": "inventado"}], [vaga()]
    )
    assert len(result) == 1
    assert result[0]["massoterapeuta_id"] is None


def test_grafo_texto_valida_vaga_final(monkeypatch):
    monkeypatch.setattr(nodes, "interpretar_mensagem", lambda _: interpretador.Interpretacao(
        escolhido=True, horario_id=str(VAGA), justificativa="Vaga escolhida",
    ))
    monkeypatch.setattr(service, "buscar_colaborador_por_id", lambda _: {"ativo": True})
    monkeypatch.setattr(service, "buscar_horario_por_id", lambda _: vaga())
    monkeypatch.setattr(service, "buscar_agendamentos_validos_no_intervalo", lambda **_: [])
    rpc = Mock(side_effect=agendamento_repo.AgendamentoRPCError("horario_indisponivel"))
    monkeypatch.setattr(service, "criar_agendamento_transacional", rpc)
    result = agendamento_graph.invoke({"colaborador_id": str(COLABORADOR), "mensagem": "Sexta à tarde"})
    assert result["status_http"] == 409
    assert result["erro"] == "horario_indisponivel"
    rpc.assert_called_once()
