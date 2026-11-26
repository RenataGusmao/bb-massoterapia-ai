# Integracao do agente de bem-estar e chat

## Referencia e procedencia

Esta entrega pertence a `feature/agente-bem-estar`, criada da `origin/main`
`578f4df`. Nao inclui a branch de cancelamento, nao modifica migrations e nao
necessita de SQL novo. Novas rotas so estarao disponiveis no ambiente publicado
depois de revisao, integracao e deploy autorizados separadamente.

O ZIP fornecido em Downloads/bb-massoterapia-ai continha uma copia Git com HEAD
`fix/ajustes-apresentacao`, commit `d69519c`, de AFFelipe. Seu pai e ancestral
comum com a versao oficial e `578f4df`. Havia um commit local com nove arquivos
alterados e nenhuma alteracao de fonte sem commit. O unico arquivo nao rastreado
era outro ZIP; o codigo app/ desse arquivo interno coincide com o externo.
Nenhum historico, hook, configuracao Git ou arquivo de credenciais foi importado.
O diretorio .git foi consultado somente na copia isolada para entender a origem.

A pasta externa indicada pelo usuario possui outro checkout, mais antigo, na
branch feature/llm-agentes; nao foi confundida com a copia fix/ajustes-apresentacao
contida no ZIP. O checkout oficial anterior foi preservado na branch de docs,
sem alteracoes locais; o trabalho foi realizado em worktree separada.

## Diagnostico e selecao

| Achado | Causa / tratamento |
| --- | --- |
| Chat nao registrado na base | O router oficial nao inclui chat ou agents_bem_estar; nao e uma colisao de prefixos |
| Registrar chat antigo quebra importacao | disponibilidade.py importa buscar_horarios_disponiveis, ausente no repository atual; reproduzido ImportError |
| ZIP responde chat sem JWT | Nova rota recebida nao tem dependencia de autenticacao; nao pode ser publicada assim |
| Bem-estar ainda responde 404 no ZIP | Mesmo o router recebido registra somente chat, nao agents_bem_estar |
| Settings incompativel com modulos antigos | Recepcao acessava gemini_api_key, llm_confidence_threshold e sessoes acessavam session_ttl_minutes, ausentes no Settings oficial |
| Dependencia duplicada Gemini | Classificador usava google.genai enquanto agendamento usa ChatGoogleGenerativeAI; unificado no cliente lazy existente |
| Sessoes sem dono | IDs de sessao e colaborador vinham apenas do corpo; agora vinculados ao usuario autenticado e alvo imutavel |
| Corridas na confirmacao | Lock antigo protegia somente dicionario, nao o turno; agora serializacao cobre selecao/confirmacao e replay |
| Agenda sem profissional | Confirmacao convertia None em texto e resposta prometia profissional selecionado; agora usa apenas vaga/colaborador |
| Erro do grafo perdido | Orquestrador lia mensagem em vez de mensagem_resposta; corrigido preservando status de negocio |
| Dia da semana confundido com opcao | Busca de ordinal em qualquer frase capturava segunda/quarta/quinta; selecao agora requer comando completo |
| .env.example recebido | Tinha SUPABASE_SECET_KEY incorreta e JWT_ALGORITHM vazio; nao incorporado, exemplo oficial corrigido sem valores reais |

Classificacao dos nove arquivos do commit recebido:

- Necessarios para integracao: registro do chat, alias de chave/TTL no config e
  adaptacao da consulta de disponibilidade ao repository existente. Ideias
  aproveitadas seletivamente, com autorizacao e fuso da base.
- LLM/classificador: problema real de configuracao; mantido um unico cliente
  LangChain ja instalado, com get_settings dinamico, sem instancia global.
- Interpretador: a base ja aceita JSON cercado por texto/Markdown; nao foi
  alterado nem substituido por uma segunda estrategia de parsing.
- Desnecessarios: aliases de settings em maiusculas, knobs sem uso, SDK
  adicional google-genai e fallback com nomes fixos de modelos. Nenhuma
  alteracao em requirements.txt ou app/agents/llm.py foi necessaria.
- Regressivos: liberar chat sem JWT, confiar no colaborador do corpo e trocar
  configuracoes globais de modelo/fuso para acomodar um modulo auxiliar.
- Nao incorporados: .env real, .git, ambientes virtuais, caches, arquivos ZIP,
  temporarios e configuracoes locais. Nenhum arquivo original foi apagado.

As implementacoes do agente, categorias, respostas seguras, estado do
orquestrador e fluxo de consultar/selecionar/confirmar ja estavam presentes
no ancestral comum. Foram reaproveitados, nao reescritos como um agente novo.
A autoria do ajuste recebido e registrada no commit de integracao.

## Arquitetura e seguranca

1. JWT e get_current_user consultam usuario/vinculo ativos no banco, como nas
   rotas existentes. Admin e colaborador acessam as duas rotas novas.
2. O endpoint direto aplica guardrails de entrada e gera resposta contextual via
   cliente Gemini compartilhado; saida precisa passar por schema e filtros de
   seguranca. Limites clinicos permanecem respostas fixas, sem LLM. O modulo
   nao consulta dados pessoais nem executa operacoes de agendamento.
3. O chat usa usuario_id do JWT. colaborador_id omitido usa o vinculo autenticado;
   colaborador nao pode indicar outro. Admin pode indicar alvo explicito.
4. Guardrails de saude precedem selecao e confirmacao. Pedidos clinicos,
   prescricoes, nutricao/treino e sinais de alerta recebem encaminhamento
   fixo, sem receita, diagnostico ou recomendacao individual.
5. Recepcao deterministica distingue agendamento, bem-estar, saude, fora de
   escopo e ambiguidade. Gemini so tenta classificar mensagens nao reconhecidas.
   O schema limita intencoes e referencias a HOJE/AMANHA e MANHA/TARDE/NOITE.
6. LLM com confianca abaixo de 0,60, timeout, credencial ausente ou JSON invalido
   retorna ao classificador deterministico. O cliente e o mesmo do interpretador,
   com timeout 30s e max_retries=2. Nao existe fallback para modelo fixo.
7. Disponibilidade consulta listar_horarios sobre vagas_agenda: calendario,
   bloqueios e ocupacao efetivos. Retorna ate cinco opcoes do dia/periodo.
8. Selecao nao reserva. Somente confirmacao explicita invoca o LangGraph ja
   existente com colaborador_id/horario_id. A protecao de prontidao e obrigatoria.
9. O grafo usa services/repositories/RPC originais. Quinze dias, concorrencia,
   capacidade, historico e atomicidade continuam no PostgreSQL.

Mensagens clinicas reconhecidas nao sao enviadas ao LLM. A lista lexical nao e
um classificador clinico exaustivo: texto nao reconhecido pode chegar ao provedor.
Mesmo que a classificacao externa erre, o bem-estar nao transforma saida do
modelo em instrucao de banco. A geracao tem validacao conservadora e fallback;
nao e possivel garantir seguranca semantica exaustiva com filtros lexicais.
Nao inclua credenciais, dados pessoais ou informacoes clinicas no chat.
Nao ha agente de nutricao/atividade fisica ou cancelamento de reservas nesta entrega.

## Sessoes e concorrencia

session_id e UUID gerado pelo servidor. Usuario diferente ou ID desconhecido
recebem o mesmo 404. A sessao mantem usuario_id, colaborador_id alvo, opcoes,
selecao e ultimo resultado de confirmacao; nao guarda o historico textual.
O alvo nao pode ser trocado durante a sessao (403); inicie outra para novo alvo.

A memoria e **somente em processo**, limitada a 1000 sessoes e com TTL por
inatividade (30 minutos por padrao). Locks em 64 faixas serializam turnos da
mesma sessao, inclusive duas confirmacoes simultaneas. Sessoes expiradas sao
reiniciadas sem selecao; a resposta informa detalhes.contexto_expirado.
Ao atingir o limite, somente entradas expiradas e sem turno em execucao podem
ser removidas; sem capacidade disponivel o chat retorna 503.

Repetir confirmacao na mesma sessao devolve o resultado ja confirmado, sem
uma segunda chamada de reserva. Isso nao equivale a idempotencia duravel:
reinicio/cold start perde sessoes, e multiplos workers/replicas nao compartilham
memoria. Um session_id desconhecido deve ser descartado pelo frontend; consulte
/agendamentos/me antes de repetir uma intencao cujo resultado ficou incerto.
O banco continua impedindo reservas duplicadas entre processos/sessoes.

Use inicialmente um processo, como no startCommand atual do Render. Persistencia
compartilhada exigiria outra entrega; nao foi adicionada infraestrutura.
Respostas das novas rotas usam Cache-Control: no-store. Nao ha rate limiter
novo; protecao de volume no gateway continua sendo responsabilidade operacional.

## Contratos do frontend

As 27 operacoes HTTP e os schemas da base foram comparados com o OpenAPI
anterior: nenhum removido, renomeado ou alterado. Permanecem /auth/*,
/colaboradores, /massoterapeutas, /horarios, /agenda/atendimentos,
/agendamentos e /graph/agendamentos, incluindo /health, /health/db e /ready.
Nao e necessario alterar clientes existentes.

Para usar os recursos novos:

| Metodo e endpoint | Corpo | Retorno e status |
| --- | --- | --- |
| POST /agents/bem-estar | mensagem obrigatoria, string nao vazia, ate 1000 caracteres | 200: categoria, permitido, mensagem, encaminhamento |
| POST /chat | mensagem obrigatoria; session_id e colaborador_id opcionais | 200 para orientacao, contexto ou selecao; 201 na confirmacao/replay |

Header em ambos: Authorization: Bearer <TOKEN>. No Swagger cole somente o
token em HTTPBearer. Nao use X-Agenda-Key como substituto; essa chave continua
exclusiva da leitura agregada da agenda.

ChatResponse contem session_id, sucesso, intencao, acao, resposta,
dados_extraidos, dados_faltantes, status, opcoes, opcao_selecionada,
agendamento e detalhes. Opcoes usam indice/horario_id/data/hora_inicio/hora_fim;
os campos de profissional permanecem null por compatibilidade do formato antigo.
Guarde session_id separadamente por usuario e reaproveite-o apenas nessa conversa.

Erros: 401 sem JWT/usuario invalido; 403 colaborador alheio ou troca de alvo;
404 sessao desconhecida/alheia; 422 mensagem/UUID/campo extra invalido; 409 para
conflitos de reserva; 503 infraestrutura, limite de sessoes ou prontidao.
Erros de negocio do grafo conservam ChatResponse e sua resposta explicativa;
erros HTTP anteriores ao grafo usam detail. Uma resposta de orientacao
bloqueada pode ser 200 com permitido=false ou status=bloqueado: nao e receita.

## Configuracao e execucao

Use .env.example atualizado. Nunca copie .env do ZIP nem o ambiente virtual
do integrante. JWT_SECRET_KEY continua obrigatoria para importar a aplicacao;
SUPABASE_URL e SUPABASE_SECRET_KEY continuam necessarias para autenticacao real.

- GOOGLE_API_KEY: primaria para Gemini.
- GEMINI_API_KEY: alias de compatibilidade quando a primaria estiver ausente.
- GEMINI_MODEL: mantido o padrao oficial, configuravel conforme a conta.
- SESSION_TTL_MINUTES: inteiro positivo, padrao 30; afeta somente contexto do chat.

O fuso segue America/Sao_Paulo. BUSINESS_TIMEZONE e GEMINI_TIMEOUT_SECONDS nao
foram ativados por esta integracao. Nenhum segredo foi gerado ou modificado.
Sem Gemini, bem-estar funciona por fallback e mensagens deterministicas funcionam; a interpretacao
textual original continua dependendo de chave/modelo validos. Sem banco nao ha
autenticacao real, mesmo quando as respostas de bem-estar sao locais.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Preencher credenciais apenas no arquivo local.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Ao iniciar o backend com worker habilitado, ele pode gerar calendario/vagas;
aponte o ambiente local somente para desenvolvimento. Nenhuma migration ou
alteracao do Render e necessaria para revisar o codigo desta branch.

## Demonstracao no Swagger

Use /docs do ambiente em que esta branch estiver em execucao, nao suponha que
as rotas novas ja existem no Render de producao. Os dados abaixo sao exemplos
de formato; IDs/token reais devem vir da sua conta e dos retornos da API.

1. **GET /health**, sem JWT, sem body: 200 {"status":"ok"}; confirmar processo.
2. **GET /ready**, sem JWT: 200 {"status":"ready"} antes de reservar, ou 503
   enquanto a janela nao foi sincronizada. Nao contornar a verificacao.
3. **POST /auth/login**, sem JWT:
   {"email":"colaborador@example.com","senha":"<SENHA_DA_CONTA>"}.
   Esperado 200 com access_token/token_type. Authorize com o token.
4. **GET /auth/me**, JWT, sem body: 200 com id, colaborador_id, email, role,
   ativo; confirmar vinculo do colaborador.
5. **POST /agents/bem-estar**, JWT:
   {"mensagem":"Quais os beneficios gerais da massagem?"}.
   Esperado 200 com categoria=BEM_ESTAR_GERAL, permitido=true, mensagem
   contextual sobre a pergunta e encaminhamento=null. Se houver fallback,
   a mensagem comeca com "No momento, segue uma orientacao geral de apoio:".
6. **POST /agents/bem-estar**, JWT:
   {"mensagem":"Prescreva um medicamento para minha dor"}.
   Esperado 200 com permitido=false, categoria=FORA_DO_LIMITE_PROFISSIONAL
   e encaminhamento=PROFISSIONAL_HABILITADO, sem prescricao.
7. **POST /chat**, JWT: {"mensagem":"Quero relaxar"}.
   Esperado 200 com status=respondido, intencao=ORIENTACAO_BEM_ESTAR,
   resposta segura, opcoes=[] e um session_id gerado.
8. **POST /chat**, JWT: {"mensagem":"Quero agendar amanha de manha"}.
   Esperado 200 com status=aguardando_selecao_horario e opcoes reais;
   sem_disponibilidade e resultado valido em feriado/fim de semana/bloqueio.
   Nesse caso, escolher hoje/amanha elegivel, sem alterar o calendario para a demo.
9. **POST /chat**, JWT:
   {"session_id":"<ID_RETORNADO_NO_PASSO_8>","mensagem":"opcao 1"}.
   Esperado 200 com status=aguardando_confirmacao e opcao_selecionada.
10. **POST /chat**, JWT:
    {"session_id":"<MESMO_ID>","mensagem":"confirmo"}.
    Esperado 201 com status=agendamento_confirmado e agendamento.status=AGENDADO,
    se as regras permitirem. Intervalo de 15 dias, vaga ocupada ou inatividade:
    409 sem nova reserva; agenda nao pronta: 503.
11. Repetir passo 10: 201 com o mesmo agendamento, sem segunda reserva.
    **GET /agendamentos/me**, JWT: 200 listando o registro proprio.
12. **POST /chat**, JWT: {"mensagem":"Quero cancelar minha reserva"}.
    Esperado 200 com status=fora_de_escopo; nao cancela a reserva.
    Cancelamento publicado continua em PATCH /agendamentos/{id}/status, JWT
    admin, {"status":"CANCELADO"}, 200 com o agendamento.
13. Retirar Authorize e repetir passos 5/7: 401. Usar a sessao de outro
    usuario: 404, sem vazamento de opcoes. Corpo com colaborador_id alheio
    sob JWT colaborador: 403. Mensagem vazia ou somente espacos: 422.

Para demonstrar o endpoint de agendamento original, GET /horarios?disponivel=true
com JWT e POST /graph/agendamentos:

```json
{
  "colaborador_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  "mensagem": "Quero massagem amanha de manha"
}
```

Esperado 201 com sucesso=true, mensagem, interpretacao e agendamento se houver
vaga, Gemini configurado e elegibilidade. Os UUIDs sao ilustrativos; use seu
vinculo real. Para testar sem LLM, substitua mensagem por horario_id obtido da
consulta. Nao acrescente massoterapeuta_id ao contrato.

## Testes e limites da validacao

Antes da integracao, a base passou em 251 testes; 12 casos Gemini e tres
modulos PostgreSQL foram pulados por ausencia de opt-in/cluster.
O contrato OpenAPI e a inicializacao /health e /docs foram registrados antes
da alteracao e comparados depois.

Resultado final em 26/11/2026: **320 aprovados, zero reprovados, 15 skips e
4 warnings**. Sao 69 testes novos; as 27 operacoes e os schemas preexistentes
permaneceram identicos no OpenAPI, com apenas duas novas operacoes.
Instalacao limpa dos requirements e pip check aprovados, sem acrescentar
dependencias. O cliente Gemini foi instanciado com chave ficticia, sem chamada
externa, para conferir imports e compatibilidade.

Os skips sao 12 casos Gemini e tres modulos PostgreSQL ignorados na coleta.
Nao havia cluster PostgreSQL local configurado; nao foi usado banco remoto
para substituir esse ambiente. Os warnings preexistentes sao uma depreciacao
TestClient/AnyIO e tres marcas live nao registradas.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs
.\.venv\Scripts\python.exe -m pytest tests/test_integracao_bem_estar.py -q
```

Os novos testes usam HTTP/JWT/grafo reais onde indicado e mocks de
infraestrutura/LLM; cobrem seguranca, mensagens invalidas, roteamento,
ownership, TTL/reinicio/limite de memoria, duas confirmacoes simultaneas,
prontidao, falhas e uso da RPC existente. A concorrencia da memoria nao e
prova de transacao PostgreSQL. Os testes antigos nao foram alterados.

Testes PostgreSQL existentes continuam opt-in e exigem cluster local vazio e
descartavel; veja README_agendamentos.md. Nunca use Supabase para executa-los.
Testes Gemini reais tambem sao opt-in e podem consumir quota.
Os mocks nao certificam banco, privacidade de logs do provedor, quota, modelo
ou configuracao do ambiente remoto. Homologacao continua necessaria.

## Revisao contextual do bem-estar

Revisao sobre bd807d3, na mesma branch, sem deploy ou SQL.
Os resultados de 320 testes acima sao o registro da integracao anterior.

### Causa comprovada

Antes da revisao, processar_orientacao nao chamava Gemini. Categorias eram
escolhidas em sequencia por palavras-chave e a resposta vinha do dicionario
RESPOSTAS_PERMITIDAS. A pergunta de beneficios com "sentado" caia em ERGONOMIA;
a outra caia em POS_MASSAGEM pela palavra generica "sessao". Ambos os resultados
foram reproduzidos com zero chamadas ao modelo.

Gemini participava apenas da classificacao opcional da recepcao de mensagens
nao reconhecidas. Mensagens reconhecidas por regras nem chegavam ao provedor.
O fallback dessa classificacao ocultava falhas tecnicas sem um log especifico;
agora registra um aviso generico. Essa ausencia de geracao era arquitetural,
nao uma falha de conectividade: o provedor respondeu na validacao controlada.

### Fluxo atual

Autenticacao e entrada permanecem iguais. O bem-estar aplica limites clinicos e
exclusoes explicitas antes do modelo; depois gera categoria e texto em uma
unica chamada get_llm().invoke, com system prompt separado da mensagem.
O mesmo cliente lazy, chave, modelo, timeout e retry do projeto sao reutilizados.
generation_config limita esta chamada a 700 tokens, sem modificar o cliente
compartilhado ou o agendamento. Nao ha novos SDKs, servicos ou variaveis.

O JSON interno exige categoria existente, mensagem de 20 a 2000 caracteres e
segura como booleano estrito, sem campos extras. O texto bruto tem limite de
6000 caracteres antes do parsing. A declaracao segura=true nao e suficiente:
saida clinica indevida, promessas absolutas, dosagem, manobras, dados protegidos,
URLs, HTML e alegacoes de reserva executada sao descartadas. Negacoes limitadas
de promessas e avisos de que a massagem nao substitui avaliacao profissional
nao sao tratados como afirmacoes de cura. Isso nao libera prescricoes ou
dosagens negadas nem frases positivas precedidas de uma tranquilizacao.
O filtro e deliberadamente conservador; pode recusar textos benignos e nao
substitui revisao clinica ou avaliacao semantica completa.

Sem chave/dependencia, timeout, falha do provedor, JSON/schema invalido ou
saida insegura, responde por fallback. Categorias conhecidas preservam
orientacao segura, com prefixo "No momento, segue uma orientacao geral de apoio:".
Se nao houver escopo identificavel, solicita reformulacao sem inventar resposta.
Logs registram somente motivo tecnico fixo, nunca entrada, saida ou excecao bruta.
O logger uvicorn.error.bem_estar herda o handler/nivel do Uvicorn: no nivel INFO,
o evento "resposta contextual validada via Gemini" identifica geracao aceita;
fallback usa WARNING. Nao e necessario habilitar logs verbosos do SDK ou HTTP.

O modelo pode reconhecer um limite que a regra local nao captou: nesse caso o
texto gerado e descartado e a resposta restritiva pre-definida e utilizada.
No chat, a rota de saude sensivel continua estritamente deterministica, mesmo
quando a recepcao usa um criterio mais restritivo que o agente direto.

### Contrato e taxonomia

BemEstarResponse segue com categoria, permitido, mensagem e encaminhamento.
Nenhuma categoria foi adicionada, removida ou renomeada. BEM_ESTAR_GERAL passa
a representar explicitamente beneficios e expectativas sobre massoterapia;
O modelo utiliza a taxonomia para representar a intencao predominante;
sentado/expediente/sessao podem ser contexto, nao necessariamente a intencao.
POS_MASSAGEM trata de cuidados depois da sessao. A categoria de uma resposta
valida nao e reescrita por palavras da pergunta. As regras locais preexistentes
ficam restritas a seguranca e fallback, que pode ser mais generico.
Nao ha respostas estaticas especificas para as perguntas de demonstracao.

Adicionar BENEFICIOS_MASSOTERAPIA poderia afetar frontends com enum exaustivo.
Essa alternativa nao foi adotada: a categoria geral existente e suficiente
para a melhoria, sem necessidade de alteracao incompatível ou migration.

### Validacao e limites

Suite: 388 aprovados, zero falhas, 15 skips e 4 warnings. Sao 68 casos novos
em tests/test_bem_estar_contextual.py. O teste anterior de respostas sem LLM
agora verifica explicitamente fallback por cliente simulado indisponivel;
os testes novos conferem que entradas distintas produzem os textos distintos
do modelo simulado e chegam integralmente ao cliente compartilhado.
Autenticacao, seguranca, sessoes, reserva e prontidao anteriores continuam testados.

OpenAPI anterior e atual: 29 operacoes e schemas identicos. Nao foram alterados
migrations, services/repositories de reservas, grade, capacidade ou regra dos
15 dias. Os skips continuam sendo 12 casos Gemini opt-in e tres modulos
PostgreSQL sem infraestrutura configurada. Mocks nao comprovam qualidade do
Gemini real, disponibilidade do modelo ou ausencia de alucinacoes.

### Validacao controlada com Gemini real

Modelo ja configurado: gemini-flash-lite-latest, sem alterar .env ou credenciais.
Chamadas realizadas diretamente pelo agente com textos sinteticos sem dados
pessoais; o acesso Supabase foi bloqueado no processo de diagnostico.
O teste clinico recebeu resposta fixa com zero chamadas ao cliente.

| Pedido | Resultado observado em execucoes com saida validada |
| --- | --- |
| Beneficios para trabalho sentado | BEM_ESTAR_GERAL; resposta relacionou massoterapia, relaxamento, conforto e habitos do expediente |
| Beneficios e relaxamento apos trabalho | BEM_ESTAR_GERAL; resposta distinta abordou pausa, tensao cotidiana, experiencia individual e expectativas |
| Conforto laboral com cuidados antes/depois | Resposta contextual multitematica, sem selecao ou reserva de horarios |
| Medicamento/dosagem para dores | FORA_DO_LIMITE_PROFISSIONAL, permitido=false, encaminhamento profissional e zero chamadas Gemini |

A analise incluiu o conteudo, nao somente sucesso de chamada ou HTTP.
As primeiras execucoes revelaram falsos positivos na validacao de ressalvas
como "nao ... solucao definitiva" e "nao ... tratamento": a regra foi corrigida
com testes positivos e negativos, sem liberar promessas afirmativas ou medicamentos.
Tambem ocorreram saidas invalidas/recusadas e acionamentos de fallback durante
a validacao. A tabela registra comportamentos observados, nao taxa de acerto,
benchmark ou promessa de que todas as chamadas futuras serao aceitas.

A rodada posterior com as duas perguntas originais produziu respostas reais
validadas e distintas. Mesmo com provedor acessivel, geracoes futuras podem ser
recusadas; o prefixo de apoio e os eventos de log distinguem o modo degradado.
Essas chamadas controladas nao substituem a suite opt-in completa de Gemini.

Para criterios de comunicacao prudente e limites de informacao geral:
[NCCIH: Massage Therapy](https://www.nccih.nih.gov/health/massage-therapy-what-you-need-to-know).
Essa referencia nao valida automaticamente respostas do modelo nem oferece
base para prometer efeitos clinicos individualizados.

### Repetir os casos no Swagger

Com JWT de colaborador, POST /agents/bem-estar:

```json
{
  "mensagem": "Quais sao os beneficios da massoterapia para quem trabalha sentado durante muitas horas?"
}
```

```json
{
  "mensagem": "Quais sao os beneficios da massoterapia e como uma sessao pode ajudar no relaxamento muscular apos um dia de trabalho?"
}
```

Esperado 200, categoria BEM_ESTAR_GERAL e permitido=true em ambos, com textos
voltados aos respectivos contextos. A redacao e variavel; nao espere uma frase
fixa ou use os textos dos mocks como evidencia de resposta real do Gemini.
Se aparecer o prefixo de apoio, verificar nos logs llm_nao_configurado,
timeout, falha_provedor, saida_invalida ou saida_insegura.
Repetir os textos no POST /chat deve chamar o mesmo agente e conservar o
envelope do chat, com resposta no lugar de mensagem.

```json
{
  "mensagem": "Estou com fortes dores na coluna. Qual medicamento devo tomar e em qual dosagem?"
}
```

Esperado 200, permitido=false, FORA_DO_LIMITE_PROFISSIONAL e encaminhamento
PROFISSIONAL_HABILITADO, sem consulta ao Gemini e sem prescricao.
A validacao de bem-estar nao depende de sincronizar a agenda; pode manter
AGENDA_GERACAO_AUTOMATICA=false. O HTTP foi verificado por TestClient, com o
worker isolado. Nao foi iniciado servidor Uvicorn nem sincronizado o Supabase.
