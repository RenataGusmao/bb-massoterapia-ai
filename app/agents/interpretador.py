import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.agents.llm import LLMConfigurationError, get_llm
from app.database.repositories.agendamentos import listar_agendamentos_ativos_do_colaborador
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


INTENCOES_VALIDAS = {"agendar", "cancelar", "remarcar", "outra"}

PROMPT_INTENCAO = """Você classifica mensagens de colaboradores de um sistema de massoterapia corporativa.

Classifique a intenção da mensagem em UMA das opções:
- "agendar": quer marcar uma nova sessão (ex.: "quero massagem quinta de manhã", "tem horário amanhã?").
- "cancelar": quer cancelar ou desmarcar uma sessão já marcada (ex.: "cancela minha massagem", "não vou poder ir sexta", "desmarcar meu horário").
- "remarcar": quer trocar uma sessão já marcada por outro dia ou horário (ex.: "quero remarcar para segunda", "trocar meu horário").
- "outra": qualquer outro assunto, ou quando a intenção não estiver clara.

Responda APENAS com um objeto JSON, sem markdown, sem crases, sem explicação fora dele:
{"intencao": "agendar"}"""

PROMPT_CANCELAMENTO = """Você é um assistente de massoterapia corporativa.

Receberá a mensagem de um colaborador que quer cancelar uma sessão e a lista dos agendamentos ativos dele.
Sua tarefa é identificar QUAL agendamento da lista ele quer cancelar.

Regras obrigatórias:
- Escolha SOMENTE um agendamento_id que exista exatamente na lista fornecida.
- Nunca invente ids, datas ou horários.
- Se houver mais de um agendamento e a mensagem não indicar qual, devolva escolhido = false.
- Se a data ou o horário citados não baterem com nenhum agendamento da lista, devolva escolhido = false.
- Se houver apenas um agendamento e a mensagem não citar data nem horário, escolha esse agendamento.
- Considere referências relativas de data usando a data de hoje informada.
- "manhã" = antes de 12:00, "tarde" = entre 12:00 e 18:00, "noite" = após 18:00.

Responda APENAS com um objeto JSON, sem markdown, sem crases, sem explicação fora dele:
{"escolhido": true, "agendamento_id": "...", "justificativa": "..."}
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


@dataclass(frozen=True)
class InterpretacaoCancelamento:
    escolhido: bool
    agendamento_id: str | None = None
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


DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


def hoje_local() -> date:
    return datetime.now(ZoneInfo("America/Recife")).date()


def _texto_da_resposta(content) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        partes = []
        for parte in content:
            if isinstance(parte, str):
                partes.append(parte)
            elif isinstance(parte, dict) and parte.get("type") == "text":
                partes.append(parte.get("text", ""))
        return "".join(partes)

    return str(content)


def interpretar_mensagem(mensagem: str, hoje: date | None = None) -> Interpretacao:
    hoje = hoje or hoje_local()
    horarios = listar_horarios_disponiveis(a_partir_de=hoje)

    if not horarios:
        return Interpretacao(escolhido=False, motivo="Não há horários disponíveis na agenda.")

    try:
        llm = get_llm()
    except LLMConfigurationError as exc:
        raise InterpretacaoError(str(exc)) from exc

    data_referencia = f"{hoje.isoformat()} ({DIAS_SEMANA[hoje.weekday()]})"

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

    dados = _extrair_json(_texto_da_resposta(resposta.content))

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


def identificar_intencao(mensagem: str) -> str:
    try:
        llm = get_llm()
    except LLMConfigurationError as exc:
        raise InterpretacaoError(str(exc)) from exc

    resposta = llm.invoke(
        [
            {"role": "system", "content": PROMPT_INTENCAO},
            {"role": "user", "content": f"Mensagem do colaborador: {mensagem}"},
        ]
    )

    dados = _extrair_json(_texto_da_resposta(resposta.content))
    intencao = str(dados.get("intencao", "")).strip().lower()

    return intencao if intencao in INTENCOES_VALIDAS else "outra"


def _formatar_agendamentos(agendamentos: list[dict]) -> str:
    return "\n".join(
        f"- agendamento_id={agendamento['id']} | data={agendamento['data_agendamento']} "
        f"| inicio={agendamento['hora_inicio']} | fim={agendamento['hora_fim']}"
        for agendamento in agendamentos
    )


def _descrever_agendamento(agendamento: dict) -> str:
    data = date.fromisoformat(str(agendamento["data_agendamento"]))
    hora = str(agendamento["hora_inicio"])[:5]
    return f"{DIAS_SEMANA[data.weekday()]}, {data.strftime('%d/%m/%Y')} às {hora}"


def interpretar_pedido_cancelamento(
    mensagem: str,
    colaborador_id: str,
    hoje: date | None = None,
) -> InterpretacaoCancelamento:
    hoje = hoje or hoje_local()
    agendamentos = listar_agendamentos_ativos_do_colaborador(colaborador_id, hoje)

    if not agendamentos:
        return InterpretacaoCancelamento(
            escolhido=False,
            motivo="Você não tem agendamentos ativos para cancelar.",
        )

    try:
        llm = get_llm()
    except LLMConfigurationError as exc:
        raise InterpretacaoError(str(exc)) from exc

    data_referencia = f"{hoje.isoformat()} ({DIAS_SEMANA[hoje.weekday()]})"

    user_prompt = (
        f"Data de hoje: {data_referencia}\n\n"
        f"Agendamentos ativos do colaborador:\n{_formatar_agendamentos(agendamentos)}\n\n"
        f"Mensagem do colaborador: {mensagem}"
    )

    resposta = llm.invoke(
        [
            {"role": "system", "content": PROMPT_CANCELAMENTO},
            {"role": "user", "content": user_prompt},
        ]
    )

    dados = _extrair_json(_texto_da_resposta(resposta.content))
    agendamento_id = str(dados.get("agendamento_id", ""))

    escolhido = next(
        (agendamento for agendamento in agendamentos if str(agendamento["id"]) == agendamento_id),
        None,
    )

    if dados.get("escolhido") is not True or escolhido is None:
        lista = "; ".join(_descrever_agendamento(agendamento) for agendamento in agendamentos)
        return InterpretacaoCancelamento(
            escolhido=False,
            motivo=(
                "Não identifiquei qual agendamento você quer cancelar. "
                f"Seus agendamentos ativos: {lista}."
            ),
        )

    return InterpretacaoCancelamento(
        escolhido=True,
        agendamento_id=str(escolhido["id"]),
        justificativa=dados.get("justificativa"),
    )