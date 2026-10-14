-- READ ONLY. Run before and after 005 with an administrative connection.
-- No credential values or personal rows are returned.
select current_user as executor, n.nspname, r.rolname as dono,
       pg_has_role(current_user,n.nspowner,'USAGE') as executor_pode_gerenciar, n.nspacl
from pg_namespace n join pg_roles r on r.oid=n.nspowner where n.nspname='public';

select rolname, rolsuper, rolbypassrls, rolcreaterole, rolinherit
from pg_roles where rolname in ('anon','authenticated','service_role');

select membro.rolname as membro, grupo.rolname as grupo
from pg_auth_members m join pg_roles membro on membro.oid=m.member
join pg_roles grupo on grupo.oid=m.roleid
where membro.rolname in ('anon','authenticated','service_role');

select c.relname, c.relkind, r.rolname as dono, c.relrowsecurity, c.relforcerowsecurity,
       pg_has_role(current_user,c.relowner,'USAGE') as executor_pode_gerenciar, c.relacl
from pg_class c join pg_namespace n on n.oid=c.relnamespace
join pg_roles r on r.oid=c.relowner
where n.nspname='public' and c.relkind in ('r','p','v','m','f','S');

select c.relname, a.attname, a.attacl
from pg_attribute a join pg_class c on c.oid=a.attrelid
join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and a.attnum>0 and not a.attisdropped and a.attacl is not null;

select schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check
from pg_policies where schemaname='public';

select p.oid::regprocedure as rotina, r.rolname as dono, p.prosecdef, p.proacl,
       pg_has_role(current_user,p.proowner,'USAGE') as executor_pode_gerenciar
from pg_proc p join pg_namespace n on n.oid=p.pronamespace
join pg_roles r on r.oid=p.proowner where n.nspname='public';

select r.rolname as criador, n.nspname, d.defaclobjtype, d.defaclacl
from pg_default_acl d join pg_roles r on r.oid=d.defaclrole
left join pg_namespace n on n.oid=d.defaclnamespace
where d.defaclnamespace in (0,'public'::regnamespace);

select r.rolname, has_schema_privilege(r.rolname,'public','USAGE') as uso,
       has_schema_privilege(r.rolname,'public','CREATE') as criar
from pg_roles r where r.rolname in ('anon','authenticated','service_role');

select r.rolname, c.relname,
       has_table_privilege(r.rolname,c.oid,'SELECT') as ler,
       has_table_privilege(r.rolname,c.oid,'INSERT') as inserir,
       has_table_privilege(r.rolname,c.oid,'DELETE,TRUNCATE') as apagar,
       has_any_column_privilege(r.rolname,c.oid,'UPDATE') as atualizar_alguma_coluna
from pg_roles r cross join pg_class c join pg_namespace n on n.oid=c.relnamespace
where r.rolname in ('anon','authenticated','service_role') and n.nspname='public'
  and c.relkind in ('r','p','v','m','f');
