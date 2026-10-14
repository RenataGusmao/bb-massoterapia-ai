begin;

-- Run after 001, 002 and 003. No historical rows are rewritten.
alter table public.usuarios drop constraint if exists usuarios_role_valida;
alter table public.usuarios add constraint usuarios_role_valida
    check (role in ('admin', 'colaborador', 'terceirizada'));
alter table public.usuarios drop constraint if exists usuarios_terceirizada_sem_colaborador;
alter table public.usuarios add constraint usuarios_terceirizada_sem_colaborador
    check (role <> 'terceirizada' or colaborador_id is null);

create table if not exists public.usuarios_agenda_lotes (
    usuario_id uuid not null references public.usuarios(id) on delete cascade,
    disponibilidade_id uuid not null references public.disponibilidades(id) on delete restrict,
    primary key (usuario_id, disponibilidade_id)
);
alter table public.usuarios_agenda_lotes enable row level security;
revoke all on public.usuarios_agenda_lotes from public;
-- Custom JWT accounts are accessed through the backend, never through public REST.
revoke all on public.usuarios from public;

create or replace function public.provisionar_terceirizada(
    p_admin_id uuid, p_email text, p_senha_hash text, p_disponibilidade_ids uuid[]
) returns jsonb language plpgsql security invoker set search_path = public, pg_temp
as $$
declare
    v_usuario public.usuarios;
    v_quantidade integer;
begin
    perform id from public.usuarios
        where id = p_admin_id and role = 'admin' and ativo for share;
    if not found then
        raise exception 'Administrador ativo obrigatorio' using errcode = '42501';
    end if;
    if p_email is null or btrim(p_email) = '' or p_senha_hash is null
        or p_senha_hash not like '$argon2%'
        or coalesce(cardinality(p_disponibilidade_ids),0) not between 1 and 100
        or array_position(p_disponibilidade_ids, null) is not null
        or (select count(distinct id) from unnest(p_disponibilidade_ids) id)
            <> cardinality(p_disponibilidade_ids)
    then
        raise exception 'Entrada invalida' using errcode = '22023';
    end if;
    -- Hold the referenced lots until the account and grants have both been inserted.
    perform id from public.disponibilidades
        where id = any(p_disponibilidade_ids) order by id for key share;
    get diagnostics v_quantidade = row_count;
    if v_quantidade <> cardinality(p_disponibilidade_ids) then
        raise exception 'Lote inexistente' using errcode = '22023';
    end if;
    insert into public.usuarios (email, senha_hash, role, colaborador_id)
        values (lower(btrim(p_email)), p_senha_hash, 'terceirizada', null)
        returning * into v_usuario;
    insert into public.usuarios_agenda_lotes (usuario_id, disponibilidade_id)
        select v_usuario.id, id from unnest(p_disponibilidade_ids) id;
    return jsonb_build_object(
        'id',v_usuario.id, 'email',v_usuario.email, 'role',v_usuario.role,
        'ativo',v_usuario.ativo, 'colaborador_id',null
    );
end;
$$;

create or replace function public.consultar_agenda_terceirizada(
    p_usuario_id uuid, p_inicio date, p_fim date,
    p_statuses text[] default null, p_pagina integer default 1, p_tamanho integer default 50
) returns jsonb language plpgsql stable security invoker set search_path = public, pg_temp
as $$
declare v_resultado jsonb;
begin
    if not exists (select 1 from public.usuarios
        where id = p_usuario_id and role = 'terceirizada' and ativo) then
        raise exception 'Acesso institucional negado' using errcode = '42501';
    end if;
    if p_inicio is null or p_fim is null or p_fim - p_inicio not between 0 and 30
        or p_pagina is null or p_pagina not between 1 and 10000
        or p_tamanho is null or p_tamanho not between 1 and 100
        or (p_statuses is not null and (
            cardinality(p_statuses) not between 1 and 4
            or array_position(p_statuses,null) is not null
            or not p_statuses <@ array['AGENDADO','CANCELADO','CONCLUIDO','FALTOU']::text[]
        ))
    then raise exception 'Filtros invalidos' using errcode = '22023';
    end if;
    -- One row per appointment; EXISTS cannot multiply rows by access grants.
    with autorizados as materialized (
        select a.id, a.data_agendamento as data, a.hora_inicio, a.hora_fim,
            a.status, a.horario_id, h.disponibilidade_id
        from public.agendamentos a
        join public.horarios_disponiveis h on h.id = a.horario_id
        where a.data_agendamento between p_inicio and p_fim
            and (p_statuses is null or a.status::text = any(p_statuses))
            and exists (
                select 1 from public.usuarios_agenda_lotes acesso
                where acesso.usuario_id = p_usuario_id
                    and acesso.disponibilidade_id = h.disponibilidade_id
            )
    ), pagina as (
        select * from autorizados order by data, hora_inicio, horario_id, id
        limit p_tamanho offset (p_pagina - 1) * p_tamanho
    )
    select jsonb_build_object(
        'itens',coalesce((select jsonb_agg(to_jsonb(p) order by data,hora_inicio,horario_id,id) from pagina p),'[]'::jsonb),
        'total',(select count(*) from autorizados),
        'pagina',p_pagina,'tamanho_pagina',p_tamanho
    ) into v_resultado;
    return v_resultado;
end;
$$;

revoke all on function public.provisionar_terceirizada(uuid,text,text,uuid[]) from public;
revoke all on function public.consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer) from public;
do $$
declare v_role text;
begin
    foreach v_role in array array['anon','authenticated'] loop
        if exists (select 1 from pg_roles where rolname=v_role) then
            execute format('revoke all on public.usuarios_agenda_lotes from %I',v_role);
            execute format('revoke all on public.usuarios from %I',v_role);
            execute format('revoke all on function public.provisionar_terceirizada(uuid,text,text,uuid[]) from %I',v_role);
            execute format('revoke all on function public.consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer) from %I',v_role);
        end if;
    end loop;
    if exists (select 1 from pg_roles where rolname='service_role') then
        grant select, insert, delete on public.usuarios_agenda_lotes to service_role;
        grant select, insert, update on public.usuarios to service_role;
        grant execute on function public.provisionar_terceirizada(uuid,text,text,uuid[]) to service_role;
        grant execute on function public.consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer) to service_role;
    end if;
end;
$$;

notify pgrst, 'reload schema';
commit;
