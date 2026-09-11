# BB Massoterapia AI

API REST do MVP **BB Massoterapia AI**, criada em Python com FastAPI e preparada desde o início para hospedagem em nuvem, preferencialmente no Render.

Neste momento, o projeto possui a estrutura base da API, integração com Supabase PostgreSQL, fluxo básico de agendamento de massoterapia e regra de intervalo mínimo de 15 dias. Agentes de IA, autenticação, notificações, feedbacks e regras mais avançadas serão adicionados somente em etapas futuras.

## Estrutura

```text
bb-massoterapia-ai/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   └── colaboradores.py
│   │   └── router.py
│   ├── agents/
│   ├── core/
│   │   └── config.py
│   ├── database/
│   │   ├── repositories/
│   │   │   ├── agendamentos.py
│   │   │   ├── colaboradores.py
│   │   │   ├── horarios.py
│   │   │   └── massoterapeutas.py
│   │   └── supabase.py
│   ├── graphs/
│   │   └── agendamento/
│   │       ├── conditions.py
│   │       ├── graph.py
│   │       ├── nodes.py
│   │       └── state.py
│   ├── models/
│   ├── schemas/
│   │   └── colaborador.py
│   ├── services/
│   └── main.py
├── database/
│   └── schema.sql
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── render.yaml
└── README.md
```

## Como Rodar Localmente

Crie e ative um ambiente virtual:

```bash
python -m venv .venv
```

No Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Copie o arquivo de exemplo para configurar variáveis locais:

```bash
copy .env.example .env
```

Preencha no `.env`:

```env
SUPABASE_URL=
SUPABASE_SECRET_KEY=
```

Execute a API localmente:

```bash
uvicorn app.main:app --reload
```

Por padrão, a API ficará disponível em:

```text
http://127.0.0.1:8000
```

## Banco De Dados No Supabase

1. Crie um projeto no Supabase.
2. Acesse o painel do projeto.
3. Abra o SQL Editor.
4. Copie o conteúdo de `database/schema.sql`.
5. Execute o script no Supabase.

O schema inicial cria as tabelas:

- `colaboradores`
- `massoterapeutas`
- `horarios_disponiveis`
- `agendamentos`

Os IDs são UUIDs gerados pelo PostgreSQL/Supabase. O status inicial dos agendamentos aceita:

- `AGENDADO`
- `CANCELADO`
- `CONCLUIDO`
- `FALTOU`

Esta é a primeira versão do banco. A regra de negócio dos 15 dias está implementada na camada de services.

## Pendências Técnicas

A reserva do horário e a criação do agendamento ainda não são executadas dentro de uma transação PostgreSQL única. Existe um risco residual de o horário ficar indisponível caso o processo falhe depois da reserva e antes da criação do agendamento. Essa consistência deverá ser corrigida futuramente com uma função/RPC transacional no PostgreSQL.

## Variáveis De Ambiente

O projeto considera a variável `PORT`, usada por plataformas de nuvem como o Render.

Para conexão com o Supabase:

```env
SUPABASE_URL=
SUPABASE_SECRET_KEY=
```

Não coloque credenciais reais no Git. Em ambiente local, preencha esses valores apenas no arquivo `.env`, que já está ignorado pelo `.gitignore`.

Como este projeto é apenas backend, use a chave secreta do Supabase somente nas variáveis de ambiente do servidor. Não exponha essa chave em frontend, documentação pública, logs ou respostas da API.

## Configuração No Render

O arquivo `render.yaml` já define um serviço web Python com:

- instalação via `pip install -r requirements.txt`;
- inicialização com `uvicorn app.main:app --host 0.0.0.0 --port $PORT`;
- variável `PYTHON_VERSION`.

No serviço do Render, cadastre as variáveis:

```text
SUPABASE_URL
SUPABASE_SECRET_KEY
```

Depois de salvar as variáveis, faça um novo deploy pelo Render quando quiser ativar a conexão no ambiente publicado.

## Como Testar A API

Endpoint raiz:

```text
GET /
```

Resposta esperada:

```json
{
  "message": "API BB Massoterapia AI funcionando"
}
```

Endpoint de saúde:

```text
GET /health
```

Resposta esperada:

```json
{
  "status": "ok"
}
```

Endpoint de saúde do banco:

```text
GET /health/db
```

Resposta esperada quando o Supabase estiver configurado e acessível:

```json
{
  "status": "ok",
  "database": "connected"
}
```

Listar colaboradores:

```text
GET /colaboradores
```

Criar colaborador:

```bash
curl -X POST http://127.0.0.1:8000/colaboradores ^
  -H "Content-Type: application/json" ^
  -d "{\"nome\":\"Colaborador Teste\",\"matricula\":\"M001\",\"email\":\"colaborador@example.com\",\"setor\":\"Operações\"}"
```

Buscar colaborador por ID:

```text
GET /colaboradores/{id}
```

Documentação automática da API:

```text
http://127.0.0.1:8000/docs
```

## LangGraph — Fluxo De Agendamento

Esta implementação usa LangGraph para orquestrar o processo de agendamento de forma determinística. Não há LLM, OpenAI, Gemini, chatbot, agentes autônomos, memória ou checkpointer nesta etapa.

Conceitos principais:

- State: dados que percorrem o fluxo.
- Node: etapa executável do fluxo.
- Edge: conexão fixa entre nodes.
- Conditional Edge: decisão sobre qual caminho seguir conforme o State.

Neste sistema:

```text
LangGraph → orquestra
Services → executam regras de negócio
Repositories → acessam dados
Supabase → persiste dados
```

O LangGraph não duplica a regra de negócio. O endpoint experimental chama o mesmo service usado pelo endpoint tradicional `POST /agendamentos`.

Fluxo textual:

```text
START
  ↓
receber_solicitacao
  ↓
validar_entidades
  ↓
  ├─ erro ─────────────→ responder_erro → END
  ↓
validar_intervalo
  ↓
  ├─ bloqueado ────────→ responder_erro → END
  ↓
executar_agendamento
  ↓
  ├─ erro ─────────────→ responder_erro → END
  ↓
responder_sucesso
  ↓
END
```

Endpoint experimental:

```text
POST /graph/agendamentos
```

Exemplo de execução direta do grafo:

```python
from app.graphs.agendamento.graph import agendamento_graph

resultado = agendamento_graph.invoke({
    "colaborador_id": "uuid-do-colaborador",
    "massoterapeuta_id": "uuid-do-massoterapeuta",
    "horario_id": "uuid-do-horario",
})
```

## Arquitetura Multiagente

O endpoint principal de chat é `POST /chat`. Ele passa a mensagem para o Orquestrador, que chama o Agente de Recepção, interpreta a intenção retornada e decide qual componente deve responder.

O Orquestrador não possui regra própria de agendamento, saúde, bem-estar ou intervalo de 15 dias. Ele também não acessa Supabase, repositories ou SQL diretamente.

A Recepção identifica intenção. O Orquestrador decide qual componente será chamado. O Agente de Bem-Estar responde orientações gerais permitidas. O LangGraph de Agendamento executa o fluxo operacional quando chamado pelos endpoints próprios.

As duas camadas funcionam de forma determinística, sem LLM, OpenAI, Gemini, memória, checkpointer ou chamada externa de IA. Nenhuma delas realiza diagnóstico, prescrição, indicação de tratamento ou recomendação clínica. O acesso ao banco continua separado nos fluxos e serviços próprios da API.

```text
Usuário
↓
POST /chat
↓
Orquestrador
↓
Agente de Recepção
├── AGENDAMENTO
│      ↓
│  Agente/Fluxo de Agendamento
│
├── ORIENTACAO_BEM_ESTAR
│      ↓
│  Agente de Bem-Estar
│
├── SAUDE_SENSIVEL
│      ↓
│  Resposta segura
│
└── demais intenções
```

Para consultas como "Tem horário amanhã de manhã?", o chat já consulta disponibilidade real:

```text
Usuário
↓
Recepção
↓
Orquestrador
↓
Service de disponibilidade
↓
Repository
↓
Supabase
↓
horários disponíveis
↓
Chat
```

O chat textual interpreta seleções simples dentro da mesma sessão, como "quero o segundo" ou "pode ser 9h". Quando encontra opções, ele retorna `horario_id`, `massoterapeuta_id` e o índice de cada opção para que o cliente mantenha uma escolha explícita.

Após a escolha, o cliente envia os IDs para:

```text
POST /chat/agendamento/confirmar
```

Esse endpoint monta o state inicial e executa o LangGraph real de agendamento:

```text
Consulta pelo chat
↓
opções disponíveis
↓
seleção explícita do usuário
↓
POST /chat/agendamento/confirmar
↓
LangGraph de Agendamento
↓
Services
↓
Repositories
↓
Supabase
```

A recepção continua disponível em `POST /chat/recepcao`, o agente de bem-estar em `POST /agents/bem-estar` e o fluxo operacional isolado em `POST /graph/agendamentos`.

O chat também possui memória curta em processo para continuidade simples da sessão:

```text
"Tem horário amanhã de manhã?"
↓
opções numeradas
↓
"quero o segundo"
↓
seleção da opção salva na sessão
↓
"Deseja confirmar?"
↓
"sim"
↓
LangGraph
↓
agendamento
```

O `POST /chat` aceita `session_id` opcional. Quando ele não é enviado, a API gera um novo identificador e o devolve na resposta. O `colaborador_id` também pode ser enviado no payload e fica associado à sessão para a confirmação explícita do agendamento.

A memória guarda apenas dados mínimos da conversa, como últimas opções de horário, seleção atual, dados extraídos e `colaborador_id`. Ela não guarda histórico completo nem conteúdo sensível de saúde. O TTL padrão é de 30 minutos de inatividade, configurável por `SESSION_TTL_MINUTES`.

Essa memória é temporária, se perde ao reiniciar a API e não é adequada para múltiplos workers ou múltiplas instâncias. Uma evolução futura pode usar Redis, banco ou checkpointer apropriado.

## Como Preparar Para GitHub

Inicialize o repositório:

```bash
git init
git add .
git commit -m "Configura estrutura inicial FastAPI"
```

Depois, crie um repositório no GitHub e conecte o remoto:

```bash
git remote add origin https://github.com/seu-usuario/bb-massoterapia-ai.git
git branch -M main
git push -u origin main
```

## Deploy No Render

Passos gerais:

1. Suba o projeto para o GitHub.
2. Acesse o Render.
3. Crie um novo serviço usando o repositório do GitHub ou use o Blueprint apontando para o `render.yaml`.
4. Confirme o comando de build:

```bash
pip install -r requirements.txt
```

5. Confirme o comando de start:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

6. Cadastre `SUPABASE_URL` e `SUPABASE_SECRET_KEY`.
7. Faça o deploy.

Após o deploy, teste:

```text
https://sua-api.onrender.com/
https://sua-api.onrender.com/health
https://sua-api.onrender.com/health/db
https://sua-api.onrender.com/docs
```
