# BB Massoterapia AI

API REST do MVP **BB Massoterapia AI**, criada em Python com FastAPI e preparada desde o início para hospedagem em nuvem, preferencialmente no Render.

Neste momento, o projeto possui a estrutura base da API e a primeira integração com Supabase PostgreSQL para apoiar o fluxo inicial de agendamento de massoterapia. LangGraph, agentes de IA, autenticação, regra dos 15 dias, notificações, feedbacks e regras complexas de disponibilidade serão adicionados somente em etapas futuras.

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

Esta é a primeira versão do banco. A regra de negócio dos 15 dias ainda não está implementada e será tratada em uma etapa posterior.

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
