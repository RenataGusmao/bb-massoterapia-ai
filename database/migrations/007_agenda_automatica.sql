begin;
set local search_path=public,pg_catalog;

create table if not exists public.calendario_atendimento (
    data date primary key,
    feriado boolean not null
);
create table if not exists public.bloqueios_agenda (
    id uuid primary key,
    data date not null,
    hora_inicio time,
    hora_fim time,
    motivo text not null check(length(btrim(motivo)) between 1 and 200),
    ativo boolean not null default true,
    criado_em timestamptz not null default now(),
    check ((hora_inicio is null and hora_fim is null) or
           (hora_inicio is not null and hora_fim is not null and hora_fim>hora_inicio))
);
create index if not exists bloqueios_agenda_ativos on public.bloqueios_agenda(data) where ativo;

-- One gate serializes calendar/block changes against new reservations.
create or replace function public.serializar_excecao_agenda()
returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
begin
    perform pg_advisory_xact_lock(73451,1);
    return new;
end;
$$;
drop trigger if exists bloquear_agenda_serializar on public.bloqueios_agenda;
create trigger bloquear_agenda_serializar before insert or update on public.bloqueios_agenda
for each row execute function public.serializar_excecao_agenda();

create or replace function public.agenda_permite(p_data date,p_inicio time,p_fim time)
returns boolean language sql volatile security invoker set search_path=public,pg_temp as $$
    select coalesce(
        p_data between (clock_timestamp() at time zone 'America/Sao_Paulo')::date
                   and (clock_timestamp() at time zone 'America/Sao_Paulo')::date+30
        and extract(isodow from p_data) between 1 and 5
        and (p_inicio,p_fim) in (
            (time '09:40',time '10:10'),(time '10:10',time '10:40'),
            (time '10:40',time '11:10'),(time '11:10',time '11:40'),
            (time '13:00',time '13:30'),(time '13:30',time '14:00'),
            (time '14:00',time '14:30'),(time '14:30',time '15:00'),
            (time '15:00',time '15:30'),(time '15:30',time '16:00'))
        and exists(select 1 from public.calendario_atendimento c where c.data=p_data and not c.feriado)
        and not exists(select 1 from public.bloqueios_agenda b where b.ativo and b.data=p_data
            and (b.hora_inicio is null or (p_inicio<b.hora_fim and p_fim>b.hora_inicio))),false);
$$;

-- Effective availability is derived; cancellation never erases an exception.
create or replace function public.validar_disponibilidade_calendario()
returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
begin
    perform pg_advisory_xact_lock_shared(73451,1);
    if not public.agenda_permite(new.data,new.hora_inicio,new.hora_fim) then
        raise check_violation using message='Intervalo fora do calendario de atendimento ou bloqueado.';
    end if;
    return new;
end;
$$;
drop trigger if exists disponibilidades_validar_calendario on public.disponibilidades;
create trigger disponibilidades_validar_calendario before insert on public.disponibilidades
for each row execute function public.validar_disponibilidade_calendario();

create or replace view public.vagas_agenda with (security_invoker=true) as
select h.id,h.massoterapeuta_id,h.disponibilidade_id,h.numero_vaga,h.data,h.hora_inicio,h.hora_fim,
       (h.disponivel and public.agenda_permite(h.data,h.hora_inicio,h.hora_fim)
        and (h.data+h.hora_inicio) at time zone 'America/Sao_Paulo'>clock_timestamp()) as disponivel,
       h.criado_em
from public.horarios_disponiveis h;

create or replace function public.validar_reserva_calendario()
returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
declare h public.horarios_disponiveis;
begin
    -- Existing appointments and final status transitions are not rewritten.
    if new.status<>'AGENDADO' then return new; end if;
    if tg_op='UPDATE' then
        if row(new.horario_id,new.colaborador_id,new.data_agendamento,new.hora_inicio,new.hora_fim,new.status)
           is not distinct from row(old.horario_id,old.colaborador_id,old.data_agendamento,old.hora_inicio,old.hora_fim,old.status) then
            return new;
        end if;
    end if;
    perform pg_advisory_xact_lock_shared(73451,1);
    select * into strict h from public.horarios_disponiveis where id=new.horario_id;
    if not public.agenda_permite(h.data,h.hora_inicio,h.hora_fim) or
       row(new.data_agendamento,new.hora_inicio,new.hora_fim) is distinct from row(h.data,h.hora_inicio,h.hora_fim) then
        raise check_violation using message='Vaga fora do calendario de atendimento ou bloqueada.';
    end if;
    return new;
end;
$$;
drop trigger if exists agendamentos_validar_calendario on public.agendamentos;
create trigger agendamentos_validar_calendario before insert or update on public.agendamentos
for each row execute function public.validar_reserva_calendario();

-- Same contract and transactional body as 003; only the calendar gate is new.
-- Manual creation must enter the gate BEFORE taking key/day locks. The insert
-- trigger alone is too late and would invert the generator's global/day order.
create or replace function public.criar_disponibilidade_transacional(
    p_chave_idempotencia uuid, p_data date, p_hora_inicio time, p_hora_fim time,
    p_capacidade integer, p_massoterapeuta_id uuid default null, p_disponivel boolean default true
)
returns jsonb language plpgsql security invoker set search_path = public, pg_temp as $$
declare
    v_grupo public.disponibilidades%rowtype;
    v_criado boolean := false;
    v_profissional_ativo boolean;
    v_vagas jsonb;
begin
    if p_chave_idempotencia is null or p_data is null or p_hora_inicio is null
       or p_hora_fim is null or p_hora_fim <= p_hora_inicio or p_disponivel is null then
        return jsonb_build_object('sucesso', false, 'erro', 'periodo_invalido');
    end if;
    if p_capacidade is null or p_capacidade < 1 or p_capacidade > 500 then
        return jsonb_build_object('sucesso', false, 'erro', 'capacidade_invalida');
    end if;

    perform pg_advisory_xact_lock_shared(73451,1);
    perform pg_advisory_xact_lock(hashtextextended('disponibilidade:' || p_chave_idempotencia::text, 0));
    perform pg_advisory_xact_lock(192837, p_data - date '2000-01-01');
    select * into v_grupo from public.disponibilidades where chave_idempotencia = p_chave_idempotencia;
    if found then
        if v_grupo.data <> p_data or v_grupo.hora_inicio <> p_hora_inicio
           or v_grupo.hora_fim <> p_hora_fim or v_grupo.capacidade <> p_capacidade
           or v_grupo.massoterapeuta_id is distinct from p_massoterapeuta_id
           or v_grupo.disponivel_inicial <> p_disponivel then
            return jsonb_build_object('sucesso', false, 'erro', 'idempotencia_conflitante');
        end if;
    else
        if (p_data + p_hora_inicio) at time zone 'America/Sao_Paulo' <= clock_timestamp() then
            return jsonb_build_object('sucesso', false, 'erro', 'horario_passado');
        end if;
        if exists (select 1 from public.disponibilidades
            where data = p_data and hora_inicio = p_hora_inicio and hora_fim = p_hora_fim) then
            return jsonb_build_object('sucesso', false, 'erro', 'intervalo_existente');
        end if;
        if exists (select 1 from public.disponibilidades
            where tsrange(data + hora_inicio, data + hora_fim, '[)')
                  && tsrange(p_data + p_hora_inicio, p_data + p_hora_fim, '[)')) then
            return jsonb_build_object('sucesso', false, 'erro', 'intervalo_sobreposto');
        end if;
        if p_massoterapeuta_id is not null then
            select ativo into v_profissional_ativo from public.massoterapeutas
            where id = p_massoterapeuta_id for share;
            if not found then
                return jsonb_build_object('sucesso', false, 'erro', 'massoterapeuta_nao_encontrado');
            end if;
            if not v_profissional_ativo then
                return jsonb_build_object('sucesso', false, 'erro', 'massoterapeuta_inativo');
            end if;
        end if;
        insert into public.disponibilidades (
            chave_idempotencia, data, hora_inicio, hora_fim, capacidade, massoterapeuta_id, disponivel_inicial
        ) values (
            p_chave_idempotencia, p_data, p_hora_inicio, p_hora_fim,
            p_capacidade, p_massoterapeuta_id, p_disponivel
        ) returning * into v_grupo;
        insert into public.horarios_disponiveis (
            disponibilidade_id, numero_vaga, massoterapeuta_id, data, hora_inicio, hora_fim, disponivel
        ) select v_grupo.id, n, p_massoterapeuta_id, p_data, p_hora_inicio, p_hora_fim, p_disponivel
          from generate_series(1, p_capacidade) as n;
        v_criado := true;
    end if;
    select coalesce(jsonb_agg(to_jsonb(h) order by h.numero_vaga), '[]'::jsonb) into v_vagas
    from public.horarios_disponiveis h where h.disponibilidade_id = v_grupo.id;
    return jsonb_build_object(
        'sucesso', true, 'criado', v_criado,
        'disponibilidade', jsonb_build_object(
            'id', v_grupo.id, 'data', v_grupo.data, 'hora_inicio', v_grupo.hora_inicio,
            'hora_fim', v_grupo.hora_fim, 'capacidade', v_grupo.capacidade, 'vagas', v_vagas
        )
    );
exception
    when unique_violation or exclusion_violation or serialization_failure or deadlock_detected or lock_not_available then
        return jsonb_build_object('sucesso', false, 'erro', 'conflito_disponibilidade');
end;
$$;

create or replace function public.gerar_agenda_automatica(p_calendario jsonb,p_capacidade integer default 1)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare
    hoje date := (clock_timestamp() at time zone 'America/Sao_Paulo')::date;
    dia date; inicio time; fim time; resposta jsonb;
    criados integer:=0; preservados integer:=0; conflitos integer:=0;
begin
    if p_calendario is null or jsonb_typeof(p_calendario)<>'array' or jsonb_array_length(p_calendario)<>31
       or p_capacidade is null or p_capacidade not between 1 and 500 then
        raise exception 'Calendario ou capacidade invalida' using errcode='22023';
    end if;
    if exists(select 1 from jsonb_array_elements(p_calendario) j
              where jsonb_typeof(j->'feriado') is distinct from 'boolean'
                 or (j->>'data')::date not between hoje and hoje+30 or j->>'data' is null)
       or (select count(distinct (j->>'data')::date) from jsonb_array_elements(p_calendario) j)<>31 then
        raise exception 'Calendario deve cobrir exatamente os proximos 31 dias' using errcode='22023';
    end if;
    perform pg_advisory_xact_lock(73451,1);
    insert into public.calendario_atendimento(data,feriado)
        select (j->>'data')::date,(j->>'feriado')::boolean from jsonb_array_elements(p_calendario) j
        on conflict(data) do update set feriado=excluded.feriado;
    for dia in select hoje+n from generate_series(0,30) n loop
        -- Same day lock as the existing availability RPC; never reset existing slots.
        perform pg_advisory_xact_lock(192837,dia-date '2000-01-01');
        for inicio in select t from unnest(array[time '09:40',time '10:10',time '10:40',time '11:10',
                     time '13:00',time '13:30',time '14:00',time '14:30',time '15:00',time '15:30']) t loop
            fim:=inicio+interval '30 minutes';
            if not public.agenda_permite(dia,inicio,fim) or
               (dia+inicio) at time zone 'America/Sao_Paulo'<=clock_timestamp() then continue; end if;
            if exists(select 1 from public.disponibilidades d where d.data=dia
                      and d.hora_inicio<fim and d.hora_fim>inicio) then
                preservados:=preservados+1;
                continue;
            end if;
            resposta:=public.criar_disponibilidade_transacional(gen_random_uuid(),dia,inicio,fim,p_capacidade,null,true);
            if (resposta->>'sucesso')::boolean then criados:=criados+1; else conflitos:=conflitos+1; end if;
        end loop;
    end loop;
    return jsonb_build_object('inicio',hoje,'fim',hoje+30,'criados',criados,'preservados',preservados,'conflitos',conflitos);
end;
$$;

create or replace function public.registrar_bloqueio_agenda(
    p_admin_id uuid,p_id uuid,p_data date,p_inicio time,p_fim time,p_motivo text)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare b public.bloqueios_agenda;
begin
    perform id from public.usuarios where id=p_admin_id and role='admin' and ativo for share;
    if not found then raise insufficient_privilege using message='Administrador ativo obrigatorio'; end if;
    if p_id is null or p_data is null or p_motivo is null then
        raise exception 'Dados obrigatorios ausentes' using errcode='22023';
    end if;
    perform pg_advisory_xact_lock(73451,1);
    insert into public.bloqueios_agenda(id,data,hora_inicio,hora_fim,motivo)
        values(p_id,p_data,p_inicio,p_fim,p_motivo) on conflict(id) do nothing;
    select * into strict b from public.bloqueios_agenda where id=p_id;
    if row(b.data,b.hora_inicio,b.hora_fim,b.motivo) is distinct from row(p_data,p_inicio,p_fim,p_motivo) then
        raise exception 'Chave reutilizada com outro bloqueio' using errcode='22023';
    end if;
    return to_jsonb(b)-'criado_em';
end;
$$;
create or replace function public.desativar_bloqueio_agenda(p_admin_id uuid,p_id uuid)
returns boolean language plpgsql security invoker set search_path=public,pg_temp as $$
begin
    perform id from public.usuarios where id=p_admin_id and role='admin' and ativo for share;
    if not found then raise insufficient_privilege using message='Administrador ativo obrigatorio'; end if;
    perform pg_advisory_xact_lock(73451,1);
    update public.bloqueios_agenda set ativo=false where id=p_id;
    return found;
end;
$$;

create or replace function public.consultar_agenda_leitura(p_inicio date,p_fim date)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare hoje date:=(clock_timestamp() at time zone 'America/Sao_Paulo')::date; resultado jsonb;
begin
    if p_inicio is null or p_fim is null or not (hoje<=p_inicio and p_inicio<=p_fim and p_fim<=hoje+30) then
        raise exception 'Periodo invalido' using errcode='22023';
    end if;
    select jsonb_build_object('itens',coalesce(jsonb_agg(to_jsonb(x) order by x.data,x.hora_inicio),'[]'::jsonb))
    into resultado from (
        select h.data,h.hora_inicio,h.hora_fim,count(*) as capacidade,
               count(*) filter(where exists(select 1 from public.agendamentos a where a.horario_id=h.id and a.status='AGENDADO')) as agendados,
               count(*) filter(where h.disponivel) as disponiveis
        from public.vagas_agenda h where h.data between p_inicio and p_fim
        group by h.data,h.hora_inicio,h.hora_fim
        order by h.data,h.hora_inicio limit 310
    ) x;
    return resultado;
end;
$$;

-- Explicit application ACLs only. No Supabase roles, defaults or internal triggers changed.
do $$
declare tabela text; funcao text; papel text; colunas text;
begin
    foreach tabela in array array['calendario_atendimento','bloqueios_agenda'] loop
        execute format('alter table public.%I enable row level security',tabela);
        execute format('drop policy if exists bb_backend_only on public.%I',tabela);
        execute format('create policy bb_backend_only on public.%I as restrictive for all to public using(false) with check(false)',tabela);
        execute format('revoke all on public.%I from public,service_role',tabela);
        foreach papel in array array['anon','authenticated'] loop
            if exists(select 1 from pg_roles where rolname=papel) then
                execute format('revoke all on public.%I from %I',tabela,papel);
            end if;
        end loop;
    end loop;
    revoke all on public.vagas_agenda from public,service_role;
    foreach papel in array array['anon','authenticated'] loop
        if exists(select 1 from pg_roles where rolname=papel) then
            execute format('revoke all on public.vagas_agenda from %I',papel);
        end if;
    end loop;
    foreach funcao in array array[
        'serializar_excecao_agenda()','agenda_permite(date,time,time)','validar_reserva_calendario()',
        'validar_disponibilidade_calendario()',
        'criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean)',
        'gerar_agenda_automatica(jsonb,integer)',
        'registrar_bloqueio_agenda(uuid,uuid,date,time,time,text)',
        'desativar_bloqueio_agenda(uuid,uuid)','consultar_agenda_leitura(date,date)'
    ] loop
        execute format('revoke all on function public.%s from public,service_role',funcao);
        foreach papel in array array['anon','authenticated'] loop
            if exists(select 1 from pg_roles where rolname=papel) then
                execute format('revoke all on function public.%s from %I',funcao,papel);
            end if;
        end loop;
    end loop;
    foreach tabela in array array['calendario_atendimento','bloqueios_agenda','vagas_agenda'] loop
        select string_agg(format('%I',attname),',') into colunas from pg_attribute
            where attrelid=('public.'||tabela)::regclass and attnum>0 and not attisdropped;
        execute format('revoke all (%s) on public.%I from public,service_role',colunas,tabela);
        foreach papel in array array['anon','authenticated'] loop
            if exists(select 1 from pg_roles where rolname=papel) then
                execute format('revoke all (%s) on public.%I from %I',colunas,tabela,papel);
                if has_table_privilege(papel,'public.'||tabela,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                   or has_any_column_privilege(papel,'public.'||tabela,'SELECT,INSERT,UPDATE,REFERENCES')
                   or exists(select 1 from pg_roles where rolname=papel and (rolsuper or rolbypassrls)) then
                    raise exception 'Role cliente % mantem acesso herdado a %',papel,tabela;
                end if;
            end if;
        end loop;
    end loop;
end;
$$;
grant select,insert on public.calendario_atendimento,public.bloqueios_agenda to service_role;
grant update(feriado) on public.calendario_atendimento to service_role;
grant update(ativo) on public.bloqueios_agenda to service_role;
grant select on public.vagas_agenda to service_role;
grant execute on function public.agenda_permite(date,time,time) to service_role;
grant execute on function public.criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean) to service_role;
grant execute on function public.gerar_agenda_automatica(jsonb,integer) to service_role;
grant execute on function public.registrar_bloqueio_agenda(uuid,uuid,date,time,time,text) to service_role;
grant execute on function public.desativar_bloqueio_agenda(uuid,uuid) to service_role;
grant execute on function public.consultar_agenda_leitura(date,date) to service_role;
notify pgrst,'reload schema';
commit;
