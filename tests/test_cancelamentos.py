import os
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import interpretador
from app.agents.interpretador import InterpretacaoCancelamento
from app.api.routes import graph_agendamentos
from app.core.security import verificar_api_key
from app.graphs.agendamento import nodes
from app.graphs.agendamento.graph import agendamento_graph
from app.services import agendamentos as service
from app.services.agendamentos import (
    AgendamentoNaoCancelavelError,
    AgendamentoNaoEncontradoError,
)

HOJE = date(2026, 10, 15)
COLABORADOR = str(uuid4())
OUTRO_COLABORADOR = str(uuid4())

AG_TERCA = {
    "id": "11111111-1111-1111-1111-111111111111",
    "colaborador_id": COLABORADOR,
    "data_agendamento": "2026-10-20",
    "hora_inicio": "09:00:00",
    "hora_fim": "10:00:00",
    "status": "AGENDADO",
}
AG_QUINTA = {
    "id": "22222222-2222-2222-2222-222222222222",
    "colaborador_id": COLABORADOR,
    "data_agendamento": "2026-11-12",
    "hora_inicio": "15:00:00",
    "hora_fim": "16:00:00",
    "status": "AGENDADO",
}


class LLMFalso:
    def __init__(self, content):
        self.content = content
        self.chamadas = 0

    def invoke(self, mensagens):
        self.chamadas += 1
        return SimpleNamespace(content=self.content)


def _com_llm(monkeypatch, content) -> LLMFalso:
    llm = LLMFalso(content)
    monkeypatch.setattr(interpretador, "get_llm", lambda: llm)
    return llm


def _com_agendamentos(monkeypatch, agendamentos):
    monkeypatch.setattr(
        interpretador,
        "listar_agendamentos_ativos_do_colaborador",
        lambda colaborador_id, a_partir_de: agendamentos,
    )


@pytest.mark.parametrize("intencao", ["agendar", "cancelar", "remarcar", "outra"])
def test_intencao_valida(monkeypatch, intencao):
    _com_llm(monkeypatch, f'{{"intencao": "{intencao}"}}')

    assert interpretador.identificar_intencao("qualquer mensagem") == intencao


def test_intencao_desconhecida_vira_outra(monkeypatch):
    _com_llm(monkeypatch, '{"intencao": "apagar_banco"}')

    assert interpretador.identificar_intencao("qualquer mensagem") == "outra"


def test_intencao_com_content_em_lista(monkeypatch):
    _com_llm(monkeypatch, [{"type": "text", "text": '{"intencao": "cancelar"}'}])

    assert interpretador.identificar_intencao("cancela") == "cancelar"


def test_intencao_com_resposta_invalida_levanta_erro(monkeypatch):
    _com_llm(monkeypatch, "não sei")

    with pytest.raises(interpretador.InterpretacaoError):
        interpretador.identificar_intencao("cancela")


def test_cancelamento_escolha_valida(monkeypatch):
    _com_agendamentos(monkeypatch, [AG_TERCA, AG_QUINTA])
    _com_llm(
        monkeypatch,
        f'{{"escolhido": true, "agendamento_id": "{AG_TERCA["id"]}", "justificativa": "terça"}}',
    )

    r = interpretador.interpretar_pedido_cancelamento("cancela o de terça", COLABORADOR, HOJE)

    assert r.escolhido is True
    assert r.agendamento_id == AG_TERCA["id"]


def test_cancelamento_id_inventado_nao_passa(monkeypatch):
    _com_agendamentos(monkeypatch, [AG_TERCA])
    _com_llm(
        monkeypatch,
        '{"escolhido": true, "agendamento_id": "99999999-9999-9999-9999-999999999999"}',
    )

    r = interpretador.interpretar_pedido_cancelamento("cancela", COLABORADOR, HOJE)

    assert r.escolhido is False
    assert r.agendamento_id is None


def test_cancelamento_inconclusivo_lista_agendamentos(monkeypatch):
    _com_agendamentos(monkeypatch, [AG_TERCA, AG_QUINTA])
    _com_llm(monkeypatch, '{"escolhido": false, "motivo": "ambíguo"}')

    r = interpretador.interpretar_pedido_cancelamento("cancela minha massagem", COLABORADOR, HOJE)

    assert r.escolhido is False
    assert "terça-feira, 20/10/2026 às 09:00" in r.motivo
    assert "quinta-feira, 12/11/2026 às 15:00" in r.motivo


def test_cancelamento_sem_agendamentos_nao_chama_llm(monkeypatch):
    _com_agendamentos(monkeypatch, [])
    llm = _com_llm(monkeypatch, "{}")

    r = interpretador.interpretar_pedido_cancelamento("cancela", COLABORADOR, HOJE)

    assert r.escolhido is False
    assert llm.chamadas == 0
    assert "não tem agendamentos" in r.motivo


def _preparar_servico(monkeypatch, agendamento):
    chamadas = []
    monkeypatch.setattr(service, "buscar_agendamento_por_id", lambda _id: agendamento)

    def _atualizar(agendamento_id, status):
        chamadas.append(status.value)
        return {**agendamento, "status": status.value}

    monkeypatch.setattr(service, "alterar_status_agendamento", _atualizar)
    return chamadas


def test_servico_cancela_agendamento_proprio(monkeypatch):
    chamadas = _preparar_servico(monkeypatch, AG_TERCA)

    resultado = service.cancelar_agendamento_do_colaborador(COLABORADOR, AG_TERCA["id"], HOJE)

    assert resultado["status"] == "CANCELADO"
    assert chamadas == ["CANCELADO"]


def test_servico_nao_cancela_de_outro_colaborador(monkeypatch):
    chamadas = _preparar_servico(monkeypatch, AG_TERCA)

    with pytest.raises(AgendamentoNaoEncontradoError):
        service.cancelar_agendamento_do_colaborador(OUTRO_COLABORADOR, AG_TERCA["id"], HOJE)

    assert chamadas == []


def test_servico_agendamento_inexistente(monkeypatch):
    _preparar_servico(monkeypatch, None)

    with pytest.raises(AgendamentoNaoEncontradoError):
        service.cancelar_agendamento_do_colaborador(COLABORADOR, AG_TERCA["id"], HOJE)


@pytest.mark.parametrize("status", ["CANCELADO", "CONCLUIDO", "FALTOU"])
def test_servico_nao_cancela_status_diferente_de_agendado(monkeypatch, status):
    chamadas = _preparar_servico(monkeypatch, {**AG_TERCA, "status": status})

    with pytest.raises(AgendamentoNaoCancelavelError):
        service.cancelar_agendamento_do_colaborador(COLABORADOR, AG_TERCA["id"], HOJE)

    assert chamadas == []


def test_servico_nao_cancela_agendamento_passado(monkeypatch):
    chamadas = _preparar_servico(monkeypatch, {**AG_TERCA, "data_agendamento": "2026-10-10"})

    with pytest.raises(AgendamentoNaoCancelavelError):
        service.cancelar_agendamento_do_colaborador(COLABORADOR, AG_TERCA["id"], HOJE)

    assert chamadas == []


def _grafo(monkeypatch, intencao, interpretacao=None, cancelamento=None):
    monkeypatch.setattr(nodes, "identificar_intencao", lambda mensagem: intencao)
    monkeypatch.setattr(nodes, "hoje_local", lambda: HOJE)
    if interpretacao is not None:
        monkeypatch.setattr(
            nodes, "interpretar_pedido_cancelamento", lambda mensagem, colaborador_id: interpretacao
        )
    if cancelamento is not None:
        monkeypatch.setattr(nodes, "cancelar_agendamento_do_colaborador", cancelamento)


def _invocar(mensagem="cancela minha massagem"):
    return agendamento_graph.invoke({"colaborador_id": COLABORADOR, "mensagem": mensagem})


def test_grafo_cancelamento_com_sucesso(monkeypatch):
    _grafo(
        monkeypatch,
        "cancelar",
        InterpretacaoCancelamento(escolhido=True, agendamento_id=AG_TERCA["id"], justificativa="ok"),
        lambda colaborador_id, agendamento_id, hoje: {**AG_TERCA, "status": "CANCELADO"},
    )

    r = _invocar()

    assert r["sucesso"] is True
    assert r["acao"] == "cancelar"
    assert r["status_http"] == 200
    assert r["agendamento"]["status"] == "CANCELADO"


def test_grafo_cancelamento_inconclusivo(monkeypatch):
    _grafo(
        monkeypatch,
        "cancelar",
        InterpretacaoCancelamento(escolhido=False, motivo="Qual deles?"),
    )

    r = _invocar()

    assert r["sucesso"] is False
    assert r["status_http"] == 422
    assert r["erro"] == "cancelamento_inconclusivo"
    assert r["mensagem_resposta"] == "Qual deles?"


def test_grafo_cancelamento_nao_permitido(monkeypatch):
    def _recusar(colaborador_id, agendamento_id, hoje):
        raise AgendamentoNaoCancelavelError("Somente agendamentos com status AGENDADO.")

    _grafo(
        monkeypatch,
        "cancelar",
        InterpretacaoCancelamento(escolhido=True, agendamento_id=AG_TERCA["id"]),
        _recusar,
    )

    r = _invocar()

    assert r["sucesso"] is False
    assert r["status_http"] == 409
    assert r["erro"] == "agendamento_nao_cancelavel"


@pytest.mark.parametrize(
    "intencao,erro",
    [("remarcar", "remarcacao_nao_suportada"), ("outra", "intencao_nao_suportada")],
)
def test_grafo_intencoes_nao_suportadas(monkeypatch, intencao, erro):
    _grafo(monkeypatch, intencao)

    r = _invocar("qualquer coisa")

    assert r["sucesso"] is False
    assert r["status_http"] == 422
    assert r["erro"] == erro


def test_grafo_agendar_segue_fluxo_antigo(monkeypatch):
    _grafo(monkeypatch, "agendar")
    monkeypatch.setattr(
        nodes,
        "interpretar_mensagem",
        lambda mensagem: SimpleNamespace(escolhido=False, motivo="Sem horário."),
    )

    r = _invocar("quero massagem amanhã")

    assert r["status_http"] == 422
    assert r["erro"] == "interpretacao_inconclusiva"


def test_grafo_pedido_estruturado_nao_chama_classificador(monkeypatch):
    def _nao_deveria_chamar(mensagem):
        raise AssertionError("classificador não deveria ser chamado")

    monkeypatch.setattr(nodes, "identificar_intencao", _nao_deveria_chamar)

    def _falhar_validacao(*args, **kwargs):
        raise nodes.ColaboradorNaoEncontradoError("x")

    monkeypatch.setattr(nodes, "validar_entidades_agendamento", _falhar_validacao)

    r = agendamento_graph.invoke(
        {
            "colaborador_id": COLABORADOR,
            "massoterapeuta_id": str(uuid4()),
            "horario_id": str(uuid4()),
        }
    )

    assert r["intencao"] == "agendar"
    assert r["erro"] == "colaborador_nao_encontrado"


class GrafoFalso:
    def __init__(self, resultado):
        self.resultado = resultado

    def invoke(self, state):
        return self.resultado


def _cliente(monkeypatch, resultado) -> TestClient:
    monkeypatch.setattr(graph_agendamentos, "agendamento_graph", GrafoFalso(resultado))
    app = FastAPI()
    app.include_router(graph_agendamentos.router)
    app.dependency_overrides[verificar_api_key] = lambda: None
    return TestClient(app)


def _corpo():
    return {"colaborador_id": COLABORADOR, "mensagem": "cancela minha massagem"}


def test_rota_cancelamento_devolve_200(monkeypatch):
    cliente = _cliente(
        monkeypatch,
        {
            "sucesso": True,
            "acao": "cancelar",
            "mensagem_resposta": "Agendamento cancelado com sucesso.",
            "agendamento": {**AG_TERCA, "status": "CANCELADO"},
        },
    )

    resposta = cliente.post("/graph/agendamentos", json=_corpo())

    assert resposta.status_code == 200
    assert resposta.json()["acao"] == "cancelar"
    assert resposta.json()["agendamento"]["status"] == "CANCELADO"


def test_rota_agendamento_continua_201(monkeypatch):
    cliente = _cliente(
        monkeypatch,
        {
            "sucesso": True,
            "acao": "agendar",
            "mensagem_resposta": "Agendamento realizado com sucesso.",
            "agendamento": AG_TERCA,
        },
    )

    resposta = cliente.post("/graph/agendamentos", json=_corpo())

    assert resposta.status_code == 201
    assert resposta.json()["acao"] == "agendar"


def test_rota_erro_usa_status_do_grafo(monkeypatch):
    cliente = _cliente(
        monkeypatch,
        {
            "sucesso": False,
            "status_http": 422,
            "mensagem_resposta": "Qual deles?",
            "erro": "cancelamento_inconclusivo",
        },
    )

    resposta = cliente.post("/graph/agendamentos", json=_corpo())

    assert resposta.status_code == 422
    assert resposta.json()["erro"] == "cancelamento_inconclusivo"


LIVE = os.getenv("RUN_LIVE_LLM") == "1"
RUNS = int(os.getenv("LIVE_RUNS", "3"))

live = pytest.mark.skipif(
    not LIVE, reason="defina RUN_LIVE_LLM=1 e GOOGLE_API_KEY para chamar o Gemini"
)

CASOS_INTENCAO = [
    ("quero massagem amanhã de manhã", "agendar"),
    ("tem horário na sexta?", "agendar"),
    ("agenda pra mim segunda às 14h", "agendar"),
    ("cancela minha massagem", "cancelar"),
    ("não vou poder ir na sexta, pode desmarcar", "cancelar"),
    ("preciso desmarcar meu horário", "cancelar"),
    ("cancelar agendamento de segunda", "cancelar"),
    ("quero remarcar minha massagem para quarta", "remarcar"),
    ("trocar meu horário de sexta para segunda", "remarcar"),
    ("qual o endereço da clínica?", "outra"),
    ("oi", "outra"),
]


@live
@pytest.mark.live
@pytest.mark.parametrize("mensagem,esperada", CASOS_INTENCAO)
def test_live_intencao(mensagem, esperada):
    obtidas = [interpretador.identificar_intencao(mensagem) for _ in range(RUNS)]

    assert obtidas == [esperada] * RUNS, f"'{mensagem}' esperado {esperada}, obtido {obtidas}"


CASOS_CANCELAMENTO = [
    ("dois", "cancela o de terça", AG_TERCA["id"]),
    ("dois", "cancela o do dia 12/11", AG_QUINTA["id"]),
    ("dois", "cancela o da tarde", AG_QUINTA["id"]),
    ("dois", "cancela minha massagem", None),
    ("dois", "cancela o de sábado", None),
    ("um", "cancela minha massagem", AG_TERCA["id"]),
    ("um", "cancela a de terça", AG_TERCA["id"]),
    ("um", "cancela a de sexta", None),
]


@live
@pytest.mark.live
@pytest.mark.parametrize("cenario,mensagem,esperado", CASOS_CANCELAMENTO)
def test_live_escolha_do_agendamento(monkeypatch, cenario, mensagem, esperado):
    ativos = [AG_TERCA, AG_QUINTA] if cenario == "dois" else [AG_TERCA]
    _com_agendamentos(monkeypatch, ativos)

    obtidos = []
    for _ in range(RUNS):
        r = interpretador.interpretar_pedido_cancelamento(mensagem, COLABORADOR, HOJE)
        obtidos.append(r.agendamento_id if r.escolhido else None)

    assert obtidos == [esperado] * RUNS, f"'{mensagem}' esperado {esperado}, obtido {obtidos}"