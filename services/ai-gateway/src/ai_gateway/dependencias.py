"""Provedores de injeção de dependência para o AI Gateway."""

from functools import lru_cache

from ai_core.adaptadores.ferramentas.registro import RegistroFerramentas
from ai_core.adaptadores.memoria.memoria_em_memoria import MemoriaEmMemoria
from ai_core.adaptadores.memoria.memoria_postgresql import MemoriaPostgresql
from ai_core.adaptadores.memoria.memoria_sqlite import MemoriaSQLite
from ai_core.adaptadores.observabilidade.observabilidade_memoria import (
    ObservabilidadeEmMemoria,
)
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.aplicacao.agentes.orquestrador import OrquestradorAgente
from ai_core.aplicacao.casos_de_uso.caso_gerar_fluxo import CasoDeUsoGerarRespostaFluxo
from ai_core.aplicacao.casos_de_uso.caso_gerar_resposta import CasoDeUsoGerarResposta
from ai_core.aplicacao.casos_de_uso.caso_gerar_saida_estruturada import (
    CasoDeUsoGerarSaidaEstruturada,
)
from ai_core.dominio.modelos.ferramenta import DefinicaoFerramenta
from ai_core.dominio.modelos.modelo import InformacoesModelo
from ai_core.dominio.portas.porta_memoria import PortaRepositorioMemoria
from ai_core.dominio.portas.porta_observabilidade import PortaObservabilidade
from ai_core.resiliencia.disjuntor import Disjuntor
from ai_core.resiliencia.limitador import RastreadorConsumoTokens
from ai_core.resiliencia.retentativa import PoliticaRetentativa

from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.seguranca.autenticacao import ValidadorAutenticacao


@lru_cache
def obter_configuracoes() -> ConfiguracoesGateway:
    """Retorna as configurações carregadas em cache."""
    return ConfiguracoesGateway.carregar_do_ambiente()


@lru_cache
def obter_validador_autenticacao() -> ValidadorAutenticacao:
    """Instancia o validador de chave de API."""
    return ValidadorAutenticacao(obter_configuracoes())


@lru_cache
def obter_repositorio_memoria() -> PortaRepositorioMemoria:
    """Instância de repositório para retenção de conversas (Memória, SQLite ou PostgreSQL)."""
    config = obter_configuracoes()
    if config.tipo_memoria == "sqlite":
        return MemoriaSQLite(caminho_banco=config.caminho_banco_sqlite)
    if config.tipo_memoria == "postgresql" and config.url_conexao_postgresql:
        return MemoriaPostgresql(
            url_conexao=config.url_conexao_postgresql,
            max_conexoes=config.limite_conexoes_postgresql,
        )
    return MemoriaEmMemoria()


@lru_cache
def obter_observabilidade() -> PortaObservabilidade:
    """Instância de coleta de métricas e rastreabilidade."""
    return ObservabilidadeEmMemoria()


@lru_cache
def obter_rastreador_consumo() -> RastreadorConsumoTokens:
    """Rastreador de consumo global de tokens."""
    return RastreadorConsumoTokens()


@lru_cache
def obter_roteador() -> RoteadorModelos:
    """Monta o roteador com os modelos padrão da plataforma."""
    roteador = RoteadorModelos()

    # Provedor simulado padrão para testes e fallback seguro
    provedor_simulado = AdaptadorSimulado(
        nome_provedor="simulado",
        modelos_suportados=("modelo-teste", "modelo-rapido"),
        resposta_padrao="Olá! Sou a IA da Reusable AI Backend Architecture.",
    )
    roteador.registrar_provedor(provedor_simulado)

    # Catálogo inicial de modelos
    roteador.registrar_modelo(
        InformacoesModelo(
            identificador="modelo-teste",
            nome_exibicao="Modelo de Teste Simulado",
            provedor="simulado",
            capacidades=("texto", "chat", "streaming", "ferramentas"),
            limite_contexto=8192,
        )
    )
    roteador.registrar_modelo(
        InformacoesModelo(
            identificador="modelo-rapido",
            nome_exibicao="Modelo Rápido Simulado",
            provedor="simulado",
            capacidades=("texto", "chat", "streaming"),
            limite_contexto=4096,
        )
    )

    return roteador


@lru_cache
def obter_executor_ferramentas() -> RegistroFerramentas:
    """Instância e popula o registro com ferramentas utilitárias."""
    registro = RegistroFerramentas()

    # Exemplo de ferramenta interna: somar números
    registro.registrar(
        definicao=DefinicaoFerramenta(
            nome="somar_valores",
            descricao="Soma dois números fornecidos.",
            esquema_parametros={
                "type": "object",
                "properties": {
                    "valor_a": {"type": "number", "description": "Primeiro valor"},
                    "valor_b": {"type": "number", "description": "Segundo valor"},
                },
                "required": ["valor_a", "valor_b"],
            },
        ),
        funcao=lambda valor_a, valor_b: valor_a + valor_b,
    )

    return registro


def obter_caso_gerar_resposta() -> CasoDeUsoGerarResposta:
    """Cria o caso de uso para geração síncrona."""
    return CasoDeUsoGerarResposta(
        roteador=obter_roteador(),
        repositorio_memoria=obter_repositorio_memoria(),
        observabilidade=obter_observabilidade(),
        rastreador_consumo=obter_rastreador_consumo(),
        disjuntor=Disjuntor(nome="gateway-geracao", limite_falhas=5),
        politica_retentativa=PoliticaRetentativa(max_tentativas=3),
    )


def obter_caso_gerar_fluxo() -> CasoDeUsoGerarRespostaFluxo:
    """Cria o caso de uso para geração contínua (streaming)."""
    return CasoDeUsoGerarRespostaFluxo(
        roteador=obter_roteador(),
        repositorio_memoria=obter_repositorio_memoria(),
        observabilidade=obter_observabilidade(),
    )


def obter_caso_gerar_saida_estruturada() -> CasoDeUsoGerarSaidaEstruturada:
    """Cria o caso de uso para geração estruturada com validação de esquema."""
    return CasoDeUsoGerarSaidaEstruturada(roteador=obter_roteador())


def obter_orquestrador_agente() -> OrquestradorAgente:
    """Cria o runtime do orquestrador de agentes."""
    config = obter_configuracoes()
    return OrquestradorAgente(
        roteador=obter_roteador(),
        executor_ferramentas=obter_executor_ferramentas(),
        modelo_padrao=config.modelo_padrao,
        observabilidade=obter_observabilidade(),
    )
