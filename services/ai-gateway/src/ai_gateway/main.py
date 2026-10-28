"""Ponto de entrada do serviço HTTP AI Gateway."""

from ai_core.dominio.excecoes import ErroDominio
from fastapi import FastAPI

from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.middlewares.rastreamento import MiddlewareRastreamento
from ai_gateway.middlewares.tratamento_erros import manipulador_erro_dominio
from ai_gateway.rotas import (
    roteador_agentes,
    roteador_conclusoes,
    roteador_estruturado,
    roteador_modelos,
    roteador_saude,
)


def criar_aplicacao(
    configuracoes: ConfiguracoesGateway | None = None,
) -> FastAPI:
    """Fábrica de aplicação FastAPI com middlewares e roteadores integrados."""
    config = configuracoes or ConfiguracoesGateway.carregar_do_ambiente()
    config.validar_seguranca_producao()

    aplicacao = FastAPI(
        title=config.titulo,
        version=config.versao,
        description=config.descricao,
    )
    aplicacao.state.configuracoes = config

    # Middlewares e Tratamento de Exceções
    aplicacao.add_middleware(MiddlewareRastreamento)
    aplicacao.add_exception_handler(ErroDominio, manipulador_erro_dominio)

    # Inclusão de Rotas
    aplicacao.include_router(roteador_saude)
    aplicacao.include_router(roteador_modelos)
    aplicacao.include_router(roteador_conclusoes)
    aplicacao.include_router(roteador_estruturado)
    aplicacao.include_router(roteador_agentes)

    return aplicacao


app = criar_aplicacao()
criar_aplicacao_gateway = criar_aplicacao
