from copy import deepcopy
from datetime import date
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents import cancelamento
from app.api.routes import graph_agendamentos
from app.core import security
from app.database.repositories import agendamentos as repository
from app.graphs.agendamento import nodes, nodes_cancelamento
from app.graphs.agendamento.graph import agendamento_graph
from app.main import app
from app.schemas.auth import UsuarioAutenticado
from app.services import agendamentos as service

COL = uuid4()
OUTRO = uuid4()


def reserva(**mudancas):
    return dict(id=str(uuid4()), colaborador_id=str(COL), horario_id=str(uuid4()),
                massoterapeuta_id=None, data_agendamento="2026-10-26", hora_inicio="09:40:00",
                hora_fim="10:10:00", status="AGENDADO", criado_em="2026-10-01T00:00:00Z",
                atualizado_em="2026-10-01T00:00:00Z") | mudancas


@pytest.fixture
def ambiente(monkeypatch):
    app.dependency_overrides.clear()
    app.dependency_overrides[security.get_current_user] = lambda: UsuarioAutenticado(
        id=uuid4(), email="c@example.com", role="colaborador", ativo=True, colaborador_id=COL,
    )
    monkeypatch.setattr(cancelamento, "data_local", lambda: date(2026,10,22))
    registros = [reserva()]
    listar = Mock(side_effect=lambda col: deepcopy([r for r in registros if r["colaborador_id"]==str(col)]))
    buscar = Mock(side_effect=lambda ident, col: next(
        (deepcopy(r) for r in registros if r["id"]==str(ident) and r["colaborador_id"]==str(col)), None))
    monkeypatch.setattr(repository, "listar_agendamentos_para_cancelamento", listar)
    monkeypatch.setattr(repository, "buscar_agendamento_do_colaborador", buscar)
    monkeypatch.setattr(service, "buscar_agendamento_do_colaborador", buscar)
    def rpc(ident, status):
        r = next(r for r in registros if r["id"]==str(ident))
        if r["status"] not in ("AGENDADO","CANCELADO"):
            raise repository.AgendamentoRPCError("transicao_invalida")
        r["status"] = status
        return deepcopy(r)
    atualizar = Mock(side_effect=rpc)
    monkeypatch.setattr(service, "atualizar_status_agendamento", atualizar)
    interpretar = Mock(side_effect=AssertionError("Cancelamento nao consulta vagas nem Gemini"))
    criar = Mock(side_effect=AssertionError("Cancelamento nao cria reservas"))
    monkeypatch.setattr(nodes, "interpretar_mensagem", interpretar)
    monkeypatch.setattr(nodes, "executar_criacao_agendamento", criar)
    with TestClient(app) as client:
        yield client, registros, atualizar, listar, buscar
    interpretar.assert_not_called()
    criar.assert_not_called()
    app.dependency_overrides.clear()


@pytest.mark.parametrize("mensagem",[
    "Quero cancelar meu agendamento.",
    "Cancela minha massagem do dia 26/10.",
    "N\u00e3o vou conseguir comparecer \u00e0 sess\u00e3o que marquei.",
    "Quero desmarcar minha massagem de amanh\u00e3.",
    "Quero cancelar minha sessao em 2026-10-26 as 09:40.",
    "Quero o cancelamento da minha massagem segunda de manha.",
])
def test_cancelamento_natural_no_grafo_real(ambiente, mensagem):
    client, registros, atualizar, listar, _ = ambiente
    if "amanha" in cancelamento.normalizar_mensagem(mensagem):
        registros[0]["data_agendamento"]="2026-10-23"
    resposta=client.post("/graph/agendamentos",json={"mensagem":mensagem})
    assert resposta.status_code==200
    assert resposta.json()["agendamento"]["status"]=="CANCELADO"
    assert "cancelado" in resposta.json()["mensagem"]
    atualizar.assert_called_once_with(UUID(registros[0]["id"]),"CANCELADO")
    listar.assert_called_once_with(COL)


def test_cancelamento_inexistente(ambiente):
    client, registros, atualizar, _, _=ambiente
    registros.clear()
    assert client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar meu agendamento."}).status_code==404
    atualizar.assert_not_called()


def test_nao_acessa_reserva_terceiro_nem_confia_no_corpo(ambiente):
    client, registros, atualizar, listar, buscar=ambiente
    registros[0]["colaborador_id"]=str(OUTRO)
    resposta=client.post("/graph/agendamentos",json={
        "mensagem":"Quero cancelar minha sessao.", "agendamento_id":registros[0]["id"],
    })
    assert resposta.status_code==404
    buscar.assert_called_once_with(UUID(registros[0]["id"]),COL)
    assert client.post("/graph/agendamentos",json={
        "colaborador_id":str(OUTRO),"mensagem":"Quero cancelar minha sessao.",
    }).status_code==403
    atualizar.assert_not_called()
    listar.assert_not_called()


def test_repete_cancelamento_sem_mudar_reserva_alvo(ambiente):
    client, registros, atualizar, _, _=ambiente
    pedido={"agendamento_id":registros[0]["id"]}
    assert client.post("/graph/agendamentos",json=pedido).status_code==200
    assert client.post("/graph/agendamentos",json=pedido).status_code==200
    assert len(registros)==1 and registros[0]["status"]=="CANCELADO"
    assert atualizar.call_count==2


def test_ambiguo_oferece_somente_reservas_proprias_e_exige_id(ambiente):
    client, registros, atualizar, _, _=ambiente
    registros.append(reserva())
    resposta=client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar minha massagem."})
    assert resposta.status_code==409
    assert resposta.json()["erro"]=="esclarecimento_necessario"
    opcoes=resposta.json()["sugestoes"]
    assert len(opcoes)==2
    assert set(opcoes[0])=={"agendamento_id","data","hora_inicio","status"}
    atualizar.assert_not_called()
    assert client.post("/graph/agendamentos",json={
        "agendamento_id":opcoes[1]["agendamento_id"],"mensagem":"Quero cancelar minha massagem.",
    }).status_code==200
    assert registros[0]["status"]=="AGENDADO"
    assert registros[1]["status"]=="CANCELADO"


@pytest.mark.parametrize("status",["CONCLUIDO","FALTOU"])
def test_estado_final_nao_cancelavel(ambiente,status):
    client, registros, _, _, _=ambiente
    registros[0]["status"]=status
    resposta=client.post("/graph/agendamentos",json={"agendamento_id":registros[0]["id"]})
    assert resposta.status_code==409
    assert resposta.json()["erro"]=="transicao_invalida"
    assert registros[0]["status"]==status


@pytest.mark.parametrize("mensagem",[
    "Nao quero cancelar meu agendamento.",
    "Como posso cancelar minha massagem?",
    "Quero cancelar e agendar outra massagem.",
    "Meu agendamento foi cancelado.",
    "Cancelar escolha",
    "Quero cancelar minha massagem dia 31/02.",
    "Quero cancelar minha massagem semana que vem.",
    "Cancela minha massagem as 25:10.",
    "Cancela minha massagem dia 26.",
    "Quero cancelar minha massagem dia 26/10 ou 27/10.",
    "Quero cancelar minha massagem sexta que vem.",
    "Quero cancelar minha massagem as dez.",
])
def test_pedido_impreciso_ou_nao_afirmativo_nao_altera(ambiente,mensagem):
    client, registros, atualizar, _, _=ambiente
    assert client.post("/graph/agendamentos",json={"mensagem":mensagem}).status_code==409
    atualizar.assert_not_called()
    assert registros[0]["status"]=="AGENDADO"


def test_cancelamento_independente_da_prontidao(ambiente,monkeypatch):
    client, _, _, _, _=ambiente
    gate=Mock(side_effect=AssertionError("Nao depender da geracao para cancelar"))
    monkeypatch.setattr(graph_agendamentos,"exigir_prontidao_http",gate)
    assert client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar meu agendamento."}).status_code==200
    gate.assert_not_called()


def test_servico_revalida_ownership_sem_escrita(ambiente):
    _, _, atualizar, _, _=ambiente
    with pytest.raises(service.AgendamentoNaoEncontradoError):
        service.cancelar_agendamento_do_colaborador(uuid4(),OUTRO)
    atualizar.assert_not_called()


def test_grafo_nao_aceita_identidade_apenas_do_corpo(ambiente):
    _, _, atualizar, _, _=ambiente
    resultado=agendamento_graph.invoke({"colaborador_id":str(COL),"mensagem":"Quero cancelar meu agendamento."})
    assert resultado["status_http"]==403
    atualizar.assert_not_called()


def test_nao_ignora_data_quando_id_tambem_foi_informado(ambiente):
    client, registros, atualizar, _, _=ambiente
    assert client.post("/graph/agendamentos",json={
        "agendamento_id":registros[0]["id"],"mensagem":"Cancela minha massagem de amanha.",
    }).status_code==404
    atualizar.assert_not_called()


def test_erro_infra_sem_expor_segredos(ambiente):
    client, _, atualizar, listar, _=ambiente
    listar.side_effect=RuntimeError("SEGREDO_FICTICIO")
    resposta=client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar meu agendamento."})
    assert resposta.status_code==503 and "SEGREDO" not in resposta.text
    atualizar.assert_not_called()


def test_contrato_e_seletores_incompativeis(ambiente):
    client, registros, atualizar, _, _=ambiente
    assert client.post("/graph/agendamentos",json={
        "agendamento_id":registros[0]["id"],"horario_id":registros[0]["horario_id"],
    }).status_code==422
    assert client.post("/graph/agendamentos",json={
        "mensagem":"Quero cancelar minha massagem.","horario_id":registros[0]["horario_id"],
    }).status_code==422
    spec=client.get("/openapi.json").json()
    resposta=spec["paths"]["/graph/agendamentos"]["post"]["responses"]["200"]
    assert resposta["content"]["application/json"]["schema"]["$ref"].endswith("AgendamentoGraphResponse")
    atualizar.assert_not_called()


def test_sem_token_e_sem_identidade_forjada(ambiente):
    client, _, atualizar, _, _=ambiente
    assert client.post("/graph/agendamentos",json={
        "mensagem":"Quero cancelar minha massagem.","colaborador_autenticado_id":str(OUTRO),
    }).status_code==422
    app.dependency_overrides.clear()
    assert client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar minha massagem."}).status_code==401
    atualizar.assert_not_called()


def test_cancelado_e_nova_reserva_nao_mudam_alvo_de_retry_generico(ambiente):
    client, registros, atualizar, _, _=ambiente
    registros[0]["status"]="CANCELADO"
    registros.append(reserva())
    assert client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar minha massagem."}).status_code==409
    atualizar.assert_not_called()


def test_repository_busca_id_e_colaborador_na_mesma_consulta(monkeypatch):
    banco=Mock()
    query=banco.table.return_value.select.return_value
    query.eq.return_value=query
    query.limit.return_value.execute.return_value.data=[]
    monkeypatch.setattr(repository,"get_supabase_client",lambda:banco)
    ident=uuid4()
    assert repository.buscar_agendamento_do_colaborador(ident,COL) is None
    assert [c.args for c in query.eq.call_args_list]==[("id",str(ident)),("colaborador_id",str(COL))]


def test_servico_recusa_resultado_incorreto_do_repository(monkeypatch):
    gravar=Mock()
    monkeypatch.setattr(service,"buscar_agendamento_do_colaborador",lambda *_:reserva(colaborador_id=str(OUTRO)))
    monkeypatch.setattr(service,"alterar_status_agendamento",gravar)
    with pytest.raises(service.AgendamentoNaoEncontradoError):
        service.cancelar_agendamento_do_colaborador(uuid4(),COL)
    gravar.assert_not_called()


def test_lista_truncada_pelo_supabase_exige_identificador(ambiente):
    client, _, gravar, listar, _=ambiente
    listar.side_effect=repository.ConsultaAgendamentosIncompletaError()
    resposta=client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar minha massagem."})
    assert resposta.status_code==409
    gravar.assert_not_called()


@pytest.mark.parametrize("total",[None,2,1])
def test_repository_nao_confunde_lista_truncada_com_alvo_unico(monkeypatch,total):
    banco=Mock()
    query=banco.table.return_value.select.return_value
    query.eq.return_value=query
    query.order.return_value=query
    query.execute.return_value.data=[reserva()]
    query.execute.return_value.count=total
    monkeypatch.setattr(repository,"get_supabase_client",lambda:banco)
    if total==1:
        assert len(repository.listar_agendamentos_para_cancelamento(COL))==1
    else:
        with pytest.raises(repository.ConsultaAgendamentosIncompletaError):
            repository.listar_agendamentos_para_cancelamento(COL)
    banco.table.return_value.select.assert_called_once_with("*",count="exact")
    query.eq.assert_called_once_with("colaborador_id",str(COL))
