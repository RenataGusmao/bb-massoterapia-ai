"""Current incremental migrations on the existing guarded local-only PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, time as hora, timedelta
from threading import Barrier
import time
from uuid import UUID, uuid4

import pytest

from tests.test_postgres_agendamentos import connect, database, roles_banco, ROOT, psycopg
from app.services.agenda_automatica import calendario_nacional
from app.core.datas import data_local


@pytest.fixture(scope="module")
def agenda_database(database):
    with connect() as conn:
        # Demonstrate that retired accounts are preserved, not promoted or deleted.
        conta = conn.execute("insert into public.usuarios(email,senha_hash,role) values('legado@example.com','ficticio','terceirizada') returning id").fetchone()[0]
        conn.execute((ROOT/"database/migrations/006_remover_terceirizada.sql").read_text(encoding="utf-8"))
        conn.execute((ROOT/"database/migrations/007_agenda_automatica.sql").read_text(encoding="utf-8"))
        conn.execute((ROOT/"database/migrations/008_prontidao_agenda.sql").read_text(encoding="utf-8"))
        assert conn.execute("select role,ativo from public.usuarios where id=%s",(conta,)).fetchone()==("terceirizada",False)
        try:
            yield
        finally:
            conn.execute("drop function if exists public.verificar_prontidao_agenda(jsonb)")
            conn.execute("drop view if exists public.vagas_agenda")
            conn.execute("drop trigger if exists agendamentos_validar_calendario on public.agendamentos")
            conn.execute("drop function if exists public.validar_reserva_calendario()")
            conn.execute("drop trigger if exists disponibilidades_validar_calendario on public.disponibilidades")
            conn.execute("drop function if exists public.validar_disponibilidade_calendario()")
            conn.execute("drop function if exists public.gerar_agenda_automatica(jsonb,integer)")
            conn.execute("drop function if exists public.registrar_bloqueio_agenda(uuid,uuid,date,time,time,text)")
            conn.execute("drop function if exists public.desativar_bloqueio_agenda(uuid,uuid)")
            conn.execute("drop function if exists public.consultar_agenda_leitura(date,date)")
            conn.execute("drop function if exists public.agenda_permite(date,time,time)")
            conn.execute("drop table if exists public.bloqueios_agenda,public.calendario_atendimento")
            conn.execute("drop function if exists public.serializar_excecao_agenda()")
            conn.execute("drop trigger if exists usuarios_perfis_mvp on public.usuarios")
            conn.execute("drop function if exists public.validar_perfil_usuario_mvp()")


@pytest.fixture
def agenda(agenda_database):
    with connect() as conn:
        conn.execute("truncate public.usuarios_agenda_lotes,public.usuarios,public.agendamentos,public.horarios_disponiveis,public.disponibilidades,public.massoterapeutas,public.colaboradores,public.bloqueios_agenda,public.calendario_atendimento")
        admin = conn.execute("insert into public.usuarios(email,senha_hash,role) values('admin@example.com','ficticio','admin') returning id").fetchone()[0]
        colaborador = conn.execute("insert into public.colaboradores(nome,matricula,email) values('Teste','1','c@example.com') returning id").fetchone()[0]
        return admin,colaborador


def gerar(conn, capacidade=1):
    from psycopg.types.json import Jsonb
    return conn.execute("select public.gerar_agenda_automatica(%s,%s)",(Jsonb(calendario_nacional(data_local())),capacidade)).fetchone()[0]


def vaga(conn):
    return conn.execute("select id,data,hora_inicio,hora_fim from public.vagas_agenda where disponivel and data>current_date order by data,hora_inicio limit 1").fetchone()


def bloquear(conn, admin, slot, chave=None, dia_inteiro=False):
    return conn.execute("select public.registrar_bloqueio_agenda(%s,%s,%s,%s,%s,'Excecao de teste')",
                        (admin,chave or uuid4(),slot[1],None if dia_inteiro else slot[2],None if dia_inteiro else slot[3])).fetchone()[0]


def reservar(conn,colaborador,slot):
    return conn.execute("select public.criar_agendamento_transacional(%s,null,%s)",(colaborador,slot)).fetchone()[0]


def test_pg_geracao_dias_uteis_horarios_e_feriados(agenda):
    with connect() as conn:
        conn.execute("set role service_role")
        resultado=gerar(conn)
        assert resultado["criados"]>0
        assert conn.execute("select count(*) from public.horarios_disponiveis h join public.calendario_atendimento c on c.data=h.data where c.feriado or extract(isodow from h.data)>5").fetchone()[0]==0
        assert conn.execute("select count(*) from public.horarios_disponiveis where hora_fim-hora_inicio<>interval '30 minutes' or (hora_inicio>=time '11:40' and hora_inicio<time '13:00')").fetchone()[0]==0
        assert conn.execute("select max(n) from (select count(*) n from public.horarios_disponiveis group by data)x").fetchone()[0]==10


def test_pg_geracao_repetida_preserva_capacidade_ids_e_reservas(agenda):
    admin,colaborador=agenda
    with connect() as conn:
        conn.execute("set role service_role")
        gerar(conn,2)
        slot=vaga(conn)
        reserva=reservar(conn,colaborador,slot[0])
        assert reserva["sucesso"]
        antes=conn.execute("select id,disponivel from public.horarios_disponiveis order by id").fetchall()
        assert gerar(conn,1)["criados"]==0
        assert conn.execute("select id,disponivel from public.horarios_disponiveis order by id").fetchall()==antes
        assert conn.execute("select count(*) from public.agendamentos").fetchone()[0]==1


@pytest.mark.parametrize("dia_inteiro",[False,True])
def test_pg_bloqueio_persiste_cancelamento_regeracao_e_desbloqueio(agenda,dia_inteiro):
    admin,colaborador=agenda
    with connect() as conn:
        conn.execute("set role service_role")
        gerar(conn)
        slot=vaga(conn)
        reserva=reservar(conn,colaborador,slot[0])
        assert reserva["sucesso"]
        chave=uuid4()
        b=bloquear(conn,admin,slot,chave,dia_inteiro)
        assert bloquear(conn,admin,slot,chave,dia_inteiro)==b
        assert gerar(conn)["criados"]==0
        assert conn.execute("select public.atualizar_status_agendamento(%s,'CANCELADO')",(reserva["agendamento"]["id"],)).fetchone()[0]["sucesso"]
        assert not conn.execute("select disponivel from public.vagas_agenda where id=%s",(slot[0],)).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            reservar(conn,colaborador,slot[0])
        assert conn.execute("select status from public.agendamentos").fetchone()[0]=="CANCELADO"
        assert conn.execute("select public.desativar_bloqueio_agenda(%s,%s)",(admin,UUID(b["id"]))).fetchone()[0]
        assert conn.execute("select disponivel from public.vagas_agenda where id=%s",(slot[0],)).fetchone()[0]
        assert reservar(conn,colaborador,slot[0])["sucesso"]


def test_pg_duas_geracoes_concorrentes_sem_duplicar(agenda):
    def executar():
        with connect() as conn:
            conn.execute("set role service_role")
            return gerar(conn)
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados=list(pool.map(lambda _:executar(),range(2)))
    assert sum(r["criados"]>0 for r in resultados)==1
    with connect() as conn:
        assert conn.execute("select count(*) from (select disponibilidade_id,numero_vaga from public.horarios_disponiveis group by 1,2 having count(*)>1)x").fetchone()[0]==0


def test_pg_bloqueio_antes_da_geracao_nao_cria_intervalo(agenda):
    admin,_=agenda
    with connect() as conn:
        gerar(conn)
        slot=vaga(conn)
        conn.execute("truncate public.usuarios_agenda_lotes,public.agendamentos,public.horarios_disponiveis,public.disponibilidades")
        bloquear(conn,admin,slot)
        gerar(conn)
        assert conn.execute("select count(*) from public.horarios_disponiveis where data=%s and hora_inicio=%s",(slot[1],slot[2])).fetchone()[0]==0


def test_pg_regra_15_dias_permanece(agenda):
    _,colaborador=agenda
    with connect() as conn:
        conn.execute("set role service_role")
        gerar(conn)
        slot=vaga(conn)
        assert reservar(conn,colaborador,slot[0])["sucesso"]
        outra=conn.execute("select id from public.vagas_agenda where disponivel and data between %s and %s order by data,hora_inicio limit 1",(slot[1],slot[1]+timedelta(days=14))).fetchone()[0]
        assert reservar(conn,colaborador,outra)["erro"]=="intervalo_minimo"


@pytest.mark.parametrize("role",["anon","authenticated"])
def test_pg_acl_privadas_e_rpcs(agenda,role):
    with connect() as conn:
        for objeto in ("calendario_atendimento","bloqueios_agenda","vagas_agenda"):
            assert not conn.execute("select has_table_privilege(%s,%s,'select,insert,update,delete')",(role,"public."+objeto)).fetchone()[0]
        for funcao in ("gerar_agenda_automatica(jsonb,integer)","consultar_agenda_leitura(date,date)","registrar_bloqueio_agenda(uuid,uuid,date,time,time,text)",
                       "criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean)"):
            assert not conn.execute("select has_function_privilege(%s,%s,'execute')",(role,"public."+funcao)).fetchone()[0]
        conn.execute("set role "+role)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from public.vagas_agenda")


def test_pg_agenda_sem_pii_e_perfil_apos_reaplicacao(agenda):
    with connect() as conn:
        conn.execute((ROOT/"database/migrations/006_remover_terceirizada.sql").read_text(encoding="utf-8"))
        conn.execute((ROOT/"database/migrations/007_agenda_automatica.sql").read_text(encoding="utf-8"))
        conn.execute("set role service_role")
        gerar(conn)
        hoje=data_local()
        dados=conn.execute("select public.consultar_agenda_leitura(%s,%s)",(hoje,hoje+timedelta(days=30))).fetchone()[0]
        assert dados["itens"]
        assert set(dados["itens"][0])=={"data","hora_inicio","hora_fim","capacidade","agendados","disponiveis"}
        assert conn.execute("select to_regprocedure('public.provisionar_terceirizada(uuid,text,text,uuid[])')").fetchone()[0] is None
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("insert into public.usuarios(email,senha_hash,role,ativo) values('invalida@example.com','x','terceirizada',false)")


def test_pg_calendario_incompleto_falha_sem_criar_vagas(agenda):
    with connect() as conn:
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            conn.execute("select public.gerar_agenda_automatica('[]'::jsonb,1)")
        assert conn.execute("select count(*) from public.horarios_disponiveis").fetchone()[0]==0


def test_pg_cadastro_manual_nao_burla_calendario(agenda):
    with connect() as conn:
        conn.execute("set role service_role")
        gerar(conn)
        sabado=conn.execute("select data from public.calendario_atendimento where extract(isodow from data)=6 order by data limit 1").fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("select public.criar_disponibilidade_transacional(%s,%s,'09:40','10:10',2,null,true)",(uuid4(),sabado))
        assert conn.execute("select count(*) from public.disponibilidades where data=%s",(sabado,)).fetchone()[0]==0


def test_pg_bloqueio_concorrente_impede_reserva_que_aguarda(agenda):
    from threading import Event
    admin,colaborador=agenda
    iniciou=Event()
    with connect() as conn:
        gerar(conn)
        slot=vaga(conn)
    def tentar_reserva():
        with connect() as worker:
            worker.execute("set role service_role")
            worker.execute("set statement_timeout='10s'")
            iniciou.set()
            with pytest.raises(psycopg.errors.CheckViolation):
                reservar(worker,colaborador,slot[0])
    with ThreadPoolExecutor(max_workers=1) as pool, connect() as bloqueador:
        with bloqueador.transaction():
            bloquear(bloqueador,admin,slot)
            futuro=pool.submit(tentar_reserva)
            assert iniciou.wait(timeout=5)
        futuro.result(timeout=15)
    with connect() as conn:
        assert conn.execute("select count(*) from public.agendamentos").fetchone()[0]==0
        assert conn.execute("select disponivel from public.horarios_disponiveis where id=%s",(slot[0],)).fetchone()[0]
        assert not conn.execute("select disponivel from public.vagas_agenda where id=%s",(slot[0],)).fetchone()[0]


def test_pg_concorrencia_na_mesma_vaga_preservada(agenda):
    from threading import Barrier
    _,colaborador=agenda
    with connect() as conn:
        gerar(conn)
        slot=vaga(conn)
        outro=conn.execute("insert into public.colaboradores(nome,matricula,email) values('Teste','2','outro@example.com') returning id").fetchone()[0]
    barreira=Barrier(2)
    def executar(pessoa):
        with connect() as conn:
            conn.execute("set role service_role")
            conn.execute("set statement_timeout='10s'")
            barreira.wait(timeout=5)
            return reservar(conn,pessoa,slot[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados=list(pool.map(executar,[colaborador,outro]))
    assert sum(x["sucesso"] for x in resultados)==1


def test_pg_calendario_feriado_falha_fechado_apos_cancelar(agenda):
    from psycopg.types.json import Jsonb
    _,colaborador=agenda
    with connect() as conn:
        conn.execute("set role service_role")
        gerar(conn)
        slot=vaga(conn)
        reserva=reservar(conn,colaborador,slot[0])
        calendario=calendario_nacional(data_local())
        for entrada in calendario:
            if entrada["data"]==slot[1].isoformat():
                entrada["feriado"]=True
        conn.execute("select public.gerar_agenda_automatica(%s,1)",(Jsonb(calendario),))
        assert conn.execute("select public.atualizar_status_agendamento(%s,'CANCELADO')",(reserva["agendamento"]["id"],)).fetchone()[0]["sucesso"]
        with pytest.raises(psycopg.errors.CheckViolation):
            reservar(conn,colaborador,slot[0])


def prontidao(conn, calendario=None):
    from psycopg.types.json import Jsonb
    return conn.execute("select public.verificar_prontidao_agenda(%s)",
                        (Jsonb(calendario if calendario is not None else calendario_nacional(data_local())),)).fetchone()[0]


def test_pg_prontidao_exige_calendario_e_vagas_reais(agenda):
    with connect() as conn:
        conn.execute("set role service_role")
        assert not prontidao(conn)["pronta"]
        gerar(conn,2)
        assert prontidao(conn)["pronta"]
        assert prontidao(conn)["intervalos_pendentes"]==0
        conn.execute("reset role")
        slot=vaga(conn)
        conn.execute("delete from public.horarios_disponiveis where id=%s",(slot[0],))
        assert not prontidao(conn)["pronta"]
        # The generator intentionally preserves damaged existing lots; readiness must not mask them.
        gerar(conn,2)
        assert not prontidao(conn)["pronta"]


def test_pg_calendario_incompleto_ou_divergente_nao_pronto(agenda):
    with connect() as conn:
        gerar(conn)
        conn.execute("delete from public.calendario_atendimento where data=%s",(data_local(),))
        assert not prontidao(conn)["pronta"]
        gerar(conn)
        conn.execute("update public.calendario_atendimento set feriado=not feriado where data=%s",(data_local(),))
        assert not prontidao(conn)["pronta"]


def test_pg_toda_janela_bloqueada_pronta_sem_vagas(agenda):
    admin,_=agenda
    with connect() as conn:
        conn.execute("set role service_role")
        for n in range(31):
            dia=data_local()+timedelta(days=n)
            conn.execute("select public.registrar_bloqueio_agenda(%s,%s,%s,null,null,'Sem atendimento')",
                         (admin,uuid4(),dia))
        assert gerar(conn)["criados"]==0
        estado=prontidao(conn)
        assert estado["pronta"]
        assert estado["intervalos_esperados"]==0
        assert conn.execute("select count(*) from public.horarios_disponiveis").fetchone()[0]==0
        assert gerar(conn)["criados"]==0
        assert prontidao(conn)==estado


def test_pg_feriados_e_finais_de_semana_nao_exigem_lotes(agenda):
    with connect() as conn:
        gerar(conn)
        assert prontidao(conn)["pronta"]
        assert conn.execute("select count(*) from public.disponibilidades d join public.calendario_atendimento c using(data) where c.feriado or extract(isodow from d.data)>5").fetchone()[0]==0


def test_pg_reservas_e_capacidade_ocupada_nao_invalidam_prontidao(agenda):
    _,colaborador=agenda
    with connect() as conn:
        conn.execute("set role service_role")
        gerar(conn)
        slot=vaga(conn)
        assert reservar(conn,colaborador,slot[0])["sucesso"]
        antes=conn.execute("select id,disponivel from public.horarios_disponiveis order by id").fetchall()
        assert prontidao(conn)["pronta"]
        assert gerar(conn)["criados"]==0
        assert prontidao(conn)["pronta"]
        assert conn.execute("select id,disponivel from public.horarios_disponiveis order by id").fetchall()==antes


@pytest.mark.parametrize("role",["anon","authenticated"])
def test_pg_verificacao_prontidao_privada_e_invoker(agenda,role):
    with connect() as conn:
        conn.execute((ROOT/"database/migrations/008_prontidao_agenda.sql").read_text(encoding="utf-8"))
        assert not conn.execute("select prosecdef from pg_proc where oid='public.verificar_prontidao_agenda(jsonb)'::regprocedure").fetchone()[0]
        assert not conn.execute("select has_function_privilege(%s,'public.verificar_prontidao_agenda(jsonb)','execute')",(role,)).fetchone()[0]
        conn.execute("set role "+role)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            prontidao(conn)


def test_pg_sql_pre_validacao_somente_catalogos_compativel(agenda):
    with connect() as conn:
        with conn.transaction():
            conn.execute("set transaction read only")
            linhas=conn.execute((ROOT/"database/diagnostico_pre_agenda_automatica.sql").read_text(encoding="utf-8")).fetchall()
        assert len(linhas)==16
        assert not [linha for linha in linhas if linha[2].startswith("SIM")]


def test_pg_rpc_prontidao_realmente_somente_leitura(agenda):
    with connect() as conn:
        gerar(conn)
        conn.execute("set role service_role")
        with conn.transaction():
            conn.execute("set transaction read only")
            assert prontidao(conn)["pronta"]


def preparar_disputa(agenda):
    from psycopg.types.json import Jsonb
    admin,colaborador=agenda
    calendario=calendario_nacional(data_local())
    dia=next(date.fromisoformat(x["data"]) for x in calendario
             if not x["feriado"] and date.fromisoformat(x["data"])>data_local()
             and date.fromisoformat(x["data"]).weekday()<5)
    with connect() as conn:
        outro=conn.execute("insert into public.colaboradores(nome,matricula,email) values('Teste','2','outro@example.com') returning id").fetchone()[0]
        conn.execute("set role service_role")
        conn.execute("""insert into public.calendario_atendimento
            select (j->>'data')::date,(j->>'feriado')::boolean from jsonb_array_elements(%s) j""",
                     (Jsonb(calendario),))
        lote=conn.execute("select public.criar_disponibilidade_transacional(%s,%s,'09:40','10:10',2,null,true)",
                          (uuid4(),dia)).fetchone()[0]["disponibilidade"]
        reserva=reservar(conn,colaborador,UUID(lote["vagas"][0]["id"]))
        assert reserva["sucesso"]
        return {
            "admin":admin,"colaborador":outro,"dia":dia,"lote":lote,
            "reserva":reserva["agendamento"],"chave":uuid4(),
            "livre":(UUID(lote["vagas"][1]["id"]),dia,hora(9,40),hora(10,10)),
            "manual":(None,dia,hora(10,10),hora(10,40)),
        }


def configurar_worker(conn):
    conn.execute("set statement_timeout='10s'")
    conn.execute("set deadlock_timeout='100ms'")
    conn.execute("set role service_role")


def executar_operacao(conn,operacao,contexto):
    try:
        if operacao=="gerar":
            return gerar(conn)
        if operacao=="manual":
            return conn.execute(
                "select public.criar_disponibilidade_transacional(%s,%s,'10:10','10:40',2,null,true)",
                (contexto["chave"],contexto["dia"])).fetchone()[0]
        if operacao=="reservar":
            return reservar(conn,contexto["colaborador"],contexto["livre"][0])
        if operacao=="bloquear":
            return bloquear(conn,contexto["admin"],contexto["alvo_bloqueio"])
        raise AssertionError(operacao)
    except psycopg.errors.CheckViolation as exc:
        if operacao not in ("manual","reservar") or "fora do calendario" not in exc.diag.message_primary:
            raise
        return {"erro":"calendario_bloqueado"}


def aguardar_bloqueio(monitor,pid,bloqueador):
    limite=time.monotonic()+5
    while time.monotonic()<limite:
        if bloqueador in monitor.execute("select pg_blocking_pids(%s)",(pid,)).fetchone()[0]:
            return
        time.sleep(.01)
    raise AssertionError("A segunda sessao nao aguardou o lock esperado")


def conferir_resultado(operacao,resultado,permitir_bloqueio=False):
    if operacao=="gerar":
        assert resultado["conflitos"]==0
    elif operacao=="bloquear":
        assert resultado["ativo"]
    else:
        # Do not let an RPC's exception handler hide a deadlock as a business conflict.
        assert (resultado.get("sucesso")
                or (operacao=="manual" and resultado.get("erro")=="intervalo_existente")
                or (permitir_bloqueio and resultado.get("erro")=="calendario_bloqueado"))


def conferir_historico(contexto):
    with connect() as conn:
        ids={str(r[0]) for r in conn.execute("select id from public.horarios_disponiveis").fetchall()}
        assert {h["id"] for h in contexto["lote"]["vagas"]}<=ids
        assert conn.execute("select capacidade from public.disponibilidades where id=%s",
                            (UUID(contexto["lote"]["id"]),)).fetchone()[0]==2
        assert conn.execute("select to_jsonb(a) from public.agendamentos a where id=%s",
                            (UUID(contexto["reserva"]["id"]),)).fetchone()[0]==contexto["reserva"]
        assert not conn.execute("select disponivel from public.horarios_disponiveis where id=%s",
                                (UUID(contexto["reserva"]["horario_id"]),)).fetchone()[0]
        assert conn.execute("""select count(*) from (
            select disponibilidade_id,numero_vaga from public.horarios_disponiveis
            group by 1,2 having count(*)>1)x""").fetchone()[0]==0
        assert conn.execute("""select count(*) from public.horarios_disponiveis h
            where h.disponivel is distinct from not exists(
                select 1 from public.agendamentos a where a.horario_id=h.id and a.status<>'CANCELADO')""").fetchone()[0]==0


@pytest.mark.parametrize("repeticao",range(4))
@pytest.mark.parametrize("ordem",["a_primeiro","b_primeiro","simultaneo"])
@pytest.mark.parametrize("operacoes",[
    ("gerar","manual"),("gerar","reservar"),("bloquear","reservar"),
    ("gerar","gerar"),("manual","bloquear"),
])
def test_pg_disputas_agenda_sem_deadlock(agenda,operacoes,ordem,repeticao):
    contexto=preparar_disputa(agenda)
    contexto["alvo_bloqueio"]=contexto["manual"] if "manual" in operacoes else contexto["livre"]
    with connect() as a, connect() as b, connect() as monitor, ThreadPoolExecutor(max_workers=2) as pool:
        configurar_worker(a)
        configurar_worker(b)
        if ordem=="simultaneo":
            barreira=Barrier(2)
            def simultaneo(conn,op):
                barreira.wait(timeout=5)
                return executar_operacao(conn,op,contexto)
            futuros=[pool.submit(simultaneo,c,op) for c,op in zip((a,b),operacoes)]
            resultados=[f.result(timeout=15) for f in futuros]
        else:
            primeiro,segundo=(0,1) if ordem=="a_primeiro" else (1,0)
            conexoes=(a,b)
            resultados=[None,None]
            # Keep the first transaction open until the peer is demonstrably waiting.
            with conexoes[primeiro].transaction():
                resultados[primeiro]=executar_operacao(conexoes[primeiro],operacoes[primeiro],contexto)
                futuro=pool.submit(executar_operacao,conexoes[segundo],operacoes[segundo],contexto)
                aguardar_bloqueio(monitor,conexoes[segundo].info.backend_pid,conexoes[primeiro].info.backend_pid)
            resultados[segundo]=futuro.result(timeout=15)
        for op,resultado in zip(operacoes,resultados):
            conferir_resultado(op,resultado,permitir_bloqueio="bloquear" in operacoes)
        if "bloquear" in operacoes:
            alvo=contexto["alvo_bloqueio"]
            assert monitor.execute("select not public.agenda_permite(%s,%s,%s)",alvo[1:]).fetchone()[0]
        if set(operacoes)=={"bloquear","reservar"} and ordem!="simultaneo":
            reserva=resultados[operacoes.index("reservar")]
            assert bool(reserva.get("sucesso"))==(ordem=="b_primeiro")
        if set(operacoes)=={"manual","bloquear"} and ordem!="simultaneo":
            manual=resultados[operacoes.index("manual")]
            assert bool(manual.get("sucesso"))==(ordem=="a_primeiro")
        if "gerar" in operacoes:
            assert prontidao(monitor)["pronta"]
    conferir_historico(contexto)


@pytest.mark.parametrize("repeticao",range(3))
def test_pg_manual_adquire_global_antes_de_esperar_chave(agenda,repeticao):
    contexto=preparar_disputa(agenda)
    with ThreadPoolExecutor(max_workers=2) as pool, connect() as controle, connect() as manual, connect() as gerador:
        configurar_worker(manual)
        configurar_worker(gerador)
        with controle.transaction():
            controle.execute("select pg_advisory_xact_lock(hashtextextended('disponibilidade:'||%s,0))",
                             (str(contexto["chave"]),))
            mf=pool.submit(executar_operacao,manual,"manual",contexto)
            aguardar_bloqueio(controle,manual.info.backend_pid,controle.info.backend_pid)
            assert controle.execute("""select exists(select 1 from pg_locks where pid=%s
                and locktype='advisory' and classid=73451 and objid=1
                and objsubid=2 and mode='ShareLock' and granted)""",
                (manual.info.backend_pid,)).fetchone()[0]
            gf=pool.submit(executar_operacao,gerador,"gerar",contexto)
            aguardar_bloqueio(controle,gerador.info.backend_pid,manual.info.backend_pid)
            assert not controle.execute("""select exists(select 1 from pg_locks where pid=%s
                and locktype='advisory' and classid=192837 and granted)""",
                (gerador.info.backend_pid,)).fetchone()[0]
        criado=mf.result(timeout=15)
        conferir_resultado("manual",criado)
        conferir_resultado("gerar",gf.result(timeout=15))
        assert criado["criado"]
    conferir_historico(contexto)


def test_pg_manual_retries_concorrentes_preservam_chave_e_capacidade(agenda):
    contexto=preparar_disputa(agenda)
    barreira=Barrier(2)
    def criar():
        with connect() as conn:
            configurar_worker(conn)
            barreira.wait(timeout=5)
            return executar_operacao(conn,"manual",contexto)
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados=list(pool.map(lambda _:criar(),range(2)))
    assert all(r["sucesso"] for r in resultados)
    assert sum(r["criado"] for r in resultados)==1
    assert resultados[0]["disponibilidade"]==resultados[1]["disponibilidade"]
    conferir_historico(contexto)
