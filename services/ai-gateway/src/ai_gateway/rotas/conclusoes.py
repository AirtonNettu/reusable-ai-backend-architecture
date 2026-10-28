"""Rotas de chat e geração de texto (síncrona e streaming)."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from ai_core.aplicacao.casos_de_uso.caso_gerar_fluxo import CasoDeUsoGerarRespostaFluxo
from ai_core.aplicacao.casos_de_uso.caso_gerar_resposta import CasoDeUsoGerarResposta
from ai_core.dominio.modelos.geracao import (
    ConfiguracaoGeracao,
    RequisicaoGeracao,
)
from ai_core.dominio.modelos.mensagem import Mensagem
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ai_gateway.dependencias import (
    obter_caso_gerar_fluxo,
    obter_caso_gerar_resposta,
    obter_validador_autenticacao,
)
from ai_gateway.esquemas.chat import (
    EsquemaEscolhaChat,
    EsquemaMensagem,
    EsquemaRequisicaoChat,
    EsquemaRespostaChat,
    EsquemaUsoTokens,
)

roteador_conclusoes = APIRouter(prefix="/v1/chat", tags=["Conclusões"])


async def _gerador_eventos_sse(
    caso_fluxo: CasoDeUsoGerarRespostaFluxo,
    requisicao_dominio: RequisicaoGeracao,
    id_conversa: str | None,
    id_usuario: str | None = None,
) -> AsyncIterator[str]:
    """Empacota cada pedaço de resposta no formato Server-Sent Events (SSE)."""
    async for pedaco in caso_fluxo.executar(
        requisicao=requisicao_dominio,
        id_conversa=id_conversa,
        id_usuario=id_usuario,
    ):
        dados_sse = {
            "texto": pedaco.texto,
            "finalizado": pedaco.finalizado,
            "motivo_finalizacao": pedaco.motivo_finalizacao,
        }
        yield f"data: {json.dumps(dados_sse, ensure_ascii=False)}\n\n"

    yield "data: [DONE]\n\n"


@roteador_conclusoes.post(
    "/conclusoes",
    response_model=EsquemaRespostaChat,
    responses={
        200: {
            "description": "Resposta síncrona ou fluxo Server-Sent Events (SSE) caso stream=True."
        }
    },
)
async def criar_conclusao_chat(
    requisicao: EsquemaRequisicaoChat,
    caso_resposta: Annotated[
        CasoDeUsoGerarResposta, Depends(obter_caso_gerar_resposta)
    ],
    caso_fluxo: Annotated[CasoDeUsoGerarRespostaFluxo, Depends(obter_caso_gerar_fluxo)],
    _autenticado: Annotated[str | None, Depends(obter_validador_autenticacao())] = None,
) -> EsquemaRespostaChat | StreamingResponse:
    """Gera conclusão conversacional com suporte a streaming e retenção de contexto."""
    mensagens_dominio = tuple(
        Mensagem(papel=m.papel, conteudo=m.conteudo, nome=m.nome)
        for m in requisicao.mensagens
    )

    requisicao_dominio = RequisicaoGeracao(
        modelo=requisicao.modelo,
        mensagens=mensagens_dominio,
        configuracao=ConfiguracaoGeracao(
            temperatura=requisicao.temperatura,
            max_tokens=requisicao.max_tokens,
        ),
    )

    if requisicao.stream:
        return StreamingResponse(
            _gerador_eventos_sse(
                caso_fluxo=caso_fluxo,
                requisicao_dominio=requisicao_dominio,
                id_conversa=requisicao.id_conversa,
                id_usuario=_autenticado,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    resposta_dominio = await caso_resposta.executar(
        requisicao=requisicao_dominio,
        id_conversa=requisicao.id_conversa,
        id_usuario=_autenticado,
    )

    return EsquemaRespostaChat(
        identificador=f"chatcmpl-{uuid.uuid4().hex[:8]}",
        modelo=resposta_dominio.modelo,
        escolhas=[
            EsquemaEscolhaChat(
                indice=0,
                mensagem=EsquemaMensagem(
                    papel="assistente",
                    conteudo=resposta_dominio.texto,
                ),
                motivo_finalizacao=resposta_dominio.motivo_finalizacao,
            )
        ],
        uso=EsquemaUsoTokens(
            tokens_entrada=resposta_dominio.uso.tokens_entrada,
            tokens_saida=resposta_dominio.uso.tokens_saida,
            total_tokens=resposta_dominio.uso.total_tokens,
        ),
    )
