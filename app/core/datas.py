from datetime import date, datetime
from zoneinfo import ZoneInfo


def agora_local() -> datetime:
    return datetime.now(ZoneInfo("America/Sao_Paulo"))


def data_local() -> date:
    return agora_local().date()
