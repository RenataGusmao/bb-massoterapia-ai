import asyncio
import logging
from datetime import datetime, time, timedelta
from threading import RLock

import holidays

from app.core.config import get_settings
from app.core.datas import agora_local, data_local
from app.database.supabase import get_supabase_client

logger = logging.getLogger(__name__)
_lock = RLock()
_dia_sincronizado = None


class AgendaNaoProntaError(RuntimeError):
    def __init__(self):
        super().__init__("Agenda ainda nao sincronizada. Tente novamente em instantes.")


def reiniciar_prontidao() -> None:
    global _dia_sincronizado
    with _lock:
        _dia_sincronizado = None


def _validar_estado_banco(calendario: list[dict]) -> None:
    resultado = get_supabase_client().rpc("verificar_prontidao_agenda", {
        "p_calendario": calendario,
    }).execute().data
    if not isinstance(resultado, dict) or resultado.get("pronta") is not True:
        logger.error("Agenda incompleta: calendario ou cobertura das vagas nao confirmados no banco.")
        raise AgendaNaoProntaError()
    if resultado.get("inicio") != calendario[0]["data"] or resultado.get("fim") != calendario[-1]["data"]:
        raise AgendaNaoProntaError()


def exigir_agenda_pronta() -> None:
    global _dia_sincronizado
    if _dia_sincronizado != data_local():
        raise AgendaNaoProntaError()
    with _lock:
        if _dia_sincronizado != data_local():
            _dia_sincronizado = None
            raise AgendaNaoProntaError()
        try:
            _validar_estado_banco(calendario_nacional(data_local()))
        except Exception as exc:
            _dia_sincronizado = None
            logger.error("Agenda nao pronta: verificacao do banco falhou; nova sincronizacao necessaria.")
            raise AgendaNaoProntaError() from exc


def exigir_prontidao_http() -> None:
    from fastapi import HTTPException
    try:
        exigir_agenda_pronta()
    except AgendaNaoProntaError as exc:
        raise HTTPException(503, str(exc), headers={"Retry-After": "60", "Cache-Control": "no-store"}) from exc


def calendario_nacional(hoje):
    fim = hoje + timedelta(days=30)
    nacionais = holidays.country_holidays("BR", years=range(hoje.year, fim.year + 1), observed=False, categories=holidays.PUBLIC)
    return [{"data": (dia := hoje + timedelta(days=n)).isoformat(), "feriado": dia in nacionais}
            for n in range(31)]


def sincronizar_agenda() -> dict:
    global _dia_sincronizado
    with _lock:
        _dia_sincronizado = None
        capacidade = get_settings().agenda_capacidade
        if not 1 <= capacidade <= 500:
            raise ValueError("AGENDA_CAPACIDADE deve estar entre 1 e 500.")
        hoje = data_local()
        calendario = calendario_nacional(hoje)
        resultado = get_supabase_client().rpc("gerar_agenda_automatica", {
            "p_calendario": calendario, "p_capacidade": capacidade,
        }).execute().data
        _validar_estado_banco(calendario)
        if data_local() != hoje:
            raise AgendaNaoProntaError()
        _dia_sincronizado = hoje
        logger.info("Agenda sincronizada e verificada no banco para a janela de 31 dias.")
        return resultado


async def executar_sincronizacao() -> bool:
    try:
        await asyncio.to_thread(sincronizar_agenda)
        return True
    except Exception:
        # Never include SDK payloads, keys or personal data in scheduler logs.
        logger.error("Falha na geracao automatica da agenda; verificar migrations e conexao.")
        return False


async def manter_agenda() -> None:
    decorrido = 0
    while True:
        agora = agora_local()
        meia_noite = datetime.combine(agora.date() + timedelta(days=1), time.min, tzinfo=agora.tzinfo)
        intervalo = min(60, max(1, (meia_noite - agora).total_seconds() + 1))
        await asyncio.sleep(intervalo)
        decorrido += intervalo
        if _dia_sincronizado != data_local() or decorrido >= 3600:
            await executar_sincronizacao()
            decorrido = 0


async def iniciar_agenda() -> None:
    await executar_sincronizacao()
    await manter_agenda()
