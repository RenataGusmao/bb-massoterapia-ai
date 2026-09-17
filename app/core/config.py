import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv()


class SettingsError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_secret_key: str | None
    business_timezone: str
    session_ttl_minutes: int
    gemini_api_key: str | None
    gemini_model: str
    llm_confidence_threshold: float
    gemini_timeout_seconds: int

    def require_supabase(self) -> tuple[str, str]:
        if not self.supabase_url or not self.supabase_secret_key:
            raise SettingsError(
                "SUPABASE_URL e SUPABASE_SECRET_KEY devem estar configuradas para operações de banco."
            )

        return self.supabase_url, self.supabase_secret_key


@lru_cache
def get_settings() -> Settings:
    return Settings(
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY"),
        business_timezone=os.getenv("BUSINESS_TIMEZONE", "America/Recife"),
        session_ttl_minutes=int(os.getenv("SESSION_TTL_MINUTES", "30")),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        llm_confidence_threshold=float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.60")),
        gemini_timeout_seconds=int(os.getenv("GEMINI_TIMEOUT_SECONDS", "5")),
    )
