

-- ---------------------------------------------------------------------
-- 1. Criacao de agendamento (validacao + reserva + insert, atomico)
-- ---------------------------------------------------------------------
create or replace function criar_agendamento_transacional(
    p_colaborador_id uuid,
    p_massoterapeuta_id uuid,
    p_horario_id uuid
)
returns jsonb
language plpgsql
as $$
declare
    v_horario horarios_disponiveis%rowtype;
    v_massoterapeuta_ativo boolean;
    v_conflito date;
    v_agendamento agendamentos%rowtype;
begin
    
    select * into v_horario
    from horarios_disponiveis
    where id = p_horario_id
    for update;

    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_nao_encontrado');
    end if;

    if not exists (select 1 from colaboradores where id = p_colaborador_id) then
        return jsonb_build_object('sucesso', false, 'erro', 'colaborador_nao_encontrado');
    end if;

    select ativo into v_massoterapeuta_ativo
    from massoterapeutas
    where id = p_massoterapeuta_id;

    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'massoterapeuta_nao_encontrado');
    end if;

    if v_massoterapeuta_ativo is false then
        return jsonb_build_object('sucesso', false, 'erro', 'massoterapeuta_inativo');
    end if;

    if v_horario.massoterapeuta_id <> p_massoterapeuta_id then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_massoterapeuta_invalido');
    end if;

    if v_horario.disponivel is false then
        return jsonb_build_object('sucesso', false, 'erro', 'horario_indisponivel');
    end if;

    
    select data_agendamento into v_conflito
    from agendamentos
    where colaborador_id = p_colaborador_id
      and status in ('AGENDADO', 'CONCLUIDO')
      and abs(data_agendamento - v_horario.data) < 15
    order by abs(data_agendamento - v_horario.data)
    limit 1;

    if v_conflito is not null then
        return jsonb_build_object(
            'sucesso', false,
            'erro', 'intervalo_minimo',
            'detalhe', format(
                'Já existe sessão válida em %s. Novo agendamento permitido somente a partir de %s.',
                to_char(v_conflito, 'DD/MM/YYYY'),
                to_char(v_conflito + 15, 'DD/MM/YYYY')
            )
        );
    end if;

    update horarios_disponiveis
    set disponivel = false
    where id = p_horario_id;

    insert into agendamentos (
        colaborador_id,
        massoterapeuta_id,
        horario_id,
        data_agendamento,
        hora_inicio,
        hora_fim,
        status
    )
    values (
        p_colaborador_id,
        p_massoterapeuta_id,
        p_horario_id,
        v_horario.data,
        v_horario.hora_inicio,
        v_horario.hora_fim,
        'AGENDADO'
    )
    returning * into v_agendamento;

    return jsonb_build_object('sucesso', true, 'agendamento', to_jsonb(v_agendamento));
end;
$$;


-- ---------------------------------------------------------------------
-- 2. Mudanca de status (cancelar / concluir / faltou)
--    Ao cancelar, o horario volta a ficar disponivel na mesma transacao.
-- ---------------------------------------------------------------------
create or replace function atualizar_status_agendamento(
    p_agendamento_id uuid,
    p_status varchar
)
returns jsonb
language plpgsql
as $$
declare
    v_agendamento agendamentos%rowtype;
begin
    if p_status not in ('AGENDADO', 'CANCELADO', 'CONCLUIDO', 'FALTOU') then
        return jsonb_build_object('sucesso', false, 'erro', 'status_invalido');
    end if;

    select * into v_agendamento
    from agendamentos
    where id = p_agendamento_id
    for update;

    if not found then
        return jsonb_build_object('sucesso', false, 'erro', 'agendamento_nao_encontrado');
    end if;

    if v_agendamento.status = p_status then
        return jsonb_build_object('sucesso', true, 'agendamento', to_jsonb(v_agendamento));
    end if;

    update agendamentos
    set status = p_status,
        atualizado_em = now()
    where id = p_agendamento_id
    returning * into v_agendamento;

    
    if p_status = 'CANCELADO' then
        update horarios_disponiveis
        set disponivel = true
        where id = v_agendamento.horario_id;
    end if;

    return jsonb_build_object('sucesso', true, 'agendamento', to_jsonb(v_agendamento));
end;
$$;
