import asyncio
import importlib
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.schemas.auth import UsuarioAutenticado
from app.schemas.agendamento import AgendamentoCreate
from app.services import agenda_automatica as service, agendamentos

pytestmark = pytest.mark.usefixtures("prontidao_real")


@pytest.fixture
def prontidao_real():
    service.reiniciar_prontidao()
    app.dependency_overrides.clear()
    yield
    service.reiniciar_prontidao()
    app.dependency_overrides.clear()


@pytest.fixture
def banco(monkeypatch):
    client = Mock()
    def rpc(nome, params):
        if nome == "gerar_agenda_automatica":
            data = {"criados": 0, "preservados": 200, "conflitos": 0}
        else:
            calendario = params["p_calendario"]
            data = {"pronta": True, "inicio": calendario[0]["data"], "fim": calendario[-1]["data"]}
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=data))
    client.rpc.side_effect = rpc
    monkeypatch.setattr(service, "get_supabase_client", lambda: client)
    return client


def test_primeira_sincronizacao_falha_fecha_api_e_preserva_diagnostico(banco):
    banco.rpc.side_effect = ConnectionError("segredo ficticio")
    assert asyncio.run(service.executar_sincronizacao()) is False
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        resposta = client.get("/ready")
        assert resposta.status_code == 503
        assert resposta.headers["Retry-After"] == "60"
        assert "segredo" not in resposta.text


@pytest.mark.parametrize("resultado", [None, {}, {"pronta": False}, {"pronta": True}])
def test_ausencia_de_excecao_nao_basta_para_prontidao(banco, resultado):
    banco.rpc.return_value.execute.return_value.data = resultado
    banco.rpc.side_effect = None
    with pytest.raises(service.AgendaNaoProntaError):
        service.sincronizar_agenda()
    with pytest.raises(service.AgendaNaoProntaError):
        service.exigir_agenda_pronta()


def test_recuperacao_exige_nova_geracao_e_confirmacao_no_banco(banco):
    rpc = banco.rpc.side_effect
    banco.rpc.side_effect = ConnectionError()
    assert asyncio.run(service.executar_sincronizacao()) is False
    banco.rpc.side_effect = rpc
    assert asyncio.run(service.executar_sincronizacao()) is True
    service.exigir_agenda_pronta()
    assert banco.rpc.call_args.args[0] == "verificar_prontidao_agenda"


def test_indisponibilidade_posterior_invalida_prontidao(banco):
    service.sincronizar_agenda()
    banco.rpc.side_effect = ConnectionError()
    with pytest.raises(service.AgendaNaoProntaError):
        service.exigir_agenda_pronta()
    assert service._dia_sincronizado is None


def test_virada_de_data_falha_fechada_ate_recompor_janela(banco, monkeypatch):
    service.sincronizar_agenda()
    amanha = service.data_local() + timedelta(days=1)
    monkeypatch.setattr(service, "data_local", lambda: amanha)
    with pytest.raises(service.AgendaNaoProntaError):
        service.exigir_agenda_pronta()
    service.sincronizar_agenda()
    service.exigir_agenda_pronta()


@pytest.mark.parametrize("rota", ["/agendamentos", "/graph/agendamentos"])
def test_reserva_nao_chega_a_rpc_ou_grafo_sem_agenda(rota, monkeypatch):
    from app.api.routes import agendamentos as rota_agendamentos, graph_agendamentos
    colaborador = uuid4()
    app.dependency_overrides[get_current_user] = lambda: UsuarioAutenticado(
        id=uuid4(), email="c@example.com", role="colaborador", ativo=True, colaborador_id=colaborador,
    )
    criar = Mock()
    grafo = Mock()
    monkeypatch.setattr(rota_agendamentos, "criar_agendamento_para_horario", criar)
    monkeypatch.setattr(graph_agendamentos.agendamento_graph, "invoke", grafo)
    with TestClient(app) as client:
        resposta = client.post(rota, json={"colaborador_id": str(colaborador), "horario_id": str(uuid4())})
        assert resposta.status_code == 503
        if rota == "/graph/agendamentos":
            from app.schemas.agendamento import AgendamentoGraphErrorResponse
            erro = AgendamentoGraphErrorResponse.model_validate(resposta.json())
            assert erro.erro == "agenda_nao_pronta"
        assert client.post(rota, json={
            "colaborador_id": str(uuid4()), "horario_id": str(uuid4()),
        }).status_code == 403
    criar.assert_not_called()
    grafo.assert_not_called()


def test_servico_central_tambem_bloqueia_reserva_sem_prontidao(monkeypatch):
    criar = Mock()
    monkeypatch.setattr(agendamentos, "criar_agendamento_transacional", criar)
    with pytest.raises(agendamentos.AgendaNaoSincronizadaError) as erro:
        agendamentos.executar_criacao_agendamento(AgendamentoCreate(
            colaborador_id=uuid4(), horario_id=uuid4(),
        ))
    assert erro.value.status_http == 503
    criar.assert_not_called()


def test_health_ready_e_recuperacao_manual_admin(banco):
    app.dependency_overrides[get_current_user] = lambda: UsuarioAutenticado(
        id=uuid4(), email="a@example.com", role="admin", ativo=True,
    )
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.post("/horarios/sincronizar").status_code == 200
        assert client.get("/ready").json() == {"status": "ready"}
        assert client.post("/horarios/sincronizar").status_code == 200
        assert client.get("/ready").status_code == 200
    assert sum(c.args[0] == "gerar_agenda_automatica" for c in banco.rpc.call_args_list) == 2


def test_reinicio_ou_retomada_nao_reutiliza_flag_antiga(banco, monkeypatch):
    main = importlib.import_module("app.main")
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(agenda_geracao_automatica=True))
    async def iniciar():
        assert service._dia_sincronizado is None
        await service.executar_sincronizacao()
        await asyncio.Event().wait()
    monkeypatch.setattr(main, "iniciar_agenda", iniciar)
    async def executar():
        for _ in range(2):
            async with main.lifespan(app):
                with pytest.raises(service.AgendaNaoProntaError):
                    service.exigir_agenda_pronta()
                for _ in range(200):
                    if service._dia_sincronizado is not None:
                        break
                    await asyncio.sleep(0.01)
                service.exigir_agenda_pronta()
    asyncio.run(executar())


def test_worker_tenta_recuperacao_sem_reiniciar_processo(monkeypatch):
    esperas = []
    async def sleep(segundos):
        esperas.append(segundos)
        if len(esperas) == 3:
            raise asyncio.CancelledError()
    sync = AsyncMock(return_value=False)
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    monkeypatch.setattr(service, "executar_sincronizacao", sync)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.manter_agenda())
    assert sync.await_count == 2
    assert all(0 < n <= 60 for n in esperas)


def test_openapi_documenta_ready_e_liveness():
    schema = app.openapi()
    assert "503" in schema["paths"]["/ready"]["get"]["responses"]
    assert "/health" in schema["paths"]


def test_primeira_sincronizacao_lenta_nao_bloqueia_health(banco, monkeypatch):
    from threading import Event
    import time
    main = importlib.import_module("app.main")
    iniciou, liberar = Event(), Event()
    rpc = banco.rpc.side_effect
    def demorado(nome, parametros):
        if nome == "gerar_agenda_automatica":
            iniciou.set()
            assert liberar.wait(timeout=5)
        return rpc(nome, parametros)
    banco.rpc.side_effect = demorado
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(agenda_geracao_automatica=True))
    with TestClient(app) as client:
        try:
            assert iniciou.wait(timeout=5)
            assert client.get("/health").status_code == 200
            assert client.get("/ready").status_code == 503
        finally:
            liberar.set()
        for _ in range(200):
            if service._dia_sincronizado is not None:
                break
            time.sleep(0.01)
        resposta = client.get("/ready")
        assert resposta.status_code == 200
        assert resposta.headers["Cache-Control"] == "no-store"
