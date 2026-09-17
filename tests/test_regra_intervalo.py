from datetime import date
from uuid import uuid4

import pytest

from app.services import agendamentos as service
from app.services.agendamentos import IntervaloAgendamentoError

COLABORADOR = uuid4()


def _fake_conflitos(datas: list[str]):
    def _buscar(colaborador_id, data_inicio, data_fim):
        return [
            {"data_agendamento": data}
            for data in datas
            if data_inicio <= date.fromisoformat(data) <= data_fim
        ]

    return _buscar


def test_sem_agendamento_anterior_permite(monkeypatch):
    monkeypatch.setattr(service, "buscar_agendamentos_validos_no_intervalo", _fake_conflitos([]))

    service._validar_intervalo_minimo(COLABORADOR, date(2026, 3, 10))


def test_agendamento_ha_14_dias_bloqueia(monkeypatch):
    monkeypatch.setattr(
        service,
        "buscar_agendamentos_validos_no_intervalo",
        _fake_conflitos(["2026-02-24"]),
    )

    with pytest.raises(IntervaloAgendamentoError) as erro:
        service._validar_intervalo_minimo(COLABORADOR, date(2026, 3, 10))

    assert "2026-03-11" in erro.value.detail


def test_agendamento_ha_exatos_15_dias_permite(monkeypatch):
    monkeypatch.setattr(
        service,
        "buscar_agendamentos_validos_no_intervalo",
        _fake_conflitos(["2026-02-23"]),
    )

    service._validar_intervalo_minimo(COLABORADOR, date(2026, 3, 10))


def test_agendamento_futuro_proximo_bloqueia(monkeypatch):
    monkeypatch.setattr(
        service,
        "buscar_agendamentos_validos_no_intervalo",
        _fake_conflitos(["2026-03-20"]),
    )

    with pytest.raises(IntervaloAgendamentoError):
        service._validar_intervalo_minimo(COLABORADOR, date(2026, 3, 10))
