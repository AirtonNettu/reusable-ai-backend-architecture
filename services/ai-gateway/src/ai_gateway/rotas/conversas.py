"""Rotas HTTP para consulta e gestão do histórico de conversas persistidas."""

from typing import Annotated

from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria
from fastapi import APIRouter, Depends, Path, Query

from ai_gateway.dependencias import (
    obter_repositorio_memoria,
    obter_validador_autenticacao,
)
from ai_gateway.esquemas.chat import EsquemaMensagem
from ai_gateway.esquemas.conversas import (
    EsquemaHistoricoConversa,
    EsquemaRemocaoConversa,
)

roteador_conversas = APIRouter(prefix="/v1/conversas", tags=["Conversas"])


@roteador_conversas.get(
    "/{id_conversa}",
    response_model=EsquemaHistoricoConversa,
    summary="Recuperar histórico de mensagens da conversa",
    description="Recupera mensagens persistidas garantindo isolamento multilocatário por usuário.",
)
async def obter_historico_conversa(
    id_conversa: Annotated[
        str,
        Path(
            min_length=1,
            max_length=128,
            pattern=r"^[a-zA-Z0-9_\-\.:]+$",
            description="Identificador da conversa a ser recuperada",
        ),
    ],
    limite: Annotated[
        int | None,
        Query(
            ge=1,
            le=500,
            description="Quantidade máxima de mensagens recentes a retornar",
        ),
    ] = None,
    memoria: Annotated[
        PortaRepositorioMemoria, Depends(obter_repositorio_memoria)
    ] = None,
    _autenticado: Annotated[str | None, Depends(obter_validador_autenticacao())] = None,
) -> EsquemaHistoricoConversa:
    """Recupera mensagens gravadas no banco para o usuário autenticado."""
    mensagens_dominio = await memoria.recuperar_historico(
        id_conversa=id_conversa,
        limite=limite,
        id_usuario=_autenticado,
    )

    mensagens_esquema = [
        EsquemaMensagem(
            papel=m.papel,
            conteudo=m.conteudo,
            nome=m.nome,
        )
        for m in mensagens_dominio
    ]

    return EsquemaHistoricoConversa(
        id_conversa=id_conversa,
        id_usuario=_autenticado,
        mensagens=mensagens_esquema,
        total_mensagens=len(mensagens_esquema),
    )


@roteador_conversas.delete(
    "/{id_conversa}",
    response_model=EsquemaRemocaoConversa,
    summary="Limpar histórico de uma conversa",
    description="Exclui mensagens da conversa assegurando que o solicitante seja o legítimo proprietário.",
)
async def limpar_historico_conversa(
    id_conversa: Annotated[
        str,
        Path(
            min_length=1,
            max_length=128,
            pattern=r"^[a-zA-Z0-9_\-\.:]+$",
            description="Identificador da conversa a ser excluída",
        ),
    ],
    memoria: Annotated[
        PortaRepositorioMemoria, Depends(obter_repositorio_memoria)
    ] = None,
    _autenticado: Annotated[str | None, Depends(obter_validador_autenticacao())] = None,
) -> EsquemaRemocaoConversa:
    """Remove todo o histórico da conversa sob validação de autorização."""
    await memoria.limpar_historico(
        id_conversa=id_conversa,
        id_usuario=_autenticado,
    )
    return EsquemaRemocaoConversa(
        id_conversa=id_conversa,
        sucesso=True,
        mensagem=f"Histórico da conversa '{id_conversa}' removido com sucesso.",
    )
