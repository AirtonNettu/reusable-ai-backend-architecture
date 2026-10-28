"""Esquemas Pydantic para as rotas de chat e conclusão com salvaguardas de validação."""

from typing import Literal

from pydantic import BaseModel, Field


class EsquemaMensagem(BaseModel):
    """Mensagem enviada ou recebida na conversa."""

    papel: Literal["sistema", "usuario", "assistente", "ferramenta"] = Field(
        description="Papel do autor da mensagem no diálogo"
    )
    conteudo: str = Field(
        min_length=1,
        max_length=65_536,
        description="Conteúdo textual da mensagem (máximo 64 KB)",
    )
    nome: str | None = Field(
        default=None,
        max_length=64,
        description="Identificador opcional do participante",
    )


class EsquemaRequisicaoChat(BaseModel):
    """Corpo de requisição para conclusão de chat com proteções contra DoS."""

    modelo: str = Field(
        default="modelo-teste",
        min_length=1,
        max_length=128,
        description="Nome do modelo desejado",
    )
    mensagens: list[EsquemaMensagem] = Field(
        min_length=1,
        max_length=200,
        description="Histórico de mensagens (máximo 200 mensagens por requisição)",
    )
    temperatura: float = Field(
        default=0.7, ge=0.0, le=2.0, description="Criatividade da geração"
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=32_768,
        description="Limite máximo de tokens gerados",
    )
    stream: bool = Field(
        default=False, description="Habilita streaming assíncrono via SSE"
    )
    id_conversa: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[a-zA-Z0-9_\-\.:]+$",
        description="ID seguro da conversa para retenção de memória",
    )


class EsquemaUsoTokens(BaseModel):
    """Métricas de contagem de tokens."""

    tokens_entrada: int
    tokens_saida: int
    total_tokens: int


class EsquemaEscolhaChat(BaseModel):
    """Escolha individual de resposta gerada pelo modelo."""

    indice: int = 0
    mensagem: EsquemaMensagem
    motivo_finalizacao: str


class EsquemaRespostaChat(BaseModel):
    """Resposta consolidada de conclusão de chat."""

    identificador: str
    modelo: str
    escolhas: list[EsquemaEscolhaChat]
    uso: EsquemaUsoTokens
