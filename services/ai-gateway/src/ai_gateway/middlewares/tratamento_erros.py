"""Tratamento global de exceções e mapeamento para respostas RFC 7807."""

from ai_core.dominio.excecoes import (
    ErroAcessoNaoAutorizadoConversa,
    ErroAutenticacaoProvedor,
    ErroConexaoProvedor,
    ErroDisjuntorAberto,
    ErroDominio,
    ErroFerramentaNaoAutorizada,
    ErroLimitePassosAgente,
    ErroLimiteTaxa,
    ErroModeloNaoSuportado,
    ErroTimeoutProvedor,
    ErroValidacao,
)
from ai_core.resiliencia.orcamento import ErroLimiteOrcamentoTokens
from fastapi import Request, status
from fastapi.responses import JSONResponse


def mapear_erro_dominio_para_status(erro: ErroDominio) -> int:
    """Define o status HTTP correspondente à exceção de domínio."""
    if isinstance(erro, ErroValidacao):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(erro, ErroAutenticacaoProvedor):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(erro, (ErroFerramentaNaoAutorizada, ErroAcessoNaoAutorizadoConversa)):
        return status.HTTP_403_FORBIDDEN
    if isinstance(erro, ErroModeloNaoSuportado):
        return status.HTTP_404_NOT_FOUND
    if isinstance(erro, ErroTimeoutProvedor):
        return status.HTTP_408_REQUEST_TIMEOUT
    if isinstance(erro, (ErroLimiteTaxa, ErroLimiteOrcamentoTokens)):
        return status.HTTP_429_TOO_MANY_REQUESTS
    if isinstance(erro, ErroDisjuntorAberto):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(erro, ErroConexaoProvedor):
        return status.HTTP_502_BAD_GATEWAY
    if isinstance(erro, ErroLimitePassosAgente):
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    return status.HTTP_500_INTERNAL_SERVER_ERROR


async def manipulador_erro_dominio(request: Request, exc: ErroDominio) -> JSONResponse:
    """Captura e serializa exceções de domínio em formato JSON uniforme."""
    codigo_status = mapear_erro_dominio_para_status(exc)
    cabecalhos: dict[str, str] = {}

    if isinstance(exc, ErroLimiteTaxa) and exc.segundos_espera is not None:
        cabecalhos["Retry-After"] = str(int(exc.segundos_espera))

    corpo = {
        "tipo": type(exc).__name__,
        "mensagem": exc.mensagem,
        "codigo_status": codigo_status,
        "detalhes": exc.detalhes,
    }

    return JSONResponse(
        status_code=codigo_status,
        content=corpo,
        headers=cabecalhos,
    )
