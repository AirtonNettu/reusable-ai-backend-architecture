"""Testes de validação da infraestrutura local Docker, Compose, migrações e ciclo de vida."""

from unittest.mock import AsyncMock, patch

import pytest
from ai_core.adaptadores.memoria.memoria_postgresql import MemoriaPostgresql
from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.main import ciclo_vida_aplicacao, criar_aplicacao
from ai_gateway.migrar import executar_migracoes_cli


def test_validacao_especificacao_dockerfile() -> None:
    """Verifica se o Dockerfile respeita as regras de segurança e multi-stage."""
    with open("Dockerfile", "r", encoding="utf-8") as arquivo:
        conteudo = arquivo.read()

    # Multi-stage com uv e python 3.13-slim
    assert "FROM ghcr.io/astral-sh/uv:latest AS uv_bin" in conteudo
    assert "FROM python:3.13-slim AS builder" in conteudo
    assert "FROM python:3.13-slim AS runtime" in conteudo

    # Segurança: usuário e grupo não-root
    assert "groupadd -g 10001 appgroup" in conteudo
    assert "useradd -u 10001 -g appgroup" in conteudo
    assert "USER appuser" in conteudo

    # Exposição correta de porta e healthcheck
    assert "EXPOSE 8000" in conteudo
    assert "HEALTHCHECK" in conteudo
    assert "http://127.0.0.1:8000/health" in conteudo


def test_validacao_especificacao_docker_compose() -> None:
    """Verifica se o docker-compose.yml atende aos requisitos arquiteturais."""
    with open("docker-compose.yml", "r", encoding="utf-8") as arquivo:
        conteudo = arquivo.read()

    # Serviços essenciais definidos
    assert "postgres:" in conteudo
    assert "ai-gateway:" in conteudo
    assert "ollama:" in conteudo

    # Versão do PostgreSQL 17 e imagem alpine
    assert "image: postgres:17-alpine" in conteudo

    # Volume persistente
    assert "dados_postgresql:/var/lib/postgresql/data" in conteudo
    assert "ia_dados_postgresql" in conteudo

    # Ollama isolado por perfil opcional
    assert "profiles:" in conteudo
    assert "- ollama" in conteudo

    # Restrição de segurança: PostgreSQL NÃO deve publicar porta no host por padrão
    assert 'ports:\n      - "127.0.0.1:5432:5432"' not in conteudo
    assert 'ports:\n      - "5432:5432"' not in conteudo

    # Readiness e dependências
    assert "condition: service_healthy" in conteudo


def test_validacao_dockerignore() -> None:
    """Verifica se arquivos sensíveis ou transitórios estão no .dockerignore."""
    with open(".dockerignore", "r", encoding="utf-8") as arquivo:
        linhas = [linha.strip() for linha in arquivo if linha.strip()]

    assert ".git" in linhas
    assert ".venv" in linhas
    assert ".env" in linhas
    assert "*.py[cod]" in linhas or "*.pyc" in linhas


@pytest.mark.asyncio
async def test_ciclo_vida_aplicacao_memoria_transparente() -> None:
    """Valida que o ciclo de vida não gera efeitos colaterais quando memória é em-memória."""
    config = ConfiguracoesGateway(ambiente="teste", tipo_memoria="memoria")
    app = criar_aplicacao(config)

    async with ciclo_vida_aplicacao(app):
        assert app.state.configuracoes.tipo_memoria == "memoria"


@pytest.mark.asyncio
async def test_ciclo_vida_aplicacao_postgresql_executa_migracoes_e_fecha() -> None:
    """Valida que o ciclo de vida aciona migrações e encerra o pool para PostgreSQL."""
    config = ConfiguracoesGateway(
        ambiente="teste",
        tipo_memoria="postgresql",
        url_conexao_postgresql="postgresql://usuario:senha@localhost:5432/banco",
    )
    app = criar_aplicacao(config)

    mock_repo = AsyncMock(spec=MemoriaPostgresql)
    with patch("ai_gateway.main.obter_repositorio_memoria", return_value=mock_repo):
        async with ciclo_vida_aplicacao(app):
            mock_repo.executar_migracoes.assert_awaited_once()

        mock_repo.fechar.assert_awaited_once()


@pytest.mark.asyncio
async def test_utilitario_migrar_cli_com_memoria() -> None:
    """Valida execução da CLI de migração quando o tipo de memória não é PostgreSQL."""
    config = ConfiguracoesGateway(ambiente="teste", tipo_memoria="memoria")
    with patch("ai_gateway.migrar.obter_configuracoes", return_value=config):
        codigo = await executar_migracoes_cli()
        assert codigo == 0


@pytest.mark.asyncio
async def test_utilitario_migrar_cli_com_postgresql_sucesso() -> None:
    """Valida execução da CLI de migração com PostgreSQL."""
    config = ConfiguracoesGateway(
        ambiente="teste",
        tipo_memoria="postgresql",
        url_conexao_postgresql="postgresql://usuario:senha@localhost:5432/banco",
    )
    mock_repo = AsyncMock(spec=MemoriaPostgresql)

    with (
        patch("ai_gateway.migrar.obter_configuracoes", return_value=config),
        patch("ai_gateway.migrar.obter_repositorio_memoria", return_value=mock_repo),
    ):
        codigo = await executar_migracoes_cli()
        assert codigo == 0
        mock_repo.executar_migracoes.assert_awaited_once()
        mock_repo.fechar.assert_awaited_once()
