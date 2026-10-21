import re
import unicodedata

from app.agents.recepcao.intents import Intencao


SENSITIVE_HEALTH_KEYWORDS = (
    "dor forte",
    "dor no peito",
    "peito",
    "hernia",
    "hernia de disco",
    "coluna",
    "lombar",
    "lesao",
    "doenca",
    "diagnostico",
    "tratamento",
    "remedio",
    "medicamento",
    "suplemento",
    "qual massagem devo fazer",
    "que massagem devo fazer",
)

OUT_OF_SCOPE_KEYWORDS = (
    "cancelar",
    "cancelamento",
    "remarcar",
    "reagendar",
    "capital da franca",
    "capital",
)

SCHEDULING_KEYWORDS = (
    "agendar",
    "agendamento",
    "marcar",
    "horario",
    "tem horario",
    "tem agenda",
    "disponibilidade",
    "massagem",
    "massoterapia",
    "sessao",
    "atendimento",
)

WELLBEING_KEYWORDS = (
    "depois da massagem",
    "relaxar",
    "relaxamento",
    "autocuidado",
    "bem estar",
    "bem-estar",
    "hidratacao",
    "beber agua",
    "descanso",
    "pausa",
    "ergonomia",
)


def normalizar_mensagem(mensagem: str) -> str:
    texto = unicodedata.normalize("NFD", mensagem.strip().lower())
    texto = "".join(char for char in texto if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", texto)


def classificar_intencao(mensagem: str) -> Intencao:
    texto = normalizar_mensagem(mensagem)

    if not texto or len(texto) < 3:
        return Intencao.NAO_ENTENDIDO

    if _contem_termo(texto, SENSITIVE_HEALTH_KEYWORDS):
        return Intencao.SAUDE_SENSIVEL

    if _contem_termo(texto, OUT_OF_SCOPE_KEYWORDS):
        return Intencao.FORA_DE_ESCOPO

    if _contem_termo(texto, WELLBEING_KEYWORDS):
        return Intencao.ORIENTACAO_BEM_ESTAR

    if _contem_termo(texto, SCHEDULING_KEYWORDS):
        return Intencao.AGENDAMENTO

    return Intencao.NAO_ENTENDIDO


def _contem_termo(texto: str, termos: tuple[str, ...]) -> bool:
    return any(termo in texto for termo in termos)
