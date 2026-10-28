"""Esquemas Pydantic para a rota de saída estruturada com validação de esquema."""

from typing import Any

from ai_core.dominio.excecoes import ErroValidacao
from ai_core.dominio.servicos.validador_esquema import ValidadorEsquemaJson
from pydantic import BaseModel, Field, field_validator

from ai_gateway.esquemas.chat import EsquemaMensagem


class EsquemaRequisicaoChatEstruturado(BaseModel):
    """Corpo de requisição para geração com validação rigorosa de esquema."""

    modelo: str = Field(
        default="modelo-teste",
        min_length=1,
        max_length=128,
        description="Nome do modelo",
    )
    mensagens: list[EsquemaMensagem] = Field(
        min_length=1,
        max_length=200,
        description="Histórico de mensagens",
    )
    esquema_json: dict[str, Any] = Field(
        description="JSON Schema que define a estrutura de dados esperada na resposta"
    )
    max_tentativas: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Tentativas de autocorreção em caso de JSON inválido",
    )

    @field_validator("esquema_json")
    @classmethod
    def validar_esquema(cls, v: dict[str, Any]) -> dict[str, Any]:
        validador = ValidadorEsquemaJson()
        try:
            validador.validar_definicao_esquema(v)
        except ErroValidacao as erro:
            raise ValueError(f"Esquema JSON inválido: {erro.mensagem}") from erro
        return v


class EsquemaRespostaChatEstruturado(BaseModel):
    """Resposta contendo os dados validados segundo o esquema solicitado."""

    sucesso: bool
    dados: dict[str, Any] | None = None
    tentativas: int
    json_bruto: str
    erros_validacao: list[str] = Field(default_factory=list)
