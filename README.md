# BB Massoterapia AI

API REST do MVP **BB Massoterapia AI**, criada em Python com FastAPI e preparada desde o início para hospedagem em nuvem, preferencialmente no Render.

Neste momento, o projeto possui integração com Supabase PostgreSQL, autenticação JWT própria, controle básico de acesso por perfil, fluxo de agendamento com LangGraph/Gemini e regra de intervalo mínimo de 15 dias.

## Acesso Institucional

A etapa 4 adiciona a role `terceirizada`, provisionamento administrativo em
`POST /auth/terceirizadas` e agenda minimizada em `GET /agenda/terceirizada`.
O admin atribui lotes explicitamente; nao ha acesso global nem cadastro publico.
As consultas gerais de horarios e profissionais agora exigem JWT admin/colaborador.
Consulte [contratos, migration 004 e exemplos Swagger](database/README_terceirizada.md).
Migrations pendentes devem ser aplicadas manualmente na ordem 001 -> 002 -> 003 -> 004 -> 005.
Nenhuma foi executada no Supabase real. Consulte o
[guia de seguranca e manutencao](database/README_seguranca.md) antes da aplicacao:
a 005 fecha o acesso direto aos objetos da aplicacao e instala os grants explicitos
do servidor, preservando defaults e mecanismos internos administrados pelo Supabase.

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
GOOGLE_API_KEY=
GEMINI_MODEL=gemini-flash-latest
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
API_KEY=
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
PORT=8000
```

`JWT_SECRET_KEY` é obrigatória. Gere um segredo longo e aleatório para cada ambiente e nunca o inclua no repositório.

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
4. Execute o conteúdo de `database/schema.sql`.
5. Execute o conteúdo de `database/auth_schema.sql`.
6. Execute as migrations 001 -> 002 -> 003 -> 004 -> 005, com clientes bloqueados
   durante toda a sequencia. Execute os diagnosticos e siga README_seguranca.md.

O schema inicial cria as tabelas:

- `colaboradores`
- `massoterapeutas`
- `horarios_disponiveis`
- `agendamentos`
- `usuarios`
- `disponibilidades`
- `usuarios_agenda_lotes` (migration 004)

Os IDs são UUIDs gerados pelo PostgreSQL/Supabase. O status inicial dos agendamentos aceita:

- `AGENDADO`
- `CANCELADO`
- `CONCLUIDO`
- `FALTOU`

O intervalo de 15 dias é verificado na RPC e reforçado por constraint de exclusão no PostgreSQL. O service mantém uma pré-validação para o grafo; a decisão definitiva ocorre na transação.

## Pendências Técnicas

A criação usa a RPC `criar_agendamento_transacional`: validações, reserva e inserção acontecem na mesma transação. Cancelamentos preservam o histórico e permitem reutilização da vaga. Em bancos existentes, aplique as migrations 001 -> 002 -> 003 -> 004 -> 005 antes de executar o backend atualizado.

Consulte [database/README_agendamentos.md](database/README_agendamentos.md) para diagnóstico, ordem de aplicação, transições de status e testes reais de concorrência.

## Autenticação JWT

O login é realizado em `POST /auth/login` com e-mail e senha. A API valida o hash Argon2 persistido na tabela `usuarios` e retorna um JWT Bearer. O endpoint `GET /auth/me` consulta novamente o usuário no banco, portanto bloqueios e mudanças de perfil passam a valer sem esperar o token expirar.

Fluxo:

```text
login
→ valida usuário e senha
→ gera JWT
→ cliente envia Authorization: Bearer <token>
→ FastAPI valida assinatura e expiração
→ consulta o usuário ativo no banco
→ libera ou bloqueia a rota conforme o perfil
```

Para gerar o hash do primeiro usuário, com o ambiente virtual ativo:

```bash
python -c "from app.core.security import gerar_hash_senha; print(gerar_hash_senha('troque-esta-senha'))"
```

Insira somente o hash retornado em `senha_hash`:

```sql
insert into usuarios (colaborador_id, email, senha_hash, role)
values ('UUID_DO_COLABORADOR', 'admin@example.com', 'HASH_ARGON2_GERADO', 'admin');
```

Não existe endpoint público de cadastro de usuários nesta versão.

Rotas públicas:

- `GET /`
- `GET /health`
- `GET /health/db`
- `POST /auth/login`

Rotas para usuário autenticado:

- `GET /auth/me`
- `GET /colaboradores/{colaborador_id}` (somente o próprio cadastro; admin pode consultar todos)
- `GET /agendamentos/me` (filtrado pelo vínculo do usuário)
- `POST /agendamentos`
- `GET /agendamentos/{agendamento_id}`
- `POST /graph/agendamentos`
- `GET /massoterapeutas` e detalhe (admin ou colaborador)
- `GET /horarios` e detalhe (admin ou colaborador)

A terceirizada acessa somente `GET /auth/me` e `GET /agenda/terceirizada`
com seu JWT. O login e as rotas tecnicas publicas continuam disponiveis.
Ela nao acessa consultas administrativas, agendamentos individuais ou escritas.

Rotas exclusivas de administrador:

- `GET /agendamentos`
- `GET /colaboradores`
- `POST /colaboradores`
- `POST /auth/colaboradores`
- `POST /auth/terceirizadas`
- `PATCH /agendamentos/{agendamento_id}/status`
- `POST /horarios`
- `POST /massoterapeutas`

O payload de agendamento continua recebendo `colaborador_id` para preservar o contrato existente. Para role colaborador, a API exige que esse ID corresponda ao vínculo autenticado, tanto no endpoint tradicional quanto no endpoint LangGraph, antes de executar o fluxo. Tentativas em nome de terceiros retornam 403. Consultas de agendamentos de terceiros retornam 404, sem revelar sua existência. Admin mantém acesso aos cadastros e agendamentos de todos.

### Contas Individuais De Colaboradores

JWT exige `sub`, `exp` e `role`: sub UUID textual, exp inteiro e role uma das
tres existentes. O perfil atual no banco prevalece na autorizacao.
Email nao textual recebe 422. Hash persistido invalido recebe 401 sem detalhes.
RLS e grants impedem as roles SQL anon/authenticated de contornar o FastAPI;
service_role usa a allowlist descrita no guia de seguranca.

Um admin autenticado provisiona a conta de um colaborador existente e ativo:

```http
POST /auth/colaboradores
Authorization: Bearer <TOKEN_ADMIN>
Content-Type: application/json

{"colaborador_id": "<UUID_COLABORADOR>", "senha": "<SENHA_FORTE_COM_12_OU_MAIS_CARACTERES>"}
```

A API usa o e-mail do cadastro existente, fixa a role em `colaborador` e armazena somente hash Argon2. Não aceita `role`, `email` ou `ativo` no payload. A resposta 201 contém somente id, colaborador_id, email, role e ativo. Duplicidade de vínculo/e-mail retorna 409, inclusive em conflito concorrente detectado pela constraint do banco. Não há endpoint público de criação de contas.

O colaborador usa o mesmo `POST /auth/login` com e-mail e senha. Login e cada requisição autenticada verificam usuário ativo e vínculo com colaborador existente/ativo. Admin continua podendo autenticar sem vínculo.

No Swagger, autorize primeiro o admin e execute o provisionamento. Depois faça login do colaborador, troque o token em Authorize e teste `/auth/me`, `/agendamentos/me` e o cadastro individual. Cole somente o token no campo HTTPBearer.

### Migration Do Vínculo

Em bancos existentes, execute manualmente `database/migrations/001_usuarios_colaborador_vinculo.sql` no SQL Editor do Supabase. O script exige vínculo para contas com role colaborador, mantendo admins sem vínculo permitidos. Se houver contas de colaboradores sem vínculo, a migration aborta sem corrigir ou apagar dados; revise essas contas manualmente e aplique novamente. A FK e as constraints únicas existentes permanecem.

Em bancos novos, o `auth_schema.sql` atualizado já inclui essa constraint. Nenhum script é executado automaticamente pela API.

## Disponibilidade Por Vagas

Administradores cadastram lotes de vagas sem profissional usando capacidade e chave de idempotência em `POST /horarios`. Cada vaga tem ID próprio e pode ser reservada independentemente. Consulte [database/README_disponibilidade.md](database/README_disponibilidade.md) para contratos, compatibilidade e migration 003.

A dependência antiga de `x-api-key` foi mantida temporariamente no código para compatibilidade, mas não é exigida junto com JWT nas rotas migradas.

## Variáveis De Ambiente

O projeto considera a variável `PORT`, usada por plataformas de nuvem como o Render.

Variáveis reconhecidas:

```env
SUPABASE_URL=
SUPABASE_SECRET_KEY=
GOOGLE_API_KEY=
GEMINI_MODEL=gemini-flash-latest
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
API_KEY=
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
PORT=8000
```

`API_KEY` é opcional e existe somente para compatibilidade temporária com integrações legadas. `JWT_ALGORITHM` e `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` possuem os valores padrão mostrados; `JWT_SECRET_KEY` não possui valor padrão.

Não coloque credenciais reais no Git. Em ambiente local, preencha esses valores apenas no arquivo `.env`, que já está ignorado pelo `.gitignore`.

Como este projeto é apenas backend, use a chave secreta do Supabase somente nas variáveis de ambiente do servidor. Não exponha essa chave em frontend, documentação pública, logs ou respostas da API.

## Configuração No Render

O arquivo `render.yaml` já define um serviço web Python com:

- instalação via `pip install -r requirements.txt`;
- inicialização com `uvicorn app.main:app --host 0.0.0.0 --port $PORT`;
- variável `PYTHON_VERSION`.

No serviço do Render, cadastre ao menos as variáveis:

```text
SUPABASE_URL
SUPABASE_SECRET_KEY
JWT_SECRET_KEY
```

Cadastre também `GOOGLE_API_KEY` para usar a interpretação de linguagem natural do fluxo Gemini e ajuste as demais variáveis conforme o ambiente.

Depois de salvar as variáveis, faça um novo deploy pelo Render quando quiser ativar a conexão no ambiente publicado.

## Testes Automatizados

Com as dependências instaladas:

```bash
pytest
```

Os testes `test_postgres_*` são ignorados quando não há PostgreSQL isolado configurado (dependências em `requirements-postgres-test.txt`); os demais usam mocks e não acessam Supabase nem Gemini. O comportamento do interpretador com o modelo real só pode ser confirmado com `GOOGLE_API_KEY` válida, enviando `POST /graph/agendamentos` com `colaborador_id` e `mensagem`.

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

Para testar a autenticação no Swagger:

1. Execute `POST /auth/login` com e-mail e senha válidos.
2. Copie o valor de `access_token` da resposta.
3. Clique em **Authorize** no topo do Swagger.
4. Cole apenas o token no campo do esquema HTTP Bearer; o Swagger adiciona o prefixo `Bearer`.
5. Confirme em **Authorize** e execute os endpoints protegidos.

## LangGraph — Fluxo De Agendamento

Esta implementação usa LangGraph para orquestrar o processo de agendamento. Quando a requisição traz apenas uma mensagem em linguagem natural, o interpretador usa Gemini; quando IDs estruturados são enviados, o fluxo não precisa chamar o modelo.

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

O 201 tem contrato OpenAPI tipado: sucesso, mensagem, interpretacao nullable e
agendamento completo, com profissional opcional. Erros do grafo preservam
sucesso/mensagem/erro/sugestoes; 422 tambem documenta detail da validacao do FastAPI.

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
    "horario_id": "uuid-do-horario",
})
```

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
