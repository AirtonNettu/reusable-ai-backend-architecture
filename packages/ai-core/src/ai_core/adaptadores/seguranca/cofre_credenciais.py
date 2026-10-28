"""Gerenciamento seguro e mascaramento de credenciais de provedores."""

import os
from collections.abc import Mapping


class CofreCredenciais:
    """Gerencia leitura segura e mascaramento de chaves de API e segredos."""

    def __init__(self, fonte_ambiente: Mapping[str, str] | None = None) -> None:
        self._ambiente = fonte_ambiente if fonte_ambiente is not None else os.environ

    def obter_chave(self, nome_variavel: str, obrigatoria: bool = False) -> str | None:
        """Obtém o valor de uma credencial a partir do ambiente seguro."""
        valor = self._ambiente.get(nome_variavel)
        if obrigatoria and not valor:
            raise ValueError(
                f"A credencial obrigatória '{nome_variavel}' não foi configurada no ambiente."
            )
        return valor

    @staticmethod
    def mascarar_chave(chave: str | None) -> str:
        """Retorna representação mascarada para fins de log seguro e auditoria."""
        if not chave:
            return "[NÃO CONFIGURADA]"
        if len(chave) <= 8:
            return "****"
        return f"{chave[:4]}...{chave[-4:]}"
