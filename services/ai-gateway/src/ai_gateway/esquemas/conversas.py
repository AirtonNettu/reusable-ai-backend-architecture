"""Esquemas Pydantic para consulta e gestão de conversas persistidas."""

from pydantic import BaseModel, Field

from ai_gateway.esquemas.chat import EsquemaMensagem


class EsquemaHistoricoConversa(BaseModel):
    """Representação estruturada do histórico de uma conversa."""

    id_conversa: str = Field(
        description="Identificador único da conversa",
        examples=["conv-demonstracao-01"],
    )
    id_usuario: str | None = Field(
        default=None,
        description="Identificador do usuário proprietário da conversa",
        examples=["usr_demonstracao"],
    )
    mensagens: list[EsquemaMensagem] = Field(
        default_factory=list,
        description="Lista ordenada das mensagens trocadas na conversa",
    )
    total_mensagens: int = Field(
        ge=0,
        description="Quantidade total de mensagens registradas na conversa",
    )


class EsquemaRemocaoConversa(BaseModel):
    """Resposta após solicitação de limpeza de histórico de conversa."""

    id_conversa: str
    sucesso: bool = True
    mensagem: str = "Histórico de conversa removido com sucesso."
