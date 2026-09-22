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
    google_api_key: str | None
    gemini_model: str
    allowed_origins: tuple[str, ...]
    api_key: str | None

    def require_supabase(self) -> tuple[str, str]:
        if not self.supabase_url or not self.supabase_secret_key:
            raise SettingsError(
                "SUPABASE_URL e SUPABASE_SECRET_KEY devem estar configuradas para operações de banco."
            )

        return self.supabase_url, self.supabase_secret_key

    def require_google_api_key(self) -> str:
        if not self.google_api_key:
            raise SettingsError(
                "GOOGLE_API_KEY deve estar configurada para usar o interpretador de linguagem natural."
            )

        return self.google_api_key

    @property
    def auth_habilitada(self) -> bool:
        return bool(self.api_key)


def _parse_origins(valor: str | None) -> tuple[str, ...]:
    if not valor:
        return ("*",)

    origens = tuple(origem.strip() for origem in valor.split(",") if origem.strip())
    return origens or ("*",)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
        allowed_origins=_parse_origins(os.getenv("ALLOWED_ORIGINS")),
        api_key=os.getenv("API_KEY") or None,
    )
