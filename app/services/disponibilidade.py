from datetime import date, time, timedelta

from app.core.datas import data_local
from app.database.repositories.horarios import listar_horarios

PERIODOS = {
    "MANHA": (time.min, time(12)),
    "TARDE": (time(12), time(18)),
    "NOITE": (time(18), time.max),
}
LIMITE_OPCOES_CHAT = 5


def consultar_disponibilidade_chat(dados_extraidos: dict[str, str]) -> dict:
    dia = resolver_data_referencia(dados_extraidos.get("referencia_data"))
    periodo = PERIODOS.get(dados_extraidos.get("periodo"))
    horarios = listar_horarios(apenas_disponiveis=True, dia=dia)
    # The effective view already enforces calendar, blocks, time and physical occupancy.
    horarios = [h for h in horarios if h.get("disponivel") and (
        periodo is None or periodo[0] <= time.fromisoformat(str(h["hora_inicio"])) < periodo[1]
    )]
    opcoes = [
        {"indice": i, "horario_id": str(h["id"]), "massoterapeuta_id": None,
         "massoterapeuta_nome": None, "data": str(h["data"]),
         "hora_inicio": str(h["hora_inicio"]), "hora_fim": str(h["hora_fim"])}
        for i, h in enumerate(horarios[:LIMITE_OPCOES_CHAT], 1)
    ]
    return {"data_resolvida": dia.isoformat(), "opcoes": opcoes, "total_encontrado": len(horarios)}


def resolver_data_referencia(referencia_data: str | None) -> date:
    return data_local() + timedelta(days=1 if referencia_data == "AMANHA" else 0)
