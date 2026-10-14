begin;
set local search_path = public, extensions;
create extension if not exists btree_gist;

-- Apply in a maintenance window. No rows are deleted or repaired.
lock table public.agendamentos, public.horarios_disponiveis in access exclusive mode;
do $$
begin
    if exists (
        select horario_id from public.agendamentos
        where status <> 'CANCELADO' group by horario_id having count(*) > 1
    ) then
        raise exception 'Vagas com multiplos agendamentos nao cancelados. Consulte database/diagnostico_agendamentos.sql.';
    end if;
    if exists (
        select 1 from public.agendamentos a join public.agendamentos b
          on a.colaborador_id = b.colaborador_id and a.id < b.id
        where a.status in ('AGENDADO', 'CONCLUIDO')
          and b.status in ('AGENDADO', 'CONCLUIDO')
          and abs(a.data_agendamento - b.data_agendamento) < 15
    ) then
        raise exception 'Sessoes conflitantes no intervalo de 15 dias. Revise os dados manualmente.';
    end if;
    if exists (
        select 1 from public.horarios_disponiveis h join public.agendamentos a on a.horario_id = h.id
        where h.disponivel and a.status <> 'CANCELADO'
    ) then
        raise exception 'Vagas livres com agendamento nao cancelado. Revise a disponibilidade manualmente.';
    end if;
end;
$$;

alter table public.agendamentos drop constraint if exists agendamentos_horario_unico;
create unique index if not exists agendamentos_horario_nao_cancelado_unico
    on public.agendamentos (horario_id) where status <> 'CANCELADO';

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'public.agendamentos'::regclass
          and conname = 'agendamentos_intervalo_minimo'
    ) then
        alter table public.agendamentos add constraint agendamentos_intervalo_minimo
            exclude using gist (
                colaborador_id with =,
                daterange(data_agendamento, data_agendamento + 15, '[)') with &&
            ) where (status in ('AGENDADO', 'CONCLUIDO'));
    end if;
end;
$$;

-- Canonical definitions also available in database/rpc_agendamentos.sql.
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

    select ativo into v_massoterapeuta_ativo
    from public.massoterapeutas where id = p_massoterapeuta_id for share;
    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'massoterapeuta_nao_encontrado');
    end if;
    if not v_massoterapeuta_ativo then
        return jsonb_build_object('sucesso', false, 'erro', 'massoterapeuta_inativo');
    end if;

    select * into v_horario
    from public.horarios_disponiveis where id = p_horario_id for update;
    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_nao_encontrado');
    end if;
    if v_horario.massoterapeuta_id <> p_massoterapeuta_id then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_massoterapeuta_invalido');
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
        p_colaborador_id, p_massoterapeuta_id, p_horario_id,
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

commit;
