import os
import pytest

# Tests never seed a remote database through FastAPI startup.
os.environ["AGENDA_GERACAO_AUTOMATICA"] = "false"
os.environ.setdefault("JWT_SECRET_KEY", "segredo-de-teste-com-tamanho-adequado")


@pytest.fixture(autouse=True)
def isolar_prontidao_de_banco_nos_testes_unitarios(request, monkeypatch):
    # Readiness integration tests opt out explicitly; old unit tests mock only their own layer.
    if "prontidao_real" not in request.fixturenames:
        from app.services import agenda_automatica
        monkeypatch.setattr(agenda_automatica, "exigir_agenda_pronta", lambda: None)
