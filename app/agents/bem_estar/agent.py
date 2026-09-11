from app.agents.bem_estar.categories import CategoriaBemEstar
from app.agents.bem_estar.safety import identificar_limite_de_seguranca, normalizar_mensagem


RESPOSTAS_PERMITIDAS = {
    CategoriaBemEstar.HIDRATACAO: (
        "Manter uma hidratação adequada ao longo do dia é uma medida simples de "
        "autocuidado e bem-estar."
    ),
    CategoriaBemEstar.POS_MASSAGEM: (
        "Após a sessão, procure respeitar a resposta do seu corpo, manter-se "
        "hidratado e evitar esforço intenso imediatamente se estiver se sentindo "
        "sensível ou cansado."
    ),
    CategoriaBemEstar.ERGONOMIA: (
        "Alternar a postura e fazer pequenas pausas durante períodos prolongados "
        "sentado pode contribuir para maior conforto ao longo do expediente."
    ),
    CategoriaBemEstar.DESCANSO_RELAXAMENTO: (
        "Pequenas pausas, respiração tranquila e redução de estímulos por alguns "
        "minutos podem ajudar no relaxamento durante o dia."
    ),
    CategoriaBemEstar.BEM_ESTAR_GERAL: (
        "Posso compartilhar orientações gerais de bem-estar, como pausas, descanso, "
        "hidratação e autocuidado, sem substituir avaliação profissional."
    ),
}

RESPOSTA_FORA_DO_LIMITE = (
    "Essa orientação depende de avaliação individual por profissional habilitado. "
    "Posso fornecer informações gerais sobre bem-estar, mas não indicar diagnóstico, "
    "tratamento, prescrição ou técnica para uma condição clínica."
)

RESPOSTA_SINAL_DE_ALERTA = (
    "Esse relato pode envolver um sinal importante de saúde. Procure atendimento de "
    "saúde adequado e, se houver possibilidade de urgência, busque atendimento de "
    "urgência imediatamente."
)


def processar_orientacao(mensagem: str) -> dict:
    categoria = classificar_orientacao(mensagem)

    if categoria == CategoriaBemEstar.SINAL_DE_ALERTA:
        return {
            "categoria": categoria,
            "permitido": False,
            "mensagem": RESPOSTA_SINAL_DE_ALERTA,
            "encaminhamento": "ATENDIMENTO_DE_SAUDE",
        }

    if categoria == CategoriaBemEstar.FORA_DO_LIMITE_PROFISSIONAL:
        return {
            "categoria": categoria,
            "permitido": False,
            "mensagem": RESPOSTA_FORA_DO_LIMITE,
            "encaminhamento": "PROFISSIONAL_HABILITADO",
        }

    return {
        "categoria": categoria,
        "permitido": True,
        "mensagem": RESPOSTAS_PERMITIDAS[categoria],
        "encaminhamento": None,
    }


def classificar_orientacao(mensagem: str) -> CategoriaBemEstar:
    limite = identificar_limite_de_seguranca(mensagem)
    if limite is not None:
        return limite

    texto = normalizar_mensagem(mensagem)

    if _contem_termo(texto, ("agua", "hidratacao", "hidratar", "beber")):
        return CategoriaBemEstar.HIDRATACAO

    if _contem_termo(texto, ("depois da massagem", "apos a massagem", "pos massagem", "sessao")):
        return CategoriaBemEstar.POS_MASSAGEM

    if _contem_termo(texto, ("sentado", "postura", "ergonomia", "cadeira", "mesa")):
        return CategoriaBemEstar.ERGONOMIA

    if _contem_termo(texto, ("relaxar", "relaxamento", "descansar", "descanso", "pausa", "trabalho")):
        return CategoriaBemEstar.DESCANSO_RELAXAMENTO

    return CategoriaBemEstar.BEM_ESTAR_GERAL


def _contem_termo(texto: str, termos: tuple[str, ...]) -> bool:
    return any(termo in texto for termo in termos)
