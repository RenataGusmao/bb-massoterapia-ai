from app.core.config import get_settings
from app.llm.schemas import RecepcaoLLMClassification


CLASSIFICADOR_RECEPCAO_PROMPT = """
Você é um classificador de intenção para um sistema de massoterapia corporativa.
Classifique a mensagem do usuário sem responder à pergunta.
Não forneça orientação médica, diagnóstico, prescrição ou recomendação clínica.
Produza apenas JSON estruturado conforme o schema.

Intenções válidas:
- AGENDAMENTO: marcar, consultar ou iniciar fluxo de sessão de massoterapia.
- ORIENTACAO_BEM_ESTAR: autocuidado geral, pós-massagem, relaxamento, hidratação, ergonomia básica.
- SAUDE_SENSIVEL: sintomas, dor intensa, diagnósticos, medicamentos, suplementos, tratamento ou condição clínica.
- FORA_DE_ESCOPO: cancelamento, remarcação ou assunto fora do MVP.
- NAO_ENTENDIDO: mensagem insuficiente ou ambígua.

Saúde sensível tem prioridade sobre agendamento.
Extraia referencia_data somente quando for HOJE ou AMANHA.
Extraia periodo somente quando for MANHA, TARDE ou NOITE.
""".strip()


class GeminiClassificationError(RuntimeError):
    pass


def classificar_recepcao_com_gemini(mensagem: str) -> RecepcaoLLMClassification:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise GeminiClassificationError("Gemini API key ausente.")

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise GeminiClassificationError("Dependência google-genai indisponível.") from exc

    try:
        client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=settings.gemini_timeout_seconds * 1000),
        )
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=f"{CLASSIFICADOR_RECEPCAO_PROMPT}\n\nMensagem do usuário:\n{mensagem}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RecepcaoLLMClassification,
            ),
        )
    except Exception as exc:
        raise GeminiClassificationError("Falha técnica ao classificar com Gemini.") from exc

    try:
        if getattr(response, "parsed", None) is not None:
            return RecepcaoLLMClassification.model_validate(response.parsed)

        return RecepcaoLLMClassification.model_validate_json(response.text or "")
    except Exception as exc:
        raise GeminiClassificationError("Resposta inválida do Gemini.") from exc
