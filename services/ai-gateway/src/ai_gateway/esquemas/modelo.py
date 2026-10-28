"""Esquemas Pydantic para consulta ao catálogo de modelos."""

from pydantic import BaseModel, Field


class EsquemaInformacaoModelo(BaseModel):
    """Metadados de um modelo registrado."""

    identificador: str = Field(description="Nome único do modelo")
    nome_exibicao: str = Field(description="Nome de exibição amigável")
    provedor: str = Field(description="Provedor responsável")
    capacidades: list[str] = Field(description="Lista de capacidades suportadas")
    limite_contexto: int = Field(description="Janela de contexto em tokens")


class EsquemaListaModelos(BaseModel):
    """Lista de modelos disponíveis na plataforma."""

    dados: list[EsquemaInformacaoModelo]
