"""Exceções de domínio do AI Core.

Hierarquia de exceções sem qualquer dependência de bibliotecas HTTP ou frameworks.
"""


class ErroDominio(Exception):
    """Exceção base para todas as falhas de domínio do AI Core."""

    def __init__(
        self, mensagem: str, detalhes: dict[str, object] | None = None
    ) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.detalhes = detalhes or {}


class ErroValidacao(ErroDominio):
    """Lançada quando dados ou esquemas de domínio são inválidos."""


class ErroProvedor(ErroDominio):
    """Lançada quando ocorre uma falha na comunicação ou execução de um provedor LLM."""

    def __init__(
        self,
        mensagem: str,
        provedor: str,
        codigo_status: int | None = None,
        detalhes: dict[str, object] | None = None,
        tokens_faturados: int = 0,
    ) -> None:
        super().__init__(mensagem, detalhes)
        self.provedor = provedor
        self.codigo_status = codigo_status
        self.tokens_faturados = tokens_faturados


class ErroConexaoProvedor(ErroProvedor):
    """Falha de conectividade ou rede com o provedor."""


class ErroAutenticacaoProvedor(ErroProvedor):
    """Falha de autenticação ou credencial rejeitada pelo provedor."""


class ErroLimiteTaxa(ErroProvedor):
    """Limite de taxa (rate limit / quota) atingido no provedor."""

    def __init__(
        self,
        mensagem: str,
        provedor: str,
        segundos_espera: float | None = None,
        detalhes: dict[str, object] | None = None,
    ) -> None:
        super().__init__(mensagem, provedor=provedor, detalhes=detalhes)
        self.segundos_espera = segundos_espera


class ErroTimeoutProvedor(ErroProvedor):
    """Tempo limite de espera esgotado na chamada ao provedor."""


class ErroModeloNaoSuportado(ErroDominio):
    """Modelo solicitado não é suportado pelo provedor ou roteador."""


class ErroDisjuntorAberto(ErroDominio):
    """Operação bloqueada preventivamente porque o circuito do serviço está aberto."""

    def __init__(self, nome_circuito: str, mensagem: str | None = None) -> None:
        texto = (
            mensagem
            or f"O circuito '{nome_circuito}' está aberto e não aceita requisições."
        )
        super().__init__(texto, detalhes={"nome_circuito": nome_circuito})
        self.nome_circuito = nome_circuito


class ErroFerramentaNaoAutorizada(ErroDominio):
    """Tentativa de executar ferramenta sem a devida autorização ou permissão."""


class ErroAcessoNaoAutorizadoConversa(ErroDominio):
    """Tentativa de acessar, consultar ou modificar conversa pertencente a outro usuário."""


class ErroExecucaoFerramenta(ErroDominio):
    """Falha durante a execução interna de uma ferramenta."""


class ErroLimitePassosAgente(ErroDominio):
    """Agente excedeu o limite máximo de iterações do ciclo de raciocínio."""
