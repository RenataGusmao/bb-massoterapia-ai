"""Opt-in real roles on the same guarded disposable PostgreSQL as booking tests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from tests.test_postgres_agendamentos import (
    DSN, ROOT, connect, database, entidades, psycopg, roles_banco,
)

MIGRATION = ROOT / "database/migrations/005_seguranca_permissoes.sql"
TABELAS = ("colaboradores","massoterapeutas","horarios_disponiveis","agendamentos",
           "disponibilidades","usuarios","usuarios_agenda_lotes")
RPCS = (
    "criar_agendamento_transacional(uuid,uuid,uuid)",
    "atualizar_status_agendamento(uuid,character varying)",
    "criar_disponibilidade_transacional(uuid,date,time without time zone,time without time zone,integer,uuid,boolean)",
    "provisionar_terceirizada(uuid,text,text,uuid[])",
    "consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer)",
)


def rpc(conn, nome, parametros):
    placeholders=",".join(["%s"]*len(parametros))
    return conn.execute(f"select public.{nome}({placeholders})",parametros).fetchone()[0]


@pytest.mark.parametrize("role", ["anon","authenticated"])
@pytest.mark.parametrize("tabela", TABELAS)
def test_pg_role_cliente_sem_leitura(entidades, role, tabela):
    with connect() as conn:
        conn.execute(f"set role {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"select * from public.{tabela}")


@pytest.mark.parametrize("role", ["anon","authenticated"])
@pytest.mark.parametrize("operacao", [
    "insert into public.agendamentos default values",
    "update public.agendamentos set status='CANCELADO'",
    "delete from public.agendamentos",
])
def test_pg_role_cliente_sem_escrita(entidades, role, operacao):
    with connect() as conn:
        conn.execute(f"set role {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(operacao)


def test_pg_role_grants_rls_e_funcoes(entidades):
    with connect() as conn:
        for tabela in TABELAS:
            assert conn.execute("select relrowsecurity from pg_class where oid=%s::regclass",
                                ("public."+tabela,)).fetchone()[0]
            assert conn.execute("select count(*) from pg_policy where polrelid=%s::regclass and polname='bb_backend_only' and not polpermissive",
                                ("public."+tabela,)).fetchone()[0] == 1
            for role in ("anon","authenticated"):
                assert not conn.execute("select has_table_privilege(%s,%s,'select,insert,update,delete,truncate')",
                                        (role,"public."+tabela)).fetchone()[0]
            assert conn.execute("select has_table_privilege('service_role',%s,'select')",
                                ("public."+tabela,)).fetchone()[0]
            assert not conn.execute("select has_table_privilege('service_role',%s,'delete,truncate')",
                                    ("public."+tabela,)).fetchone()[0]
        for funcao in RPCS:
            for role in ("anon","authenticated","public"):
                assert not conn.execute("select has_function_privilege(%s,%s,'execute')",
                                        (role,"public."+funcao)).fetchone()[0]
            assert conn.execute("select has_function_privilege('service_role',%s,'execute')",
                                ("public."+funcao,)).fetchone()[0]
            assert not conn.execute("select prosecdef from pg_proc where oid=%s::regprocedure",
                                    ("public."+funcao,)).fetchone()[0]
        assert not conn.execute("select has_function_privilege('service_role','public.validar_vaga_disponibilidade()','execute')").fetchone()[0]
        assert not conn.execute("select has_schema_privilege('service_role','public','create')").fetchone()[0]
        assert not conn.execute("select has_column_privilege('service_role','public.agendamentos','colaborador_id','update')").fetchone()[0]
        assert conn.execute("select has_column_privilege('service_role','public.agendamentos','status','update')").fetchone()[0]


@pytest.mark.parametrize("role", ["anon","authenticated"])
def test_pg_role_rls_derrota_politica_permissiva(entidades, role):
    class RollbackTeste(Exception):
        pass
    with connect() as conn, pytest.raises(RollbackTeste):
        with conn.transaction():
            conn.execute(f"grant usage on schema public to {role}")
            conn.execute(f"grant select,insert,update,delete on public.colaboradores to {role}")
            conn.execute("create policy test_permissiva on public.colaboradores for all to public using(true) with check(true)")
            conn.execute(f"set local role {role}")
            assert conn.execute("select * from public.colaboradores").fetchall() == []
            assert conn.execute("update public.colaboradores set ativo=false").rowcount == 0
            assert conn.execute("delete from public.colaboradores").rowcount == 0
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute("insert into public.colaboradores(nome,matricula,email) values('Ficticio','x','x@example.com')")
            raise RollbackTeste()


def test_pg_role_service_fluxo_completo(entidades):
    colaboradores, _, slots=entidades
    with connect() as conn:
        conn.execute("set role service_role")
        assert conn.execute("select count(*) from public.colaboradores").fetchone()[0] == 2
        primeiro=rpc(conn,"criar_agendamento_transacional",(colaboradores[0],None,slots[0]))
        assert primeiro["sucesso"]
        assert rpc(conn,"criar_agendamento_transacional",(colaboradores[0],None,slots[1]))["erro"]=="intervalo_minimo"
        assert rpc(conn,"atualizar_status_agendamento",(primeiro["agendamento"]["id"],"CANCELADO"))["sucesso"]
        segundo=rpc(conn,"criar_agendamento_transacional",(colaboradores[1],None,slots[0]))
        assert segundo["sucesso"]
        assert conn.execute("select count(*) from public.agendamentos where horario_id=%s",(slots[0],)).fetchone()[0] == 2
        assert rpc(conn,"atualizar_status_agendamento",(primeiro["agendamento"]["id"],"AGENDADO"))["erro"]=="transicao_invalida"
        assert conn.execute("select disponivel from public.horarios_disponiveis where id=%s",(slots[0],)).fetchone()[0] is False


def test_pg_role_service_agenda_escopo_e_capacidade(entidades):
    colaboradores, _, slots=entidades
    with connect() as conn:
        admin=conn.execute("insert into public.usuarios(email,senha_hash,role) values('admin@example.com','teste','admin') returning id").fetchone()[0]
        conn.execute("set role service_role")
        grupo=rpc(conn,"criar_disponibilidade_transacional",(uuid4(), "2099-01-01","09:00","09:30",2,None,True))["disponibilidade"]
        conta=rpc(conn,"provisionar_terceirizada",(admin,"institucional@example.com","$argon2id$ficticio",[UUID(grupo["id"])]))
        for colaborador,vaga in zip(colaboradores,grupo["vagas"]):
            assert rpc(conn,"criar_agendamento_transacional",(colaborador,None,vaga["id"]))["sucesso"]
        agenda=rpc(conn,"consultar_agenda_terceirizada",(conta["id"],grupo["data"],grupo["data"],None,1,100))
        assert agenda["total"]==2 and len({item["horario_id"] for item in agenda["itens"]})==2
        assert all("colaborador_id" not in item for item in agenda["itens"])
        assert rpc(conn,"consultar_agenda_terceirizada",(conta["id"],"2099-01-02","2099-01-02",None,1,100))["total"]==0
        outro_lote=rpc(conn,"criar_disponibilidade_transacional",(uuid4(),"2099-01-01","10:00","10:30",1,None,True))["disponibilidade"]
        terceiro=conn.execute("insert into public.colaboradores(nome,matricula,email) values('Ficticio','3','c3@example.com') returning id").fetchone()[0]
        assert rpc(conn,"criar_agendamento_transacional",(terceiro,None,outro_lote["vagas"][0]["id"]))["sucesso"]
        assert rpc(conn,"consultar_agenda_terceirizada",(conta["id"],grupo["data"],grupo["data"],None,1,100))["total"]==2


@pytest.mark.parametrize("mesmo_colaborador", [False,True])
def test_pg_role_service_concorrencia(entidades, mesmo_colaborador):
    colaboradores, _, slots=entidades
    barrier=Barrier(2)
    def worker(colaborador,vaga):
        with connect() as conn:
            conn.execute("set role service_role")
            conn.execute("set statement_timeout='10s'")
            barrier.wait(timeout=5)
            return rpc(conn,"criar_agendamento_transacional",(colaborador,None,vaga))
    with ThreadPoolExecutor(max_workers=2) as pool:
        tarefas=[pool.submit(worker,colaboradores[0],slots[0]),
                 pool.submit(worker,colaboradores[0] if mesmo_colaborador else colaboradores[1],
                             slots[1] if mesmo_colaborador else slots[0])]
        resultado=[t.result(timeout=15) for t in tarefas]
    assert sum(r["sucesso"] for r in resultado)==1
    assert next(r["erro"] for r in resultado if not r["sucesso"])==("intervalo_minimo" if mesmo_colaborador else "horario_indisponivel")


def test_pg_role_outros_objetos_defaults_e_reexecucao(entidades):
    with connect() as conn:
        try:
            conn.execute("""
                create table public.test_extra(id serial primary key);
                create view public.test_view as select * from public.test_extra;
                create function public.test_proxy() returns int language sql as 'select 1';
                grant select on public.test_extra,public.test_view to anon;
                grant execute on function public.test_proxy() to anon;
                alter default privileges in schema public grant select on tables to anon;
            """)
            defaults=conn.execute("select * from pg_default_acl order by oid").fetchall()
            for _ in range(2):
                conn.execute(MIGRATION.read_text(encoding="utf-8"))
            assert conn.execute("select * from pg_default_acl order by oid").fetchall()==defaults
            assert conn.execute("select has_table_privilege('anon','public.test_extra','select')").fetchone()[0]
            assert conn.execute("select has_table_privilege('anon','public.test_view','select')").fetchone()[0]
            assert conn.execute("select has_function_privilege('anon','public.test_proxy()','execute')").fetchone()[0]
            conn.execute("create table public.test_futuro(id serial)")
            assert conn.execute("select has_table_privilege('anon','public.test_futuro','select')").fetchone()[0]
            for tabela in TABELAS:
                assert not conn.execute("select has_table_privilege('anon',%s,'select')",("public."+tabela,)).fetchone()[0]
        finally:
            conn.execute("drop view if exists public.test_view")
            conn.execute("drop table if exists public.test_extra,public.test_futuro cascade")
            conn.execute("drop function if exists public.test_proxy()")
            conn.execute("alter default privileges in schema public revoke select on tables from anon")


@pytest.mark.parametrize("security_definer", [False,True])
def test_pg_role_executor_limitado_defaults_supabase_e_ensure_rls(entidades, security_definer):
    from psycopg import sql
    colaboradores, _, slots=entidades
    executor="bb_migration_executor"
    with connect() as conn:
        assert conn.execute("select count(*) from pg_roles where rolname in ('supabase_admin','bb_migration_executor')").fetchone()[0]==0
        assert conn.execute("select count(*) from pg_event_trigger where evtname='ensure_rls'").fetchone()[0]==0
        original_owner=conn.execute("select pg_get_userbyid(nspowner) from pg_namespace where nspname='public'").fetchone()[0]
        created=[]
        try:
            # All roles and DDL are confined to the guarded disposable test cluster.
            for role,attributes in ((executor,"nosuperuser"),("supabase_admin","superuser")):
                conn.execute(sql.SQL("create role {} nologin {}").format(sql.Identifier(role),sql.SQL(attributes)))
                created.append(role)
            conn.execute("""
                alter default privileges for role supabase_admin in schema public grant select on tables to anon;
                alter default privileges for role supabase_admin grant execute on functions to authenticated;
                create table public.test_managed(id integer);
                alter table public.test_managed owner to supabase_admin;
                grant select on public.test_managed to anon;
            """)
            conn.execute(f"""
                create function public.rls_auto_enable() returns event_trigger language plpgsql
                security {'definer' if security_definer else 'invoker'} set search_path=pg_catalog as $body$
                declare command record;
                begin
                    for command in select * from pg_event_trigger_ddl_commands() loop
                        if command.schema_name='public' and command.object_type='table' then
                            execute format('alter table %s enable row level security',command.object_identity);
                        end if;
                    end loop;
                end;
                $body$;
                alter function public.rls_auto_enable() owner to supabase_admin;
                grant execute on function public.rls_auto_enable() to public,anon,authenticated,service_role;
                create event trigger ensure_rls on ddl_command_end when tag in ('CREATE TABLE')
                    execute function public.rls_auto_enable();
            """)
            for tabela in TABELAS:
                conn.execute(sql.SQL("alter table public.{} owner to {}").format(sql.Identifier(tabela),sql.Identifier(executor)))
            for funcao in (*RPCS,"atualizar_updated_at_usuarios()","validar_vaga_disponibilidade()","proteger_configuracao_disponibilidade()"):
                conn.execute(sql.SQL("alter function public."+funcao+" owner to {}").format(sql.Identifier(executor)))
            conn.execute(sql.SQL("alter schema public owner to {}").format(sql.Identifier(executor)))
            defaults=conn.execute("select * from pg_default_acl order by oid").fetchall()
            event=conn.execute("select * from pg_event_trigger where evtname='ensure_rls'").fetchall()
            function=conn.execute("select proowner,proacl,prosecdef,proconfig,prosrc from pg_proc where oid='public.rls_auto_enable()'::regprocedure").fetchone()
            conn.execute(sql.SQL("set role {}").format(sql.Identifier(executor)))
            assert not conn.execute("select pg_has_role(current_user,'supabase_admin','USAGE')").fetchone()[0]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("alter default privileges for role supabase_admin revoke execute on functions from public")
            for _ in range(2):
                conn.execute(MIGRATION.read_text(encoding="utf-8"))
            conn.execute("create table public.test_rls_futuro(id integer)")
            assert conn.execute("select relrowsecurity from pg_class where oid='public.test_rls_futuro'::regclass").fetchone()[0]
            conn.execute("reset role")
            assert conn.execute("select * from pg_default_acl order by oid").fetchall()==defaults
            assert conn.execute("select * from pg_event_trigger where evtname='ensure_rls'").fetchall()==event
            assert conn.execute("select proowner,proacl,prosecdef,proconfig,prosrc from pg_proc where oid='public.rls_auto_enable()'::regprocedure").fetchone()==function
            assert conn.execute("select has_table_privilege('anon','public.test_managed','select')").fetchone()[0]
            for tabela in TABELAS:
                for role in ("anon","authenticated"):
                    assert not conn.execute("select has_table_privilege(%s,%s,'select,insert,update,delete')",(role,"public."+tabela)).fetchone()[0]
            conn.execute("set role anon")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("select * from public.usuarios")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("select public.criar_agendamento_transacional(null,null,null)")
            conn.execute("reset role")
            admin=conn.execute("insert into public.usuarios(email,senha_hash,role) values('isolado@example.com','teste','admin') returning id").fetchone()[0]
            conn.execute("set role service_role")
            reserva=rpc(conn,"criar_agendamento_transacional",(colaboradores[0],None,slots[0]))
            assert reserva["sucesso"]
            assert rpc(conn,"atualizar_status_agendamento",(reserva["agendamento"]["id"],"CANCELADO"))["sucesso"]
            grupo=rpc(conn,"criar_disponibilidade_transacional",(uuid4(),"2099-05-01","09:00","09:30",1,None,True))["disponibilidade"]
            conta=rpc(conn,"provisionar_terceirizada",(admin,"isolada@example.com","$argon2id$ficticio",[UUID(grupo["id"])]))
            assert rpc(conn,"consultar_agenda_terceirizada",(conta["id"],grupo["data"],grupo["data"],None,1,100))["total"]==0
            for funcao in RPCS:
                assert not conn.execute("select prosecdef from pg_proc where oid=%s::regprocedure",("public."+funcao,)).fetchone()[0]
        finally:
            conn.execute("rollback")
            conn.execute("reset role")
            conn.execute("drop event trigger if exists ensure_rls")
            conn.execute("drop function if exists public.rls_auto_enable()")
            conn.execute("drop table if exists public.test_managed,public.test_rls_futuro")
            for tabela in TABELAS:
                conn.execute(sql.SQL("alter table public.{} owner to {}").format(sql.Identifier(tabela),sql.Identifier(original_owner)))
            for funcao in (*RPCS,"atualizar_updated_at_usuarios()","validar_vaga_disponibilidade()","proteger_configuracao_disponibilidade()"):
                conn.execute(sql.SQL("alter function public."+funcao+" owner to {}").format(sql.Identifier(original_owner)))
            conn.execute(sql.SQL("alter schema public owner to {}").format(sql.Identifier(original_owner)))
            for role in reversed(created):
                conn.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
                conn.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))


@pytest.mark.parametrize("legado", [False,True])
def test_pg_role_instalacao_nova_e_upgrade(entidades, legado):
    with connect() as conn:
        conn.execute("drop table public.usuarios_agenda_lotes,public.usuarios,public.agendamentos,public.horarios_disponiveis,public.disponibilidades,public.massoterapeutas,public.colaboradores cascade")
        if legado:
            conn.execute("alter default privileges in schema public grant all on tables to anon,authenticated,service_role")
        inicial="tests/fixtures/schema_pre_003.sql" if legado else "database/schema.sql"
        conn.execute((ROOT/inicial).read_text(encoding="utf-8"))
        conn.execute((ROOT/"database/auth_schema.sql").read_text(encoding="utf-8"))
        for path in sorted((ROOT/"database/migrations").glob("00[1-4]_*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        colaborador=conn.execute("insert into public.colaboradores(nome,matricula,email) values('Ficticio','1','c@example.com') returning id").fetchone()[0]
        grupo=rpc(conn,"criar_disponibilidade_transacional",(uuid4(),"2099-02-01","09:00","09:30",1,None,True))["disponibilidade"]
        antes=rpc(conn,"criar_agendamento_transacional",(colaborador,None,grupo["vagas"][0]["id"]))["agendamento"]
        conn.execute(MIGRATION.read_text(encoding="utf-8"))
        assert str(conn.execute("select id from public.agendamentos").fetchone()[0])==antes["id"]
        conn.execute("set role service_role")
        assert rpc(conn,"atualizar_status_agendamento",(antes["id"],"CANCELADO"))["sucesso"]
        conn.execute("reset role")
        for role in ("anon","authenticated"):
            assert not conn.execute("select has_table_privilege(%s,'public.usuarios','select')",(role,)).fetchone()[0]


@pytest.mark.parametrize("caso", ["sem_bypass","heranca_cliente"])
def test_pg_role_precondicoes_falham_sem_aplicacao_parcial(entidades, caso):
    with connect() as conn:
        try:
            if caso=="sem_bypass":
                conn.execute("alter role service_role nobypassrls")
            else:
                conn.execute("grant service_role to anon")
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute(MIGRATION.read_text(encoding="utf-8"))
            conn.execute("rollback")
            assert conn.execute("select count(*) from public.colaboradores").fetchone()[0] == 2
            assert conn.execute("select has_function_privilege('service_role','public.criar_agendamento_transacional(uuid,uuid,uuid)','execute')").fetchone()[0]
        finally:
            conn.execute("rollback")
            if caso=="sem_bypass":
                conn.execute("alter role service_role bypassrls")
            else:
                conn.execute("revoke service_role from anon")
