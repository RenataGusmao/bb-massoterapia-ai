from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.database.repositories.horarios import buscar_horarios_disponiveis
from app.database.repositories.massoterapeutas import buscar_massoterapeuta_por_id


PERIODOS = {
    "MANHA": (time(6, 0), time(11, 59)),
    "TARDE": (time(12, 0), time(17, 59)),
    "NOITE": (time(18, 0), time(22, 0)),
}

LIMITE_OPCOES_CHAT = 5


def consultar_disponibilidade_chat(dados_extraidos: dict[str, str]) -> dict:
    data_consulta = resolver_data_referencia(dados_extraidos.get("referencia_data"))
    faixa_periodo = resolver_faixa_periodo(dados_extraidos.get("periodo"))

    horarios = buscar_horarios_disponiveis(
        data_consulta=data_consulta,
        hora_inicio=faixa_periodo[0] if faixa_periodo else None,
        hora_fim=faixa_periodo[1] if faixa_periodo else None,
    )

    opcoes = [
        {"indice": indice, **_formatar_opcao(horario)}
        for indice, horario in enumerate(horarios[:LIMITE_OPCOES_CHAT], start=1)
    ]

    return {
        "data_resolvida": data_consulta.isoformat(),
        "opcoes": opcoes,
        "total_encontrado": len(horarios),
    }


def resolver_data_referencia(referencia_data: str | None) -> date:
    hoje = obter_data_local_negocio()

    if referencia_data == "HOJE":
        return hoje

    if referencia_data == "AMANHA":
        return hoje + timedelta(days=1)

    return hoje


def resolver_faixa_periodo(periodo: str | None) -> tuple[time, time] | None:
    if periodo is None:
        return None

    return PERIODOS.get(periodo)


def obter_data_local_negocio() -> date:
    timezone_name = get_settings().business_timezone

    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = timezone_recife_fallback()

    return datetime.now(timezone).date()


def timezone_recife_fallback() -> timezone:
    return timezone(timedelta(hours=-3), name="America/Recife")


def _formatar_opcao(horario: dict) -> dict:
    massoterapeuta_id = horario.get("massoterapeuta_id")
    massoterapeuta_nome = None

    if massoterapeuta_id:
        massoterapeuta = buscar_massoterapeuta_por_id(massoterapeuta_id)
        if massoterapeuta is not None:
            massoterapeuta_nome = massoterapeuta.get("nome")

    return {
        "horario_id": horario.get("id"),
        "massoterapeuta_id": massoterapeuta_id,
        "massoterapeuta_nome": massoterapeuta_nome,
        "data": horario.get("data"),
        "hora_inicio": horario.get("hora_inicio"),
        "hora_fim": horario.get("hora_fim"),
    }
