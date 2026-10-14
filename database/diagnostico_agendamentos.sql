-- Read-only checks to run before migration 002. No automatic data repairs.
select role, count(*) as contas_sem_vinculo
from public.usuarios
where role = 'colaborador' and colaborador_id is null
group by role;

select horario_id, count(*) as reservas_nao_canceladas
from public.agendamentos
where status <> 'CANCELADO'
group by horario_id having count(*) > 1;

select a.id as agendamento_a, b.id as agendamento_b, a.colaborador_id,
       a.data_agendamento as data_a, b.data_agendamento as data_b
from public.agendamentos a join public.agendamentos b
  on a.colaborador_id = b.colaborador_id and a.id < b.id
where a.status in ('AGENDADO', 'CONCLUIDO')
  and b.status in ('AGENDADO', 'CONCLUIDO')
  and abs(a.data_agendamento - b.data_agendamento) < 15;

select h.id as horario_id, a.id as agendamento_id, a.status
from public.horarios_disponiveis h join public.agendamentos a on a.horario_id = h.id
where h.disponivel and a.status <> 'CANCELADO';

-- Review these manually: false may represent an intentionally blocked slot.
select h.id as horario_id
from public.horarios_disponiveis h
where not h.disponivel and not exists (
    select 1 from public.agendamentos a
    where a.horario_id = h.id and a.status <> 'CANCELADO'
);
