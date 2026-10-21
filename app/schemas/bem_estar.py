from pydantic import BaseModel, ConfigDict, Field

from app.agents.bem_estar.categories import CategoriaBemEstar


class BemEstarRequest(BaseModel):
    mensagem: str = Field(..., min_length=1)


class BemEstarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    categoria: CategoriaBemEstar
    permitido: bool
    mensagem: str
    encaminhamento: str | None
