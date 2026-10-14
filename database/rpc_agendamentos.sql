-- Calendar times are interpreted in America/Sao_Paulo.
-- Both operations lock collaborator -> slot -> appointment in that order.
create or replace function public.criar_agendamento_transacional(
    p_colaborador_id uuid,
    p_massoterapeuta_id uuid,
    p_horario_id uuid
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
    v_horario public.horarios_disponiveis%rowtype;
    v_colaborador_ativo boolean;
    v_massoterapeuta_ativo boolean;
    v_profissional_id uuid;
    v_conflito date;
    v_agendamento public.agendamentos%rowtype;
begin
    select ativo into v_colaborador_ativo
    from public.colaboradores where id = p_colaborador_id for update;
    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'colaborador_nao_encontrado');
    end if;
    if not v_colaborador_ativo then
        return jsonb_build_object('sucesso', false, 'erro', 'colaborador_inativo');
    end if;

    select * into v_horario
    from public.horarios_disponiveis where id = p_horario_id for update;
    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_nao_encontrado');
    end if;
    if v_horario.massoterapeuta_id is not null and p_massoterapeuta_id is not null
       and v_horario.massoterapeuta_id <> p_massoterapeuta_id then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_massoterapeuta_invalido');
    end if;
    v_profissional_id := coalesce(v_horario.massoterapeuta_id, p_massoterapeuta_id);
    if v_profissional_id is not null then
        select ativo into v_massoterapeuta_ativo
        from public.massoterapeutas where id = v_profissional_id for share;
        if not found then
            return jsonb_build_object('sucesso', false, 'erro', 'massoterapeuta_nao_encontrado');
        end if;
        if not v_massoterapeuta_ativo then
            return jsonb_build_object('sucesso', false, 'erro', 'massoterapeuta_inativo');
        end if;
    end if;
    if (v_horario.data + v_horario.hora_inicio) at time zone 'America/Sao_Paulo' <= clock_timestamp() then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_passado');
    end if;
    if not v_horario.disponivel or exists (
        select 1 from public.agendamentos
        where horario_id = p_horario_id and status <> 'CANCELADO'
    ) then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_indisponivel');
    end if;

    select data_agendamento into v_conflito
    from public.agendamentos
    where colaborador_id = p_colaborador_id
      and status in ('AGENDADO', 'CONCLUIDO')
      and data_agendamento between v_horario.data - 14 and v_horario.data + 14
    order by abs(data_agendamento - v_horario.data), data_agendamento
    limit 1;
    if v_conflito is not null then
        return jsonb_build_object(
            'sucesso', false, 'erro', 'intervalo_minimo',
            'detalhe', format('Ja existe sessao valida em %s. Escolha data ate %s ou a partir de %s.',
                v_conflito, v_conflito - 15, v_conflito + 15)
        );
    end if;

    -- Availability can change while waiting for locks: recheck at the write.
    update public.horarios_disponiveis set disponivel = false
    where id = p_horario_id and disponivel
      and (data + hora_inicio) at time zone 'America/Sao_Paulo' > clock_timestamp();
    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_passado');
    end if;

    insert into public.agendamentos (
        colaborador_id, massoterapeuta_id, horario_id,
        data_agendamento, hora_inicio, hora_fim, status
    ) values (
        p_colaborador_id, v_profissional_id, p_horario_id,
        v_horario.data, v_horario.hora_inicio, v_horario.hora_fim, 'AGENDADO'
    ) returning * into v_agendamento;
    return jsonb_build_object('sucesso', true, 'agendamento', to_jsonb(v_agendamento));
exception
    -- Entering an exception handler rolls back all writes in this block.
    when unique_violation then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_indisponivel');
    when exclusion_violation then
        return jsonb_build_object('sucesso', false, 'erro', 'intervalo_minimo');
    when serialization_failure or deadlock_detected or lock_not_available then
        return jsonb_build_object('sucesso', false, 'erro', 'conflito_concorrente');
end;
$$;

create or replace function public.atualizar_status_agendamento(
    p_agendamento_id uuid,
    p_status varchar
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
    v_agendamento public.agendamentos%rowtype;
    v_colaborador_id uuid;
    v_horario_id uuid;
begin
    if p_status is null or p_status not in ('AGENDADO', 'CANCELADO', 'CONCLUIDO', 'FALTOU') then
        return jsonb_build_object('sucesso', false, 'erro', 'status_invalido');
    end if;
    select colaborador_id, horario_id into v_colaborador_id, v_horario_id
    from public.agendamentos where id = p_agendamento_id;
    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'agendamento_nao_encontrado');
    end if;

    perform id from public.colaboradores where id = v_colaborador_id for update;
    perform id from public.horarios_disponiveis where id = v_horario_id for update;
    select * into v_agendamento
    from public.agendamentos where id = p_agendamento_id for update;
    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'agendamento_nao_encontrado');
    end if;
    if v_agendamento.status = p_status then
        return jsonb_build_object('sucesso', true, 'agendamento', to_jsonb(v_agendamento));
    end if;
    if v_agendamento.status <> 'AGENDADO' or p_status = 'AGENDADO' then
        return jsonb_build_object('sucesso', false, 'erro', 'transicao_invalida');
    end if;

    update public.agendamentos set status = p_status, atualizado_em = clock_timestamp()
    where id = p_agendamento_id returning * into v_agendamento;
    if p_status = 'CANCELADO' then
        update public.horarios_disponiveis set disponivel = true
        where id = v_horario_id and not exists (
            select 1 from public.agendamentos
            where horario_id = v_horario_id and status <> 'CANCELADO'
        );
    else
        update public.horarios_disponiveis set disponivel = false where id = v_horario_id;
    end if;
    return jsonb_build_object('sucesso', true, 'agendamento', to_jsonb(v_agendamento));
exception
    when unique_violation then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_indisponivel');
    when exclusion_violation then
        return jsonb_build_object('sucesso', false, 'erro', 'intervalo_minimo');
    when serialization_failure or deadlock_detected or lock_not_available then
        return jsonb_build_object('sucesso', false, 'erro', 'conflito_concorrente');
end;
$$;

-- JWT authorization belongs to FastAPI. These RPCs must not be exposed to clients.
revoke execute on function public.criar_agendamento_transacional(uuid, uuid, uuid) from public;
revoke execute on function public.atualizar_status_agendamento(uuid, varchar) from public;
do $$
declare
    v_role text;
begin
    for v_role in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
        execute format('revoke execute on function public.criar_agendamento_transacional(uuid, uuid, uuid) from %I', v_role);
        execute format('revoke execute on function public.atualizar_status_agendamento(uuid, varchar) from %I', v_role);
    end loop;
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        grant execute on function public.criar_agendamento_transacional(uuid, uuid, uuid) to service_role;
        grant execute on function public.atualizar_status_agendamento(uuid, varchar) to service_role;
    end if;
end;
$$;


create or replace function public.proteger_configuracao_disponibilidade()
returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
    if row(new.chave_idempotencia, new.data, new.hora_inicio, new.hora_fim,
           new.capacidade, new.massoterapeuta_id, new.disponivel_inicial, new.legado)
       is distinct from
       row(old.chave_idempotencia, old.data, old.hora_inicio, old.hora_fim,
           old.capacidade, old.massoterapeuta_id, old.disponivel_inicial, old.legado) then
        raise check_violation using message = 'Configuração da disponibilidade é imutável.';
    end if;
    return new;
end;
$$;
drop trigger if exists disponibilidades_proteger_configuracao on public.disponibilidades;
create trigger disponibilidades_proteger_configuracao before update on public.disponibilidades
for each row execute function public.proteger_configuracao_disponibilidade();
revoke execute on function public.proteger_configuracao_disponibilidade() from public;

create or replace function public.validar_vaga_disponibilidade()
returns trigger language plpgsql set search_path = public, pg_temp as $$
declare
    v_grupo public.disponibilidades%rowtype;
begin
    select * into v_grupo from public.disponibilidades where id = new.disponibilidade_id for share;
    if not found or new.numero_vaga < 1 or new.numero_vaga > v_grupo.capacidade
       or new.data <> v_grupo.data or new.hora_inicio <> v_grupo.hora_inicio or new.hora_fim <> v_grupo.hora_fim then
        raise check_violation using message = 'Vaga incompatível com a disponibilidade.';
    end if;
    return new;
end;
$$;

drop trigger if exists horarios_validar_vaga on public.horarios_disponiveis;
create trigger horarios_validar_vaga
before insert or update of disponibilidade_id, numero_vaga, data, hora_inicio, hora_fim
on public.horarios_disponiveis for each row execute function public.validar_vaga_disponibilidade();

create or replace function public.criar_disponibilidade_transacional(
    p_chave_idempotencia uuid, p_data date, p_hora_inicio time, p_hora_fim time,
    p_capacidade integer, p_massoterapeuta_id uuid default null, p_disponivel boolean default true
)
returns jsonb language plpgsql set search_path = public, pg_temp as $$
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

    -- Serialize retries by key, then changes to the same calendar day.
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
        -- Historical overlaps remain; new intervals cannot overlap any existing interval.
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

revoke all on table public.disponibilidades from public;
revoke execute on function public.criar_disponibilidade_transacional(uuid, date, time, time, integer, uuid, boolean) from public;
revoke execute on function public.validar_vaga_disponibilidade() from public;
do $$
declare v_role text;
begin
    for v_role in select rolname from pg_roles where rolname in ('anon', 'authenticated') loop
        execute format('revoke all on table public.disponibilidades from %I', v_role);
        execute format('revoke execute on function public.criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean) from %I', v_role);
        execute format('revoke execute on function public.validar_vaga_disponibilidade() from %I', v_role);
    end loop;
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        grant select, insert, update on public.disponibilidades to service_role;
        grant execute on function public.criar_disponibilidade_transacional(uuid,date,time,time,integer,uuid,boolean) to service_role;
    end if;
end;
$$;
