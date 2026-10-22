import json
import re
from dataclasses import dataclass
from datetime import date

from app.agents.llm import LLMConfigurationError, get_llm
from app.core.datas import data_local
from app.database.repositories.horarios import listar_horarios_disponiveis

MAX_HORARIOS_NO_PROMPT = 40

DIAS_SEMANA = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)

SYSTEM_PROMPT = """Você é um assistente de agendamento de massoterapia corporativa.

Receberá a mensagem de um colaborador e uma lista de horários disponíveis.
Sua tarefa é escolher UMA vaga da lista que melhor atenda ao pedido.

Regras obrigatórias:
- Pedidos de cancelar, desmarcar ou reagendar nunca devem escolher uma vaga; devolva escolhido = false.
- Escolha SOMENTE um horario_id que exista exatamente na lista fornecida.
- Nunca invente ids, datas ou horários.
- Não escolha profissionais; a vaga é identificada somente por horario_id.
- Se a mensagem for vaga demais ou nenhum horário servir exatamente, devolva escolhido = false.
- Nesse caso, tente sugerir até 3 horários da lista que sejam os mais próximos do pedido
  (mesmo dia da semana em outra data, mesmo período do dia, ou datas próximas). Cada sugestão
  deve usar um horario_id que exista de verdade na lista. Se não houver nada minimamente
  parecido, devolva sugestoes como uma lista vazia.
- Considere referências relativas de data usando a data de hoje informada.
- Use o dia da semana indicado entre parênteses em cada horário; não calcule o dia da semana por conta própria.
- "manhã" = antes de 12:00, "tarde" = entre 12:00 e 18:00, "noite" = após 18:00.

Responda APENAS com um objeto JSON, sem markdown, sem crases, sem explicação fora dele:
{"escolhido": true, "horario_id": "...", "justificativa": "..."}
ou
{"escolhido": false, "motivo": "...", "sugestoes": [{"horario_id": "...", "motivo": "..."}]}"""


class InterpretacaoError(RuntimeError):
    pass


class InterpretacaoRespostaInvalidaError(InterpretacaoError):
    pass


@dataclass(frozen=True)
class Interpretacao:
    escolhido: bool
    horario_id: str | None = None
    massoterapeuta_id: str | None = None
    justificativa: str | None = None
    motivo: str | None = None
    sugestoes: list[dict] | None = None


def _dia_semana(valor) -> str:
    try:
        return DIAS_SEMANA[date.fromisoformat(str(valor)[:10]).weekday()]
    except ValueError:
        return "desconhecido"


def _agrupar_horarios(horarios: list[dict]) -> list[tuple[dict, int]]:
    grupos: dict[tuple, list[dict]] = {}
    for horario in horarios:
        chave = (
            str(horario["data"]),
            str(horario["hora_inicio"]),
            str(horario["hora_fim"]),
            str(horario.get("massoterapeuta_id") or ""),
        )
        grupos.setdefault(chave, []).append(horario)

    return [(vagas[0], len(vagas)) for vagas in grupos.values()]


def _formatar_horarios(horarios: list[dict]) -> str:
    linhas = []
    for horario, vagas_livres in _agrupar_horarios(horarios)[:MAX_HORARIOS_NO_PROMPT]:
        linhas.append(
            f"- horario_id={horario['id']} | data={horario['data']} ({_dia_semana(horario['data'])}) "
            f"| inicio={horario['hora_inicio']} | fim={horario['hora_fim']} | vagas_livres={vagas_livres}"
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

    dados = None
    try:
        dados = json.loads(limpo)
    except json.JSONDecodeError:
        decodificador = json.JSONDecoder()
        for inicio in re.finditer(r"\{", limpo):
            try:
                candidato, _ = decodificador.raw_decode(limpo[inicio.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(candidato, dict):
                dados = candidato
                break

    if not isinstance(dados, dict):
        raise InterpretacaoRespostaInvalidaError("Resposta do modelo não é um JSON válido.")

    return dados


def _validar_sugestoes(sugestoes_brutas: list, horarios: list[dict]) -> list[dict]:
    if not sugestoes_brutas or not isinstance(sugestoes_brutas, list):
        return []

    horarios_por_id = {str(horario["id"]): horario for horario in horarios}
    sugestoes_validas = []

    for sugestao in sugestoes_brutas[:3]:
        if not isinstance(sugestao, dict):
            continue

        horario_id = str(sugestao.get("horario_id", ""))
        horario_real = horarios_por_id.get(horario_id)

        if horario_real is None:
            continue

        sugestoes_validas.append(
            {
                "horario_id": str(horario_real["id"]),
                "massoterapeuta_id": (
                    str(horario_real["massoterapeuta_id"]) if horario_real.get("massoterapeuta_id") else None
                ),
                "data": str(horario_real["data"]),
                "hora_inicio": str(horario_real["hora_inicio"]),
                "hora_fim": str(horario_real["hora_fim"]),
                "motivo": sugestao.get("motivo"),
            }
        )

    return sugestoes_validas


def interpretar_mensagem(mensagem: str, hoje: date | None = None) -> Interpretacao:
    data_referencia = hoje or data_local()
    horarios = listar_horarios_disponiveis(data_referencia)

    if not horarios:
        return Interpretacao(escolhido=False, motivo="Não há horários disponíveis na agenda.")

    try:
        llm = get_llm()
    except LLMConfigurationError as exc:
        raise InterpretacaoError(str(exc)) from exc

    user_prompt = (
        f"Data de hoje: {data_referencia.isoformat()} ({_dia_semana(data_referencia.isoformat())})\n\n"
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

    escolhido = dados.get("escolhido")
    if escolhido is not True and str(escolhido).strip().lower() != "true":
        sugestoes = _validar_sugestoes(dados.get("sugestoes") or [], horarios)
        return Interpretacao(
            escolhido=False,
            motivo=dados.get("motivo") or "Não foi possível identificar um horário no pedido.",
            sugestoes=sugestoes,
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
        massoterapeuta_id=(
            str(horario_escolhido["massoterapeuta_id"]) if horario_escolhido.get("massoterapeuta_id") else None
        ),
        justificativa=dados.get("justificativa"),
    )
