import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import horarios
from app.core.config import get_settings
from app.core.security import get_current_user
from app.main import app
from app.schemas.agenda import BloqueioCreate
from app.schemas.auth import UsuarioAutenticado
from app.services import agenda_automatica as service


@pytest.fixture(autouse=True)
def limpar():
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.parametrize("hoje", [date(2026, 12, 20), date(2028, 2, 15), date(2026, 4, 1)])
def test_calendario_31_dias_nacionais_e_virada_de_ano(hoje):
    calendario = service.calendario_nacional(hoje)
    assert len(calendario) == len({x["data"] for x in calendario}) == 31
    assert calendario[0]["data"] == hoje.isoformat()
    assert calendario[-1]["data"] == (hoje + timedelta(days=30)).isoformat()
    datas = {x["data"]: x["feriado"] for x in calendario}
    for dia in ("2026-12-25", "2027-01-01", "2026-04-21"):
        if dia in datas:
            assert datas[dia]


def test_pontos_facultativos_nao_sao_feriados_nacionais():
    datas = {x["data"]: x["feriado"] for x in service.calendario_nacional(date(2026, 2, 1))}
    assert not datas["2026-02-17"]


def test_worker_usa_rpc_existente_de_geracao_sem_dados_pessoais(monkeypatch):
    banco = Mock()
    banco.rpc.return_value.execute.return_value.data = {"criados": 200}
    banco.rpc.side_effect = [
        Mock(execute=Mock(return_value=Mock(data={"criados": 200}))),
        Mock(execute=Mock(return_value=Mock(data={
            "pronta": True, "inicio": "2026-12-20", "fim": "2027-01-19",
        }))),
    ]
    monkeypatch.setattr(service, "get_supabase_client", lambda: banco)
    monkeypatch.setattr(service, "data_local", lambda: date(2026, 12, 20))
    assert service.sincronizar_agenda() == {"criados": 200}
    nome, parametros = banco.rpc.call_args_list[0].args
    assert nome == "gerar_agenda_automatica"
    assert parametros["p_capacidade"] == 1
    assert len(parametros["p_calendario"]) == 31


def test_worker_limita_capacidade(monkeypatch):
    monkeypatch.setenv("AGENDA_CAPACIDADE", "501")
    get_settings.cache_clear()
    with pytest.raises(ValueError):
        service.sincronizar_agenda()


def test_worker_nao_registra_excecoes_com_segredos(monkeypatch, caplog):
    monkeypatch.setattr(service, "sincronizar_agenda", Mock(side_effect=RuntimeError("SEGREDO_FICTICIO")))
    asyncio.run(service.executar_sincronizacao())
    assert "Falha na geracao" in caplog.text
    assert "SEGREDO_FICTICIO" not in caplog.text


def test_lifespan_gera_no_inicio_e_cancela_worker(monkeypatch):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    main = importlib.import_module("app.main")
    iniciar = AsyncMock()
    esperar = asyncio.Event()
    async def loop():
        await esperar.wait()
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(agenda_geracao_automatica=True))
    async def iniciar_com_worker():
        await iniciar()
        await loop()
    monkeypatch.setattr(main, "iniciar_agenda", iniciar_com_worker)
    async def executar():
        async with main.lifespan(app):
            await asyncio.sleep(0)
            iniciar.assert_awaited_once()
    asyncio.run(executar())


def test_worker_renova_a_cada_hora(monkeypatch):
    from unittest.mock import AsyncMock
    chamadas = []
    async def sleep(segundos):
        chamadas.append(segundos)
        if len(chamadas) == 61:
            raise asyncio.CancelledError
    sincronizar = AsyncMock()
    monkeypatch.setattr(service, "agora_local", lambda: datetime(2026, 12, 1, 12))
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    monkeypatch.setattr(service, "executar_sincronizacao", sincronizar)
    monkeypatch.setattr(service, "_dia_sincronizado", service.data_local())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.manter_agenda())
    assert chamadas == [60] * 61
    sincronizar.assert_awaited_once()


@pytest.mark.parametrize("mudanca", [
    {"hora_inicio": "09:40"}, {"hora_fim": "10:10"},
    {"hora_inicio": "10:10", "hora_fim": "09:40"},
    {"hora_inicio": "09:40+03:00", "hora_fim": "10:10+03:00"},
])
def test_bloqueio_rejeita_intervalos_invalidos(mudanca):
    with pytest.raises(ValueError):
        BloqueioCreate(chave_idempotencia=uuid4(), data="2026-12-01", motivo="Sem atendimento", **mudanca)


@pytest.mark.parametrize("rota,metodo,body", [
    ("/horarios/sincronizar", "post", None),
    ("/horarios/bloqueios", "post", {}),
    ("/horarios/bloqueios/" + str(uuid4()), "delete", None),
])
def test_excecoes_apenas_admin(rota, metodo, body):
    app.dependency_overrides[get_current_user] = lambda: UsuarioAutenticado(
        id=uuid4(), colaborador_id=uuid4(), email="c@example.com", role="colaborador", ativo=True,
    )
    with TestClient(app) as client:
        kwargs = {"json": body} if body is not None else {}
        assert client.request(metodo, rota, **kwargs).status_code == 403


def test_bloqueio_http_e_idempotencia_encaminhados(monkeypatch):
    admin = uuid4()
    chave = uuid4()
    app.dependency_overrides[get_current_user] = lambda: UsuarioAutenticado(
        id=admin, email="admin@example.com", role="admin", ativo=True,
    )
    gravar = Mock(return_value={"id": str(chave), "data": "2026-12-01",
                               "hora_inicio": None, "hora_fim": None, "motivo": "Sem atendimento", "ativo": True})
    monkeypatch.setattr(horarios, "criar_bloqueio", gravar)
    with TestClient(app) as client:
        assert client.post("/horarios/bloqueios", json={
            "chave_idempotencia": str(chave), "data": "2026-12-01", "motivo": "Sem atendimento",
        }).status_code == 201
    assert gravar.call_args.args[0] == admin
    assert gravar.call_args.args[1].chave_idempotencia == chave
