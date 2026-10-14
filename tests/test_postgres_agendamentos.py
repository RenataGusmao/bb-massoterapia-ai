"""Real transactions; opt-in only, on an empty, disposable loopback database."""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest


DSN = os.getenv("TEST_POSTGRES_DSN")
if not DSN or os.getenv("TEST_POSTGRES_ALLOW_SCHEMA_SETUP") != "1":
    pytest.skip("PostgreSQL isolado não configurado; concorrência real não executada.", allow_module_level=True)

psycopg = pytest.importorskip("psycopg")
from psycopg.conninfo import conninfo_to_dict
from psycopg import sql

config = conninfo_to_dict(DSN)
if (
    config.get("host") not in {"127.0.0.1", "::1", "localhost"}
    or not config.get("dbname", "").startswith("bb_massoterapia_test")
):
    raise RuntimeError("Os testes exigem banco local descartável bb_massoterapia_test*. Não use Supabase.")

ROOT = Path(__file__).resolve().parents[1]


def connect():
    return psycopg.connect(DSN, autocommit=True, connect_timeout=5)


@pytest.fixture(scope="module")
def roles_banco():
    # Roles are cluster-wide: use a disposable cluster without these names.
    criadas = []
    with connect() as conn:
        assert conn.execute("select count(*) from pg_tables where schemaname='public'").fetchone()[0] == 0
        assert conn.execute("select count(*) from pg_roles where rolname in ('anon','authenticated','service_role')").fetchone()[0] == 0, "Use um cluster descartavel sem roles preexistentes."
        try:
            for role in ("anon","authenticated","service_role"):
                conn.execute(sql.SQL("create role {} nologin {}").format(
                    sql.Identifier(role), sql.SQL("bypassrls" if role=="service_role" else "")))
                criadas.append(role)
            yield
        finally:
            for role in reversed(criadas):
                conn.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
                conn.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))


@pytest.fixture(scope="module")
def database(roles_banco):
    with connect() as conn:
        assert conn.execute(
            "select count(*) from pg_tables where schemaname = 'public'"
        ).fetchone()[0] == 0, "Use um banco de teste vazio."
        assert conn.execute(
            "select to_regprocedure('public.criar_agendamento_transacional(uuid,uuid,uuid)')"
        ).fetchone()[0] is None, "O banco não está vazio."
        try:
            conn.execute((ROOT / "tests/fixtures/schema_pre_003.sql").read_text(encoding="utf-8"))
            # Simulate upgrading the original schema, not just a new database.
            conn.execute("""
                alter table public.agendamentos drop constraint agendamentos_intervalo_minimo;
                drop index public.agendamentos_horario_nao_cancelado_unico;
                alter table public.agendamentos add constraint agendamentos_horario_unico unique(horario_id);
            """)
            for path in (
                "database/auth_schema.sql",
                "database/migrations/001_usuarios_colaborador_vinculo.sql",
                "database/migrations/002_agendamentos_transacionais.sql",
                "database/migrations/003_disponibilidade_sem_profissional.sql",
                "database/migrations/004_acesso_terceirizada.sql",
                "database/migrations/005_seguranca_permissoes.sql",
            ):
                conn.execute((ROOT / path).read_text(encoding="utf-8"))
            yield
        finally:
            # Only objects created above, after asserting an empty disposable database.
            conn.execute("drop table if exists public.usuarios_agenda_lotes, public.usuarios, public.agendamentos, public.horarios_disponiveis, public.disponibilidades, public.massoterapeutas, public.colaboradores cascade")
            conn.execute("drop function if exists public.provisionar_terceirizada(uuid,text,text,uuid[])")
            conn.execute("drop function if exists public.consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer)")
            conn.execute("drop function if exists public.criar_agendamento_transacional(uuid,uuid,uuid)")
            conn.execute("drop function if exists public.atualizar_status_agendamento(uuid,varchar)")
            conn.execute("drop function if exists public.atualizar_updated_at_usuarios()")
            conn.execute("drop function if exists public.test_falhar_insert()")
            conn.execute("drop function if exists public.criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean)")
            conn.execute("drop function if exists public.validar_vaga_disponibilidade()")
            conn.execute("drop function if exists public.proteger_configuracao_disponibilidade()")


@pytest.fixture
def entidades(database):
    with connect() as conn:
        conn.execute((ROOT / "database/migrations/004_acesso_terceirizada.sql").read_text(encoding="utf-8"))
        conn.execute((ROOT / "database/migrations/005_seguranca_permissoes.sql").read_text(encoding="utf-8"))
        conn.execute("drop trigger if exists test_insert_falha on public.agendamentos")
        conn.execute("drop function if exists public.test_falhar_insert()")
        conn.execute("truncate public.usuarios_agenda_lotes, public.usuarios, public.agendamentos, public.horarios_disponiveis, public.disponibilidades, public.massoterapeutas, public.colaboradores")
        colaboradores = [uuid4(), uuid4()]
        for index, colaborador in enumerate(colaboradores):
            conn.execute(
                "insert into public.colaboradores (id,nome,matricula,email) values (%s,%s,%s,%s)",
                (colaborador, "Teste", str(index), f"colaborador{index}@example.com"),
            )
        profissional = uuid4()
        conn.execute("insert into public.massoterapeutas (id,nome) values (%s,'Teste')", (profissional,))
        slots = []
        for dias in (30, 31, 44, 45):
            resultado = conn.execute(
                """select public.criar_disponibilidade_transacional(
                    %s,(clock_timestamp() at time zone 'America/Sao_Paulo')::date + %s,
                    '10:00'::time,'10:30'::time,1,%s,true)""",
                (uuid4(), dias, profissional),
            ).fetchone()[0]
            assert resultado["sucesso"]
            slots.append(resultado["disponibilidade"]["vagas"][0]["id"])
        return colaboradores, profissional, slots


def criar(colaborador, profissional, slot):
    with connect() as conn:
        return conn.execute(
            "select public.criar_agendamento_transacional(%s,%s,%s)",
            (colaborador, profissional, slot),
        ).fetchone()[0]


def status(agendamento, valor):
    with connect() as conn:
        return conn.execute(
            "select public.atualizar_status_agendamento(%s,%s)", (agendamento, valor)
        ).fetchone()[0]


def disponibilidade(slot):
    with connect() as conn:
        return conn.execute(
            "select disponivel from public.horarios_disponiveis where id=%s", (slot,)
        ).fetchone()[0]


def institucional(slots, role="admin", ativo=True):
    with connect() as conn:
        admin = conn.execute(
            "insert into public.usuarios(email,senha_hash,role,ativo) values(%s,'teste',%s,%s) returning id",
            (f"{uuid4()}@example.com", role, ativo),
        ).fetchone()[0]
        lotes = [conn.execute("select disponibilidade_id from public.horarios_disponiveis where id=%s",
                             (slot,)).fetchone()[0] for slot in slots]
        return conn.execute("select public.provisionar_terceirizada(%s,%s,%s,%s)",
                            (admin, f"{uuid4()}@example.com", "$argon2id$ficticio", lotes)).fetchone()[0]


def agenda_pg(usuario, inicio, fim=None, statuses=None, pagina=1, tamanho=50):
    with connect() as conn:
        return conn.execute("select public.consultar_agenda_terceirizada(%s,%s,%s,%s,%s,%s)",
                            (usuario, inicio, fim or inicio, statuses, pagina, tamanho)).fetchone()[0]


def test_pg_004_roles_vinculos_e_reexecucao(entidades):
    _, _, slots = entidades
    conta = institucional(slots[:1])
    with connect() as conn:
        assert conta["role"] == "terceirizada" and conta["colaborador_id"] is None
        assert "senha_hash" not in conta
        conn.execute((ROOT / "database/migrations/004_acesso_terceirizada.sql").read_text(encoding="utf-8"))
        assert conn.execute("select count(*) from public.usuarios_agenda_lotes").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("insert into public.usuarios(email,senha_hash,role) values('invalido@example.com','teste','colaborador')")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""insert into public.usuarios(email,senha_hash,role,colaborador_id)
                select 'institucional-invalido@example.com','teste','terceirizada',id
                from public.colaboradores limit 1""")
        assert not conn.execute("select has_table_privilege('public','public.usuarios','select')").fetchone()[0]
        assert not conn.execute("""select has_function_privilege(
            'public', 'public.consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer)', 'execute')""").fetchone()[0]


@pytest.mark.parametrize("caso", ["inexistente", "duplicado", "vazio", "sem_admin", "inativo"])
def test_pg_004_provisionamento_atomico_invalido(entidades, caso):
    _, _, slots = entidades
    with connect() as conn:
        admin = conn.execute("insert into public.usuarios(email,senha_hash,role,ativo) values('admin@example.com','teste',%s,%s) returning id",
                             ("terceirizada" if caso == "sem_admin" else "admin", caso != "inativo")).fetchone()[0]
        lote = conn.execute("select disponibilidade_id from public.horarios_disponiveis where id=%s", (slots[0],)).fetchone()[0]
        lotes = [] if caso == "vazio" else [lote, lote] if caso == "duplicado" else [uuid4()] if caso == "inexistente" else [lote]
        with pytest.raises(psycopg.Error):
            conn.execute("select public.provisionar_terceirizada(%s,'conta@example.com','$argon2id$ficticio',%s)", (admin, lotes))
        assert conn.execute("select count(*) from public.usuarios").fetchone()[0] == 1
        assert conn.execute("select count(*) from public.usuarios_agenda_lotes").fetchone()[0] == 0


def test_pg_004_duplicidade_email_sem_conta_parcial(entidades):
    _, _, slots = entidades
    conta = institucional(slots[:1])
    with connect() as conn:
        admin = conn.execute("select id from public.usuarios where role='admin'").fetchone()[0]
        lote = conn.execute("select disponibilidade_id from public.horarios_disponiveis where id=%s", (slots[0],)).fetchone()[0]
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("select public.provisionar_terceirizada(%s,%s,'$argon2id$ficticio',%s)", (admin, conta["email"].upper(), [lote]))
        assert conn.execute("select count(*) from public.usuarios_agenda_lotes").fetchone()[0] == 1


def test_pg_004_agenda_escopo_filtros_historico_e_paginacao(entidades):
    colaboradores, profissional, slots = entidades
    conta = institucional([slots[0]])
    primeiro = criar(colaboradores[0], profissional, slots[0])["agendamento"]
    status(primeiro["id"], "CANCELADO")
    segundo = criar(colaboradores[1], profissional, slots[0])["agendamento"]
    terceiro = criar(colaboradores[0], profissional, slots[1])["agendamento"]
    inicio, fim = primeiro["data_agendamento"], terceiro["data_agendamento"]
    retorno = agenda_pg(conta["id"], inicio, fim)
    assert retorno["total"] == 2
    assert {item["id"] for item in retorno["itens"]} == {primeiro["id"], segundo["id"]}
    assert all(set(item) == {"id","data","hora_inicio","hora_fim","status","horario_id","disponibilidade_id"}
               for item in retorno["itens"])
    for valor in ["CANCELADO", "AGENDADO"]:
        filtrado = agenda_pg(conta["id"], inicio, statuses=[valor])
        assert filtrado["total"] == 1 and filtrado["itens"][0]["status"] == valor
    for valor in ["CONCLUIDO", "FALTOU"]:
        assert agenda_pg(conta["id"], inicio, statuses=[valor])["total"] == 0
    p1 = agenda_pg(conta["id"], inicio, pagina=1, tamanho=1)
    p2 = agenda_pg(conta["id"], inicio, pagina=2, tamanho=1)
    assert p1["total"] == p2["total"] == 2
    assert p1["itens"][0]["id"] != p2["itens"][0]["id"]
    assert agenda_pg(conta["id"], inicio, pagina=3, tamanho=1)["itens"] == []
    assert agenda_pg(conta["id"], fim)["total"] == 0
    with connect() as conn:
        conn.execute("update public.usuarios set ativo=false where id=%s", (conta["id"],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        agenda_pg(conta["id"], inicio)


def test_pg_004_multiplas_vagas_e_contas_isoladas(entidades):
    colaboradores, _, slots = entidades
    with connect() as conn:
        lote = conn.execute("""select public.criar_disponibilidade_transacional(
            %s,current_date+60,'10:00'::time,'10:30'::time,2,null,true)""", (uuid4(),)).fetchone()[0]["disponibilidade"]
    vagas = [v["id"] for v in lote["vagas"]]
    conta = institucional(vagas[:1])
    outra = institucional(slots[:1])
    agendamentos = [criar(c, None, v)["agendamento"] for c,v in zip(colaboradores,vagas)]
    retorno = agenda_pg(conta["id"], lote["data"])
    assert retorno["total"] == 2
    assert len({i["horario_id"] for i in retorno["itens"]}) == 2
    assert agenda_pg(outra["id"], lote["data"])["total"] == 0
    for a, valor in zip(agendamentos, ["CONCLUIDO","FALTOU"]):
        status(a["id"], valor)
        assert agenda_pg(conta["id"], lote["data"], statuses=[valor])["total"] == 1


def test_pg_004_falha_grant_reverte_conta(entidades):
    _, _, slots = entidades
    with connect() as conn:
        conn.execute("""
            create function public.test_falhar_acesso() returns trigger language plpgsql as $$
            begin raise exception 'falha simulada'; end; $$;
            create trigger test_acesso_falha before insert on public.usuarios_agenda_lotes
            for each row execute function public.test_falhar_acesso();
        """)
        try:
            with pytest.raises(psycopg.errors.RaiseException):
                institucional(slots[:1])
            assert conn.execute("select count(*) from public.usuarios where role='terceirizada'").fetchone()[0] == 0
            assert conn.execute("select count(*) from public.usuarios_agenda_lotes").fetchone()[0] == 0
        finally:
            conn.execute("drop trigger test_acesso_falha on public.usuarios_agenda_lotes")
            conn.execute("drop function public.test_falhar_acesso()")


def test_pg_004_revogar_lote_remove_acesso(entidades):
    colaboradores, profissional, slots = entidades
    conta = institucional(slots[:1])
    registro = criar(colaboradores[0], profissional, slots[0])["agendamento"]
    assert agenda_pg(conta["id"], registro["data_agendamento"])["total"] == 1
    with connect() as conn:
        conn.execute("delete from public.usuarios_agenda_lotes where usuario_id=%s", (conta["id"],))
    assert agenda_pg(conta["id"], registro["data_agendamento"])["total"] == 0
    with connect() as conn:
        assert conn.execute("select count(*) from public.agendamentos where id=%s", (registro["id"],)).fetchone()[0] == 1


@pytest.mark.parametrize("caso", ["periodo", "pagina", "tamanho", "status"])
def test_pg_004_filtros_defensivos(entidades, caso):
    _, _, slots = entidades
    conta = institucional(slots[:1])
    with connect() as conn:
        dia = conn.execute("select current_date").fetchone()[0]
    from datetime import timedelta
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        agenda_pg(conta["id"], dia, dia + timedelta(days=31) if caso=="periodo" else dia,
                  ["OUTRO"] if caso=="status" else None,
                  0 if caso=="pagina" else 1, 101 if caso=="tamanho" else 50)


def test_pg_criacao_atomica(entidades):
    colaboradores, profissional, slots = entidades
    resultado = criar(colaboradores[0], profissional, slots[0])
    assert resultado["sucesso"] is True
    assert not disponibilidade(slots[0])
    with connect() as conn:
        assert conn.execute("select count(*) from public.agendamentos").fetchone()[0] == 1


def test_pg_falha_insert_reverte_reserva(entidades):
    colaboradores, profissional, slots = entidades
    with connect() as conn:
        conn.execute("""
            create function public.test_falhar_insert() returns trigger language plpgsql as $$
            begin raise exception 'falha simulada'; end; $$;
            create trigger test_insert_falha before insert on public.agendamentos
            for each row execute function public.test_falhar_insert();
        """)
    with pytest.raises(psycopg.errors.RaiseException):
        criar(colaboradores[0], profissional, slots[0])
    assert disponibilidade(slots[0])
    with connect() as conn:
        assert conn.execute("select count(*) from public.agendamentos").fetchone()[0] == 0


def test_pg_vaga_indisponivel_nao_insere(entidades):
    colaboradores, profissional, slots = entidades
    with connect() as conn:
        conn.execute("update public.horarios_disponiveis set disponivel=false where id=%s", (slots[0],))
    assert criar(colaboradores[0], profissional, slots[0])["erro"] == "horario_indisponivel"
    with connect() as conn:
        assert conn.execute("select count(*) from public.agendamentos").fetchone()[0] == 0


@pytest.mark.parametrize("mesmo_colaborador", [False, True])
def test_pg_concorrencia_real(entidades, mesmo_colaborador):
    colaboradores, profissional, slots = entidades
    barrier = Barrier(2)

    def worker(colaborador, slot):
        with psycopg.connect(DSN, autocommit=True, application_name="bb_test_worker") as conn:
            conn.execute("set statement_timeout='10s'")
            barrier.wait(timeout=5)
            return conn.execute(
                "select public.criar_agendamento_transacional(%s,%s,%s)",
                (colaborador, profissional, slot),
            ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        with connect() as blocker:
            with blocker.transaction():
                if mesmo_colaborador:
                    blocker.execute("select id from public.colaboradores where id=%s for update", (colaboradores[0],))
                else:
                    blocker.execute("select id from public.horarios_disponiveis where id=%s for update", (slots[0],))
                futures = [
                    pool.submit(worker, colaboradores[0], slots[0]),
                    pool.submit(
                        worker,
                        colaboradores[0] if mesmo_colaborador else colaboradores[1],
                        slots[1] if mesmo_colaborador else slots[0],
                    ),
                ]
                deadline = time.monotonic() + 5
                waiting = 0
                while time.monotonic() < deadline:
                    blocker.execute("select pg_stat_clear_snapshot()")
                    waiting = blocker.execute("""
                        select count(*) from pg_stat_activity
                        where application_name='bb_test_worker' and wait_event_type='Lock'
                    """).fetchone()[0]
                    if waiting == 2:
                        break
                    time.sleep(0.02)
                assert waiting == 2, "As duas conexões devem disputar o bloqueio."
            resultados = [future.result(timeout=10) for future in futures]
    assert sum(r["sucesso"] is True for r in resultados) == 1
    assert [r["erro"] for r in resultados if not r["sucesso"]] == [
        "intervalo_minimo" if mesmo_colaborador else "horario_indisponivel"
    ]
    with connect() as conn:
        assert conn.execute("select count(*) from public.agendamentos").fetchone()[0] == 1
    if mesmo_colaborador:
        assert sum(disponibilidade(slot) for slot in slots[:2]) == 1


def test_pg_cancelar_reusar_preservar_historico(entidades):
    colaboradores, profissional, slots = entidades
    primeiro = criar(colaboradores[0], profissional, slots[0])["agendamento"]["id"]
    assert status(primeiro, "CANCELADO")["agendamento"]["status"] == "CANCELADO"
    assert disponibilidade(slots[0])
    segundo = criar(colaboradores[1], profissional, slots[0])["agendamento"]["id"]
    assert primeiro != segundo
    assert status(primeiro, "AGENDADO")["erro"] == "transicao_invalida"
    assert status(primeiro, "CANCELADO")["sucesso"] is True
    assert not disponibilidade(slots[0])
    with connect() as conn:
        rows = conn.execute(
            "select status from public.agendamentos where horario_id=%s order by criado_em",
            (slots[0],),
        ).fetchall()
    assert rows == [("CANCELADO",), ("AGENDADO",)]


@pytest.mark.parametrize("origem", ["AGENDADO", "CANCELADO", "CONCLUIDO", "FALTOU"])
@pytest.mark.parametrize("destino", ["AGENDADO", "CANCELADO", "CONCLUIDO", "FALTOU"])
def test_pg_transicoes(entidades, origem, destino):
    colaboradores, profissional, slots = entidades
    agendamento = criar(colaboradores[0], profissional, slots[0])["agendamento"]["id"]
    if origem != "AGENDADO":
        assert status(agendamento, origem)["sucesso"] is True
    resultado = status(agendamento, destino)
    permitido = origem == destino or origem == "AGENDADO"
    assert resultado["sucesso"] is permitido
    if not permitido:
        assert resultado["erro"] == "transicao_invalida"
    final = destino if permitido else origem
    assert disponibilidade(slots[0]) is (final == "CANCELADO")


@pytest.mark.parametrize("indice,permitido", [(2, False), (3, True)])
def test_pg_limite_14_15_dias(entidades, indice, permitido):
    colaboradores, profissional, slots = entidades
    assert criar(colaboradores[0], profissional, slots[0])["sucesso"]
    resultado = criar(colaboradores[0], profissional, slots[indice])
    assert resultado["sucesso"] is permitido
    if not permitido:
        assert resultado["erro"] == "intervalo_minimo"
        assert disponibilidade(slots[indice])


@pytest.mark.parametrize("entidade,erro", [
    ("colaboradores", "colaborador_inativo"),
    ("massoterapeutas", "massoterapeuta_inativo"),
])
def test_pg_inativos(entidades, entidade, erro):
    colaboradores, profissional, slots = entidades
    identificador = colaboradores[0] if entidade == "colaboradores" else profissional
    with connect() as conn:
        conn.execute(
            sql.SQL("update public.{} set ativo=false where id=%s").format(sql.Identifier(entidade)),
            (identificador,),
        )
    assert criar(colaboradores[0], profissional, slots[0])["erro"] == erro
    assert disponibilidade(slots[0])


@pytest.mark.parametrize("mesmo_dia", [False, True])
def test_pg_horarios_passados(entidades, mesmo_dia):
    colaboradores, profissional, slots = entidades
    with connect() as conn:
        # Past rows simulate migrated history; current availability is immutable.
        grupo = conn.execute("""
            insert into public.disponibilidades(
                chave_idempotencia,data,hora_inicio,hora_fim,capacidade,massoterapeuta_id,legado
            ) select %s,
                (clock_timestamp() at time zone 'America/Sao_Paulo')::date - %s,
                case when %s then greatest('00:00'::time,
                    (clock_timestamp() at time zone 'America/Sao_Paulo')::time - interval '1 minute')
                    else '10:00'::time end,
                '23:59:59'::time,1,%s,true returning id
        """, (uuid4(), 0 if mesmo_dia else 1, mesmo_dia, profissional)).fetchone()[0]
        slot = conn.execute("""
            insert into public.horarios_disponiveis(
                disponibilidade_id,numero_vaga,massoterapeuta_id,data,hora_inicio,hora_fim
            ) select id,1,massoterapeuta_id,data,hora_inicio,hora_fim
              from public.disponibilidades where id=%s returning id
        """, (grupo,)).fetchone()[0]
    assert criar(colaboradores[0], profissional, slot)["erro"] == "horario_passado"
    assert disponibilidade(slot)


def test_pg_constraints_impedem_insert_direto_conflitante(entidades):
    colaboradores, profissional, slots = entidades
    assert criar(colaboradores[0], profissional, slots[0])["sucesso"]
    with connect() as conn:
        with pytest.raises(psycopg.errors.ExclusionViolation):
            conn.execute("""
                insert into public.agendamentos (
                    colaborador_id,massoterapeuta_id,horario_id,data_agendamento,hora_inicio,hora_fim,status
                ) select %s,massoterapeuta_id,id,data,hora_inicio,hora_fim,'AGENDADO'
                  from public.horarios_disponiveis where id=%s
            """, (colaboradores[0], slots[1]))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("""
                insert into public.agendamentos (
                    colaborador_id,massoterapeuta_id,horario_id,data_agendamento,hora_inicio,hora_fim,status
                ) select %s,massoterapeuta_id,id,data,hora_inicio,hora_fim,'AGENDADO'
                  from public.horarios_disponiveis where id=%s
            """, (colaboradores[1], slots[0]))


def test_pg_migration_reexecutavel(entidades):
    with connect() as conn:
        conn.execute((ROOT / "database/migrations/002_agendamentos_transacionais.sql").read_text(encoding="utf-8"))
        conn.execute((ROOT / "database/migrations/003_disponibilidade_sem_profissional.sql").read_text(encoding="utf-8"))


def test_pg_schema_novo_e_sequencia_completa(entidades):
    with connect() as conn:
        conn.execute("drop table public.usuarios_agenda_lotes, public.usuarios, public.agendamentos, public.horarios_disponiveis, public.disponibilidades, public.massoterapeutas, public.colaboradores cascade")
        for path in (
            "database/schema.sql", "database/auth_schema.sql",
            "database/migrations/001_usuarios_colaborador_vinculo.sql",
            "database/migrations/002_agendamentos_transacionais.sql",
            "database/migrations/003_disponibilidade_sem_profissional.sql",
            "database/migrations/004_acesso_terceirizada.sql",
            "database/migrations/005_seguranca_permissoes.sql",
        ):
            conn.execute((ROOT / path).read_text(encoding="utf-8"))
        resultado = cadastrar_vagas()
        assert resultado["sucesso"]
        assert len(resultado["disponibilidade"]["vagas"]) == 2


def test_pg_migration_conflito_aborta_sem_apagar_historico(entidades):
    colaboradores, profissional, slots = entidades
    assert criar(colaboradores[0], profissional, slots[0])["sucesso"]
    with connect() as conn:
        conn.execute("begin")
        conn.execute("alter table public.agendamentos drop constraint agendamentos_intervalo_minimo")
        conn.execute("""
            insert into public.agendamentos (
                colaborador_id,massoterapeuta_id,horario_id,data_agendamento,hora_inicio,hora_fim,status
            ) select %s,massoterapeuta_id,id,data,hora_inicio,hora_fim,'AGENDADO'
              from public.horarios_disponiveis where id=%s
        """, (colaboradores[0], slots[1]))
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute((ROOT / "database/migrations/002_agendamentos_transacionais.sql").read_text(encoding="utf-8"))
        conn.execute("rollback")
        assert conn.execute("select count(*) from public.agendamentos").fetchone()[0] == 1


def cadastrar_vagas(capacidade=2, chave=None, inicio="09:00", fim="09:30", dias=60):
    with connect() as conn:
        return conn.execute("""
            select public.criar_disponibilidade_transacional(
                %s,(clock_timestamp() at time zone 'America/Sao_Paulo')::date + %s,
                %s::time,%s::time,%s,null,true)
        """, (chave or uuid4(), dias, inicio, fim, capacidade)).fetchone()[0]


def test_pg_capacidade_e_retry_sem_profissional(entidades):
    chave = uuid4()
    primeiro = cadastrar_vagas(2, chave)
    assert primeiro["sucesso"] and primeiro["criado"]
    vagas = primeiro["disponibilidade"]["vagas"]
    assert len(vagas) == 2
    assert all(v["massoterapeuta_id"] is None for v in vagas)
    segundo = cadastrar_vagas(2, chave)
    assert segundo["sucesso"] and not segundo["criado"]
    assert [v["id"] for v in segundo["disponibilidade"]["vagas"]] == [v["id"] for v in vagas]
    assert cadastrar_vagas(3, chave)["erro"] == "idempotencia_conflitante"
    assert cadastrar_vagas(2)["erro"] == "intervalo_existente"


@pytest.mark.parametrize("capacidade", [0, -1, 501])
def test_pg_capacidade_invalida(entidades, capacidade):
    assert cadastrar_vagas(capacidade)["erro"] == "capacidade_invalida"


@pytest.mark.parametrize("inicio,fim", [("09:15", "09:45"), ("08:45", "09:15"), ("08:00", "10:00")])
def test_pg_intervalos_sobrepostos(entidades, inicio, fim):
    assert cadastrar_vagas()["sucesso"]
    assert cadastrar_vagas(inicio=inicio, fim=fim)["erro"] == "intervalo_sobreposto"
    assert cadastrar_vagas(inicio="09:30", fim="10:00")["sucesso"]


def test_pg_cadastro_passado_sem_criar_grupo(entidades):
    assert cadastrar_vagas(dias=-1)["erro"] == "horario_passado"
    with connect() as conn:
        assert conn.execute("select count(*) from public.disponibilidades").fetchone()[0] == 4


@pytest.mark.parametrize("mesma_chave", [True, False])
def test_pg_repeticao_concorrente_nao_duplica_capacidade(entidades, mesma_chave):
    barrier = Barrier(2)
    chave = uuid4()

    def worker(key):
        with psycopg.connect(DSN, autocommit=True, application_name="bb_test_worker") as conn:
            conn.execute("set statement_timeout='10s'")
            barrier.wait(timeout=5)
            return conn.execute("""
                select public.criar_disponibilidade_transacional(
                    %s,(clock_timestamp() at time zone 'America/Sao_Paulo')::date+60,
                    '09:00'::time,'09:30'::time,2,null,true)
            """, (key,)).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        with connect() as blocker:
            with blocker.transaction():
                blocker.execute("""
                    select pg_advisory_xact_lock(192837,
                        (clock_timestamp() at time zone 'America/Sao_Paulo')::date+60-date '2000-01-01')
                """)
                futures = [pool.submit(worker, chave), pool.submit(worker, chave if mesma_chave else uuid4())]
                deadline = time.monotonic() + 5
                waiting = 0
                while time.monotonic() < deadline:
                    blocker.execute("select pg_stat_clear_snapshot()")
                    waiting = blocker.execute(
                        "select count(*) from pg_stat_activity where application_name='bb_test_worker' and wait_event_type='Lock'"
                    ).fetchone()[0]
                    if waiting == 2:
                        break
                    time.sleep(0.02)
                assert waiting == 2
            resultados = [future.result(timeout=10) for future in futures]
    assert sum(r.get("criado", False) for r in resultados) == 1
    if mesma_chave:
        assert all(r["sucesso"] for r in resultados)
        assert resultados[0]["disponibilidade"]["id"] == resultados[1]["disponibilidade"]["id"]
    else:
        assert [r["erro"] for r in resultados if not r["sucesso"]] == ["intervalo_existente"]
    with connect() as conn:
        assert conn.execute("""
            select count(*) from public.horarios_disponiveis
            where data=(clock_timestamp() at time zone 'America/Sao_Paulo')::date+60
        """).fetchone()[0] == 2


@pytest.mark.parametrize("mesmo_colaborador", [True, False])
def test_pg_reservas_simultaneas_vagas_mesmo_intervalo(entidades, mesmo_colaborador):
    colaboradores, _, _ = entidades
    vagas = cadastrar_vagas()["disponibilidade"]["vagas"]
    barrier = Barrier(2)

    def worker(colaborador, slot):
        with psycopg.connect(DSN, autocommit=True, application_name="bb_test_worker") as conn:
            conn.execute("set statement_timeout='10s'")
            barrier.wait(timeout=5)
            return conn.execute(
                "select public.criar_agendamento_transacional(%s,null,%s)", (colaborador, slot)
            ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        with connect() as blocker:
            with blocker.transaction():
                blocker.execute(
                    "select id from public.horarios_disponiveis where disponibilidade_id=%s for update",
                    (vagas[0]["disponibilidade_id"],),
                )
                futures = [
                    pool.submit(worker, colaboradores[0], vagas[0]["id"]),
                    pool.submit(worker, colaboradores[0] if mesmo_colaborador else colaboradores[1], vagas[1]["id"]),
                ]
                deadline = time.monotonic() + 5
                waiting = 0
                while time.monotonic() < deadline:
                    blocker.execute("select pg_stat_clear_snapshot()")
                    waiting = blocker.execute(
                        "select count(*) from pg_stat_activity where application_name='bb_test_worker' and wait_event_type='Lock'"
                    ).fetchone()[0]
                    if waiting == 2:
                        break
                    time.sleep(0.02)
                assert waiting == 2
            resultados = [future.result(timeout=10) for future in futures]
    assert sum(r["sucesso"] for r in resultados) == (1 if mesmo_colaborador else 2)
    if mesmo_colaborador:
        assert [r["erro"] for r in resultados if not r["sucesso"]] == ["intervalo_minimo"]
    else:
        assert all(r["agendamento"]["massoterapeuta_id"] is None for r in resultados)
        assert all(not disponibilidade(v["id"]) for v in vagas)


def test_pg_cancelamento_afeta_somente_uma_vaga(entidades):
    colaboradores, _, _ = entidades
    chave = uuid4()
    vagas = cadastrar_vagas(chave=chave)["disponibilidade"]["vagas"]
    primeiro = criar(colaboradores[0], None, vagas[0]["id"])["agendamento"]["id"]
    segundo = criar(colaboradores[1], None, vagas[1]["id"])["agendamento"]["id"]
    repetido = cadastrar_vagas(chave=chave)
    assert not repetido["criado"]
    assert all(not v["disponivel"] for v in repetido["disponibilidade"]["vagas"])
    assert status(primeiro, "CANCELADO")["sucesso"]
    assert disponibilidade(vagas[0]["id"])
    assert not disponibilidade(vagas[1]["id"])
    novo = criar(colaboradores[0], None, vagas[0]["id"])["agendamento"]["id"]
    assert novo != primeiro
    assert status(primeiro, "AGENDADO")["erro"] == "transicao_invalida"
    assert status(primeiro, "CANCELADO")["sucesso"]
    assert not disponibilidade(vagas[0]["id"])
    with connect() as conn:
        assert conn.execute("select status from public.agendamentos where id=%s", (segundo,)).fetchone()[0] == "AGENDADO"
        assert conn.execute("select count(*) from public.agendamentos").fetchone()[0] == 3


def test_pg_capacidade_protegida_de_insert_ou_reducao(entidades):
    grupo = cadastrar_vagas()["disponibilidade"]
    with connect() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("""
                insert into public.horarios_disponiveis(disponibilidade_id,numero_vaga,data,hora_inicio,hora_fim)
                select id,3,data,hora_inicio,hora_fim from public.disponibilidades where id=%s
            """, (grupo["id"],))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("update public.disponibilidades set capacidade=1 where id=%s", (grupo["id"],))
        assert conn.execute("select count(*) from public.horarios_disponiveis where disponibilidade_id=%s", (grupo["id"],)).fetchone()[0] == 2


def test_pg_rollback_cadastro_nao_deixa_capacidade_parcial(entidades):
    with connect() as conn:
        conn.execute("""
            create function public.test_falhar_vaga() returns trigger language plpgsql as $$
            begin if new.numero_vaga=2 then raise exception 'falha simulada'; end if; return new; end; $$;
            create trigger test_vaga_falha before insert on public.horarios_disponiveis
            for each row execute function public.test_falhar_vaga();
        """)
        try:
            with pytest.raises(psycopg.errors.RaiseException):
                cadastrar_vagas()
            assert conn.execute("select count(*) from public.disponibilidades").fetchone()[0] == 4
        finally:
            conn.execute("drop trigger test_vaga_falha on public.horarios_disponiveis")
            conn.execute("drop function public.test_falhar_vaga()")


def test_pg_migration_preserva_historicos_e_sobreposicoes(entidades):
    # This database has already passed the empty disposable database guard.
    with connect() as conn:
        conn.execute("drop table public.usuarios_agenda_lotes, public.usuarios, public.agendamentos, public.horarios_disponiveis, public.disponibilidades, public.massoterapeutas, public.colaboradores cascade")
        for path in (
            "tests/fixtures/schema_pre_003.sql", "database/auth_schema.sql",
            "database/migrations/001_usuarios_colaborador_vinculo.sql",
            "database/migrations/002_agendamentos_transacionais.sql",
        ):
            conn.execute((ROOT / path).read_text(encoding="utf-8"))
        colaboradores = [uuid4(), uuid4()]
        profissionais = [uuid4(), uuid4()]
        slots = [uuid4(), uuid4(), uuid4()]
        for i in range(2):
            conn.execute("insert into public.colaboradores(id,nome,matricula,email) values(%s,'Teste',%s,%s)",
                         (colaboradores[i], str(i), f"teste{i}@example.com"))
            conn.execute("insert into public.massoterapeutas(id,nome) values(%s,'Teste')", (profissionais[i],))
        for i, slot in enumerate(slots):
            conn.execute("""
                insert into public.horarios_disponiveis(id,massoterapeuta_id,data,hora_inicio,hora_fim)
                values(%s,%s,current_date+90,%s::time,%s::time)
            """, (slot, profissionais[i % 2], "10:00" if i < 2 else "10:15", "10:30" if i < 2 else "10:45"))
        ids = []
        for i, valor in enumerate(("CANCELADO", "AGENDADO")):
            resultado = conn.execute("""
                insert into public.agendamentos(colaborador_id,massoterapeuta_id,horario_id,data_agendamento,hora_inicio,hora_fim,status)
                select %s,massoterapeuta_id,id,data,hora_inicio,hora_fim,%s
                from public.horarios_disponiveis where id=%s returning id
            """, (colaboradores[i], valor, slots[i])).fetchone()[0]
            ids.append(resultado)
        conn.execute("update public.horarios_disponiveis set disponivel=false where id=%s", (slots[1],))
        antes = conn.execute("select id,massoterapeuta_id,data,hora_inicio,hora_fim,disponivel from public.horarios_disponiveis order by id").fetchall()
        conn.execute((ROOT / "database/migrations/003_disponibilidade_sem_profissional.sql").read_text(encoding="utf-8"))
        depois = conn.execute("select id,massoterapeuta_id,data,hora_inicio,hora_fim,disponivel from public.horarios_disponiveis order by id").fetchall()
        assert antes == depois
        assert conn.execute("select capacidade from public.disponibilidades order by hora_inicio").fetchall() == [(2,), (1,)]
        assert conn.execute("select count(*) from public.disponibilidades where legado").fetchone()[0] == 2
        assert conn.execute("select status from public.agendamentos where id=%s", (ids[0],)).fetchone()[0] == "CANCELADO"
        novo = conn.execute("select public.criar_agendamento_transacional(%s,null,%s)", (colaboradores[0], slots[0])).fetchone()[0]
        assert novo["sucesso"] and novo["agendamento"]["massoterapeuta_id"] == str(profissionais[0])
        conflito = conn.execute("""
            select public.criar_disponibilidade_transacional(%s,current_date+90,'10:30'::time,'11:00'::time,1,null,true)
        """, (uuid4(),)).fetchone()[0]
        assert conflito["erro"] == "intervalo_sobreposto"
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("delete from public.massoterapeutas where id=%s", (profissionais[0],))
        conn.execute((ROOT / "database/migrations/003_disponibilidade_sem_profissional.sql").read_text(encoding="utf-8"))
