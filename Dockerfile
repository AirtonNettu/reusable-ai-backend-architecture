# syntax=docker/dockerfile:1
# ------------------------------------------------------------------------------
# Estágio 1: Extração da ferramenta uv
# ------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:latest AS uv_bin

# ------------------------------------------------------------------------------
# Estágio 2: Construção e compilação do ambiente virtual (Builder)
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Injetar o binário uv do estágio anterior
COPY --from=uv_bin /uv /uvx /bin/

# Copiar manifestos e códigos-fonte do workspace
COPY pyproject.toml uv.lock .python-version /app/
COPY packages/ /app/packages/
COPY services/ /app/services/

# Sincronizar todos os pacotes do monorepo e dependências de produção
RUN uv sync --frozen --all-packages --no-dev


# ------------------------------------------------------------------------------
# Estágio 3: Imagem final de execução mínima (Runtime)
# ------------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Criação de usuário e grupo com privilégios restritos (não-root)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -d /app appuser

WORKDIR /app

# Copiar artefatos do estágio builder com posse do usuário restrito
COPY --from=builder --chown=appuser:appgroup /app /app

# Variáveis operacionais de execução com PATH completo
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app/packages/ai-core/src:/app/services/ai-gateway/src"

USER appuser

EXPOSE 8000

# Sonda interna de integridade (Healthcheck) sem dependências externas
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

# Comando de inicialização padrão do Gateway
CMD ["uvicorn", "ai_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
