from functools import lru_cache

from app.core.config import SettingsError, get_settings


class LLMConfigurationError(RuntimeError):
    pass


@lru_cache
def get_llm():
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise LLMConfigurationError(
            "Dependência langchain-google-genai não instalada. "
            "Rode: pip install -r requirements.txt"
        ) from exc

    settings = get_settings()

    try:
        api_key = settings.require_google_api_key()
    except SettingsError as exc:
        raise LLMConfigurationError(str(exc)) from exc

    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=api_key,
        temperature=0,
        max_retries=2,
    )
