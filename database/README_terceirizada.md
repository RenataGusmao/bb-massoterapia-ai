# Acesso Institucional

## Arquitetura e Escopo

A role terceirizada reutiliza o login JWT, a consulta de usuario ativo a cada
requisicao e o hash Argon2 existentes. A autorizacao usa a role atual do banco,
nao a role declarada no token. Nao ha cadastro publico nem contas de profissionais.

Como ainda nao existe uma entidade de empresa ou tenant, o escopo e uma lista
explicita de lotes de disponibilidade atribuida pelo admin ao criar a conta.
usuarios_agenda_lotes armazena os vinculos. Um lote autoriza todas as suas vagas
e o historico de atendimentos dessas vagas, mas nao outros lotes. Lotes novos
nao sao incluidos automaticamente. Sem vinculos, a consulta retorna lista vazia.
O cliente nao pode informar usuario_id nem ampliar seu proprio escopo.

POST /auth/terceirizadas exige admin ativo, email institucional, senha de 12 a
256 caracteres contendo maiuscula, minuscula, numero e simbolo, e entre 1 e 100
UUIDs distintos de lotes existentes. Campos role, ativo e colaborador_id nao
sao aceitos. O backend calcula o hash; a RPC valida novamente o administrador,
cria usuario e vinculos em uma transacao. Qualquer falha reverte ambos.
Email duplicado, inclusive com diferenca de caixa, retorna 409; lote inexistente
ou entrada invalida retorna 422; indisponibilidade de infraestrutura retorna 503.
Nao envie senhas em logs. TLS e gerenciamento seguro de credenciais sao
obrigatorios em producao.

## Permissoes

| Recurso | Admin | Colaborador | Terceirizada |
| --- | --- | --- | --- |
| Login e /auth/me | Sim | Sim | Sim |
| Provisionar contas | Sim | Nao | Nao |
| Listas administrativas, cadastrar disponibilidade, alterar status | Sim | Nao | Nao |
| Consultar horarios e profissionais | Sim | Sim | Nao |
| Criar agendamentos REST/graph | Sim | Apenas proprios | Nao |
| Consultar agendamento individual | Sim | Apenas proprio | Nao |
| GET /agenda/terceirizada | Nao; usa consultas administrativas existentes | Nao | Apenas lotes autorizados |

As consultas gerais GET /horarios e GET /massoterapeutas, inclusive detalhes,
agora exigem JWT de admin ou colaborador. Antes eram publicas. Essa mudanca evita
contornar o escopo institucional removendo o token e precisa ser considerada
no frontend. Rotas tecnicas de health e raiz continuam publicas, sem agenda
ou dados pessoais. A API key legada nao substitui JWT nesses recursos.

## Consulta e Contratos

GET /agenda/terceirizada aceita:

- data=AAAA-MM-DD, ou data_inicio e data_fim juntos;
- sem datas, consulta o dia atual em America/Sao_Paulo;
- intervalo inclusivo de 1 a 31 dias;
- status repetido na query, ate quatro valores validos;
- pagina entre 1 e 10000, tamanho_pagina entre 1 e 100, padrao 50.

Nao combine data com periodo. Filtros invalidos retornam 422, autenticacao
invalida/expirada ou usuario inativo retorna 401, role incorreta retorna 403.
Erros internos da consulta retornam 503 sem divulgar mensagens do banco.

A resposta tem itens, total, pagina e tamanho_pagina. Cada item contem apenas
id, data, hora_inicio, hora_fim, status, horario_id e disponibilidade_id.
Nao retorna nome ou ID de colaborador, email pessoal, matricula, setor,
profissional, senha, hash ou token. O response_model aplica uma segunda
barreira de minimizacao apos a projecao explicita na RPC.

Sem filtro de status, todos os quatro estados aparecem. CANCELADO e historico,
nao uma reserva vigente; AGENDADO e a reserva vigente; CONCLUIDO e FALTOU
sao resultados finais. Cancelamento seguido de reutilizacao produz dois itens
com IDs de atendimento diferentes para a mesma vaga: nao e duplicacao.
Vagas simultaneas aparecem separadamente. A consulta usa EXISTS para os acessos,
evitando multiplicacao por joins, e ordem data/hora/vaga/atendimento deterministica.
Total e pagina usam o mesmo snapshot SQL. Paginas vazias preservam o total.
Entre requisicoes independentes, mudancas na agenda podem alterar a paginacao.

## Migration 004

Banco existente: diagnosticos anteriores -> 001 -> 002 -> 003 -> 004 -> 005.
Banco novo: schema.sql -> auth_schema.sql -> 001 -> 002 -> 003 -> 004 -> 005.
O modelo final de grants/RLS e manutencao sem trafego esta em README_seguranca.md.
Nao reaplique schema.sql para atualizar banco existente. Nenhuma migration foi
executada automaticamente no Supabase.

A 004 e transacional e reexecutavel. Amplia usuarios_role_valida para tres roles,
preserva usuarios_colaborador_vinculo_obrigatorio e adiciona a constraint
usuarios_terceirizada_sem_colaborador. Nao reescreve nem exclui usuarios,
vagas ou agendamentos historicos. Cria usuarios_agenda_lotes com PK composta,
FKs e RLS sem politicas publicas; permite acesso somente pelo backend com
service_role/BYPASSRLS. As duas RPCs sao SECURITY INVOKER, nao SECURITY DEFINER,
e sua execucao e revogada de PUBLIC, anon e authenticated.
A tabela usuarios tambem fica inacessivel a essas roles de acesso publico;
Na 005, service_role recebe SELECT/INSERT e UPDATE(ativo) em usuarios, inclusive
para os locks de provisionamento, sem alterar o login backend.
Os erros de validacao de senha nao devolvem o valor enviado ao cliente.
Uma permissao revogada entre o JWT e a RPC retorna 403, nao um erro interno.
A chave privilegiada
continua exclusivamente no backend; p_usuario_id/p_admin_id nao autenticam
chamadores externos por si mesmos. Nao exponha RPCs via uma credencial privilegiada
no frontend. A migration notifica o PostgREST para recarregar o schema.

Execute database/diagnostico_terceirizada.sql manualmente antes da 004. Se houver
role invalida, colaborador sem vinculo ou futura terceirizada vinculada a pessoa,
a validacao deve parar: investigue os registros em ambiente administrativo e
defina a correcao manual, sem apagar historico. Constraints customizadas antigas
que tambem limitem role a dois valores precisam ser reconciliadas pelo operador.
Faça backup e aplique em janela de manutencao por causa dos locks de DDL.
Se houver erro, execute ROLLBACK na sessao antes de investigar e repetir.

Para revogar uma conta, o operador autorizado pode definir usuarios.ativo=false.
Para revogar/adicionar lotes, altere usuarios_agenda_lotes somente em sessao
administrativa, validando que o usuario e institucional. Ainda nao existe um
endpoint de gerenciamento posterior de escopo: nao use credenciais admin no
frontend da terceirizada nem reprovisione o mesmo email para atualizar acessos.

## Swagger

1. Aplique 001 -> 002 -> 003 -> 004 -> 005 manualmente em manutencao conforme README_seguranca.md e obtenha IDs reais de lotes existentes.
2. Entre com admin em POST /auth/login e use Authorize com seu Bearer JWT.
3. POST /auth/terceirizadas, substituindo o lote e usando credenciais novas:

```json
{
  "email": "agenda-institucional@example.com",
  "senha": "Senha-Ficticia123!",
  "disponibilidade_ids": ["11111111-1111-4111-8111-111111111111"]
}
```

Resposta 201:

```json
{
  "id": "22222222-2222-4222-8222-222222222222",
  "colaborador_id": null,
  "email": "agenda-institucional@example.com",
  "role": "terceirizada",
  "ativo": true
}
```

4. POST /auth/login com email e senha da conta criada; substitua o token em
Authorize. GET /auth/me identifica a conta, sem hash.
5. Consulte GET /agenda/terceirizada?data=2099-01-01 ou
GET /agenda/terceirizada?data_inicio=2099-01-01&data_fim=2099-01-31&status=AGENDADO&status=CANCELADO&pagina=1&tamanho_pagina=20.

Exemplo de resposta:

```json
{
  "itens": [{
    "id": "33333333-3333-4333-8333-333333333333",
    "data": "2099-01-01",
    "hora_inicio": "09:00:00",
    "hora_fim": "09:30:00",
    "status": "AGENDADO",
    "horario_id": "44444444-4444-4444-8444-444444444444",
    "disponibilidade_id": "11111111-1111-4111-8111-111111111111"
  }],
  "total": 1,
  "pagina": 1,
  "tamanho_pagina": 20
}
```

6. Confirme 403 em consultas administrativas, POST /agendamentos,
PATCH /agendamentos/{id}/status, POST /horarios e provisionamento.
7. Com admin/colaboradores, crie dois atendimentos em vagas simultaneas de um
lote autorizado. Cancele um e reutilize a vaga. A agenda deve preservar o
cancelado e mostrar o novo atendimento, sem incluir lotes nao autorizados.
8. Desative a conta em ambiente administrativo: login e agenda devem retornar 401.
Os exemplos sao ficticios e nao devem ser usados como credenciais de producao.

## Verificacao e Pendencias

Arquivos criados nesta etapa:

- app/api/routes/agenda.py
- app/database/repositories/agenda.py
- app/schemas/agenda.py
- database/migrations/004_acesso_terceirizada.sql
- database/diagnostico_terceirizada.sql
- database/README_terceirizada.md
- tests/test_agenda_terceirizada.py

Arquivos modificados nesta etapa, preservando as alteracoes anteriores:

- app/api/router.py
- app/api/routes/auth.py
- app/api/routes/agendamentos.py
- app/api/routes/horarios.py
- app/api/routes/massoterapeutas.py
- app/core/security.py
- app/schemas/auth.py
- app/main.py
- tests/test_postgres_agendamentos.py
- tests/test_vagas_sem_profissional.py
- README.md

tests/test_agenda_terceirizada.py verifica HTTP, JWT, hash, roles, validacoes e
contratos com repositories mockados; nao comprova transacoes.
Os casos test_pg_004_* em tests/test_postgres_agendamentos.py aplicam a migration
em PostgreSQL real local descartavel e verificam constraints, rollback de conta
se a insercao do acesso falhar, email duplicado, escopo, capacidade, status,
historico e paginacao. Os testes concorrentes anteriores permanecem na suite.
Use as instrucoes de PostgreSQL isolado em README_agendamentos.md.

O ambiente Supabase real e suas grants/RLS customizadas ainda devem ser
validados manualmente apos as migrations. Nao ha tenants, escalas, profissionais
com login, gerenciamento posterior de acessos, recuperacao de senha ou
limitacao de tentativas de login nesta etapa. Nao foram alteradas as RPCs de
reserva/status, a capacidade, a regra de 15 dias ou a integracao Gemini/LangGraph.
