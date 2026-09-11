create extension if not exists "pgcrypto";

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

create table if not exists horarios_disponiveis (
    id uuid primary key default gen_random_uuid(),
    massoterapeuta_id uuid not null references massoterapeutas(id) on delete cascade,
    data date not null,
    hora_inicio time not null,
    hora_fim time not null,
    disponivel boolean not null default true,
    criado_em timestamptz not null default now(),
    constraint horarios_periodo_valido check (hora_fim > hora_inicio),
    constraint horarios_unicos_por_massoterapeuta unique (massoterapeuta_id, data, hora_inicio, hora_fim)
);

create table if not exists agendamentos (
    id uuid primary key default gen_random_uuid(),
    colaborador_id uuid not null references colaboradores(id) on delete restrict,
    massoterapeuta_id uuid not null references massoterapeutas(id) on delete restrict,
    horario_id uuid not null references horarios_disponiveis(id) on delete restrict,
    data_agendamento date not null,
    hora_inicio time not null,
    hora_fim time not null,
    status varchar(20) not null,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    constraint agendamentos_status_valido check (status in ('AGENDADO', 'CANCELADO', 'CONCLUIDO', 'FALTOU')),
    constraint agendamentos_periodo_valido check (hora_fim > hora_inicio),
    constraint agendamentos_horario_unico unique (horario_id)
);

create index if not exists idx_horarios_disponiveis_data
    on horarios_disponiveis (data);

create index if not exists idx_agendamentos_colaborador
    on agendamentos (colaborador_id);

create index if not exists idx_agendamentos_data
    on agendamentos (data_agendamento);
