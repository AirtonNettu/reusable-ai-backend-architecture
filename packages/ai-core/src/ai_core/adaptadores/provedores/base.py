"""Classe base para adaptadores de provedores LLM via HTTP."""

import httpx

from ai_core.dominio.excecoes import (
    ErroAutenticacaoProvedor,
    ErroConexaoProvedor,
    ErroLimiteTaxa,
    ErroProvedor,
    ErroTimeoutProvedor,
)
from ai_core.dominio.portas.porta_provedor import PortaProvedorLLM


class AdaptadorProvedorHttpBase(PortaProvedorLLM):
    """Base com tratamento padronizado de erros de rede e ciclo de vida HTTP."""

    def __init__(
        self,
        nome_provedor: str,
        url_base: str,
        chave_api: str | None = None,
        timeout_segundos: float = 60.0,
        cliente_http: httpx.AsyncClient | None = None,
    ) -> None:
        self._nome_provedor = nome_provedor
        self._url_base = url_base.rstrip("/")
        self._chave_api = chave_api
        self._timeout_segundos = timeout_segundos
        self._cliente_externo = cliente_http
        self._cliente_proprio: httpx.AsyncClient | None = None

    @property
    def nome_provedor(self) -> str:
        return self._nome_provedor

    def obter_cliente(self) -> httpx.AsyncClient:
        """Retorna o cliente HTTP assíncrono configurado."""
        if self._cliente_externo is not None:
            return self._cliente_externo
        if self._cliente_proprio is None or self._cliente_proprio.is_closed:
            self._cliente_proprio = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout_segundos)
            )
        return self._cliente_proprio

    async def fechar(self) -> None:
        """Encerra recursos de conexão caso o cliente seja de gerenciamento interno."""
        if self._cliente_proprio and not self._cliente_proprio.is_closed:
            await self._cliente_proprio.aclose()

    def tratar_erro_resposta(self, resposta: httpx.Response) -> None:
        """Mapeia status HTTP para exceções de domínio padronizadas."""
        if resposta.is_success:
            return

        status = resposta.status_code
        detalhes: dict[str, object] = {
            "status_code": status,
            "corpo_resposta": resposta.text,
        }

        if status in (401, 403):
            raise ErroAutenticacaoProvedor(
                mensagem=f"Falha de autenticação junto ao provedor '{self.nome_provedor}': {resposta.text}",
                provedor=self.nome_provedor,
                codigo_status=status,
                detalhes=detalhes,
            )
        if status == 429:
            segundos_espera: float | None = None
            cabecalho_retry = resposta.headers.get("retry-after")
            if cabecalho_retry:
                try:
                    segundos_espera = float(cabecalho_retry)
                except ValueError:
                    pass
            raise ErroLimiteTaxa(
                mensagem=f"Limite de taxa excedido no provedor '{self.nome_provedor}'.",
                provedor=self.nome_provedor,
                segundos_espera=segundos_espera,
                detalhes=detalhes,
            )
        raise ErroProvedor(
            mensagem=f"Erro retornado pelo provedor '{self.nome_provedor}' (HTTP {status}): {resposta.text}",
            provedor=self.nome_provedor,
            codigo_status=status,
            detalhes=detalhes,
        )

    def tratar_excecao_transporte(self, erro: Exception) -> None:
        """Mapeia exceções de baixo nível do HTTPX para exceções de domínio."""
        if isinstance(erro, httpx.TimeoutException):
            raise ErroTimeoutProvedor(
                mensagem=f"Tempo limite ({self._timeout_segundos}s) esgotado no provedor '{self.nome_provedor}'.",
                provedor=self.nome_provedor,
                detalhes={"erro_origem": str(erro)},
            ) from erro
        if isinstance(erro, httpx.RequestError):
            raise ErroConexaoProvedor(
                mensagem=f"Falha de conexão com provedor '{self.nome_provedor}': {erro}",
                provedor=self.nome_provedor,
                detalhes={"erro_origem": str(erro)},
            ) from erro
