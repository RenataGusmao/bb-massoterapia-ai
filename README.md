# BB Massoterapia AI

API REST do MVP **BB Massoterapia AI**, criada em Python com FastAPI e preparada desde o início para hospedagem em nuvem, preferencialmente no Render.

Neste momento, o projeto possui integração com Supabase PostgreSQL, autenticação JWT própria, controle básico de acesso por perfil, fluxo de agendamento com LangGraph/Gemini e regra de intervalo mínimo de 15 dias.

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

O schema inicial cria as tabelas:

- `colaboradores`
- `massoterapeutas`
- `horarios_disponiveis`
- `agendamentos`
- `usuarios`

Os IDs são UUIDs gerados pelo PostgreSQL/Supabase. O status inicial dos agendamentos aceita:

- `AGENDADO`
- `CANCELADO`
- `CONCLUIDO`
- `FALTOU`

Esta é a primeira versão do banco. A regra de negócio dos 15 dias está implementada na camada de services.

## Pendências Técnicas

A reserva do horário e a criação do agendamento ainda não são executadas dentro de uma transação PostgreSQL única. Existe um risco residual de o horário ficar indisponível caso o processo falhe depois da reserva e antes da criação do agendamento. Essa consistência deverá ser corrigida futuramente com uma função/RPC transacional no PostgreSQL.

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
- `GET /colaboradores`
- `POST /colaboradores`
- `GET /colaboradores/{colaborador_id}`
- `GET /massoterapeutas`
- `GET /massoterapeutas/{massoterapeuta_id}`
- `GET /horarios`
- `GET /horarios/{horario_id}`

Rotas para usuário autenticado:

- `GET /auth/me`
- `POST /agendamentos`
- `GET /agendamentos/{agendamento_id}`
- `POST /graph/agendamentos`

Rotas exclusivas de administrador:

- `GET /agendamentos`
- `PATCH /agendamentos/{agendamento_id}/status`
- `POST /horarios`
- `POST /massoterapeutas`

Nesta primeira versão, `colaborador_id` ainda é recebido no payload de agendamento. A próxima etapa de autorização por ownership deve substituir esse valor pelo `colaborador_id` do usuário autenticado, inclusive no endpoint LangGraph. Até isso ser implementado, autenticação não impede um usuário de informar o ID de outro colaborador.

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
