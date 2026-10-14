# Agendamentos Transacionais

## Banco Existente

Não execute novamente o schema inicial como substituto de uma migration.

1. Execute somente as consultas de `database/diagnostico_agendamentos.sql`.
2. Revise contas de colaboradores sem vínculo antes de aplicar a migration 001.
3. Execute manualmente `database/migrations/001_usuarios_colaborador_vinculo.sql`.
4. Revise os conflitos de reservas, intervalo e disponibilidade encontrados pelo diagnóstico.
5. Em janela de manutenção, execute integralmente `database/migrations/002_agendamentos_transacionais.sql`.
6. Execute a migration 003 conforme database/README_disponibilidade.md.
7. Execute a migration 004 e depois 005 conforme README_terceirizada.md e README_seguranca.md.
8. So reabra API e acesso direto de clientes apos validar ACL/RLS e PostgREST.

A migration 002 inclui as RPCs da etapa transacional. A migration 003 instala as versões canônicas atuais de `database/rpc_agendamentos.sql`; não reaplique a 002 após a 003. A ordem completa é 001 -> 002 -> 003 -> 004 -> 005. Nenhuma foi aplicada no Supabase real.

A janela 001-004 pode preservar grants legados expostos. Bloqueie clientes da
Data API alem do FastAPI durante toda a sequencia, conforme README_seguranca.md.

A migration é transacional: um erro deve abortar a alteração inteira. Se o cliente SQL deixar a sessão em estado de erro, execute ROLLBACK antes de repetir. Os scripts não excluem, cancelam ou corrigem registros automaticamente.

## Dados Que Exigem Revisão

- Contas com role colaborador e vínculo nulo impedem a migration 001.
- Mais de um agendamento não cancelado por vaga impede a unicidade parcial.
- Sessões AGENDADO/CONCLUIDO do mesmo colaborador com menos de 15 dias impedem a constraint de exclusão.
- Vaga marcada livre com registro não cancelado impede a migration 002.
- Vaga ocupada sem registro não cancelado é reportada para revisão: pode ser bloqueio intencional.

Revise os registros e o histórico real antes de qualquer correção manual. Não apague agendamentos para aplicar a migration nem altere sessões concluídas apenas para satisfazer a constraint. Se os dados representam exceções reais à regra, defina explicitamente uma política de saneamento antes de prosseguir.

## Banco Novo

Execute `schema.sql`, `auth_schema.sql` e migrations 001 -> 002 -> 003 -> 004 -> 005. As tabelas iniciais ja recebem RLS/REVOKE, mas a allowlist explicita do servidor e instalada pela 005.

O PostgreSQL precisa permitir a extensão btree_gist. A migration configura seu search_path de sessão para public e extensions, compatível com extensão instalada em qualquer desses schemas.

## Garantias Da Criação

O backend tradicional chama somente criar_agendamento_transacional. O LangGraph mantém sua pré-validação, mas usa a mesma RPC na execução.

A RPC bloqueia primeiro o colaborador e depois a vaga, revalida atividade, profissional, disponibilidade, horário e intervalo, e só então altera a disponibilidade e insere. O bloqueio do colaborador serializa suas solicitações para vagas distintas. O índice parcial impede dois registros não cancelados na mesma vaga. A constraint de exclusão protege o intervalo de 15 dias inclusive contra inserts concorrentes fora da RPC.

Datas e horas de atendimento são interpretadas em America/Sao_Paulo. O início deve ser posterior a clock_timestamp(), incluindo a verificação após a espera pelo bloqueio.

Qualquer falha de insert reverte a reserva. Não há compensação por chamadas HTTP separadas.

Os status CANCELADO e FALTOU não contam para o intervalo de 15 dias; AGENDADO e CONCLUIDO contam. CONCLUIDO e FALTOU continuam ocupando a vaga histórica. Somente CANCELADO libera a vaga.

## Status E Contrato HTTP

| Origem | Destino permitido |
| --- | --- |
| AGENDADO | CANCELADO, CONCLUIDO, FALTOU |
| CANCELADO | Somente repetição de CANCELADO |
| CONCLUIDO | Somente repetição de CONCLUIDO |
| FALTOU | Somente repetição de FALTOU |

Repetir AGENDADO também é idempotente. Cancelar novamente um agendamento antigo não libera a vaga de uma reserva posterior. Não existe reativação de estados finais.

As RPCs retornam `{sucesso, agendamento}` ou `{sucesso:false, erro, detalhe?}`. O repository valida o envelope e devolve somente o agendamento ou um erro de domínio. A resposta HTTP continua compatível com AgendamentoResponse.

| Situação | HTTP |
| --- | --- |
| Criação | 201 |
| Status atualizado/repetido | 200 |
| Entidade inexistente | 404 |
| Inativo, passado, ocupado, intervalo, transição inválida, concorrência | 409 |
| Profissional incompatível ou status inválido | 422 |
| Criação em nome de terceiro / operação admin por colaborador | 403 |
| Sem token | 401 |
| Banco não configurado | 503 |
| Falha inesperada/contrato RPC inválido | 500, mensagem genérica |

Permissões de execução das RPCs são removidas de PUBLIC, anon e authenticated. No Supabase, service_role recebe execução; use a chave secreta do servidor, nunca a chave anon. As funções continuam SECURITY INVOKER e a autorização individual permanece no FastAPI.

## Testes Com Mocks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Os testes de API/service/repository verificam os contratos, a tradução de erros, os acessos e a ausência de compensação. Eles não provam locks, atomicidade ou concorrência PostgreSQL.

## Testes Com PostgreSQL Real

Use um PostgreSQL local descartável e vazio. Não utilize o banco Supabase, dados reais ou um banco de desenvolvimento compartilhado.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-postgres-test.txt
$env:TEST_POSTGRES_DSN="host=127.0.0.1 port=5432 dbname=bb_massoterapia_test user=USUARIO_TESTE password=SENHA_TESTE"
$env:TEST_POSTGRES_ALLOW_SCHEMA_SETUP="1"
.\.venv\Scripts\python.exe -m pytest tests/test_postgres_agendamentos.py -q
```

Os modulos PostgreSQL so executam com opt-in, loopback, banco vazio bb_massoterapia_test* e cluster descartavel sem roles anon/authenticated/service_role preexistentes. O operador precisa ser superuser para criar roles de teste com BYPASSRLS e extensoes. Fixtures limpam os objetos e roles criadas; nao use um cluster compartilhado. Consulte README_seguranca.md para os testes por role.

São exercitados: upgrade do schema antigo, rollback após falha de insert, indisponibilidade, duas conexões simultâneas, limite de 14/15 dias, colaboradores/profissionais inativos, horários passados, todas as transições, cancelamento/reutilização, histórico e constraints em inserts diretos. O teste concorrente confirma dois workers esperando locks antes de liberar a disputa.

Sem configuração, esse módulo é pulado explicitamente.

## Validação No Swagger

1. Autorize um colaborador ativo.
2. Crie para seu próprio ID numa vaga futura: 201.
3. Repita para a mesma vaga: 409.
4. Tente outra vaga em menos de 15 dias: 409; em 15 dias ou mais, permitido.
5. Como admin, altere o primeiro registro para CANCELADO: 200, objeto sem envelope.
6. Confira o registro CANCELADO e o horário livre no Supabase.
7. Reserve a mesma vaga novamente: novo ID e histórico anterior preservado.
8. Tente reativar o cancelado: 409.
9. Repita seu cancelamento: 200; a vaga da nova reserva deve continuar ocupada.
10. Confirme que colaborador não altera status de admin e não agenda para terceiros.

Os contratos de disponibilidade e o vínculo opcional com profissionais estão documentados em database/README_disponibilidade.md.
