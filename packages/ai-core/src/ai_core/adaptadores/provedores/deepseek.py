"""Adaptador para o provedor DeepSeek (compatível com API OpenAI)."""

import httpx

from ai_core.adaptadores.provedores.openai import AdaptadorOpenAI


class AdaptadorDeepSeek(AdaptadorOpenAI):
    """Adaptador para a API DeepSeek."""

    def __init__(
        self,
        chave_api: str,
        url_base: str = "https://api.deepseek.com",
        timeout_segundos: float = 60.0,
        cliente_http: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            nome_provedor="deepseek",
            url_base=url_base,
            chave_api=chave_api,
            timeout_segundos=timeout_segundos,
            cliente_http=cliente_http,
        )

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return ("deepseek-chat", "deepseek-reasoner")
