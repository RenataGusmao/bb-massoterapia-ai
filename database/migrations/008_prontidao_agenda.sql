begin;
set local search_path=public,pg_catalog;

-- Read-only verification, independent of the generator's success envelope.
-- Existing overlapping lots follow the preservation policy of migration 007.
create or replace function public.verificar_prontidao_agenda(p_calendario jsonb)
returns jsonb language sql stable security invoker set search_path=public,pg_temp as $$
with referencia as (
    select (statement_timestamp() at time zone 'America/Sao_Paulo')::date as hoje
), esperado as (
    select (j->>'data')::date as data,(j->>'feriado')::boolean as feriado
    from jsonb_array_elements(p_calendario) j
), calendario as (
    select count(*)=31 and count(distinct e.data)=31
           and bool_and(e.data between r.hoje and r.hoje+30
                        and c.data is not null and c.feriado=e.feriado) as completo
    from esperado e cross join referencia r
    left join public.calendario_atendimento c on c.data=e.data
), intervalos as (
    select r.hoje+n as data,t as inicio,(t+interval '30 minutes')::time as fim
    from referencia r cross join generate_series(0,30) n
    cross join unnest(array[time '09:40',time '10:10',time '10:40',time '11:10',
        time '13:00',time '13:30',time '14:00',time '14:30',time '15:00',time '15:30']) t
    where public.agenda_permite(r.hoje+n,t,(t+interval '30 minutes')::time)
      and ((r.hoje+n)+t) at time zone 'America/Sao_Paulo'>statement_timestamp()
), lotes as (
    select d.id,d.data,d.hora_inicio,d.hora_fim,d.capacidade,
           count(h.id) as vagas,
           count(h.id) filter(where row(h.data,h.hora_inicio,h.hora_fim)
               is distinct from row(d.data,d.hora_inicio,d.hora_fim)) as divergencias
    from public.disponibilidades d cross join referencia r
    left join public.vagas_agenda h on h.disponibilidade_id=d.id
    where d.data between r.hoje and r.hoje+30
    group by d.id
), cobertura as (
    select count(*) as esperados,
           count(*) filter(where not exists (
               select 1 from lotes d where d.data=i.data
                 and d.hora_inicio<i.fim and d.hora_fim>i.inicio
                 and d.vagas=d.capacidade and d.divergencias=0
           )) as pendentes
    from intervalos i
)
select jsonb_build_object(
    'pronta',coalesce(c.completo,false) and x.pendentes=0,
    'inicio',r.hoje,'fim',r.hoje+30,
    'calendario_completo',coalesce(c.completo,false),
    'intervalos_esperados',x.esperados,'intervalos_pendentes',x.pendentes)
from calendario c cross join cobertura x cross join referencia r;
$$;

revoke all on function public.verificar_prontidao_agenda(jsonb) from public,service_role;
do $$
declare papel text;
begin
    foreach papel in array array['anon','authenticated'] loop
        if exists(select 1 from pg_roles where rolname=papel) then
            execute format('revoke all on function public.verificar_prontidao_agenda(jsonb) from %I',papel);
            if has_function_privilege(papel,'public.verificar_prontidao_agenda(jsonb)','execute') then
                raise exception 'Role cliente % mantem acesso herdado a verificacao da agenda',papel;
            end if;
        end if;
    end loop;
end;
$$;
grant execute on function public.verificar_prontidao_agenda(jsonb) to service_role;
notify pgrst,'reload schema';
commit;
