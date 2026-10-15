from functools import lru_cache

from supabase import Client, create_client

from app.core.config import SettingsError, get_settings


class SupabaseConfigurationError(RuntimeError):
    pass


@lru_cache
def get_supabase_client() -> Client:
    try:
        supabase_url, supabase_secret_key = get_settings().require_supabase()
    except SettingsError as exc:
        raise SupabaseConfigurationError(str(exc)) from exc

    return create_client(supabase_url, supabase_secret_key)


def check_database_connection() -> bool:
    client = get_supabase_client()
    client.table("colaboradores").select("id").limit(1).execute()
    return True
