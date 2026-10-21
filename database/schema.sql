begin;
set local search_path = public, extensions;
create extension if not exists "pgcrypto";
create extension if not exists btree_gist;

create table if not exists colaboradores (
    id uuid primary key default gen_random_uuid(),
    nome varchar(160) not null,
    matricula varchar(80) not null unique,
    email varchar(255) not null unique,
    setor varchar(120),
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

create table if not exists massoterapeutas (
    id uuid primary key default gen_random_uuid(),
    nome varchar(160) not null,
    email varchar(255) unique,
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

create table if not exists public.disponibilidades (
    id uuid primary key default gen_random_uuid(),
    chave_idempotencia uuid not null unique,
    data date not null,
    hora_inicio time not null,
    hora_fim time not null,
    capacidade integer not null check (capacidade > 0),
    massoterapeuta_id uuid references public.massoterapeutas(id) on delete restrict,
    disponivel_inicial boolean not null default true,
    legado boolean not null default false,
    criado_em timestamptz not null default now(),
    constraint disponibilidades_periodo_valido check (hora_fim > hora_inicio),
    constraint disponibilidades_intervalo_unico unique (data, hora_inicio, hora_fim),
    constraint disponibilidades_sem_sobreposicao exclude using gist (
        tsrange(data + hora_inicio, data + hora_fim, '[)') with &&
    ) where (not legado)
);

create table if not exists horarios_disponiveis (
    id uuid primary key default gen_random_uuid(),
    massoterapeuta_id uuid references massoterapeutas(id) on delete restrict,
    disponibilidade_id uuid not null,
    numero_vaga integer not null,
    data date not null,
    hora_inicio time not null,
    hora_fim time not null,
    disponivel boolean not null default true,
    criado_em timestamptz not null default now(),
    constraint horarios_periodo_valido check (hora_fim > hora_inicio),
    constraint horarios_disponibilidade_fkey foreign key (disponibilidade_id)
        references public.disponibilidades(id) on delete restrict,
    constraint horarios_numero_vaga_positivo check (numero_vaga > 0),
    constraint horarios_vaga_unica unique (disponibilidade_id, numero_vaga)
);

create table if not exists agendamentos (
    id uuid primary key default gen_random_uuid(),
    colaborador_id uuid not null references colaboradores(id) on delete restrict,
    massoterapeuta_id uuid references massoterapeutas(id) on delete restrict,
    horario_id uuid not null references horarios_disponiveis(id) on delete restrict,
    data_agendamento date not null,
    hora_inicio time not null,
    hora_fim time not null,
    status varchar(20) not null,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    constraint agendamentos_status_valido check (status in ('AGENDADO', 'CANCELADO', 'CONCLUIDO', 'FALTOU')),
    constraint agendamentos_periodo_valido check (hora_fim > hora_inicio),
    constraint agendamentos_intervalo_minimo exclude using gist (
        colaborador_id with =,
        daterange(data_agendamento, data_agendamento + 15, '[)') with &&
    ) where (status in ('AGENDADO', 'CONCLUIDO'))
);

create unique index if not exists agendamentos_horario_nao_cancelado_unico
    on agendamentos (horario_id) where status <> 'CANCELADO';

create index if not exists idx_horarios_disponiveis_data
    on horarios_disponiveis (data);

create index if not exists idx_agendamentos_colaborador
    on agendamentos (colaborador_id);

create index if not exists idx_agendamentos_data
    on agendamentos (data_agendamento);

-- Initial tables are private even before migration 005 installs server privileges.
do $$
declare v_table text; v_role text;
begin
    foreach v_table in array array['colaboradores','massoterapeutas','disponibilidades','horarios_disponiveis','agendamentos'] loop
        execute format('alter table public.%I enable row level security',v_table);
        execute format('revoke all on public.%I from public',v_table);
        foreach v_role in array array['anon','authenticated'] loop
            if exists (select 1 from pg_roles where rolname=v_role) then
                execute format('revoke all on public.%I from %I',v_table,v_role);
            end if;
        end loop;
    end loop;
end;
$$;
commit;
