from typing import Literal

from pydantic import BaseModel, Field

class RecepcaoLLMClassification(BaseModel):
    intencao: Literal[
        "AGENDAMENTO",
        "ORIENTACAO_BEM_ESTAR",
        "SAUDE_SENSIVEL",
        "FORA_DE_ESCOPO",
        "NAO_ENTENDIDO",
    ]
    confianca: float = Field(..., ge=0, le=1)
    referencia_data: Literal["HOJE", "AMANHA"] | None = None
    periodo: Literal["MANHA", "TARDE", "NOITE"] | None = None
