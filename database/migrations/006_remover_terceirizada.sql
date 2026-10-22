begin;

-- Quarantine legacy accounts without deleting identities or historical lot grants.
update public.usuarios set ativo=false where role='terceirizada' and ativo;
alter table public.usuarios drop constraint if exists usuarios_role_valida;
alter table public.usuarios add constraint usuarios_role_valida check (
    role in ('admin','colaborador') or (role='terceirizada' and not ativo)
);
create or replace function public.validar_perfil_usuario_mvp()
returns trigger language plpgsql security invoker set search_path=public,pg_temp as $$
begin
    if new.role not in ('admin','colaborador') and
       (tg_op='INSERT' or new.role is distinct from old.role or new.ativo) then
        raise check_violation using message='Somente admin e colaborador podem autenticar.';
    end if;
    return new;
end;
$$;
drop trigger if exists usuarios_perfis_mvp on public.usuarios;
create trigger usuarios_perfis_mvp before insert or update on public.usuarios
for each row execute function public.validar_perfil_usuario_mvp();
drop function if exists public.provisionar_terceirizada(uuid,text,text,uuid[]);
drop function if exists public.consultar_agenda_terceirizada(uuid,date,date,text[],integer,integer);
revoke all on public.usuarios_agenda_lotes from public,service_role;
revoke all on function public.validar_perfil_usuario_mvp() from public,service_role;
do $$
declare papel text;
begin
    foreach papel in array array['anon','authenticated'] loop
        if exists(select 1 from pg_roles where rolname=papel) then
            execute format('revoke all on public.usuarios_agenda_lotes from %I',papel);
            execute format('revoke all on function public.validar_perfil_usuario_mvp() from %I',papel);
        end if;
    end loop;
end;
$$;
notify pgrst,'reload schema';
commit;
