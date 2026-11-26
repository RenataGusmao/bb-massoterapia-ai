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
    "prescreva", "prescrever", "receita", "dose", "dosagem", "ibuprofeno",
    "antibiotico", "anti inflamatorio", "diabetes", "pressao alta", "gravidez",
    "gestante", "contraindicacao", "trombose", "febre", "dor", "sintoma",
    "nutricao", "emagrecer", "musculacao",
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
    texto = unicodedata.normalize("NFD", mensagem.strip().lower().replace("-", " "))
    texto = "".join(char for char in texto if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", texto)


def identificar_limite_de_seguranca(mensagem: str) -> CategoriaBemEstar | None:
    texto = normalizar_mensagem(mensagem)

    if _contem_termo(texto, ALERT_KEYWORDS):
        return CategoriaBemEstar.SINAL_DE_ALERTA

    if (_contem_termo(texto, PROFESSIONAL_LIMIT_KEYWORDS)
            or re.search(r"\b(?:diagnostic\w*|prescri\w*|medicament\w*|remedio\w*|"
                         r"tratament\w*|contraindic\w*|doenc\w*|sintoma\w*|"
                         r"diagnos\w*|prescrib\w*|lesoes|dores)\b", texto)):
        return CategoriaBemEstar.FORA_DO_LIMITE_PROFISSIONAL

    return None


def _contem_termo(texto: str, termos: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(termo)}\b", texto) for termo in termos)
