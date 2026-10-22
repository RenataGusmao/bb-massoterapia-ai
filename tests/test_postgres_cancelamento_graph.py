"""Real cancellation RPC through HTTP/LangGraph, on the guarded disposable cluster."""
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tests.test_postgres_agendamentos import connect, database, roles_banco, psycopg
from tests.test_postgres_agenda_automatica import agenda_database, agenda, gerar, vaga, reservar, bloquear
from app.core import security
from app.database.repositories import agendamentos as repository
from app.main import app
from app.services import agendamentos as service


@pytest.fixture
def cliente_graph(agenda,monkeypatch):
    admin,colaborador=agenda
    with connect() as conn:
        conn.execute("set role service_role")
        gerar(conn)
        slot=vaga(conn)
        reserva=reservar(conn,colaborador,slot[0])
        assert reserva["sucesso"]
        usuario=conn.execute("""insert into public.usuarios(email,senha_hash,role,colaborador_id)
            values('graph@example.com','ficticio','colaborador',%s) returning id""",(colaborador,)).fetchone()[0]

    def buscar_usuario(ident):
        with connect() as conn:
            conn.execute("set role service_role")
            return conn.execute("select to_jsonb(u) from public.usuarios u where id=%s",(ident,)).fetchone()[0]
    def buscar_colaborador(ident):
        with connect() as conn:
            conn.execute("set role service_role")
            return conn.execute("select to_jsonb(c) from public.colaboradores c where id=%s",(ident,)).fetchone()[0]
    def buscar(ident,col):
        with connect() as conn:
            conn.execute("set role service_role")
            row=conn.execute("select to_jsonb(a) from public.agendamentos a where id=%s and colaborador_id=%s",
                             (ident,col)).fetchone()
            return row[0] if row else None
    def listar(col):
        with connect() as conn:
            conn.execute("set role service_role")
            return [r[0] for r in conn.execute(
                "select to_jsonb(a) from public.agendamentos a where colaborador_id=%s",(col,)).fetchall()]
    class ClienteRPC:
        def rpc(self,nome,parametros):
            assert nome=="atualizar_status_agendamento"
            def execute():
                with connect() as conn:
                    conn.execute("set role service_role")
                    dados=conn.execute("select public.atualizar_status_agendamento(%s,%s)",
                        (UUID(parametros["p_agendamento_id"]),parametros["p_status"])).fetchone()[0]
                    return SimpleNamespace(data=dados)
            return SimpleNamespace(execute=execute)
    monkeypatch.setattr(security,"buscar_usuario_por_id",buscar_usuario)
    monkeypatch.setattr(security,"buscar_colaborador_por_id",buscar_colaborador)
    monkeypatch.setattr(repository,"buscar_agendamento_do_colaborador",buscar)
    monkeypatch.setattr(repository,"listar_agendamentos_para_cancelamento",listar)
    monkeypatch.setattr(service,"buscar_agendamento_do_colaborador",buscar)
    monkeypatch.setattr(repository,"get_supabase_client",lambda:ClienteRPC())
    app.dependency_overrides.clear()
    token=security.criar_access_token(usuario,"colaborador")
    with TestClient(app) as client:
        client.headers["Authorization"]="Bearer "+token
        yield client,admin,colaborador,slot,reserva["agendamento"]
    app.dependency_overrides.clear()


@pytest.mark.parametrize("bloqueado",[False,True])
def test_pg_grafo_cancela_preserva_grade_bloqueios_e_historico(cliente_graph,bloqueado):
    client,admin,colaborador,slot,reserva=cliente_graph
    with connect() as conn:
        if bloqueado:
            conn.execute("set role service_role")
            bloquear(conn,admin,slot,dia_inteiro=True)
        ids=conn.execute("select id from public.horarios_disponiveis order by id").fetchall()
        lotes=conn.execute("select to_jsonb(d) from public.disponibilidades d order by id").fetchall()
        calendario=conn.execute("select * from public.calendario_atendimento order by data").fetchall()
        excecoes=conn.execute("select * from public.bloqueios_agenda order by id").fetchall()
    pedido={"mensagem":"Quero cancelar minha massagem.","agendamento_id":reserva["id"]}
    for _ in range(2):
        resposta=client.post("/graph/agendamentos",json=pedido)
        assert resposta.status_code==200
        assert resposta.json()["agendamento"]["status"]=="CANCELADO"
    with connect() as conn:
        conn.execute("set role service_role")
        assert conn.execute("select disponivel from public.horarios_disponiveis where id=%s",(slot[0],)).fetchone()[0]
        assert conn.execute("select disponivel from public.vagas_agenda where id=%s",(slot[0],)).fetchone()[0] is not bloqueado
        assert gerar(conn)["criados"]==0
        assert conn.execute("select id from public.horarios_disponiveis order by id").fetchall()==ids
        assert conn.execute("select to_jsonb(d) from public.disponibilidades d order by id").fetchall()==lotes
        assert conn.execute("select * from public.calendario_atendimento order by data").fetchall()==calendario
        assert conn.execute("select * from public.bloqueios_agenda order by id").fetchall()==excecoes
        assert conn.execute("select status from public.agendamentos where id=%s",(UUID(reserva["id"]),)).fetchone()[0]=="CANCELADO"
        if not bloqueado:
            nova=reservar(conn,colaborador,slot[0])
            assert nova["sucesso"]  # Cancelled history does not count against the 15-day exclusion.
    if not bloqueado:
        assert client.post("/graph/agendamentos",json=pedido).status_code==200
        with connect() as conn:
            assert not conn.execute("select disponivel from public.horarios_disponiveis where id=%s",(slot[0],)).fetchone()[0]
            assert conn.execute("select count(*) from public.agendamentos where horario_id=%s",(slot[0],)).fetchone()[0]==2


@pytest.mark.parametrize("status",["CONCLUIDO","FALTOU"])
def test_pg_grafo_respeita_estados_finais(cliente_graph,status):
    client,_,_,slot,reserva=cliente_graph
    with connect() as conn:
        conn.execute("set role service_role")
        assert conn.execute("select public.atualizar_status_agendamento(%s,%s)",
                            (UUID(reserva["id"]),status)).fetchone()[0]["sucesso"]
    resposta=client.post("/graph/agendamentos",json={"agendamento_id":reserva["id"]})
    assert resposta.status_code==409
    with connect() as conn:
        assert conn.execute("select status from public.agendamentos where id=%s",(UUID(reserva["id"]),)).fetchone()[0]==status
        assert not conn.execute("select disponivel from public.horarios_disponiveis where id=%s",(slot[0],)).fetchone()[0]


def test_pg_grafo_ambiguo_nao_cancela_e_esclarecimento_funciona(cliente_graph):
    client,_,colaborador,slot,reserva=cliente_graph
    with connect() as conn:
        conn.execute("set role service_role")
        outra=conn.execute("""select id from public.vagas_agenda where disponivel and data>=%s
            order by data,hora_inicio limit 1""",(slot[1]+timedelta(days=15),)).fetchone()[0]
        segunda=reservar(conn,colaborador,outra)
        assert segunda["sucesso"]
    resposta=client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar meu agendamento."})
    assert resposta.status_code==409
    assert len(resposta.json()["sugestoes"])==2
    with connect() as conn:
        assert conn.execute("select count(*) from public.agendamentos where status='AGENDADO'").fetchone()[0]==2
    assert client.post("/graph/agendamentos",json={"agendamento_id":reserva["id"]}).status_code==200
    # A generic replay must not silently target the remaining active reservation.
    assert client.post("/graph/agendamentos",json={"mensagem":"Quero cancelar meu agendamento."}).status_code==409


def test_pg_grafo_nao_cancela_terceiro_e_ownership_nao_e_mutavel_pelo_backend(cliente_graph):
    client,_,colaborador,slot,reserva=cliente_graph
    with connect() as conn:
        outro=conn.execute("insert into public.colaboradores(nome,matricula,email) values('Outro','2','outro@example.com') returning id").fetchone()[0]
        conn.execute("set role service_role")
        outra=conn.execute("select id from public.vagas_agenda where disponivel and data>%s order by data,hora_inicio limit 1",
                           (slot[1],)).fetchone()[0]
        terceiro=reservar(conn,outro,outra)
        assert terceiro["sucesso"]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update public.agendamentos set colaborador_id=%s where id=%s",
                         (outro,UUID(reserva["id"])))
    assert client.post("/graph/agendamentos",json={"agendamento_id":terceiro["agendamento"]["id"]}).status_code==404
    assert client.post("/graph/agendamentos",json={
        "colaborador_id":str(outro),"mensagem":"Quero cancelar meu agendamento.",
    }).status_code==403
    assert client.post("/graph/agendamentos",json={"agendamento_id":reserva["id"]},
                       headers={"Authorization":""}).status_code==401
    with connect() as conn:
        assert conn.execute("select count(*) from public.agendamentos where status='AGENDADO'").fetchone()[0]==2
