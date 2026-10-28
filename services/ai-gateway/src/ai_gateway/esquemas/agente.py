"""Esquemas Pydantic para execução e orquestração de agentes."""

from pydantic import BaseModel, Field

from ai_gateway.esquemas.chat import EsquemaUsoTokens


class EsquemaRequisicaoAgente(BaseModel):
    """Corpo de requisição para acionamento de um agente."""

    objetivo: str = Field(
        description="Objetivo de alto nível a ser resolvido pelo agente"
    )
    nome_agente: str = Field(
        default="assistente-geral", description="Nome identificador do agente"
    )
    instrucao_sistema: str = Field(
        default="Você é um assistente útil e resolutivo.",
        description="Diretriz comportamental base",
    )
    limite_passos: int = Field(
        default=8, ge=1, le=30, description="Máximo de iterações permitidas"
    )
    ferramentas_permitidas: list[str] = Field(
        default_factory=list, description="Lista opcional de ferramentas autorizadas"
    )


class EsquemaPassoAgente(BaseModel):
    """Registro de uma iteração cognitiva executada pelo agente."""

    numero_passo: int
    pensamento: str
    resposta_parcial: str


class EsquemaRespostaAgente(BaseModel):
    """Resultado final da execução do agente."""

    resposta_final: str
    passos: list[EsquemaPassoAgente]
    sucesso: bool
    total_tokens: EsquemaUsoTokens
    tempo_total_segundos: float
    erro: str | None = None
