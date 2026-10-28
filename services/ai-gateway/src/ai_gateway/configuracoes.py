"""Configurações operacionais do AI Gateway."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ConfiguracoesGateway:
    """Configurações carregadas do ambiente para execução do serviço."""

    titulo: str = "Reusable AI Backend Architecture"
    versao: str = "0.1.0"
    descricao: str = (
        "HTTP Gateway para plataforma corporativa de Inteligência Artificial."
    )
    chave_api_mestre: str | None = None
    chaves_servicos_confiaveis: tuple[str, ...] = ()
    permitir_delegacao_m2m: bool = True
    mapeamento_chaves_usuarios: dict[str, str] = field(default_factory=dict)
    modelo_padrao: str = "modelo-teste"
    tempo_limite_requisicao_segundos: float = 60.0
    tipo_memoria: str = "memoria"
    caminho_banco_sqlite: str = ":memory:"
    url_conexao_postgresql: str | None = None
    limite_conexoes_postgresql: int = 10

    @classmethod
    def carregar_do_ambiente(cls) -> "ConfiguracoesGateway":
        """Instancia configurações a partir de variáveis de ambiente."""
        chave_mestre = os.getenv("GATEWAY_API_KEY")
        chaves_confiaveis_brutas = os.getenv("GATEWAY_CHAVES_CONFIAVEIS", "")
        chaves_confiaveis = tuple(
            c.strip() for c in chaves_confiaveis_brutas.split(",") if c.strip()
        )

        return cls(
            chave_api_mestre=chave_mestre,
            chaves_servicos_confiaveis=chaves_confiaveis,
            permitir_delegacao_m2m=os.getenv(
                "GATEWAY_PERMITIR_DELEGACAO_M2M", "true"
            ).lower()
            in ("true", "1", "yes"),
            modelo_padrao=os.getenv("GATEWAY_MODELO_PADRAO", "modelo-teste"),
            tempo_limite_requisicao_segundos=float(
                os.getenv("GATEWAY_TIMEOUT_SEGUNDOS", "60.0")
            ),
            tipo_memoria=os.getenv("GATEWAY_MEMORIA_TIPO", "memoria"),
            caminho_banco_sqlite=os.getenv("GATEWAY_SQLITE_PATH", ":memory:"),
            url_conexao_postgresql=os.getenv("GATEWAY_POSTGRES_URL"),
            limite_conexoes_postgresql=int(
                os.getenv("GATEWAY_POSTGRES_POOL_SIZE", "10")
            ),
        )
