# Agenda automatica e leitura protegida

## Escopo atual

Somente admin e colaborador autenticam por JWT. Nao existe perfil/login de
massoterapeuta. POST /auth/terceirizadas e GET /agenda/terceirizada foram retirados
(retornam 404). JWTs antigos desse perfil sao rejeitados mesmo antes da migration.
006 inativa contas antigas da terceirizada sem promover, apagar ou trocar emails,
senhas e vinculos. A role legada permanece apenas em contas inativas para auditoria.
Um trigger impede novas contas desse perfil e sua reativacao. A tabela de lotes
legada e preservada sem grants ao backend; as duas RPCs exclusivas sao removidas.

## Calendario

America/Sao_Paulo, hoje ate hoje+30 (31 datas inclusivas). Segunda a sexta,
excluindo feriados nacionais do Brasil, calculados com a biblioteca holidays,
categoria PUBLIC, sem subdivisao, sem pontos facultativos ou compensacoes.
Referencia: https://holidays.readthedocs.io/en/latest/auto_gen_docs/brazil/

Inicios: 09:40, 10:10, 10:40, 11:10, 13:00, 13:30, 14:00, 14:30, 15:00, 15:30.
Cada intervalo dura 30 minutos. Hoje so sao criados intervalos ainda nao iniciados.
O intervalo 11:40-13:00 nao tem sessoes. A capacidade inicial e 1, configuravel
entre 1 e 500 por AGENDA_CAPACIDADE para lotes futuros. Lotes existentes nunca
tem capacidade, chave, IDs, disponibilidade fisica ou historico reescritos.

A inicializacao do FastAPI inicia a sincronizacao em segundo plano, sem impedir
o diagnostico do processo. Um worker renova a cada hora e na virada do dia.
Locks do PostgreSQL serializam geradores e
coordenam alteracoes de calendario/bloqueios com novas reservas. A criacao
reutiliza criar_disponibilidade_transacional, nao outra implementacao de vagas.
Intervalos existentes/sobrepostos, inclusive legados, sao preservados e nao duplicados.
Por isso um dia legado pode ter menos de dez novos lotes. Nunca apagar o legado
para forcar dez intervalos. Rodar novamente nao libera vagas ocupadas/bloqueadas.

A 007 atualiza criar_disponibilidade_transacional, preservando assinatura,
retorno, idempotencia e regras da 003, para entrar no lock global compartilhado
(73451,1) ANTES dos locks de chave e dia. O gerador entra no mesmo lock em modo
exclusivo antes dos locks diarios (datas crescentes). Seus locks posteriores
nao disputam com criacoes manuais enquanto ele possui o global exclusivo.
O trigger de calendario continua como defesa adicional, nao como primeira
aquisicao do lock da RPC. Assim a criacao manual nao pode segurar o dia enquanto
aguarda o global retido pelo gerador.

Bloqueio/desbloqueio usam o global exclusivo antes de escrever a excecao e nao
adquirem locks diarios. Reservas preservam a ordem colaborador -> vaga ->
agendamento e usam o global compartilhado no trigger; o gerador nao bloqueia
linhas de vagas/agendamentos existentes, e as excecoes nao as atualizam.
Cancelamentos nao adquirem o global nem apagam excecoes. Nao ha nova ordem
invertida entre essas RPCs. Essas garantias consideram chamadas independentes
das RPCs; clientes SQL nao devem combinar operacoes ou preadquirir locks em
ordem arbitraria dentro de uma mesma transacao.

AGENDA_GERACAO_AUTOMATICA=true por padrao; false e apenas opt-out operacional.
Falhas sao registradas sem payloads sensiveis e tentadas novamente pelo worker.
Enquanto nao houver prontidao, tenta novamente a cada ate 60 segundos, sem
reiniciar o processo. O opt-out false exige sincronizacao manual autenticada:
nao dispensa a verificacao antes de novas reservas.
Se o processo estiver desligado/suspenso, o worker nao executa. Ao reiniciar ele
recompoe a janela. Uma garantia de execucao com o Render suspenso exige processo
sempre ativo ou scheduler externo futuro; nenhum servico remoto foi configurado.
Nao depender de requisicoes diarias de um administrador.

## Prontidao operacional

GET /health e apenas liveness: retorna 200 mesmo sem banco/agenda pronta.
GET /ready retorna 503 (Retry-After: 60, sem cache) ate que ESTE processo tenha
concluido uma sincronizacao seguida da verificacao real no banco; retorna
200 {"status":"ready"} depois disso. A cada consulta a /ready e antes de novas
reservas o estado e verificado novamente, sem criar registros. Falhas de leitura
invalidam a prontidao, exigindo nova sincronizacao. A virada da data tambem
invalida a janela anterior. Nenhum flag local sobrevive a uma reinicializacao.

A migration 008 acrescenta verificar_prontidao_agenda(jsonb), somente leitura,
SECURITY INVOKER e EXECUTE apenas para service_role. Confere as 31 datas e os
feriados esperados, cobertura dos intervalos futuros elegiveis, quantidade real
de vagas igual a capacidade de cada lote e coerencia das datas/horas das vagas.
Usa vagas_agenda e respeita a preservacao de lotes sobrepostos/legados da 007.
Nao exige vagas livres: ocupacao, finais de semana, feriados e bloqueios ativos
nao sao falhas de prontidao. Um lote existente danificado nao e reparado/apagado
automaticamente: o gerador o preserva e /ready permanece 503 ate correcao manual
investigada. A verificacao nao substitui locks e regras transacionais da reserva.

POST /agendamentos, POST /graph/agendamentos, POST /horarios e o servico central
de criacao recusam novas operacoes com 503 enquanto nao prontos. A autorizacao
permanece anterior ao gate HTTP. Login, consultas historicas, cancelamentos,
bloqueios e POST /horarios/sincronizar continuam acessiveis com suas permissoes.
As consultas de disponibilidade continuam derivando a disponibilidade efetiva
do banco; uma lista vazia NAO substitui o sinal /ready.

render.yaml fixa healthCheckPath: /health. Nao usar /ready como health check do
Render: uma queda do banco nao deve induzir reinicios consecutivos. A liberacao
de reservas e garantida pelos gates da API, nao pelo roteamento do Render.
O Free continua podendo suspender; ao despertar o processo recompoe e valida
a janela antes de aceitar reservas. Nenhum cron externo ou servico foi criado.
Referencias: https://render.com/docs/health-checks e https://render.com/docs/free

## Disponibilidade efetiva e reservas

GET /horarios e seu detalhe leem a view privada vagas_agenda. Ela combina
a disponibilidade fisica, calendario conhecido, janela, intervalos fixos e
bloqueios ativos. Sem calendario sincronizado, a disponibilidade falha fechada.
POST /horarios permanece para compatibilidade administrativa/capacidade, mas
nao substitui a geracao e nao torna intervalos fora do calendario reservaveis.

Triggers validam novos lotes e reservas dentro da transacao PostgreSQL. Uma
disputa com bloqueio pode retornar 409; nenhuma reserva parcial deve permanecer.
As RPCs anteriores, regra dos 15 dias, capacidade, locks e exclusoes continuam.
Cancelamento libera a vaga fisica, nao altera bloqueios nem feriados.
A view continua mostrando-a indisponivel enquanto houver impedimento.
Agendamentos anteriores nao sao cancelados ou reescritos: o administrador deve
analisar e cancelar explicitamente os que nao poderao ocorrer.

## Endpoints de administrador (JWT admin)

- POST /horarios/sincronizar: recuperacao/validacao manual da automacao, sem body.
- GET /horarios/bloqueios?data_inicio=AAAA-MM-DD&data_fim=AAAA-MM-DD: ate 31 dias.
- POST /horarios/bloqueios: registra excecao idempotente; resposta 201.
- DELETE /horarios/bloqueios/{id}: inativa a excecao, sem apagar; resposta 204.
  Uma outra excecao ativa sobreposta continua impedindo reservas.

Exemplo de dia inteiro:
```json
{
  "chave_idempotencia": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  "data": "2026-12-01",
  "motivo": "Sem atendimento"
}
```
Para um intervalo, acrescente hora_inicio e hora_fim, por exemplo 09:40 e 10:10.
Os intervalos sao semiabertos: encostar em 10:10 nao bloqueia a sessao seguinte.
A mesma chave/conteudo retorna a mesma excecao, inclusive se ja inativada;
a mesma chave com outro conteudo recebe 409. Para novo bloqueio, use nova chave.
Nao incluir dados pessoais no motivo.

## Leitura para profissionais, sem login

GET /agenda/atendimentos?data_inicio=AAAA-MM-DD&data_fim=AAAA-MM-DD
exige header X-Agenda-Key. O periodo fica dentro da janela atual de 31 dias.
O endpoint devolve somente data, hora_inicio, hora_fim, capacidade, agendados e
disponiveis, agrupados por intervalo (maximo 310 itens).
Nao devolve IDs de agendamento/vaga/colaborador, nomes, email, matricula, motivo,
hashes, profissionais ou tokens. Cache-Control: no-store.
A chave de leitura nao autoriza nenhum endpoint de escrita nem substitui JWT.

Configurar manualmente AGENDA_LEITURA_TOKEN_SHA256 com o SHA-256 hexadecimal de
uma chave aleatoria forte (minimo recomendado 32 bytes), exclusivamente para
este acesso. Somente o hash fica na configuracao; distribuir a chave original
por canal privado aos leitores. Sem configuracao: 503; sem chave/incorreta: 401.
Nao colocar a chave em query strings, URLs, logs, arquivos Git ou JavaScript
publicado publicamente. Usar HTTPS e rate limiting no gateway de homologacao/
producao; chaves compartilhadas nao identificam leitores e vazamentos exigem
rotacao manual do hash. Nenhuma chave foi gerada ou alterada pela implementacao.

## Migrations e implantacao futura

Nao modificar/reaplicar 001-005 em ambiente atualizado.
Banco existente: backup recuperavel, isolamento de API/Data API/outros escritores,
aplicar 006_remover_terceirizada.sql, 007_agenda_automatica.sql e depois
008_prontidao_agenda.sql manualmente.
Banco novo: schema.sql, auth_schema.sql e 001-008 em ordem. PostgreSQL >=15 e
necessario para a view security_invoker. Nao ha nova extensao SQL obrigatoria.
Atualizar dependencias Python incluindo holidays antes de iniciar o backend.

As novas tabelas, view e funcoes possuem ACL explicita privada. As tabelas
recebem RLS com policy restritiva; somente service_role recebe grants necessarios.
Todas as novas funcoes sao SECURITY INVOKER. Nenhum default privilege, ownership,
membership, role SQL ou mecanismo interno Supabase e alterado.
006/007/008 sao reexecutaveis e cada arquivo possui transacao propria.
Se 007 falhar, 006 permanece aplicada; manter trafego isolado e investigar.
Nao reexecutar 005 depois de 006: a allowlist antiga depende das RPCs retiradas.
Reverter apenas codigo antigo nao restaura essas RPCs nem reativa as contas.

Antes da 007, executar manualmente diagnostico_pre_agenda_automatica.sql no
SQL Editor. E um unico SELECT de catalogos, sem RPCs ou dados pessoais, com
resultado/possivel_bloqueio por verificacao. Rodado antes da 006, indicara essa
pendencia esperada. Confere versao >=15, estrutura das 001-005, autoridade de
CREATE/ALTER/TRIGGER/REPLACE, RPCs anteriores, btree_gist herdada da 002, UUID
nativo, timezone, grants/RLS e metadados do ensure_rls. Nao altera esse trigger
nem defaults Supabase. Novos nomes ja existentes exigem conferir definicoes;
IF NOT EXISTS nao torna uma tabela de outra aplicacao compativel.

A 007 cria calendario, bloqueios, view e helpers antes de usa-los; depende das
tabelas/RPCs e invariantes das 001-005. O trigger de usuarios da 006 e dependencia
da versao completa, embora a geracao nao invoque esse trigger. Nao precisa
pg_cron nem nova extensao; requer propriedade/autoridade herdada sobre
disponibilidades e agendamentos para instalar triggers, CREATE no public e
autoridade sobre criar_disponibilidade_transacional para CREATE OR REPLACE,
alem dos objetos homonimos ao reaplicar. A verificacao 6 do diagnostico inclui
essa autoridade; conferir seu resultado atualizado antes de aplicar a 007.
service_role deve manter
BYPASSRLS, USAGE no public e os grants explicitos da 005. ensure_rls pode atuar
no DDL, mas nao e removido ou desabilitado. A compatibilidade com o banco real
depende dos resultados do preflight e de homologacao, nao do cluster local.

Publicacao posterior: backup com restauracao confirmada; isolar FastAPI, Data
API e demais escritores; executar o diagnostico; aplicar 006 -> 007 -> 008;
conferir termino de cada transacao e schema cache; publicar codigo/dependencias
com a configuracao de leitura ja preparada. Manter isolamento ate /health=200
e /ready=200, entao testar login, bloqueios, reserva/cancelamento, concorrencia
e LangGraph antes de reabrir. A primeira requisicao apos despertar pode receber
503 e deve tentar novamente, sem contornar prontidao.
Se 008 falhar, 006/007 permanecem aplicadas; esta API falha fechada sem a RPC.
Nao reaplicar migrations anteriores nem retornar ao codigo antigo como
rollback de banco. Corrigir avancando ou restaurar backup sob isolamento.

Validar manualmente login das duas roles, rejeicao do perfil antigo, header de
leitura, minimizacao, feriados/fins de semana, bloqueios antes/depois de cancelar,
dois geradores e duas reservas concorrentes, intervalo de 15 dias e LangGraph.
Nenhuma migration nova foi aplicada ao Supabase por esta implementacao,
nem houve deploy/commit/push.

## Testes

Os testes antigos de migrations 001-005 continuam como regressao do upgrade
legado, inclusive o fluxo institucional apenas naquela fotografia historica.
test_postgres_agenda_automatica aplica 006/007/008 sobre a fixture legada em cluster
local descartavel, com roles reais, e valida o estado atual. Nunca usar producao.
Testes HTTP isolam o worker via tests/conftest.py para impedir escrita remota.
Chamadas ao Gemini nao sao necessarias para os testes de calendario.

Os testes de concorrencia da agenda executam geracao/manual, geracao/reserva,
bloqueio/reserva, dois geradores e manual/bloqueio em ambas as ordens com espera
confirmada por pg_blocking_pids e tambem com partida simultanea. Cada combinacao
e repetida quatro vezes. Tres regressoes pausam a RPC manual no lock da chave e
conferem via pg_locks que o global compartilhado ja foi adquirido antes desse
ponto, enquanto o gerador aguarda sem segurar um lock diario. Os testes rejeitam
conflitos genericos que poderiam mascarar 40P01 e verificam IDs, capacidade,
reservas preexistentes e idempotencia.
