-- Read-only preflight. No passwords, emails or collaborator identities are returned.
select role, count(*) as quantidade
from public.usuarios
where role not in ('admin','colaborador','terceirizada')
group by role;

select count(*) as colaboradores_sem_vinculo
from public.usuarios where role='colaborador' and colaborador_id is null;

select count(*) as institucionais_com_vinculo_pessoal
from public.usuarios where role='terceirizada' and colaborador_id is not null;

select conname, pg_get_constraintdef(oid) as definicao
from pg_constraint
where conrelid='public.usuarios'::regclass and contype='c';

select to_regclass('public.disponibilidades') as tabela_exigida_pela_004;
