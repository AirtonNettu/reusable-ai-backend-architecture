"""Rota de exposição de métricas para scraping pelo Prometheus."""

from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.dependencias import (
    obter_configuracoes,
    obter_metricas_prometheus,
)

roteador_metricas = APIRouter(tags=["Observabilidade"])


@roteador_metricas.get("/metrics", response_class=Response)
def expor_metricas(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> Response:
    """Exporta as métricas agregadas da aplicação em formato compatível com Prometheus 0.0.4."""
    configuracoes: ConfiguracoesGateway = (
        getattr(request.app.state, "configuracoes", None) or obter_configuracoes()
    )

    if not configuracoes.metricas_habilitadas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Métricas desabilitadas nesta instância.",
        )

    # Verificação de segurança: em produção exige token dedicado ou chave mestre
    token_esperado = configuracoes.metricas_token or (
        configuracoes.chave_api_mestre if configuracoes.e_producao else None
    )
    if token_esperado:
        token_fornecido: str | None = None
        if authorization and authorization.lower().startswith("bearer "):
            token_fornecido = authorization[7:].strip()
        elif x_api_key:
            token_fornecido = x_api_key.strip()

        if token_fornecido != token_esperado:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Acesso não autorizado ao endpoint de métricas.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    metricas = obter_metricas_prometheus()
    conteudo_bytes = metricas.gerar_exposicao_prometheus()

    return Response(
        content=conteudo_bytes,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
