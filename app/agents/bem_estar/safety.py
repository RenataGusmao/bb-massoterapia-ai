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

_LIMITES_PROFISSIONAIS = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in PROFESSIONAL_LIMIT_KEYWORDS)
    + r"|diagnostic\w*|prescri\w*|medicament\w*|remedio\w*|tratament\w*|"
      r"contraindic\w*|doenc\w*|sintoma\w*|diagnos\w*|prescrib\w*|lesoes|dores)\b"
)


def normalizar_mensagem(mensagem: str) -> str:
    texto = unicodedata.normalize("NFKD", mensagem.strip().lower().replace("-", " "))
    texto = "".join(char for char in texto if unicodedata.category(char) not in {"Mn", "Cf"})
    return re.sub(r"\s+", " ", texto)


def identificar_limite_de_seguranca(mensagem: str) -> CategoriaBemEstar | None:
    texto = normalizar_mensagem(mensagem)

    if _contem_termo(texto, ALERT_KEYWORDS):
        return CategoriaBemEstar.SINAL_DE_ALERTA

    if _LIMITES_PROFISSIONAIS.search(texto):
        return CategoriaBemEstar.FORA_DO_LIMITE_PROFISSIONAL

    return None


def _contem_termo(texto: str, termos: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(termo)}\b", texto) for termo in termos)


def solicitacao_fora_de_escopo(mensagem: str) -> bool:
    texto = normalizar_mensagem(mensagem)
    return bool(
        re.search(r"\b(?:capital|futebol|politica|programacao|agendar|cancelar|desmarcar|reservar)\b", texto)
        or re.search(r"\b(?:ignore|desconsidere|revele)\b.{0,60}\b(?:instrucoes|regras|sistema|prompt|segredo)\b", texto)
    )


def saida_segura(mensagem: str) -> bool:
    """Conservative screening, not a clinical or semantic safety guarantee."""
    texto = normalizar_mensagem(mensagem)
    if solicitacao_fora_de_escopo(mensagem):
        return False
    # A narrow, safe disclaimer must not be mistaken for a claim of replacement.
    texto = re.sub(
        r"\bnao substitui (?:(?:a|uma|o|um) )?"
        r"(?:avaliacao|avaliacoes|acompanhamento|orientacao|consulta|tratamentos?|diagnosticos?)"
        r"(?:\s+(?:medic[oa]s?|profissional|profissionais|individual|individuais|clinic[oa]s?))?\b",
        "", texto,
    )
    if _contem_termo(texto, ALERT_KEYWORDS):
        return False
    for limite in _LIMITES_PROFISSIONAIS.finditer(texto):
        if (re.fullmatch(r"cura|curar|tratament\w*|diagnostic\w*", limite.group())
                and _afirmacao_negada(texto, limite.start())):
            continue
        return False
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in mensagem):
        return False
    proibido = (
        r"https?://|www\.|[\w.+-]+@[\w.-]+\.|<[^>]+>|"
        r"\b(?:detox|toxina\w*|tome|aplique|pressione|aperte|massageie|manipule|analgesic\w*|"
        r"token|senha|cpf|matricula|email|supabase|jwt|colaborador_id|horario_id|"
        r"agendad[oa]|reservad[oa]|cancelad[oa]|confirmad[oa]|"
        r"endorfina\w*|cortisol|circulacao|imunidade|lactato)\b|"
        r"\bsubstitui\w*\s+(?:(?:a|o)\s+)?(?:avaliacao|profissional|medic\w*)\b|"
        r"\b\d+(?:[.,]\d+)?\s*(?:mg|ml|mcg)\b|"
        r"(?:agendamento|reserva|cancelamento)\s+(?:confirmad\w*|realizad\w*)"
    )
    if re.search(proibido, texto):
        return False
    promessas = r"\b(?:garant\w*|comprovad\w*|definitiv\w*|elimina\w*)\b|\bsem\s+riscos?\b|100\s*%|\bsempre\s+funciona\b"
    return all(_afirmacao_negada(texto, m.start()) for m in re.finditer(promessas, texto))


def _afirmacao_negada(texto: str, inicio: int) -> bool:
    # Recognize only bounded negations of the claim, never 'nao se preocupe, ...'.
    clausula = re.split(r"[.!?;,:\n]", texto[:inicio])[-1]
    auxiliares = (
        r"e|eh|sao|ser|sera|sendo|ha|tem|oferece|oferecem|promete|prometem|"
        r"signific\w*|constitui\w*|represent\w*|"
        r"deve|devem|devendo|pode|podem|serem|uma?|a|o|as|os|se|"
        r"considerad[oa]s?|encarad[oa]s?|entendid[oa]s?|interpretad[oa]s?|como|solucao|resultados?|efeitos?|"
        r"tratando|trata|de|clinic[oa]|garantid[oa]s?|cura|definitiv[oa]|ou|nem"
    )
    return bool(re.search(rf"\b(?:nao|nunca|sem)\s+(?:(?:{auxiliares})\s+){{0,12}}$", clausula))
