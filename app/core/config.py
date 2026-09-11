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
    )
