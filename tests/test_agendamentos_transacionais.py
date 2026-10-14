import os
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

os.environ.setdefault("JWT_SECRET_KEY", "segredo-de-teste-com-tamanho-adequado")

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.api.routes import agendamentos as routes
from app.core.security import get_current_user
from app.database.repositories import agendamentos as repo
from app.graphs.agendamento import nodes
from app.main import app
from app.schemas.agendamento import AgendamentoCreate, AgendamentoStatus
from app.schemas.auth import UsuarioAutenticado
from app.services import agendamentos as service


COLABORADOR = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
OUTRO = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
AGENDAMENTO = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
HORARIO = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


def registro(status="AGENDADO"):
    return {
        "id": str(AGENDAMENTO), "colaborador_id": str(COLABORADOR),
        "massoterapeuta_id": str(OUTRO), "horario_id": str(HORARIO),
        "data_agendamento": "2099-01-01", "hora_inicio": "10:00:00",
        "hora_fim": "10:30:00", "status": status,
        "criado_em": "2026-01-01T00:00:00Z", "atualizado_em": "2026-01-01T00:00:00Z",
    }


def payload():
    return AgendamentoCreate(
        colaborador_id=COLABORADOR, massoterapeuta_id=OUTRO, horario_id=HORARIO
    )


@pytest.fixture(autouse=True)
def isolamento():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def autenticar(role="colaborador"):
    app.dependency_overrides[get_current_user] = lambda: UsuarioAutenticado(
        id=AGENDAMENTO, colaborador_id=COLABORADOR,
        email="usuario@example.com", role=role, ativo=True,
    )


@pytest.fixture
def client():
    return TestClient(app)


def mock_rpc(monkeypatch, dados):
    client = Mock()
    client.rpc.return_value.execute.return_value.data = dados
    monkeypatch.setattr(repo, "get_supabase_client", lambda: client)
    return client


def test_criacao_usa_somente_rpc_e_extrai_agendamento(monkeypatch):
    client = mock_rpc(monkeypatch, {"sucesso": True, "agendamento": registro()})
    resultado = service.criar_agendamento_para_horario(payload())
    assert resultado["id"] == str(AGENDAMENTO)
    assert "sucesso" not in resultado
    client.table.assert_not_called()
    client.rpc.assert_called_once_with("criar_agendamento_transacional", {
        "p_colaborador_id": str(COLABORADOR),
        "p_massoterapeuta_id": str(OUTRO),
        "p_horario_id": str(HORARIO),
    })


@pytest.mark.parametrize("codigo,classe", [
    ("horario_indisponivel", service.HorarioIndisponivelError),
    ("intervalo_minimo", service.IntervaloAgendamentoError),
    ("colaborador_inativo", service.ColaboradorInativoError),
    ("horario_passado", service.HorarioPassadoError),
    ("conflito_concorrente", service.AgendamentoConcorrenteError),
])
def test_erro_de_reserva_nao_dispara_compensacao(monkeypatch, codigo, classe):
    client = mock_rpc(monkeypatch, {"sucesso": False, "erro": codigo})
    with pytest.raises(classe):
        service.criar_agendamento_para_horario(payload())
    client.table.assert_not_called()
    assert client.rpc.call_count == 1


@pytest.mark.parametrize("codigo,esperado", [
    ("colaborador_nao_encontrado", 404), ("colaborador_inativo", 409),
    ("massoterapeuta_nao_encontrado", 404), ("massoterapeuta_inativo", 409),
    ("horario_nao_encontrado", 404), ("horario_indisponivel", 409),
    ("horario_passado", 409), ("horario_massoterapeuta_invalido", 422),
    ("intervalo_minimo", 409), ("conflito_concorrente", 409),
])
def test_http_traduz_erros_rpc(client, monkeypatch, codigo, esperado):
    autenticar()
    mock_rpc(monkeypatch, {"sucesso": False, "erro": codigo})
    response = client.post("/agendamentos", json=payload().model_dump(mode="json"))
    assert response.status_code == esperado


@pytest.mark.parametrize("dados", [
    None, {}, {"sucesso": True}, {"sucesso": False}, {"sucesso": "false"},
    {"sucesso": True, "agendamento": {"id": str(AGENDAMENTO)}},
])
def test_contrato_rpc_invalido_rejeitado(monkeypatch, dados):
    mock_rpc(monkeypatch, dados)
    with pytest.raises(repo.AgendamentoRPCContractError):
        service.criar_agendamento_para_horario(payload())


@pytest.mark.parametrize("sqlstate,codigo", [
    ("23505", "horario_indisponivel"), ("23P01", "intervalo_minimo"),
    ("40001", "conflito_concorrente"), ("40P01", "conflito_concorrente"),
    ("55P03", "conflito_concorrente"),
])
def test_conflitos_postgresql_traduzidos(monkeypatch, sqlstate, codigo):
    client = mock_rpc(monkeypatch, {})
    client.rpc.return_value.execute.side_effect = APIError(
        {"code": sqlstate, "message": "erro-ficticio", "details": "", "hint": ""}
    )
    with pytest.raises(repo.AgendamentoRPCError) as exc:
        repo.criar_agendamento_transacional(COLABORADOR, OUTRO, HORARIO)
    assert exc.value.codigo == codigo


def test_falha_infra_nao_expoe_detalhes(client, monkeypatch):
    autenticar()
    rpc = mock_rpc(monkeypatch, {})
    rpc.rpc.return_value.execute.side_effect = RuntimeError("segredo-ficticio")
    response = client.post("/agendamentos", json=payload().model_dump(mode="json"))
    assert response.status_code == 500
    assert "segredo-ficticio" not in response.text


@pytest.mark.parametrize("status", ["AGENDADO", "CANCELADO", "CONCLUIDO", "FALTOU"])
def test_status_responde_objeto_sem_envelope(client, monkeypatch, status):
    autenticar("admin")
    rpc = mock_rpc(monkeypatch, {"sucesso": True, "agendamento": registro(status)})
    response = client.patch(f"/agendamentos/{AGENDAMENTO}/status", json={"status": status})
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert "sucesso" not in response.json()
    rpc.table.assert_not_called()


@pytest.mark.parametrize("codigo,esperado", [
    ("agendamento_nao_encontrado", 404), ("status_invalido", 422),
    ("transicao_invalida", 409), ("conflito_concorrente", 409),
])
def test_erros_status_http(client, monkeypatch, codigo, esperado):
    autenticar("admin")
    mock_rpc(monkeypatch, {"sucesso": False, "erro": codigo})
    assert client.patch(f"/agendamentos/{AGENDAMENTO}/status", json={"status": "AGENDADO"}).status_code == esperado


def test_status_inexistente_rejeitado_antes_rpc(client, monkeypatch):
    autenticar("admin")
    rpc = mock_rpc(monkeypatch, {})
    assert client.patch(f"/agendamentos/{AGENDAMENTO}/status", json={"status": "OUTRO"}).status_code == 422
    rpc.rpc.assert_not_called()


def test_status_somente_admin(client, monkeypatch):
    autenticar()
    rpc = mock_rpc(monkeypatch, {})
    assert client.patch(f"/agendamentos/{AGENDAMENTO}/status", json={"status": "CANCELADO"}).status_code == 403
    rpc.rpc.assert_not_called()


def test_service_rejeita_status_invalido(monkeypatch):
    rpc = mock_rpc(monkeypatch, {})
    with pytest.raises(service.StatusInvalidoError):
        service.alterar_status_agendamento(AGENDAMENTO, "OUTRO")
    rpc.rpc.assert_not_called()


def test_grafo_revalida_contexto_obsoleto_via_rpc(monkeypatch):
    mock_rpc(monkeypatch, {"sucesso": False, "erro": "intervalo_minimo"})
    result = nodes.executar_agendamento({
        **payload().model_dump(mode="json"),
        "data_agendamento": "2099-01-01",
        "colaborador": {}, "massoterapeuta": {}, "horario": {},
    })
    assert result["status_http"] == 409
    assert result["erro"] == "intervalo_minimo"


@pytest.mark.parametrize("codigo", ["colaborador_inativo", "horario_passado", "conflito_concorrente"])
def test_grafo_traduz_novos_erros(monkeypatch, codigo):
    mock_rpc(monkeypatch, {"sucesso": False, "erro": codigo})
    result = nodes.executar_agendamento({
        **payload().model_dump(mode="json"), "data_agendamento": "2099-01-01",
    })
    assert result["status_http"] == 409
    assert result["erro"] == codigo


def test_prevalidacao_grafo_rejeita_colaborador_inativo(monkeypatch):
    monkeypatch.setattr(service, "buscar_colaborador_por_id", lambda _: {"ativo": False})
    with pytest.raises(service.ColaboradorInativoError):
        service.validar_entidades_agendamento(payload())


def test_sql_canonico_presente_na_migration():
    raiz = Path(__file__).resolve().parents[1] / "database"
    assert (raiz / "rpc_agendamentos.sql").read_text(encoding="utf-8").strip() in (
        raiz / "migrations/003_disponibilidade_sem_profissional.sql"
    ).read_text(encoding="utf-8")
