# Seguranca e Permissoes

> Este guia descreve a etapa 005. A evolucao atual utiliza 006/007, retira o
> perfil terceirizada e adiciona ACLs/RLS para calendario, bloqueios e leitura
> agregada. Consulte README_agenda_automatica.md antes de implantar. Nao reaplique
> 005 apos 006: as RPCs institucionais da allowlist antiga foram retiradas.

## Modelo Final

As tabelas do BB Massoterapia AI sao privadas do backend; public pode conter
objetos internos administrados pelo Supabase. Os JWTs de
admin, colaborador e terceirizada sao validados no FastAPI; nao sao credenciais
para consultar tabelas pelo Supabase. O servidor usa uma credencial secreta
que executa como service_role, sem substituir o Authorization do SDK pelo
token do usuario. Ownership e escopo institucional continuam na API/RPC.

A migration 005 atua somente nas sete tabelas e oito funcoes da aplicacao:
as cinco RPCs e atualizar_updated_at_usuarios, validar_vaga_disponibilidade,
proteger_configuracao_disponibilidade. Revoga grants diretos de PUBLIC, anon,
authenticated e service_role (inclusive colunas), habilita RLS e instala a
policy restritiva bb_backend_only nas sete tabelas. Reinstala a allowlist do
servidor. Aborta se clientes retiverem ACLs herdadas ou uma funcao da aplicacao
for SECURITY DEFINER. Nao modifica dados.

O schema public pode conter infraestrutura Supabase: nao se revogam suas ACLs
globalmente. USAGE dos clientes pode permanecer; USAGE nao concede SELECT nem
EXECUTE nos objetos privados. Apenas o USAGE necessario do servidor e concedido.
Views, sequences, extensoes, outras aplicacoes e funcoes internas ficam intactos.
Inventarie proxies SECURITY DEFINER/views que possam expor dados privados:
a 005 nao pode neutralizar rotinas administrativas arbitrarias fora da allowlist.

| Role SQL | Schema public | Objetos da aplicacao |
| --- | --- | --- |
| PUBLIC, anon, authenticated | ACL existente preservada | Sem grants diretos; RLS restritivo nas tabelas; sem EXECUTE |
| service_role | USAGE, sem CREATE como pre-condicao | SELECT/INSERT nas sete tabelas; UPDATE limitado; cinco RPCs |

UPDATE permitido ao servidor:

- colaboradores, massoterapeutas e usuarios: ativo;
- horarios_disponiveis: disponivel;
- agendamentos: status e atualizado_em;
- disponibilidades: capacidade, para permitir SELECT FOR SHARE/KEY SHARE.

Locks de linha exigem UPDATE em pelo menos uma coluna. A concessao em capacidade
nao permite alterar a capacidade real: o trigger imutavel da etapa 3 permanece.
Nao ha DELETE, TRUNCATE, REFERENCES, TRIGGER, CREATE ou privilegios de sequences
para o servidor. IDs UUID gerados pelas tabelas existentes nao usam sequences.
A revogacao manual de lotes permanece uma operacao administrativa no banco;
nao existe repository/end-point de DELETE de acessos.

Somente estas RPCs recebem EXECUTE para service_role:
criar_agendamento_transacional, atualizar_status_agendamento,
criar_disponibilidade_transacional, provisionar_terceirizada e
consultar_agenda_terceirizada. Permanecem SECURITY INVOKER. Funcoes de trigger
nao sao RPCs do cliente; PostgreSQL executa os triggers automaticamente sem
exigir um grant EXECUTE direto ao papel que escreve a linha.

A [documentacao oficial Supabase](https://supabase.com/docs/guides/database/postgres/row-level-security#bypassing-row-level-security)
explica que a chave secreta usa service_role com BYPASSRLS. Isso nao dispensa
os grants explicitos. Um token de usuario instalado no cliente Supabase pode
mudar a role efetiva: nao compartilhe sessoes de Auth com esse cliente servidor.

## Privilegios Futuros

A 005 nao executa ALTER DEFAULT PRIVILEGES, nem global nem IN SCHEMA.
Todos os defaults permanecem intactos, inclusive os de supabase_admin e do
executor postgres. No Supabase, postgres pode administrar os objetos da
aplicacao sem ter autoridade sobre defaults de roles gerenciadas. A estrategia
anterior enumerava donos/criadores de todo public e abortava ao encontrar
supabase_admin; modificar tais roles nao e necessario para fechar objetos atuais.

Objetos futuros NAO recebem protecao automatica por esta migration. Cada nova
migration deve aplicar REVOKE de tabela/colunas/rotinas a PUBLIC e clientes,
RLS/policy restritiva e grants explicitos ao servidor, na mesma transacao da
criacao. O EXECUTE global padrao de PUBLIC e neutralizado objeto por objeto.
Nao mantenha trafego durante uma atualizacao que ainda nao instalou essas ACLs.
Reaplicar 005 protege somente os nomes/signaturas da allowlist; nao cobre novas
tabelas, funcoes, overloads, views nem schemas automaticamente.

O event trigger ensure_rls e rls_auto_enable nao sao removidos, alterados ou
incluidos nas revogacoes. Suas ACLs, ownership, corpo e configuracao permanecem.
A chamada automatica nao depende de um grant EXECUTE direto ao cliente; operacoes
internas continuam sujeitas ao contexto SECURITY INVOKER/DEFINER e privilegios
do executor/proprietario da funcao. RLS automatico sozinho nao elimina defaults,
nao instala a policy restritiva e nao impede roles com BYPASSRLS.
Valide o mecanismo real em homologacao sem assumir que corresponde ao simulador.

## Pre-condicoes e Escopo

Execute database/diagnostico_seguranca.sql e classifique resultados pelo escopo:
ownership de supabase_admin em objetos internos/defaults nao e bloqueio da 005.
Ownership insuficiente nas sete tabelas/oito funcoes da aplicacao e bloqueio real.
O executor precisa administrar esses objetos (inclusive policies) e conceder
USAGE do schema ao servidor. Nenhuma membership, ownership ou role e alterada
pela migration; GRANT OPTION sozinho nao permite ALTER TABLE/CREATE POLICY.

service_role deve existir com BYPASSRLS e sem CREATE no schema; clientes nao
podem ser superuser/BYPASSRLS nem herdar privilegios sobre os objetos privados.
Grants herdados nao sao corrigidos automaticamente: a migration aborta e deve
ser revista pelo operador. Defaults e privilegios de outros schemas/criadores
nao sao administrados. Novos objetos/assinaturas exigem nova revisao de seguranca.

## Aplicacao Segura

Nenhuma migration foi executada no Supabase real por esta implementacao.

Banco existente: diagnosticos das etapas anteriores -> 001 -> 002 -> 003 -> 004
-> 005_seguranca_permissoes.sql. Nao reaplique schema.sql para atualizar.
Banco novo: schema.sql -> auth_schema.sql -> 001 -> 002 -> 003 -> 004 -> 005.
schema.sql e auth_schema.sql ja fecham as tabelas iniciais com RLS e REVOKE,
mas nao substituem as cinco migrations nem instalam a allowlist completa.

Procedimento:

1. Confirme backup recuperavel e inventarie ownership/grants dos objetos da
   aplicacao, defaults gerenciados preservados e ensure_rls.
2. Coloque a API em manutencao e bloqueie tambem o acesso direto a Data API
   / GraphQL / Realtime por clientes. Parar somente o FastAPI nao fecha PostgREST.
   Use a configuracao de exposicao/gateway do ambiente e confirme o bloqueio
   com uma credencial publica; nao exponha registros reais para provar acesso.
3. Execute os diagnosticos e trate conflitos manualmente, preservando historico.
4. Aplique cada script integralmente, na ordem 001 -> 002 -> 003 -> 004 -> 005.
   Nao reaplique 002 apos 003, pois reinstala a RPC anterior.
5. Cada migration e transacional, mas seus COMMITs nao formam uma transacao unica
   da sequencia. 001-004 podem deixar grants legados ativos antes da 005. Se qualquer
   etapa falhar, mantenha todos os clientes bloqueados; execute ROLLBACK na sessao
   em erro, investigue e retome sem apagar dados.
6. Depois da 005, confira ACLs de tabela/coluna, RLS/policy nas sete tabelas,
   EXECUTE das cinco RPCs apenas para servidor, SECURITY INVOKER e ausencia de
   acesso herdado. Confira defaults, objetos internos e ensure_rls inalterados.
   USAGE existente dos clientes nao indica falha; SELECT/EXECUTE privados devem
   ser negados. Audite views/funcoes alternativas separadamente.
7. Em homologacao, teste REST real com anon/authenticated (negado), e com
   credencial servidor (fluxos legitimos). A negativa pode aparecer como erro
   de permissao ou recurso nao exposto; nao dependa apenas de um codigo HTTP.
8. Teste login das tres roles, ownership, reserva, intervalo, concorrencia,
   cancelamento/reuso, capacidade e lotes institucionais. Reabra o acesso somente
   quando as verificacoes SQL e PostgREST estiverem aprovadas.

A 005 e reexecutavel e nao executa UPDATE/DELETE/TRUNCATE em dados da aplicacao.
Mudancas sao de ACL, policies e RLS. DDL pode adquirir locks: janela de manutencao
continua obrigatoria. A notificacao final recarrega o schema do PostgREST.

## Login, JWT e LangGraph

Email nao textual no login recebe 422 antes de consultar o banco. Emails validos
continuam normalizados. Hash desconhecido/malformado falha fechado com a mesma
resposta 401 de credenciais invalidas, sem expor hash ou tentar corrigir senhas.
JWT exige sub, exp e role: sub textual UUID, exp inteiro NumericDate e role
textual entre as tres existentes. Expiracao e assinatura sao verificadas;
a role atual/atividade no banco continua sendo a fonte da autorizacao.
Nenhum segredo real ou parametro do ambiente foi alterado.

POST /graph/agendamentos tem AgendamentoGraphResponse tipado no 201: sucesso,
mensagem, interpretacao nullable e agendamento no contrato AgendamentoResponse,
com massoterapeuta_id nullable. Erros do grafo preservam status e campos
sucesso/mensagem/erro/sugestoes opcionais. O 422 documenta tanto o erro do grafo
quanto detail da validacao do FastAPI. Nao foram modificados os nodes, Gemini,
escolha de vagas, capacidade ou regra de 15 dias.

## Testes e Limites

tests/test_manutencao_seguranca.py usa mocks para HTTP/claims/hash/OpenAPI.
tests/test_postgres_agendamentos.py conserva os testes reais de regras de negocio,
principalmente executados como owner.
tests/test_postgres_seguranca.py usa SET ROLE anon/authenticated/service_role
com roles SQL reais e verifica tabela/coluna/schema/sequence/funcao, RLS mesmo
com policy permissiva anterior, preservacao de defaults e objetos compartilhados,
reexecucao sob executor nao-superuser sem autoridade sobre supabase_admin,
ensure_rls com funcao INVOKER e DEFINER, instalacao nova/legada,
concorrencia do servidor, historico, capacidade e isolamento institucional.
O operador owner somente prepara os dados e inspeciona os catalogs nos casos
de ACL; nao substitui a execucao dos fluxos sob as roles.

O ambiente deve ser um cluster PostgreSQL local descartavel, banco vazio
bb_massoterapia_test*, loopback e opt-in. O operador de testes precisa ser
superuser para criar roles de teste com BYPASSRLS; os nomes anon/authenticated/
service_role nao podem existir previamente. As fixtures abortam se existirem,
nao reutilizam nem alteram roles de um cluster compartilhado. Roles sao globais
ao cluster; seus grants e roles criadas sao limpos no final. Nunca use Supabase.
Instale requirements-postgres-test.txt e siga README_agendamentos.md para DSN.
Sem opt-in, ambos os modulos PostgreSQL sao pulados, e devem ser reportados.

Os testes locais nao confirmam ownership real, API keys, schema cache, gateways,
ou RLS/grants do Supabase. Homologacao remota manual permanece obrigatoria.
Nao foram realizados commits, pushes ou deploy nesta etapa.

## Arquivos da Etapa

Criados: database/migrations/005_seguranca_permissoes.sql,
database/diagnostico_seguranca.sql, database/README_seguranca.md,
tests/test_manutencao_seguranca.py e tests/test_postgres_seguranca.py.
Modificados: app/core/security.py, app/schemas/auth.py,
app/schemas/agendamento.py, app/api/routes/graph_agendamentos.py,
database/schema.sql, database/auth_schema.sql, tests/test_postgres_agendamentos.py,
README.md, database/README_agendamentos.md, database/README_disponibilidade.md,
database/README_terceirizada.md.
