from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.bem_estar.categories import CategoriaBemEstar


class BemEstarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mensagem: str = Field(..., min_length=1, max_length=1000)

    @field_validator("mensagem")
    @classmethod
    def mensagem_nao_vazia(cls, valor: str) -> str:
        if not valor.strip():
            raise ValueError("Informe uma mensagem.")
        return valor.strip()


class BemEstarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    categoria: CategoriaBemEstar
    permitido: bool
    mensagem: str
    encaminhamento: str | None
