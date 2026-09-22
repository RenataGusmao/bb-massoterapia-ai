import pytest

from app.agents.interpretador import InterpretacaoError, _extrair_json


def test_json_puro():
    assert _extrair_json('{"escolhido": false}') == {"escolhido": False}


def test_json_cercado_de_crases():
    bruto = '```json\n{"escolhido": true, "horario_id": "abc"}\n```'
    assert _extrair_json(bruto)["horario_id"] == "abc"


def test_json_com_texto_ao_redor():
    bruto = 'Claro! Aqui esta:\n{"escolhido": false, "motivo": "vago"}\nAte mais.'
    assert _extrair_json(bruto)["motivo"] == "vago"


def test_resposta_sem_json_levanta_erro():
    with pytest.raises(InterpretacaoError):
        _extrair_json("desculpe, nao consegui")
