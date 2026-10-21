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


def test_json_com_dois_objetos_no_texto():
    bruto = 'Resposta: {"escolhido": true, "horario_id": "abc"} e tambem {"x": 1}'
    assert _extrair_json(bruto)["horario_id"] == "abc"


def test_json_que_nao_e_objeto_levanta_erro():
    with pytest.raises(InterpretacaoError):
        _extrair_json('[{"escolhido": true}]')


def test_prompt_traz_dia_da_semana_e_agrupa_vagas(monkeypatch):
    from datetime import date
    from unittest.mock import Mock

    from app.agents import interpretador

    def vaga(identificador, numero):
        return {
            "id": identificador, "numero_vaga": numero, "massoterapeuta_id": None,
            "data": "2026-10-16", "hora_inicio": "09:00:00", "hora_fim": "09:30:00",
        }

    monkeypatch.setattr(
        interpretador, "listar_horarios_disponiveis", lambda *_: [vaga("a", 1), vaga("b", 2)]
    )
    llm = Mock()
    llm.invoke.return_value.content = '{"escolhido": false}'
    monkeypatch.setattr(interpretador, "get_llm", lambda: llm)

    interpretador.interpretar_mensagem("Qualquer", hoje=date(2026, 10, 15))

    prompt = llm.invoke.call_args.args[0][1]["content"]
    assert "2026-10-15 (quinta-feira)" in prompt
    assert "2026-10-16 (sexta-feira)" in prompt
    assert "vagas_livres=2" in prompt
    assert prompt.count("horario_id=") == 1


def test_capacidade_alta_nao_esconde_dias_seguintes(monkeypatch):
    from datetime import date
    from unittest.mock import Mock

    from app.agents import interpretador

    horarios = [
        {
            "id": f"v{i}", "numero_vaga": i, "massoterapeuta_id": None,
            "data": "2026-10-16", "hora_inicio": "09:00:00", "hora_fim": "09:30:00",
        }
        for i in range(1, 61)
    ]
    horarios.append(
        {
            "id": "tarde", "numero_vaga": 1, "massoterapeuta_id": None,
            "data": "2026-10-22", "hora_inicio": "14:00:00", "hora_fim": "14:30:00",
        }
    )
    monkeypatch.setattr(interpretador, "listar_horarios_disponiveis", lambda *_: horarios)
    llm = Mock()
    llm.invoke.return_value.content = '{"escolhido": true, "horario_id": "tarde"}'
    monkeypatch.setattr(interpretador, "get_llm", lambda: llm)

    resultado = interpretador.interpretar_mensagem("Quinta a tarde", hoje=date(2026, 10, 15))

    assert "2026-10-22 (quinta-feira)" in llm.invoke.call_args.args[0][1]["content"]
    assert resultado.horario_id == "tarde"
