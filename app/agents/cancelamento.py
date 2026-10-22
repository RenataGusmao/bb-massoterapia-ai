import re
from datetime import date, time, timedelta

from app.agents.recepcao.classifier import normalizar_mensagem
from app.core.datas import data_local


class EsclarecimentoCancelamento(ValueError):
    pass


def acao_solicitada(mensagem: str | None, agendamento_id=None) -> str:
    texto = normalizar_mensagem(mensagem or "")
    explicito = re.search(r"\b(?:cancel\w*|desmarc\w*)\b", texto)
    ausencia = (re.search(r"\bnao\b.{0,70}\b(?:comparecer|participar|ir)\b", texto)
                and re.search(r"\b(?:sessao|massagem|agendamento|atendimento)\b", texto))
    if explicito or ausencia:
        afirmativo = (not explicito or explicito.group() in (
            "cancelar", "cancela", "cancele", "cancelo", "desmarcar", "desmarca", "desmarque")
            or (explicito.group() == "cancelamento" and re.search(r"\b(?:quero|solicito|preciso|desejo)\b", texto)))
        if ("?" in texto
                or not afirmativo
                or re.search(r"\b(?:escolha|selecao|opcao|remarcar|reagendar|agendar|marcar|reservar)\b", texto)
                or (explicito and re.search(r"\b(?:nao|nunca|como|posso|possivel|se)\b.{0,70}\b(?:cancel\w*|desmarc\w*)\b", texto))):
            return "esclarecer"
        return "cancelar"
    if agendamento_id:
        return "cancelar" if not texto else "esclarecer"
    return "criar"


def filtrar_reservas(mensagem: str | None, reservas: list[dict], *, por_id=False) -> list[dict]:
    """Resolve only explicit references; never guess an unknown date or a reservation."""
    texto = normalizar_mensagem(mensagem or "")
    hoje = data_local()
    datas = list(re.finditer(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{4})?)\b", texto))
    relativos = list(re.finditer(r"\b(?:depois de amanha|amanha|hoje)\b", texto))
    horas = list(re.finditer(r"\b(?:as\s+\d{1,2}(?::\d{2}|h\d{0,2})?|\d{1,2}:\d{2}|\d{1,2}h\d{0,2})\b", texto))
    dias = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
    semanas = [i for i, nome in enumerate(dias) if re.search(rf"\b{nome}(?:-feira)?\b", texto)]
    periodos = [p for p in ("manha", "tarde", "noite") if re.search(rf"\b{p}\b", texto)]
    if len(datas) + len(relativos) > 1 or len(horas) > 1 or len(semanas) > 1 or len(periodos) > 1:
        raise EsclarecimentoCancelamento("Informe uma unica data e horario, ou o agendamento_id.")
    dia_exato = mes_dia = hora_exata = None
    try:
        if datas:
            valor = datas[0].group()
            if "-" in valor:
                dia_exato = date.fromisoformat(valor)
            else:
                partes = [int(p) for p in valor.split("/")]
                dia, mes = partes[:2]
                if len(partes) == 3:
                    dia_exato = date(partes[2], mes, dia)
                else:
                    date(2000, mes, dia)
                    mes_dia = (mes, dia)
        elif relativos:
            dia_exato = hoje + timedelta(days={"hoje": 0, "amanha": 1, "depois de amanha": 2}[relativos[0].group()])
        if horas:
            valor = re.sub(r"^as\s+", "", horas[0].group()).replace("h", ":")
            partes = valor.split(":")
            hora_exata = time(int(partes[0]), int(partes[1]) if len(partes) > 1 and partes[1] else 0)
    except ValueError as exc:
        raise EsclarecimentoCancelamento("Informe uma data e horario validos, por exemplo 26/10/2026 as 10:10.") from exc
    resto = texto
    for m in sorted(datas + relativos + horas, key=lambda m: m.start(), reverse=True):
        resto = resto[:m.start()] + " " * (m.end()-m.start()) + resto[m.end():]
    if re.search(r"\d|\b(?:as|das|pelas|semana|mes|proxim[oa]|ontem|anterior|passad[oa]|seguinte|vem|janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b", resto):
        raise EsclarecimentoCancelamento("Para localizar com seguranca, informe a data em DD/MM/AAAA ou o agendamento_id.")

    resultado = []
    for reserva in reservas:
        dia = date.fromisoformat(str(reserva["data_agendamento"]))
        inicio = time.fromisoformat(str(reserva["hora_inicio"]))
        if dia_exato is not None and dia != dia_exato:
            continue
        if mes_dia is not None and (dia.month, dia.day) != mes_dia:
            continue
        if semanas and dia.weekday() != semanas[0]:
            continue
        if hora_exata is not None and inicio != hora_exata:
            continue
        if periodos:
            periodo = "manha" if inicio < time(12) else "tarde" if inicio < time(18) else "noite"
            if periodo != periodos[0]:
                continue
        if not por_id and dia_exato is None and mes_dia is None and dia < hoje:
            continue
        resultado.append(reserva)
    return resultado
