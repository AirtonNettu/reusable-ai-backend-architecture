"""Ponto de entrada do serviço HTTP AI Gateway."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ai_core.adaptadores.memoria.memoria_postgresql import MemoriaPostgresql
from ai_core.dominio.excecoes import ErroDominio
from fastapi import FastAPI

from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.dependencias import obter_repositorio_memoria
from ai_gateway.middlewares.cabecalhos_seguranca import (
    MiddlewareCabecalhosSeguranca,
)
from ai_gateway.middlewares.rastreamento import MiddlewareRastreamento
from ai_gateway.middlewares.tratamento_erros import manipulador_erro_dominio
from ai_gateway.rotas import (
    roteador_agentes,
    roteador_conclusoes,
    roteador_conversas,
    roteador_estruturado,
    roteador_metricas,
    roteador_modelos,
    roteador_piloto,
    roteador_saude,
)

logger = logging.getLogger("ai_gateway")


@asynccontextmanager
async def ciclo_vida_aplicacao(aplicacao: FastAPI) -> AsyncIterator[None]:
    """Gerencia a inicialização e o encerramento gracioso dos recursos do gateway."""
    config: ConfiguracoesGateway = aplicacao.state.configuracoes

    # Execução automática e idempotente de migrações se o backend configurado for PostgreSQL
    if config.tipo_memoria == "postgresql" and config.url_conexao_postgresql:
        repositorio = obter_repositorio_memoria()
        if isinstance(repositorio, MemoriaPostgresql):
            logger.info(
                "Iniciando verificação e aplicação de migrações idempotentes no PostgreSQL..."
            )
            await repositorio.executar_migracoes()
            logger.info("Migrações do esquema PostgreSQL aplicadas com sucesso.")

    yield

    # Encerramento gracioso do pool de conexões com o PostgreSQL
    repositorio = obter_repositorio_memoria()
    if isinstance(repositorio, MemoriaPostgresql):
        logger.info("Encerrando pool de conexões com o banco PostgreSQL...")
        await repositorio.fechar()
        logger.info("Pool de conexões PostgreSQL encerrado graciosamente.")


def criar_aplicacao(
    configuracoes: ConfiguracoesGateway | None = None,
) -> FastAPI:
    """Fábrica de aplicação FastAPI com middlewares, rotas e ciclo de vida integrados."""
    config = configuracoes or ConfiguracoesGateway.carregar_do_ambiente()
    config.validar_seguranca_producao()

    aplicacao = FastAPI(
        title=config.titulo,
        version=config.versao,
        description=config.descricao,
        lifespan=ciclo_vida_aplicacao,
    )
    aplicacao.state.configuracoes = config

    # Middlewares e Tratamento de Exceções
    aplicacao.add_middleware(MiddlewareCabecalhosSeguranca)
    aplicacao.add_middleware(MiddlewareRastreamento)
    aplicacao.add_exception_handler(ErroDominio, manipulador_erro_dominio)

    # Inclusão de Rotas
    aplicacao.include_router(roteador_saude)
    aplicacao.include_router(roteador_metricas)
    aplicacao.include_router(roteador_modelos)
    aplicacao.include_router(roteador_conclusoes)
    aplicacao.include_router(roteador_estruturado)
    aplicacao.include_router(roteador_agentes)
    aplicacao.include_router(roteador_conversas)
    aplicacao.include_router(roteador_piloto)

    return aplicacao


app = criar_aplicacao()
criar_aplicacao_gateway = criar_aplicacao
