begin;

-- Invalid existing accounts must be reviewed manually before applying this migration.
do $$
begin
    if exists (select 1 from usuarios where role = 'colaborador' and colaborador_id is null) then
        raise exception 'Existem contas de colaborador sem vinculo. Revise-as antes de aplicar a migration.';
    end if;
    if not exists (
        select 1 from pg_constraint
        where conrelid = 'usuarios'::regclass
          and conname = 'usuarios_colaborador_vinculo_obrigatorio'
    ) then
        alter table usuarios add constraint usuarios_colaborador_vinculo_obrigatorio
            check (role <> 'colaborador' or colaborador_id is not null) not valid;
    end if;
end;
$$;

alter table usuarios validate constraint usuarios_colaborador_vinculo_obrigatorio;
commit;
