begin;
set local search_path = public, pg_catalog;

-- Manage only application objects, never Supabase-owned defaults or ensure_rls.
do $$
declare
    v_table text; v_function text; v_object oid; v_owner oid; v_columns text; v_role text;
begin
    if not exists (select 1 from pg_roles where rolname='service_role' and rolbypassrls) then
        raise exception '005 requires an existing service_role with BYPASSRLS. Do not create or elevate production roles here.';
    end if;
    if not pg_has_role(current_user, (select nspowner from pg_namespace where nspname='public'), 'USAGE') then
        raise exception '005 requires authority to grant service_role USAGE on schema public.';
    end if;
    foreach v_table in array array['colaboradores','massoterapeutas','horarios_disponiveis',
        'agendamentos','disponibilidades','usuarios','usuarios_agenda_lotes'] loop
        v_object := to_regclass('public.' || v_table);
        if v_object is null then
            raise exception 'Apply migrations 001 through 004 first. Missing application table %.',v_table;
        end if;
        select relowner into v_owner from pg_class where oid=v_object and relkind in ('r','p');
        if v_owner is null or not pg_has_role(current_user,v_owner,'USAGE') then
            raise exception '005 executor cannot manage application table %.',v_table;
        end if;
        execute format('revoke all on table public.%I from public, service_role',v_table);
        select string_agg(format('%I',attname),',') into v_columns from pg_attribute
            where attrelid=v_object and attnum>0 and not attisdropped;
        execute format('revoke all (%s) on public.%I from public, service_role',v_columns,v_table);
        foreach v_role in array array['anon','authenticated'] loop
            if exists (select 1 from pg_roles where rolname=v_role) then
                execute format('revoke all on table public.%I from %I',v_table,v_role);
                execute format('revoke all (%s) on public.%I from %I',v_columns,v_table,v_role);
            end if;
        end loop;
        execute format('alter table public.%I enable row level security',v_table);
        execute format('drop policy if exists bb_backend_only on public.%I',v_table);
        execute format('create policy bb_backend_only on public.%I as restrictive for all to public using (false) with check (false)',v_table);
    end loop;
    foreach v_function in array array[
        'criar_agendamento_transacional(uuid,uuid,uuid)',
        'atualizar_status_agendamento(uuid,varchar)',
        'criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean)',
        'provisionar_terceirizada(uuid,text,text,uuid[])',
        'consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer)',
        'atualizar_updated_at_usuarios()',
        'validar_vaga_disponibilidade()',
        'proteger_configuracao_disponibilidade()'
    ] loop
        v_object := to_regprocedure('public.' || v_function);
        if v_object is null then
            raise exception 'Missing application function %.',v_function;
        end if;
        select proowner into v_owner from pg_proc where oid=v_object;
        if not pg_has_role(current_user,v_owner,'USAGE') then
            raise exception '005 executor cannot manage application function %.',v_function;
        end if;
        if exists (select 1 from pg_proc where oid=v_object and prosecdef) then
            raise exception 'Application function % must remain SECURITY INVOKER.',v_function;
        end if;
        execute format('revoke all on function public.%s from public, service_role',v_function);
        foreach v_role in array array['anon','authenticated'] loop
            if exists (select 1 from pg_roles where rolname=v_role) then
                execute format('revoke all on function public.%s from %I',v_function,v_role);
            end if;
        end loop;
    end loop;
end;
$$;

-- Preserve shared schema ACLs. USAGE alone cannot grant access to private objects.
grant usage on schema public to service_role;
grant select, insert on public.colaboradores, public.massoterapeutas,
    public.horarios_disponiveis, public.agendamentos, public.disponibilidades,
    public.usuarios, public.usuarios_agenda_lotes to service_role;
-- Row locks require UPDATE on at least one column, even without changing values.
grant update (ativo) on public.colaboradores, public.massoterapeutas, public.usuarios to service_role;
grant update (disponivel) on public.horarios_disponiveis to service_role;
grant update (status, atualizado_em) on public.agendamentos to service_role;
grant update (capacidade) on public.disponibilidades to service_role;
grant execute on function public.criar_agendamento_transacional(uuid,uuid,uuid) to service_role;
grant execute on function public.atualizar_status_agendamento(uuid,varchar) to service_role;
grant execute on function public.criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean) to service_role;
grant execute on function public.provisionar_terceirizada(uuid,text,text,uuid[]) to service_role;
grant execute on function public.consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer) to service_role;

do $$
declare v_role text; v_table text; v_function text;
begin
    foreach v_role in array array['anon','authenticated'] loop
        if exists (select 1 from pg_roles where rolname=v_role) then
            if exists (select 1 from pg_roles where rolname=v_role and (rolsuper or rolbypassrls)) then
                raise exception 'Client role % is privileged. Review role configuration.',v_role;
            end if;
            foreach v_table in array array['colaboradores','massoterapeutas','horarios_disponiveis',
                'agendamentos','disponibilidades','usuarios','usuarios_agenda_lotes'] loop
                if has_table_privilege(v_role,'public.'||v_table,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                    or has_any_column_privilege(v_role,'public.'||v_table,'SELECT,INSERT,UPDATE,REFERENCES') then
                    raise exception 'Client role % retains inherited application access to %.',v_role,v_table;
                end if;
            end loop;
            foreach v_function in array array[
                'criar_agendamento_transacional(uuid,uuid,uuid)',
                'atualizar_status_agendamento(uuid,varchar)',
                'criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean)',
                'provisionar_terceirizada(uuid,text,text,uuid[])',
                'consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer)',
                'atualizar_updated_at_usuarios()',
                'validar_vaga_disponibilidade()',
                'proteger_configuracao_disponibilidade()'
            ] loop
                if has_function_privilege(v_role,'public.'||v_function,'EXECUTE') then
                    raise exception 'Client role % retains inherited application EXECUTE on %.',v_role,v_function;
                end if;
            end loop;
        end if;
    end loop;
    if has_schema_privilege('service_role','public','CREATE') then
        raise exception 'service_role retains schema ownership/CREATE. Review role configuration.';
    end if;
    foreach v_table in array array['colaboradores','massoterapeutas','horarios_disponiveis',
        'agendamentos','disponibilidades','usuarios','usuarios_agenda_lotes'] loop
        if has_table_privilege('service_role','public.'||v_table,'DELETE,TRUNCATE,REFERENCES,TRIGGER') then
            raise exception 'service_role retains excessive privileges on %. Review ownership/role memberships.',v_table;
        end if;
    end loop;
end;
$$;

notify pgrst, 'reload schema';
commit;
