# Cancelamento no LangGraph

## Diagnostico

POST /graph/agendamentos usava apenas o grafo de criacao: o interpretador Gemini
recebia vagas livres, sem conhecer reservas do usuario, e nenhum no cancelava.
A recepcao legada marca cancelamento como fora de escopo, mas nao e utilizada
por esse endpoint. Os routers de chat legados continuam fora do api_router;
nao foram publicados como parte desta alteracao.

## Fluxo publicado

O grafo agora classifica a acao antes de interpretar vagas. Criacao segue os nos
anteriores. Cancelamento segue um no dedicado, sem selecionar vaga nem chamar
Gemini. Expressao de cancelamento/desmarcacao ou impossibilidade de comparecer
e reconhecida de forma deterministica. Negacoes, perguntas, intencoes mistas e
referencias temporais nao suportadas pedem esclarecimento, sem mutacoes.

O endpoint requer JWT. colaborador_id pode ser omitido para usar o vinculo do
usuario autenticado. Se informado por um colaborador, deve coincidir com esse
vinculo. O no recebe a identidade separadamente do corpo, e cancela somente
reservas desse mesmo vinculo. Admin sem vinculo continua criando para outros
colaboradores e cancelando pelo PATCH administrativo existente; o cancelamento
self-service do grafo nao concede escopo administrativo.

O repository filtra simultaneamente id e colaborador_id. O servico revalida a
posse e chama alterar_status_agendamento(id, CANCELADO), reutilizando a RPC
atualizar_status_agendamento. As permissoes existentes nao permitem que
service_role troque colaborador_id de um agendamento. As transicoes, locks,
idempotencia e liberacao fisica da vaga permanecem na transacao PostgreSQL.

Sem seletor, consideram-se reservas desde hoje, inclusive canceladas/finalizadas
para evitar que um retry generico seja direcionado silenciosamente a outra
reserva. Datas explicitas e agendamento_id podem localizar historico anterior.
DD/MM sem ano filtra dia/mes reais, sem inferir ano; mais de uma correspondencia
exige esclarecimento. Sao aceitos DD/MM/AAAA, AAAA-MM-DD, hoje, amanha, depois de
amanha, dia da semana, horario e periodo. Referencias como "semana que vem" ou
"dia 26" exigem data precisa. Mais de uma reserva retorna ate dez opcoes proprias
com agendamento_id, data, hora_inicio e status. O cliente reenvia o pedido com
agendamento_id; nao existe sessao de cancelamento compartilhada entre usuarios.
O total exato e conferido na consulta: se o limite de linhas da Data API truncar
a lista, o grafo exige agendamento_id em vez de assumir que so existe uma reserva.

## Swagger

Autorizar com JWT Bearer. Usar POST /graph/agendamentos.

Criacao textual (201; exige prontidao):

```json
{"mensagem": "Quero massagem amanha de manha."}
```

Criacao estruturada (substituir horario_id por uma vaga obtida em GET /horarios):

```json
{"horario_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
```

Cancelamento textual (200):

```json
{"mensagem": "Quero cancelar meu agendamento."}
```

Cancelamento com data:

```json
{"mensagem": "Cancela minha massagem do dia 26/10."}
```

Esclarecimento ou repeticao segura (usar id da reserva, nao id da vaga):

```json
{
  "agendamento_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  "mensagem": "Quero cancelar minha massagem."
}
```

Resposta de sucesso mantem os campos sucesso, mensagem, interpretacao e
agendamento, com status CANCELADO. Repetir o mesmo agendamento_id retorna 200,
sem liberar uma vaga que ja foi reutilizada por outra reserva. Uma solicitacao
generica nao e uma chave de idempotencia: persistir e reenviar o id escolhido.
Ambiguidade: 409 com erro esclarecimento_necessario e sugestoes quando disponiveis.
Reserva inexistente/de terceiro: 404 indistinguivel. Vinculo forjado: 403.
CONCLUIDO/FALTOU: 409 transicao_invalida. Falha de infraestrutura: 503 generico.

Nao combinar horario_id e agendamento_id. Cancelamento nao depende de /ready;
criacao continua protegida pelo gate e pelas regras transacionais anteriores.

## Banco e testes

Nao ha nova migration, grants ou mudanca de RPC. Cancelamento nao cria/exclui
disponibilidades, nao altera capacidade, calendario, bloqueios ou sincronizacao.
Vaga cancelada volta a ficar fisicamente livre; bloqueios e feriados continuam
prevalecendo na view vagas_agenda. A exclusao de 15 dias desconsidera CANCELADO.

test_cancelamento_graph utiliza grafo real e mocks de infraestrutura.
test_postgres_cancelamento_graph utiliza HTTP, JWT e grafo reais; adapta somente
o transporte de dados para o cluster local descartavel e executa a RPC real
como service_role, incluindo reserva, cancelamento, reuso e bloqueios.
Os testes opt-in de Gemini continuam separados: cancelamento nao depende deles.
