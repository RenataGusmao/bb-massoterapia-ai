-- Somente leitura. Executar manualmente antes da 007 (depois da 006).
-- Tambem pode ser executado antes da 006: sua ausencia sera indicada.
-- Nao invoca RPCs, nao lista dados pessoais e nao altera configuracoes.
with
objetos(nome,tipo) as (values
    ('usuarios','r'),('disponibilidades','r'),
    ('horarios_disponiveis','r'),('agendamentos','r')),
relacoes as (
    select o.*,c.oid,c.relowner,c.relkind,c.relrowsecurity
    from objetos o left join pg_class c on c.oid=to_regclass('public.'||o.nome)
),
colunas(tabela,coluna,tipo) as (values
    ('usuarios','id','uuid'),('usuarios','role','text'),('usuarios','ativo','boolean'),
    ('disponibilidades','id','uuid'),('disponibilidades','data','date'),
    ('disponibilidades','hora_inicio','time without time zone'),
    ('disponibilidades','hora_fim','time without time zone'),
    ('disponibilidades','capacidade','integer'),
    ('horarios_disponiveis','id','uuid'),('horarios_disponiveis','massoterapeuta_id','uuid'),
    ('horarios_disponiveis','disponibilidade_id','uuid'),('horarios_disponiveis','numero_vaga','integer'),
    ('horarios_disponiveis','data','date'),
    ('horarios_disponiveis','hora_inicio','time without time zone'),
    ('horarios_disponiveis','hora_fim','time without time zone'),
    ('horarios_disponiveis','disponivel','boolean'),
    ('horarios_disponiveis','criado_em','timestamp with time zone'),
    ('agendamentos','horario_id','uuid'),('agendamentos','colaborador_id','uuid'),
    ('agendamentos','data_agendamento','date'),('agendamentos','status','text'),
    ('agendamentos','hora_inicio','time without time zone'),
    ('agendamentos','hora_fim','time without time zone')
),
faltantes as (
    select e.tabela||'.'||e.coluna||' ('||e.tipo||')' as nome
    from colunas e left join pg_attribute a on
        a.attrelid=to_regclass('public.'||e.tabela) and a.attname=e.coluna
        and a.attnum>0 and not a.attisdropped
    where a.attname is null or (
        format_type(a.atttypid,a.atttypmod)<>e.tipo and not
        (e.tipo='text' and a.atttypid in ('text'::regtype,'varchar'::regtype)))
),
funcoes(assinatura) as (values
    ('criar_disponibilidade_transacional(uuid,date,time without time zone,time without time zone,integer,uuid,boolean)'),
    ('criar_agendamento_transacional(uuid,uuid,uuid)'),
    ('atualizar_status_agendamento(uuid,character varying)')),
rpcs as (
    select f.*,p.oid,p.prosecdef,p.proowner
    from funcoes f left join pg_proc p on p.oid=to_regprocedure('public.'||f.assinatura)
),
novos_objetos(nome) as (values
    ('calendario_atendimento'),('bloqueios_agenda'),('vagas_agenda')),
resultado(ordem,verificacao,resultado,possivel_bloqueio) as (
    select 1,'PostgreSQL >= 15',version(),
        case when current_setting('server_version_num')::int>=150000 then 'NAO' else 'SIM' end
    union all
    select 2,'Tabelas das migrations 001-005',
        coalesce(string_agg(nome,', ') filter(where oid is null or relkind::text<>tipo),'Estrutura presente'),
        case when bool_and(oid is not null and relkind::text=tipo) then 'NAO' else 'SIM' end
    from relacoes
    union all
    select 3,'Colunas e tipos utilizados pela 007/008',
        coalesce(string_agg(nome,', '),'Compativeis'),
        case when count(*)=0 then 'NAO' else 'SIM' end from faltantes
    union all
    select 4,'CREATE/USAGE no public e linguagem plpgsql',
        'Executor: '||current_user,
        case when has_schema_privilege(current_user,'public','CREATE')
              and has_schema_privilege(current_user,'public','USAGE')
              and has_language_privilege(current_user,'plpgsql','USAGE') then 'NAO' else 'SIM' end
    union all
    select 5,'Autoridade sobre tabelas que receberao triggers',
        coalesce(string_agg(nome||' owner='||pg_get_userbyid(relowner),'; '),'Ausentes'),
        case when bool_and(oid is not null and pg_has_role(current_user,relowner,'USAGE'))
             then 'NAO' else 'SIM' end
    from relacoes where nome in ('disponibilidades','agendamentos')
    union all
    select 6,'RPCs INVOKER, grants e autoridade para atualizar a criacao',
        coalesce(string_agg(assinatura,', ') filter(where oid is null or prosecdef
            or (assinatura like 'criar_disponibilidade_transacional(%'
                and not pg_has_role(current_user,proowner,'USAGE'))
            or not coalesce(has_function_privilege(
                (select oid from pg_roles where rolname='service_role'),oid,'EXECUTE'),false)),
            'Compativeis'),
        case when bool_and(oid is not null and not prosecdef and coalesce(
            has_function_privilege((select oid from pg_roles where rolname='service_role'),oid,'EXECUTE'),false)
            and (assinatura not like 'criar_disponibilidade_transacional(%'
                 or pg_has_role(current_user,proowner,'USAGE')))
            then 'NAO' else 'SIM' end from rpcs
    union all
    select 7,'btree_gist (dependencia herdada da 002)',
        coalesce((select e.extversion||' schema='||n.nspname from pg_extension e
            join pg_namespace n on n.oid=e.extnamespace where e.extname='btree_gist'),'Ausente'),
        case when exists(select 1 from pg_extension where extname='btree_gist') then 'NAO' else 'SIM' end
    union all
    select 8,'UUID nativo e timezone',
        '007/008 nao instalam extensoes adicionais',
        case when to_regprocedure('pg_catalog.gen_random_uuid()') is not null
            and exists(select 1 from pg_timezone_names where name='America/Sao_Paulo') then 'NAO' else 'SIM' end
    union all
    select 9,'service_role com BYPASSRLS',
        coalesce((select 'BYPASSRLS='||rolbypassrls::text from pg_roles where rolname='service_role'),'Role ausente'),
        case when exists(select 1 from pg_roles where rolname='service_role' and rolbypassrls) then 'NAO' else 'SIM' end
    union all
    select 10,'Etapa 006 antes da 007/008',
        'Conferir tambem o registro operacional da aplicacao da 006',
        case when to_regprocedure('public.validar_perfil_usuario_mvp()') is not null
            and exists(select 1 from pg_trigger where tgrelid=to_regclass('public.usuarios')
                and tgname='usuarios_perfis_mvp' and tgenabled<>'D')
            and to_regprocedure('public.provisionar_terceirizada(uuid,text,text,uuid[])') is null
            and to_regprocedure('public.consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer)') is null
            then 'NAO' else 'SIM: aplicar/verificar 006' end
    union all
    select 11,'Colisoes de nomes da 007',
        coalesce(string_agg(n.nome||' tipo='||c.relkind::text||' owner='||pg_get_userbyid(c.relowner),'; '),
            'Sem objetos com os novos nomes'),
        case when count(c.oid)=0 then 'NAO' else 'ATENCAO: conferir definicoes/ownership antes de reaplicar' end
    from novos_objetos n join pg_class c on c.oid=to_regclass('public.'||n.nome)
    union all
    select 12,'Event trigger ensure_rls',
        coalesce((select 'estado='||e.evtenabled::text||' funcao='||e.evtfoid::regprocedure::text
            ||' owner='||pg_get_userbyid(p.proowner) from pg_event_trigger e
            join pg_proc p on p.oid=e.evtfoid where e.evtname='ensure_rls'),'Nao instalado'),
        'ATENCAO: preservar; conferir sua definicao se o DDL falhar'
    union all
    select 13,'RLS nas tabelas privadas existentes',
        coalesce(string_agg(nome,', ') filter(where not relrowsecurity),'Ativo'),
        case when bool_and(coalesce(relrowsecurity,false)) then 'NAO' else 'SIM' end from relacoes
    union all
    select 14,'Indices invalidos em tabelas da aplicacao',
        coalesce(string_agg(c.relname,', '),'Nenhum'),
        case when count(*)=0 then 'NAO' else 'SIM' end
    from pg_index i join pg_class c on c.oid=i.indexrelid
    where i.indrelid in (select oid from relacoes) and (not i.indisvalid or not i.indisready)
    union all
    select 15,'Grants herdados da 005 para service_role',
        'SELECT/INSERT nas tabelas; UPDATE nas colunas necessarias; USAGE no public',
        case when coalesce(has_schema_privilege((select oid from pg_roles where rolname='service_role'),
                            'public','USAGE'),false)
            and not exists (
                select 1 from relacoes r
                where not coalesce(has_table_privilege(
                    (select oid from pg_roles where rolname='service_role'),r.oid,'SELECT'),false)
                   or not coalesce(has_table_privilege(
                    (select oid from pg_roles where rolname='service_role'),r.oid,'INSERT'),false))
            and not exists (
                select 1 from (values ('horarios_disponiveis','disponivel'),
                    ('agendamentos','status'),('agendamentos','atualizado_em'),
                    ('disponibilidades','capacidade'),('usuarios','ativo')) x(tabela,coluna)
                left join pg_attribute a on a.attrelid=to_regclass('public.'||x.tabela)
                    and a.attname=x.coluna and not a.attisdropped
                where not coalesce(has_column_privilege(
                    (select oid from pg_roles where rolname='service_role'),a.attrelid,a.attnum,'UPDATE'),false))
            then 'NAO' else 'SIM' end
    union all
    select 16,'Funcoes homonimas da 007/008 ja existentes',
        coalesce(string_agg(p.oid::regprocedure::text||' owner='||pg_get_userbyid(p.proowner),'; '),
            'Sem funcoes com os novos nomes'),
        case when count(*)=0 then 'NAO'
             when bool_and(pg_has_role(current_user,p.proowner,'USAGE'))
                  then 'ATENCAO: conferir definicoes antes de substituir'
             else 'SIM: executor nao pode substituir todas as funcoes' end
    from pg_proc p join pg_namespace n on n.oid=p.pronamespace
    where n.nspname='public' and p.proname in (
        'serializar_excecao_agenda','agenda_permite','validar_disponibilidade_calendario',
        'validar_reserva_calendario','gerar_agenda_automatica','registrar_bloqueio_agenda',
        'desativar_bloqueio_agenda','consultar_agenda_leitura','verificar_prontidao_agenda')
)
select verificacao,resultado,possivel_bloqueio from resultado order by ordem;
