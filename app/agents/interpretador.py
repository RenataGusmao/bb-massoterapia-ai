import json
import re
from dataclasses import dataclass
from datetime import date

from app.agents.llm import LLMConfigurationError, get_llm
from app.database.repositories.horarios import listar_horarios_disponiveis

MAX_HORARIOS_NO_PROMPT = 40

SYSTEM_PROMPT = """Você é um assistente de agendamento de massoterapia corporativa.

Receberá a mensagem de um colaborador e uma lista de horários disponíveis.
Sua tarefa é escolher UM horário da lista que melhor atenda ao pedido.

Regras obrigatórias:
- Escolha SOMENTE um horario_id que exista exatamente na lista fornecida.
- Nunca invente ids, datas ou horários.
- Se a mensagem for vaga demais ou nenhum horário servir, devolva escolhido = false.
- Considere referências relativas de data usando a data de hoje informada.
- "manhã" = antes de 12:00, "tarde" = entre 12:00 e 18:00, "noite" = após 18:00.

Responda APENAS com um objeto JSON, sem markdown, sem crases, sem explicação fora dele:
{"escolhido": true, "horario_id": "...", "massoterapeuta_id": "...", "justificativa": "..."}
ou
{"escolhido": false, "motivo": "..."}"""


class InterpretacaoError(RuntimeError):
    pass


@dataclass(frozen=True)
class Interpretacao:
    escolhido: bool
    horario_id: str | None = None
    massoterapeuta_id: str | None = None
    justificativa: str | None = None
    motivo: str | None = None


def _formatar_horarios(horarios: list[dict]) -> str:
    linhas = []
    for horario in horarios[:MAX_HORARIOS_NO_PROMPT]:
        linhas.append(
            f"- horario_id={horario['id']} | massoterapeuta_id={horario['massoterapeuta_id']} "
            f"| data={horario['data']} | inicio={horario['hora_inicio']} | fim={horario['hora_fim']}"
        )

    return "\n".join(linhas)


def _obter_texto_resposta(conteudo) -> str:
    if isinstance(conteudo, str):
        return conteudo

    if isinstance(conteudo, list):
        partes = []
        for bloco in conteudo:
            if isinstance(bloco, str):
                partes.append(bloco)
            elif isinstance(bloco, dict):
                texto = bloco.get("text")
                if texto:
                    partes.append(str(texto))
        return "\n".join(partes)

    return str(conteudo)


def _extrair_json(texto: str) -> dict:
    limpo = texto.strip()
    limpo = re.sub(r"^```(?:json)?", "", limpo).strip()
    limpo = re.sub(r"```$", "", limpo).strip()

    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", limpo, re.DOTALL)
        if match is None:
            raise InterpretacaoError("Resposta do modelo não é um JSON válido.")

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise InterpretacaoError("Resposta do modelo não é um JSON válido.") from exc


def interpretar_mensagem(mensagem: str, hoje: date | None = None) -> Interpretacao:
    horarios = listar_horarios_disponiveis()

    if not horarios:
        return Interpretacao(escolhido=False, motivo="Não há horários disponíveis na agenda.")

    try:
        llm = get_llm()
    except LLMConfigurationError as exc:
        raise InterpretacaoError(str(exc)) from exc

    data_referencia = (hoje or date.today()).isoformat()

    user_prompt = (
        f"Data de hoje: {data_referencia}\n\n"
        f"Horários disponíveis:\n{_formatar_horarios(horarios)}\n\n"
        f"Mensagem do colaborador: {mensagem}"
    )

    resposta = llm.invoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )

    texto_resposta = _obter_texto_resposta(resposta.content)
    dados = _extrair_json(texto_resposta)

    if dados.get("escolhido") is not True:
        return Interpretacao(
            escolhido=False,
            motivo=dados.get("motivo") or "Não foi possível identificar um horário no pedido.",
        )

    horario_id = str(dados.get("horario_id", ""))

    horario_escolhido = next(
        (horario for horario in horarios if str(horario["id"]) == horario_id),
        None,
    )

    if horario_escolhido is None:
        return Interpretacao(
            escolhido=False,
            motivo="O horário sugerido não existe mais na agenda. Tente novamente.",
        )

    return Interpretacao(
        escolhido=True,
        horario_id=str(horario_escolhido["id"]),
        massoterapeuta_id=str(horario_escolhido["massoterapeuta_id"]),
        justificativa=dados.get("justificativa"),
    )