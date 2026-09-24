create table if not exists usuarios (
    id uuid primary key default gen_random_uuid(),
    colaborador_id uuid unique references colaboradores(id) on delete restrict,
    email varchar(255) not null unique,
    senha_hash text not null,
    role varchar(40) not null default 'colaborador',
    ativo boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint usuarios_role_valida check (role in ('colaborador', 'admin'))
);

create unique index if not exists idx_usuarios_email_normalizado
    on usuarios (lower(email));

create index if not exists idx_usuarios_colaborador_id
    on usuarios (colaborador_id);

create or replace function atualizar_updated_at_usuarios()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trigger_usuarios_updated_at on usuarios;

create trigger trigger_usuarios_updated_at
before update on usuarios
for each row
execute function atualizar_updated_at_usuarios();
