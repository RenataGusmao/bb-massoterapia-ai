import re
import unicodedata

from app.agents.bem_estar.categories import CategoriaBemEstar


ALERT_KEYWORDS = (
    "dor forte no peito",
    "dor no peito",
    "falta de ar",
    "desmaio",
    "desmaiei",
    "perda subita de forca",
    "perdi a forca",
    "confusao",
    "sangramento",
    "reacao intensa",
)

PROFESSIONAL_LIMIT_KEYWORDS = (
    "diagnostico",
    "diagnosticar",
    "remedio",
    "medicamento",
    "suplemento",
    "dieta",
    "caloria",
    "macronutriente",
    "treino",
    "exercicio",
    "tratamento",
    "cura",
    "curar",
    "hernia",
    "lesao",
    "exame",
    "substituir meu tratamento",
    "qual massagem e melhor",
    "que massagem devo fazer",
)


def normalizar_mensagem(mensagem: str) -> str:
    texto = unicodedata.normalize("NFD", mensagem.strip().lower())
    texto = "".join(char for char in texto if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", texto)


def identificar_limite_de_seguranca(mensagem: str) -> CategoriaBemEstar | None:
    texto = normalizar_mensagem(mensagem)

    if _contem_termo(texto, ALERT_KEYWORDS):
        return CategoriaBemEstar.SINAL_DE_ALERTA

    if _contem_termo(texto, PROFESSIONAL_LIMIT_KEYWORDS):
        return CategoriaBemEstar.FORA_DO_LIMITE_PROFISSIONAL

    return None


def _contem_termo(texto: str, termos: tuple[str, ...]) -> bool:
    return any(termo in texto for termo in termos)
