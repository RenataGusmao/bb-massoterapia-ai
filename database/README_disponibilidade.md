# Disponibilidade Sem Profissional

## Modelagem

disponibilidades representa um lote para data e intervalo, com capacidade fixa e chave de idempotência. horarios_disponiveis continua representando cada vaga individual, com disponibilidade_id e numero_vaga. Agendamentos continuam referenciando horario_id: uma única vaga física, não um contador de capacidade.

Profissional é opcional em vagas e agendamentos. IDs, vínculos, status e timestamps anteriores são preservados. Na migration, intervalos históricos idênticos são agrupados e sua capacidade corresponde ao número de vagas existentes.

## Aplicação

Banco existente: diagnosticos -> migrations 001 -> 002 -> 003 -> 004 -> 005. A 003 inclui as definições canônicas atuais de RPCs e triggers, sem exigir execução separada de rpc_agendamentos.sql. Consulte README_seguranca.md para manutencao sem trafego de clientes e grants/RLS.

Banco novo: schema.sql -> auth_schema.sql -> 001 -> 002 -> 003 -> 004 -> 005. Nenhuma migration foi executada no Supabase real.

Não reaplique schema.sql para atualizar um banco existente. A 003 é transacional e reexecutável; não exclui dados ou exige remoção de sobreposições históricas. Execute em janela de manutenção devido aos locks de DDL. Se falhar, reverta a transação da sessão e investigue o erro antes de repetir.

Intervalos históricos são identificados como legado. Sobreposições antigas permanecem disponíveis conforme o estado de cada vaga, mas nenhum novo intervalo pode se sobrepor a eles. Horários adjacentes são permitidos. A constraint de exclusão impede sobreposição entre lotes novos, e a RPC verifica também o legado sob lock por dia.

## Cadastro

> O fluxo principal agora e automatico (006/007). Consulte
> README_agenda_automatica.md. POST /horarios permanece para compatibilidade e
> capacidade administrativa; novas reservas respeitam o calendario efetivo.

Apenas admin utiliza POST /horarios:

```json
{
  "chave_idempotencia": "11111111-1111-4111-8111-111111111111",
  "data": "2099-01-01",
  "hora_inicio": "09:00",
  "hora_fim": "09:30",
  "capacidade": 2
}
```

A chave UUID deve ser gerada pelo cliente para cada cadastro lógico e reutilizada nos retries. capacidade aceita inteiros de 1 a 500 e tem padrão 1. disponivel e opcional, com padrao true. massoterapeuta_id nao faz parte do contrato de entrada; envia-lo, mesmo null, recebe 422. Nao existe role gestor nesta versao: o gestor opera com perfil admin.

Resposta 201: id do lote, data, hora_inicio, hora_fim, capacidade e lista vagas. Cada vaga contém seu próprio id, disponibilidade_id, numero_vaga, disponivel, timestamps e massoterapeuta_id nullable.

Mesma chave e mesmo conteúdo: 200 com os mesmos IDs, mesmo que as vagas já tenham sido reservadas. A resposta mostra a disponibilidade atual. Mesma chave com outro conteúdo: 409. Outra chave para um intervalo já cadastrado: 409. Não ocorre ampliação implícita da capacidade.

O início precisa estar no futuro, no fuso America/Sao_Paulo; intervalos já iniciados também são rejeitados, pois suas vagas não poderiam ser reservadas. Hora final deve ser posterior à inicial e as horas não aceitam offset. Data/intervalo/capacidade inválidos retornam 422; intervalo passado, repetido, sobreposto ou conflito de idempotência retornam 409.

Capacidade e configuração do lote são imutáveis no MVP. Não há edição, recorrência, escalas ou aumento posterior de vagas. A criação do lote e de todas as vagas é atômica. Um trigger impede número de vaga acima da capacidade ou incompatível com o intervalo.

## Consulta E Reserva

GET /horarios continua retornando uma lista de vagas individuais. Use data=AAAA-MM-DD ou data_inicio/data_fim, além de disponivel=true/false. O filtro legado massoterapeuta_id continua funcionando quando houver vínculo.

Com disponivel=true, apenas vagas ainda não iniciadas são retornadas, no fuso America/Sao_Paulo. Sem esse filtro, registros passados permanecem consultáveis.

Sem filtro de disponibilidade, são retornadas vagas livres e indisponíveis; disponivel=false pode indicar reserva ou bloqueio administrativo. Uma capacidade 2 aparece como duas vagas com IDs distintos, o mesmo disponibilidade_id e números 1 e 2.

POST /agendamentos:

```json
{
  "colaborador_id": "<UUID_DO_PROPRIO_COLABORADOR>",
  "horario_id": "<ID_DE_UMA_VAGA_LIVRE>"
}
```

O backend confere ownership, atividade, data, vaga e intervalo de 15 dias na transacao. O contrato de entrada aceita somente colaborador_id e horario_id; massoterapeuta_id recebe 422, mesmo null. O campo permanece no banco e nas respostas: o vinculo historico da vaga e preservado automaticamente pela RPC, sem selecao de profissional pelo cliente.

Cancelamento libera somente horario_id. Outra vaga do mesmo lote não é afetada. Estados finais não são reativados. Reserva, cancelamento, índice único parcial e exclusão dos 15 dias seguem as garantias da etapa 2.

## LangGraph

POST /graph/agendamentos aceita colaborador_id e horario_id sem profissional, dispensando LLM. Também aceita colaborador_id e mensagem em linguagem natural.

massoterapeuta_id tambem nao e aceito no corpo do grafo. Os exemplos OpenAPI dos
tres endpoints seguem estes contratos, sem esse campo. O prompt solicita apenas
a escolha da vaga; metadados historicos nao sao usados como entrada do cliente.

O prompt escolhe apenas horario_id de uma vaga existente. Sugestões podem conter profissional nulo. A data local usada no prompt e nos filtros é America/Sao_Paulo. tzdata foi acrescentado para suportar esse fuso também no Windows.

A disponibilidade e os 15 dias continuam sendo decididos pela RPC, inclusive após uma resposta do modelo. A integração com Gemini e a arquitetura do grafo permanecem.

## Compatibilidade E Segurança

POST /horarios agora retorna um lote com vagas, não um único HorarioResponse; o frontend deve usar vagas[].id para reservar. A chave de idempotência é obrigatória. Respostas de vagas/agendamentos aceitam massoterapeuta_id=null.

GET /horarios preserva o formato de lista e acrescenta disponibilidade_id/numero_vaga. Campos históricos e o cadastro administrativo de massoterapeutas permanecem.

RPCs continuam SECURITY INVOKER, com execucao e grants explicitos restritos ao servidor/service_role pela 005. Nenhuma chave/configuração secreta foi alterada. O acesso institucional da etapa 4 e descrito em README_terceirizada.md; horarios/profissionais exigem JWT admin/colaborador.

## Testes

Use os comandos de database/README_agendamentos.md para os testes com mocks e PostgreSQL local. Os testes de banco aplicam 001 -> 002 -> 003 -> 004 -> 005, verificam historico, instalacao nova e ACL/RLS sob roles reais conforme README_seguranca.md.

O teste de carga inicial usa tests/fixtures/schema_pre_003.sql para reproduzir o banco anterior. Mocks de Gemini verificam seleção sem profissional; chamadas reais ao Gemini e ao Supabase permanecem validação posterior à aplicação manual.
