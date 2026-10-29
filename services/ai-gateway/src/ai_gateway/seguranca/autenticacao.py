"""Middleware e dependências de autenticação, derivação de identidade e controle de acesso anti-spoofing."""

import hashlib
import re
from typing import Self

from fastapi import Header, HTTPException, Request, status

from ai_gateway.configuracoes import (
    ConfiguracoesGateway,
    eh_credencial_insegura_producao,
)

PADRAO_IDENTIFICADOR_SEGURO = re.compile(r"^[a-zA-Z0-9_\-\.:@]{1,128}$")


class IdentidadeAutenticada(str):
    """Identidade autenticada derivada criptograficamente de credenciais válidas.

    Herda de str para assegurar retrocompatibilidade estrita com métodos que esperam
    id_usuario em formato string, ao mesmo tempo que expõe metadados de locatário e privilégios.
    """

    id_usuario: str
    id_locatario: str
    e_servico_confiavel: bool

    def __new__(
        cls,
        id_usuario: str,
        id_locatario: str = "padrao",
        e_servico_confiavel: bool = False,
    ) -> Self:
        instancia = super().__new__(cls, id_usuario)
        instancia.id_usuario = id_usuario
        instancia.id_locatario = id_locatario
        instancia.e_servico_confiavel = e_servico_confiavel
        return instancia


class ValidadorAutenticacao:
    """Valida credenciais de requisição, previne falsificação de X-User-ID e deriva identidade segura."""

    def __init__(self, configuracoes: ConfiguracoesGateway | None = None) -> None:
        self._configuracoes = configuracoes

    def _derivar_id_hash(self, token: str) -> str:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        return f"usr_{digest}"

    def _validar_formato_identificador(
        self, valor: str | None, nome_campo: str
    ) -> None:
        if valor is not None and not PADRAO_IDENTIFICADOR_SEGURO.match(valor):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Formato inválido ou caracteres ilegais no cabeçalho {nome_campo}.",
            )

    async def __call__(
        self,
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_user_id: str | None = Header(default=None, alias="X-User-ID"),
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    ) -> IdentidadeAutenticada:
        config: ConfiguracoesGateway = (
            getattr(request.app.state, "configuracoes", None)
            or self._configuracoes
            or ConfiguracoesGateway.carregar_do_ambiente()
        )

        self._validar_formato_identificador(x_user_id, "X-User-ID")
        self._validar_formato_identificador(x_tenant_id, "X-Tenant-ID")

        locatario = x_tenant_id or "padrao"

        # Modo desenvolvimento sem chave configurada (estritamente bloqueado em produção - fail closed)
        if not config.chave_api_mestre and not config.mapeamento_chaves_usuarios:
            if config.e_producao:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Erro de configuração: o Gateway em produção não aceita conexões sem autenticação configurada.",
                )
            id_final = x_user_id or x_api_key or "desenvolvedor_local"
            return IdentidadeAutenticada(
                id_usuario=id_final,
                id_locatario=locatario,
                e_servico_confiavel=True,
            )

        token_enviado = x_api_key
        if not token_enviado and authorization and authorization.startswith("Bearer "):
            token_enviado = authorization[7:].strip()

        if not token_enviado:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credencial ausente nos cabeçalhos X-API-Key ou Authorization.",
            )

        # Em produção, rejeita credenciais conhecidas de demonstração ou com baixa entropia (SEC-001)
        if config.e_producao:
            token_limpo = token_enviado.strip()
            if eh_credencial_insegura_producao(token_limpo):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Credencial rejeitada: o ambiente de produção não aceita chaves de demonstração ou com baixa entropia.",
                )

        e_chave_mestre = (
            config.chave_api_mestre is not None
            and token_enviado == config.chave_api_mestre
        )
        e_servico_confiavel = (
            e_chave_mestre or token_enviado in config.chaves_servicos_confiaveis
        )

        id_usuario_vinculado = config.mapeamento_chaves_usuarios.get(token_enviado)

        # Rejeita token desconhecido
        if not e_servico_confiavel and id_usuario_vinculado is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Chave de API inválida ou rejeitada pelo Gateway.",
            )

        # Cenário 1: Serviço Confiável / Backend M2M com permissão de representação
        if e_servico_confiavel and id_usuario_vinculado is None:
            if x_user_id is not None and not config.permitir_delegacao_m2m:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Delegação de identidade via X-User-ID desabilitada nesta instância.",
                )
            id_resolvido = x_user_id or "servico_mestre"
            return IdentidadeAutenticada(
                id_usuario=id_resolvido,
                id_locatario=locatario,
                e_servico_confiavel=True,
            )

        # Cenário 2: Usuário Regular com chave vinculada
        id_legitimo = id_usuario_vinculado or self._derivar_id_hash(token_enviado)

        # Detecção e mitigação de vulnerabilidade de impersonation / spoofing
        if x_user_id is not None and x_user_id != id_legitimo:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Acesso negado: tentativa de personificação detectada. "
                    f"A credencial informada está vinculada exclusivamente a '{id_legitimo}', "
                    f"não sendo permitida a representação de '{x_user_id}'."
                ),
            )

        return IdentidadeAutenticada(
            id_usuario=id_legitimo,
            id_locatario=locatario,
            e_servico_confiavel=False,
        )
