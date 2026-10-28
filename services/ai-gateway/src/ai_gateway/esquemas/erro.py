"""Esquemas de resposta para erros padronizados."""

from pydantic import BaseModel, Field


class EsquemaRespostaErro(BaseModel):
    """Representação padronizada de falha (estilo RFC 7807 Problem Details)."""

    tipo: str = Field(description="Identificador da categoria do erro")
    mensagem: str = Field(description="Descrição compreensível da causa da falha")
    codigo_status: int = Field(description="Código HTTP retornado")
    detalhes: dict[str, object] = Field(
        default_factory=dict, description="Dados complementares para diagnóstico"
    )
