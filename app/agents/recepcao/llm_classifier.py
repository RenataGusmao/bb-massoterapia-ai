from app.agents.recepcao.classifier import classificar_intencao
from app.agents.recepcao.intents import Intencao
from app.core.config import get_settings
from app.llm import GeminiClassificationError, classificar_recepcao_com_gemini
from app.llm.schemas import RecepcaoLLMClassification


def classificar_intencao_com_llm(mensagem: str) -> tuple[Intencao, dict[str, str]]:
    try:
        classificacao = classificar_recepcao_com_gemini(mensagem)
    except GeminiClassificationError:
        return classificar_intencao(mensagem), {}

    if classificacao.confianca < get_settings().llm_confidence_threshold:
        return classificar_intencao(mensagem), {}

    return Intencao(classificacao.intencao), _extrair_dados_llm(classificacao)


def _extrair_dados_llm(classificacao: RecepcaoLLMClassification) -> dict[str, str]:
    dados: dict[str, str] = {}

    if classificacao.referencia_data is not None:
        dados["referencia_data"] = classificacao.referencia_data

    if classificacao.periodo is not None:
        dados["periodo"] = classificacao.periodo

    return dados
