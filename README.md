# BB Massoterapia AI

API REST do MVP **BB Massoterapia AI**, criada em Python com FastAPI e preparada desde o início para hospedagem em nuvem, preferencialmente no Render.

Neste momento, o projeto contém apenas a estrutura base da API. Banco de dados, Supabase, LangGraph, agentes de IA, autenticação e agendamentos serão adicionados somente em etapas futuras.

## Estrutura inicial

```text
bb-massoterapia-ai/
├── app/
│   ├── api/
│   ├── agents/
│   ├── graphs/
│   ├── services/
│   ├── models/
│   ├── schemas/
│   ├── database/
│   ├── core/
│   └── main.py
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── render.yaml
└── README.md
```

## Como rodar localmente

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

Execute a API localmente:

```bash
uvicorn app.main:app --reload
```

Por padrão, a API ficará disponível em:

```text
http://127.0.0.1:8000
```

## Como testar a API

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

Documentação automática da API:

```text
http://127.0.0.1:8000/docs
```

## Variáveis de ambiente

Copie o arquivo `.env.example` para `.env` quando precisar configurar variáveis locais:

```bash
copy .env.example .env
```

O projeto já considera a variável `PORT`, usada por plataformas de nuvem como o Render.

## Como preparar para GitHub

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

## Deploy no Render

O arquivo `render.yaml` já define um serviço web Python com:

- instalação via `pip install -r requirements.txt`;
- inicialização com `uvicorn app.main:app --host 0.0.0.0 --port $PORT`;
- variável `PYTHON_VERSION`.

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

6. Faça o deploy.

Após o deploy, teste:

```text
https://sua-api.onrender.com/
https://sua-api.onrender.com/health
https://sua-api.onrender.com/docs
```

