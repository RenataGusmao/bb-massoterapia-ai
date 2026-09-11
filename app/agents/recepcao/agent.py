import re

from app.agents.recepcao.classifier import classificar_intencao, normalizar_mensagem
from app.agents.recepcao.intents import Intencao


ENCAMINHAMENTOS = {
    Intencao.AGENDAMENTO: "agendamento",
    Intencao.ORIENTACAO_BEM_ESTAR: "bem_estar",
    Intencao.SAUDE_SENSIVEL: "resposta_segura",
    Intencao.FORA_DE_ESCOPO: "fora_de_escopo",
    Intencao.NAO_ENTENDIDO: "coleta_de_contexto",
}


def processar_mensagem_recepcao(mensagem: str) -> dict:
    intencao = classificar_intencao(mensagem)
    dados_extraidos = extrair_dados_basicos(mensagem)
    dados_faltantes = identificar_dados_faltantes(intencao, dados_extraidos)

    return {
        "intencao": intencao,
        "mensagem_recebida": mensagem,
        "dados_extraidos": dados_extraidos,
        "dados_faltantes": dados_faltantes,
        "acao": identificar_acao(intencao, dados_faltantes),
        "encaminhar_para": ENCAMINHAMENTOS[intencao],
    }


def extrair_dados_basicos(mensagem: str) -> dict[str, str]:
    texto = normalizar_mensagem(mensagem)
    dados: dict[str, str] = {}

    if "amanha" in texto:
        dados["referencia_data"] = "AMANHA"
    elif "hoje" in texto:
        dados["referencia_data"] = "HOJE"

    if _contem_palavra(texto, "manha"):
        dados["periodo"] = "MANHA"
    elif _contem_palavra(texto, "tarde"):
        dados["periodo"] = "TARDE"
    elif _contem_palavra(texto, "noite"):
        dados["periodo"] = "NOITE"

    return dados


def identificar_dados_faltantes(
    intencao: Intencao,
    dados_extraidos: dict[str, str],
) -> list[str]:
    if intencao != Intencao.AGENDAMENTO:
        return []

    faltantes: list[str] = []

    if "referencia_data" not in dados_extraidos:
        faltantes.append("data")

    return faltantes


def identificar_acao(intencao: Intencao, dados_faltantes: list[str]) -> str:
    if intencao != Intencao.AGENDAMENTO:
        return "RESPONDER"

    if dados_faltantes:
        return "COLETAR_DADOS"

    return "CONSULTAR_DISPONIBILIDADE"


def _contem_palavra(texto: str, palavra: str) -> bool:
    return re.search(rf"\b{palavra}\b", texto) is not None
