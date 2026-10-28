"""Suíte de testes automatizados para a camada de observabilidade, métricas Prometheus, tracing OpenTelemetry e logs estruturados."""

import concurrent.futures
import json
import logging

import pytest
from ai_core.adaptadores.memoria.memoria_sqlite import MemoriaSQLite
from ai_core.adaptadores.observabilidade.formatador_logs import FormatadorLogJson
from ai_core.adaptadores.observabilidade.metricas_prometheus import (
    MetricasPrometheus,
)
from ai_core.adaptadores.observabilidade.rastreador_otel import (
    ExportadorSpansMemoria,
    GerenciadorRastreamento,
)
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.resiliencia.disjuntor import Disjuntor
from ai_core.resiliencia.fallback import PoliticaFallback
from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.main import criar_aplicacao
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry


def test_metricas_prometheus_instanciacao_e_contadores() -> None:
    """Verifica se os contadores, histogramas e gauges do Prometheus funcionam e exportam formato correto."""
    registry = CollectorRegistry(auto_describe=True)
    metricas = MetricasPrometheus(registry=registry)

    metricas.registrar_requisicao_http("POST", "/v1/chat/conclusoes", 200, 0.125)
    metricas.registrar_execucao_llm("modelo-teste", "simulado", 0.450)
    metricas.registrar_tokens("modelo-teste", tokens_entrada=120, tokens_saida=45)
    metricas.registrar_falha_llm("modelo-teste", "timeout")
    metricas.registrar_fallback_llm("modelo-primario", "modelo-secundario")
    metricas.registrar_operacao_persistencia(
        "sqlite", "salvar_mensagem", 0.005, sucesso=True
    )
    metricas.definir_estado_disjuntor("gateway-geracao", 2)

    metricas.registrar_contagem("agente_passo", 1, {"modelo": "modelo-teste"})
    metricas.registrar_contagem("agente_erro", 1, {"modelo": "modelo-teste"})
    metricas.registrar_evento(
        "transicao_disjuntor",
        {"disjuntor": "circuito-teste", "novo_estado": "aberto"},
    )

    saida_bruta = metricas.gerar_exposicao_prometheus().decode("utf-8")

    assert "http_requisicoes_total" in saida_bruta
    assert 'metodo="POST"' in saida_bruta
    assert 'rota="/v1/chat/conclusoes"' in saida_bruta
    assert 'status_codigo="200"' in saida_bruta

    assert "http_requisicao_duracao_segundos_bucket" in saida_bruta
    assert "llm_execucao_duracao_segundos_bucket" in saida_bruta
    assert "llm_tokens_total" in saida_bruta
    assert 'tipo="entrada"' in saida_bruta
    assert 'tipo="saida"' in saida_bruta
    assert "llm_falhas_total" in saida_bruta
    assert "llm_fallbacks_total" in saida_bruta
    assert "persistencia_operacoes_total" in saida_bruta
    assert "agente_passos_total" in saida_bruta
    assert "agente_erros_total" in saida_bruta
    assert "disjuntor_estado" in saida_bruta


def test_endpoint_metricas_sucesso_padrao() -> None:
    """Valida exposição de métricas através do endpoint GET /metrics."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        chave_api_mestre="chave-teste",
        metricas_habilitadas=True,
        metricas_token=None,
    )
    app = criar_aplicacao(configuracoes=config)
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requisicoes_total" in response.text


def test_endpoint_metricas_protegido_por_token() -> None:
    """Verifica autenticação via Bearer token para acesso seguro às métricas Prometheus."""
    config = ConfiguracoesGateway(
        ambiente="producao",
        chave_api_mestre="chave-mestre-valida-com-mais-de-32-caracteres",
        metricas_habilitadas=True,
        metricas_token="token-prometheus-super-secreto",
    )
    app = criar_aplicacao(configuracoes=config)
    client = TestClient(app)

    # 1. Sem token: 401 Unauthorized
    resp_sem_token = client.get("/metrics")
    assert resp_sem_token.status_code == 401

    # 2. Token incorreto: 401 Unauthorized
    resp_token_invalido = client.get(
        "/metrics", headers={"Authorization": "Bearer token-errado"}
    )
    assert resp_token_invalido.status_code == 401

    # 3. Token correto: 200 OK
    resp_autorizada = client.get(
        "/metrics",
        headers={"Authorization": "Bearer token-prometheus-super-secreto"},
    )
    assert resp_autorizada.status_code == 200
    assert "http_requisicoes_total" in resp_autorizada.text


def test_endpoint_metricas_desabilitado() -> None:
    """Verifica que quando metricas_habilitadas=False o endpoint retorna 404."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        chave_api_mestre="chave-teste",
        metricas_habilitadas=False,
    )
    app = criar_aplicacao(configuracoes=config)
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 404


def test_middleware_rastreamento_injeta_cabecalhos_e_traceparent() -> None:
    """Verifica que as requisições recebem X-Request-ID, X-Process-Time e traceparent."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        chave_api_mestre="chave-teste",
        otel_habilitado=True,
    )
    app = criar_aplicacao(configuracoes=config)
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert "X-Process-Time" in response.headers
    assert "traceparent" in response.headers
    assert response.headers["traceparent"].startswith("00-")


def test_gerenciador_rastreamento_sanitizacao_e_seguranca() -> None:
    """Garante que atributos sensíveis (prompts, chaves, senhas) não são salvos nos spans OpenTelemetry."""
    exportador = ExportadorSpansMemoria()
    gerenciador = GerenciadorRastreamento(
        nome_servico="teste-rastreador",
        habilitado=True,
        exportador_customizado=exportador,
    )

    atributos_brutos = {
        "usuario_id": "usr-123",
        "modelo": "modelo-teste",
        "prompt": "Texto secreto que nunca deve ir para o trace",
        "api_key": "sk-1234567890",
        "senha": "senha-super-secreta",
        "quantidade_tokens": 42,
    }

    with gerenciador.iniciar_span("operacao_teste", atributos=atributos_brutos) as span:
        assert span.is_recording()

    spans = exportador.obter_spans_finalizados()
    assert len(spans) == 1
    span_gravado = spans[0]

    assert span_gravado.attributes is not None
    assert span_gravado.attributes.get("usuario_id") == "usr-123"
    assert span_gravado.attributes.get("modelo") == "modelo-teste"
    assert span_gravado.attributes.get("quantidade_tokens") == 42
    # Atributos sensíveis estritamente omitidos
    assert "prompt" not in span_gravado.attributes
    assert "api_key" not in span_gravado.attributes
    assert "senha" not in span_gravado.attributes


@pytest.mark.asyncio
async def test_gerenciador_rastreamento_assincrono_com_erro() -> None:
    """Verifica registro correto de exceções em spans assíncronos."""
    exportador = ExportadorSpansMemoria()
    gerenciador = GerenciadorRastreamento(
        nome_servico="teste-rastreador-assincrono",
        habilitado=True,
        exportador_customizado=exportador,
    )

    with pytest.raises(ValueError, match="Erro simulado para trace"):
        async with gerenciador.iniciar_span_assincrono("span_assincrono"):
            raise ValueError("Erro simulado para trace")

    spans = exportador.obter_spans_finalizados()
    assert len(spans) == 1
    span_gravado = spans[0]
    assert span_gravado.status.status_code.name == "ERROR"
    assert span_gravado.attributes is not None
    assert span_gravado.attributes.get("error.type") == "ValueError"


def test_gerenciador_rastreamento_desabilitado() -> None:
    """Verifica que o gerenciador funciona silenciosamente como no-op quando desabilitado."""
    gerenciador = GerenciadorRastreamento(habilitado=False)
    with gerenciador.iniciar_span("span_invalido") as span:
        assert not span.is_recording()
    trace_id, span_id = gerenciador.obter_trace_e_span_id_atuais()
    assert trace_id is None
    assert span_id is None
    assert gerenciador.obter_traceparent_w3c() is None


def test_formatador_logs_json_correlaciona_trace_e_span() -> None:
    """Verifica se o FormatadorLogJson extrai e correlaciona trace_id e span_id quando disponíveis."""
    formatador = FormatadorLogJson()
    gerenciador = GerenciadorRastreamento(habilitado=True)

    with gerenciador.iniciar_span("span_para_log"):
        registro = logging.LogRecord(
            name="ai_gateway.teste",
            level=logging.INFO,
            pathname="teste.py",
            lineno=10,
            msg="Mensagem contendo chave sk-1234567890abcdef e log estruturado",
            args=(),
            exc_info=None,
        )
        saida_json_str = formatador.format(registro)
        dados = json.loads(saida_json_str)

        assert "timestamp" in dados
        assert dados["nivel"] == "INFO"
        assert dados["logger"] == "ai_gateway.teste"
        # Deve ter injetado trace_id e span_id válidos em hex
        assert "trace_id" in dados
        assert "span_id" in dados
        assert len(dados["trace_id"]) == 32
        assert len(dados["span_id"]) == 16
        # Mascaramento de segredo
        assert "sk-1234567890abcdef" not in dados["mensagem"]
        assert "[CREDENTIAL_REDACTED]" in dados["mensagem"]


@pytest.mark.asyncio
async def test_disjuntor_emite_metricas_transicao_de_estado() -> None:
    """Verifica que transições de estado do Disjuntor atualizam o gauge Prometheus."""
    registry = CollectorRegistry(auto_describe=True)
    metricas = MetricasPrometheus(registry=registry)
    disjuntor = Disjuntor(
        nome="circuito-resiliencia",
        limite_falhas=2,
        tempo_recuperacao_segundos=0.1,
        observabilidade=metricas,
    )

    # Estado inicial: fechado (0)
    saida = metricas.gerar_exposicao_prometheus().decode("utf-8")
    assert 'disjuntor_estado{disjuntor="circuito-resiliencia"} 0.0' in saida

    # Forçar falhas para abrir o circuito
    async def operacao_falha() -> None:
        raise RuntimeError("Falha de rede simulada")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await disjuntor.executar(operacao_falha)

    saida = metricas.gerar_exposicao_prometheus().decode("utf-8")
    # Circuito aberto (2)
    assert 'disjuntor_estado{disjuntor="circuito-resiliencia"} 2.0' in saida


@pytest.mark.asyncio
async def test_politica_fallback_emite_metrica_contingencia() -> None:
    """Verifica que a PoliticaFallback contabiliza ativações de alternativas."""
    registry = CollectorRegistry(auto_describe=True)
    metricas = MetricasPrometheus(registry=registry)
    politica = PoliticaFallback(observabilidade=metricas)

    async def op_primaria() -> str:
        raise RuntimeError("Provedor primário indisponível")

    async def op_secundaria() -> str:
        return "Sucesso via fallback"

    resultado = await politica.executar_com_retaguarda(
        [("modelo-primario", op_primaria), ("modelo-secundario", op_secundaria)]
    )

    assert resultado == "Sucesso via fallback"
    saida = metricas.gerar_exposicao_prometheus().decode("utf-8")
    assert "llm_fallbacks_total" in saida
    assert 'modelo_origem="modelo-primario"' in saida
    assert 'modelo_destino="modelo-secundario"' in saida


@pytest.mark.asyncio
async def test_memoria_sqlite_emite_telemetria() -> None:
    """Verifica se operações de persistência na MemoriaSQLite geram métricas de contagem e latência."""
    registry = CollectorRegistry(auto_describe=True)
    metricas = MetricasPrometheus(registry=registry)
    memoria = MemoriaSQLite(caminho_banco=":memory:", observabilidade=metricas)

    mensagem = Mensagem(papel="usuario", conteudo="Mensagem de teste de telemetria")
    await memoria.salvar_mensagem(
        id_conversa="conv-obs-1", mensagem=mensagem, id_usuario="usr-1"
    )
    historico = await memoria.recuperar_historico(
        id_conversa="conv-obs-1", id_usuario="usr-1"
    )
    assert len(historico) == 1

    saida = metricas.gerar_exposicao_prometheus().decode("utf-8")
    assert "persistencia_operacoes_total" in saida
    assert 'operacao="salvar_mensagem"' in saida
    assert 'operacao="recuperar_historico"' in saida
    assert 'tipo_memoria="sqlite"' in saida
    assert 'sucesso="true"' in saida
    assert "persistencia_duracao_segundos_bucket" in saida


def test_propagacao_w3c_traceparent_remoto() -> None:
    """Verifica se um traceparent recebido na requisição HTTP é herdado e continuado."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        chave_api_mestre="chave-teste",
        otel_habilitado=True,
    )
    app = criar_aplicacao(configuracoes=config)
    client = TestClient(app)

    trace_id_remoto = "4bf92f3577b34da6a3ce929d0e0e4736"
    span_id_remoto = "00f067aa0ba902b7"
    traceparent_origem = f"00-{trace_id_remoto}-{span_id_remoto}-01"

    response = client.get("/health", headers={"traceparent": traceparent_origem})
    assert response.status_code == 200
    assert "traceparent" in response.headers

    traceparent_resposta = response.headers["traceparent"]
    partes = traceparent_resposta.split("-")
    assert len(partes) == 4
    assert partes[0] == "00"
    # O trace_id retornado DEVE ser o mesmo do cliente remoto
    assert partes[1] == trace_id_remoto
    # O span_id retornado é um novo span gerado no gateway (diferente do pai)
    assert partes[2] != span_id_remoto
    assert partes[3] == "01"


def test_coleta_concorrente_metricas_prometheus() -> None:
    """Valida que o registrador de métricas Prometheus é seguro para threads concorrentes."""
    registry = CollectorRegistry(auto_describe=True)
    metricas = MetricasPrometheus(registry=registry)

    def operacao_concorrente(indice: int) -> None:
        for _ in range(50):
            metricas.registrar_requisicao_http("POST", "/v1/chat/conclusoes", 200, 0.05)
            metricas.registrar_tokens("modelo-teste", tokens_entrada=10, tokens_saida=5)
            metricas.registrar_operacao_persistencia("sqlite", "salvar", 0.001, True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        tarefas = [executor.submit(operacao_concorrente, i) for i in range(8)]
        concurrent.futures.wait(tarefas)

    saida = metricas.gerar_exposicao_prometheus().decode("utf-8")
    assert "http_requisicoes_total" in saida
    assert "llm_tokens_total" in saida
    assert "persistencia_operacoes_total" in saida


def test_endpoint_metricas_producao_protecao_automatica_e_validacao() -> None:
    """Confirma proteção do endpoint /metrics em produção mesmo sem token dedicado e rejeição de token fraco."""
    # 1. Em produção, se metricas_token for fraco, rejeita inicialização
    config_token_fraco = ConfiguracoesGateway(
        ambiente="producao",
        chave_api_mestre="prod-super-segredo-de-alta-entropia-123456",
        metricas_token="fraco",
    )
    with pytest.raises(ValueError, match="no mínimo 16 caracteres"):
        config_token_fraco.validar_seguranca_producao()

    # 2. Em produção, sem metricas_token, exige automaticamente a chave_api_mestre
    config_producao = ConfiguracoesGateway(
        ambiente="producao",
        chave_api_mestre="prod-super-segredo-de-alta-entropia-123456",
        metricas_token=None,
    )
    config_producao.validar_seguranca_producao()
    app = criar_aplicacao(configuracoes=config_producao)
    client = TestClient(app)

    # Sem token -> 401
    resp_anonima = client.get("/metrics")
    assert resp_anonima.status_code == 401

    # Com chave mestre -> 200
    resp_autorizada = client.get(
        "/metrics",
        headers={"Authorization": "Bearer prod-super-segredo-de-alta-entropia-123456"},
    )
    assert resp_autorizada.status_code == 200
    assert "http_requisicoes_total" in resp_autorizada.text
