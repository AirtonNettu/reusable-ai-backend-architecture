"""Configurações operacionais do AI Gateway."""

import os
from dataclasses import dataclass, field

AMBIENTES_PRODUCAO: frozenset[str] = frozenset({"producao", "production", "prod"})
AMBIENTES_DESENVOLVIMENTO: frozenset[str] = frozenset(
    {"desenvolvimento", "development", "dev"}
)
AMBIENTES_TESTE: frozenset[str] = frozenset({"teste", "test", "testing"})
AMBIENTES_HOMOLOGACAO: frozenset[str] = frozenset({"homologacao", "staging", "stage"})

AMBIENTES_RECONHECIDOS: frozenset[str] = (
    AMBIENTES_PRODUCAO
    | AMBIENTES_DESENVOLVIMENTO
    | AMBIENTES_TESTE
    | AMBIENTES_HOMOLOGACAO
)

CHAVES_DEMONSTRACAO_INSEGURAS: frozenset[str] = frozenset(
    {
        "chave-teste-padrao",
        "chave-servico-confiavel",
        "chave-mestre-teste",
        "chave-secreta-teste",
        "dev-local-master-key-12345678",
        "dev-service-m2m-key-12345678",
        "dev-local-master-key",
        "dev-service-m2m-key",
        "segredo-sessao-piloto-desenvolvimento-local-32chars",
        "postgres_ci_password",
        "senha_ia_local",
        "teste",
        "test",
        "dev",
        "desenvolvimento",
        "admin",
        "root",
        "secret",
        "password",
        "123456",
        "12345678",
        "default",
        "padrao",
    }
)


def eh_credencial_insegura_producao(chave: str | None) -> bool:
    """Valida se uma credencial possui entropia insuficiente ou valores de demonstração/desenvolvimento."""
    if not chave:
        return True
    chave_limpa = chave.strip()
    if len(chave_limpa) < 16:
        return True
    chave_minuscula = chave_limpa.lower()
    if chave_minuscula in CHAVES_DEMONSTRACAO_INSEGURAS:
        return True
    prefixos_bloqueados = (
        "dev-",
        "dev_",
        "teste-",
        "teste_",
        "test-",
        "test_",
        "demo-",
        "demo_",
        "exemplo-",
        "example-",
    )
    if any(chave_minuscula.startswith(p) for p in prefixos_bloqueados):
        return True
    termos_bloqueados = (
        "12345678",
        "master-key",
        "chave-padrao",
        "default-key",
        "secret-key",
    )
    return any(termo in chave_minuscula for termo in termos_bloqueados)


@dataclass(frozen=True, slots=True)
class ConfiguracoesGateway:
    """Configurações carregadas do ambiente para execução do serviço."""

    titulo: str = "Reusable AI Backend Architecture"
    versao: str = "0.1.0"
    descricao: str = (
        "HTTP Gateway para plataforma corporativa de Inteligência Artificial."
    )
    ambiente: str = "desenvolvimento"
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
    metricas_habilitadas: bool = True
    metricas_token: str | None = None
    otel_habilitado: bool = True
    otel_endpoint_otlp: str | None = None
    otel_nome_servico: str = "ai-gateway"
    piloto_habilitado: bool | None = None
    piloto_segredo_sessao: str | None = None

    def __post_init__(self) -> None:
        """Valida que o ambiente configurado é reconhecido, evitando fallback silencioso."""
        self.validar_ambiente(self.ambiente)

    @classmethod
    def validar_ambiente(cls, ambiente: str) -> str:
        """Valida e normaliza o identificador de ambiente operacional."""
        if not ambiente or not ambiente.strip():
            raise ValueError(
                "Configuração inválida: o identificador de ambiente não pode ser vazio."
            )
        amb_normalizado = ambiente.strip().lower()
        if amb_normalizado not in AMBIENTES_RECONHECIDOS:
            raise ValueError(
                f"Configuração insegura: ambiente '{ambiente}' não é reconhecido. "
                "Valores permitidos: producao, desenvolvimento, teste, homologacao. "
                "Fallback silencioso bloqueado por política de segurança."
            )
        return amb_normalizado

    @property
    def e_producao(self) -> bool:
        """Indica se a instância está operando em ambiente de produção estrito."""
        return self.ambiente.strip().lower() in AMBIENTES_PRODUCAO

    @property
    def piloto_ativo(self) -> bool:
        """Determina se a aplicação piloto e suas rotas BFF estão ativas (fail-closed em produção)."""
        if self.piloto_habilitado is not None:
            return self.piloto_habilitado
        return not self.e_producao

    def validar_seguranca_producao(self) -> None:
        """Executa validação fail-closed impedindo inicialização insegura em produção."""
        if not self.e_producao:
            return

        # Produção exige obrigatoriamente chaves configuradas
        if not self.chave_api_mestre and not self.mapeamento_chaves_usuarios:
            raise ValueError(
                "Configuração insegura: ambiente de produção exige a definição explícita de "
                "credenciais válidas (chave_api_mestre ou mapeamento_chaves_usuarios)."
            )

        # Valida chave mestre (SEC-001)
        if self.chave_api_mestre is not None and eh_credencial_insegura_producao(
            self.chave_api_mestre
        ):
            raise ValueError(
                "Configuração insegura: a chave_api_mestre para produção deve possuir "
                "no mínimo 16 caracteres de entropia e não utilizar valores de demonstração, "
                "prefixos 'dev-/teste-' ou termos inseguros padrão."
            )

        # Valida chaves de serviços confiáveis (M2M) (SEC-001)
        for chave_servico in self.chaves_servicos_confiaveis:
            if eh_credencial_insegura_producao(chave_servico):
                raise ValueError(
                    "Configuração insegura: a chave de serviços confiáveis (M2M) para produção deve possuir "
                    "no mínimo 16 caracteres de entropia e não utilizar valores fracos ou de demonstração."
                )

        # Valida chaves de usuários mapeadas (SEC-001)
        for chave_usuario in self.mapeamento_chaves_usuarios:
            if eh_credencial_insegura_producao(chave_usuario):
                raise ValueError(
                    "Configuração insegura: uma das chaves mapeadas para usuários utiliza um valor "
                    "fraco ou de demonstração não permitido em produção."
                )

        # Validação fail-closed para token de métricas em produção se fornecido (SEC-001)
        if (
            self.metricas_habilitadas
            and self.metricas_token is not None
            and eh_credencial_insegura_producao(self.metricas_token)
        ):
            raise ValueError(
                "Configuração insegura: o 'metricas_token' para produção deve possuir "
                "no mínimo 16 caracteres de entropia e não utilizar valores de demonstração."
            )

        # Validação fail-closed para piloto ativo em produção (SEC-004)
        if self.piloto_ativo:
            if not self.piloto_segredo_sessao:
                raise ValueError(
                    "Configuração insegura: a aplicação piloto em produção exige a definição "
                    "explícita de 'GATEWAY_PILOTO_SEGREDO_SESSAO' dedicado para assinatura de cookies."
                )
            if eh_credencial_insegura_producao(self.piloto_segredo_sessao):
                raise ValueError(
                    "Configuração insegura: o 'piloto_segredo_sessao' para produção deve possuir "
                    "no mínimo 16 caracteres de entropia e não utilizar valores de demonstração."
                )

    @classmethod
    def carregar_do_ambiente(cls) -> "ConfiguracoesGateway":
        """Instancia configurações a partir de variáveis de ambiente com validação estrita."""
        ambiente_bruto = (
            os.getenv("GATEWAY_AMBIENTE")
            or os.getenv("ENVIRONMENT")
            or os.getenv("APP_ENV")
            or "desenvolvimento"
        )
        ambiente = cls.validar_ambiente(ambiente_bruto)
        chave_mestre = os.getenv("GATEWAY_API_KEY")
        chaves_confiaveis_brutas = os.getenv("GATEWAY_CHAVES_CONFIAVEIS", "")
        chaves_confiaveis = tuple(
            c.strip() for c in chaves_confiaveis_brutas.split(",") if c.strip()
        )

        return cls(
            ambiente=ambiente,
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
            metricas_habilitadas=os.getenv(
                "GATEWAY_METRICAS_HABILITADAS", "true"
            ).lower()
            in ("true", "1", "yes"),
            metricas_token=os.getenv("GATEWAY_METRICAS_TOKEN"),
            otel_habilitado=os.getenv("OTEL_HABILITADO", "true").lower()
            in ("true", "1", "yes"),
            otel_endpoint_otlp=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
            otel_nome_servico=os.getenv("OTEL_SERVICE_NAME", "ai-gateway"),
            piloto_habilitado=(
                os.getenv("GATEWAY_PILOTO_HABILITADO").lower() in ("true", "1", "yes")
                if os.getenv("GATEWAY_PILOTO_HABILITADO") is not None
                else None
            ),
            piloto_segredo_sessao=os.getenv("GATEWAY_PILOTO_SEGREDO_SESSAO"),
        )
