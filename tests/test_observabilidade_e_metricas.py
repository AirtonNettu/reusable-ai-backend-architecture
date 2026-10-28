"""Suíte de testes automatizados para a camada de observabilidade, métricas Prometheus, tracing OpenTelemetry e logs estruturados."""

import concurrent.futures
import json
import logging

import pytest
from ai_core.adaptadores.memoria.memoria_sqlite import MemoriaSQLite
from ai_core.adaptadores.observabilidade.formatador_logs import (
    FormatadorLogJson,
    sanitizar_mensagem_erro,
)
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
from ai_gateway.middlewares.rastreamento import (
    ROTA_NAO_RECONHECIDA,
    MiddlewareRastreamento,
)
from fastapi import FastAPI
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


def test_span_http_sanitiza_query_string_sensivel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica se spans HTTP gerados pelo middleware não registram query string sensível nem tokens."""
    exportador = ExportadorSpansMemoria()
    gerenciador = GerenciadorRastreamento(
        nome_servico="teste-sanitizacao-url",
        habilitado=True,
        exportador_customizado=exportador,
    )
    monkeypatch.setattr(
        "ai_gateway.middlewares.rastreamento.obter_gerenciador_rastreamento",
        lambda: gerenciador,
    )

    app_teste = FastAPI()
    app_teste.add_middleware(MiddlewareRastreamento)

    @app_teste.get("/teste-seguro")
    def rota_teste() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app_teste)
    resposta = client.get(
        "/teste-seguro?token=sk-1234567890abcdef&email=segredo@empresa.com&api_key=AIzaSyA1234"
    )
    assert resposta.status_code == 200

    spans = exportador.obter_spans_finalizados()
    assert len(spans) == 1
    span = spans[0]
    atributos = span.attributes or {}

    # Checar que http.url NÃO possui query string nem os segredos
    url_registrada = str(atributos.get("http.url", ""))
    assert "sk-1234567890abcdef" not in url_registrada
    assert "email=segredo@empresa.com" not in url_registrada
    assert "?" not in url_registrada
    assert url_registrada.endswith("/teste-seguro")

    # Checar atributos semânticos
    assert atributos.get("url.path") == "/teste-seguro"
    assert atributos.get("http.route") == "/teste-seguro"
    assert atributos.get("http.target") == "/teste-seguro"


def test_span_e_logs_sanitizam_excecoes_com_segredos() -> None:
    """Verifica se exceções contendo credenciais são devidamente mascaradas nos spans."""
    exportador = ExportadorSpansMemoria()
    gerenciador = GerenciadorRastreamento(
        nome_servico="teste-sanitizacao-excecao",
        habilitado=True,
        exportador_customizado=exportador,
    )

    segredo_simulado = "sk-1234567890abcdefg"
    mensagem_excecao = f"Falha na comunicação com provedor externo usando chave {segredo_simulado} e Bearer eyJhbGciOi"

    with pytest.raises(RuntimeError), gerenciador.iniciar_span("operacao_sensivel"):
        raise RuntimeError(mensagem_excecao)

    spans = exportador.obter_spans_finalizados()
    assert len(spans) == 1
    span = spans[0]
    assert span.status.status_code.name == "ERROR"

    descricao_status = span.status.description
    assert descricao_status is not None
    assert segredo_simulado not in descricao_status
    assert "[CREDENTIAL_REDACTED]" in descricao_status
    assert "RuntimeError" in descricao_status

    atributos = span.attributes or {}
    assert atributos.get("error.type") == "RuntimeError"
    assert segredo_simulado not in str(atributos.get("error.message", ""))
    assert "[CREDENTIAL_REDACTED]" in str(atributos.get("error.message", ""))


def test_middleware_captura_excecao_e_sanitiza_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Confirma que o middleware sanitiza exceções nos logs e no span sem vazar chaves sensíveis."""
    exportador = ExportadorSpansMemoria()
    gerenciador = GerenciadorRastreamento(
        nome_servico="teste-mw-excecao",
        habilitado=True,
        exportador_customizado=exportador,
    )
    monkeypatch.setattr(
        "ai_gateway.middlewares.rastreamento.obter_gerenciador_rastreamento",
        lambda: gerenciador,
    )

    app = FastAPI()
    app.add_middleware(MiddlewareRastreamento)

    @app.get("/erro-sensivel")
    async def rota_com_falha() -> None:
        raise ValueError(
            "Falha crítica com chave sk-abcdef1234567890 e token=segredo123"
        )

    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        resposta = client.get("/erro-sensivel")

    assert resposta.status_code == 500
    spans = exportador.obter_spans_finalizados()
    assert len(spans) == 1
    span = spans[0]
    assert "sk-abcdef1234567890" not in str(span.status.description)
    assert "[CREDENTIAL_REDACTED]" in str(span.status.description)

    # Checar que o log estruturado emitido pelo middleware não vazou a chave crua
    registros_erro = [r for r in caplog.records if r.name == "ai_gateway.acesso"]
    assert len(registros_erro) >= 1
    ultimo_registro = registros_erro[-1]
    assert "sk-abcdef1234567890" not in str(getattr(ultimo_registro, "erro", ""))
    assert "[CREDENTIAL_REDACTED]" in str(getattr(ultimo_registro, "erro", ""))


def test_rotas_desconhecidas_usam_categoria_fixa_baixa_cardinalidade() -> None:
    """Confirma que rotas 404 dinâmicas utilizam ROTA_NAO_RECONHECIDA para prevenir alta cardinalidade."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        chave_api_mestre="chave-teste",
        metricas_habilitadas=True,
    )
    app = criar_aplicacao(configuracoes=config)
    client = TestClient(app)

    # Requisições para caminhos não mapeados com identificadores dinâmicos
    client.get("/caminho-dinamico-12345/detalhe")
    client.get("/outro-caminho-aleatorio-98765")

    resp_metrics = client.get("/metrics")
    assert resp_metrics.status_code == 200
    texto = resp_metrics.text

    assert f'rota="{ROTA_NAO_RECONHECIDA}"' in texto
    assert "caminho-dinamico-12345" not in texto
    assert "outro-caminho-aleatorio-98765" not in texto


def test_exportador_spans_memoria_limite_e_concorrencia() -> None:
    """Verifica retenção delimitada (deque com capacidade máxima) e concorrência thread-safe."""
    from unittest.mock import MagicMock

    from opentelemetry.sdk.trace import ReadableSpan

    capacidade = 10
    exportador = ExportadorSpansMemoria(capacidade_maxima=capacidade)

    def exportar_lote(thread_id: int) -> None:
        for i in range(25):
            span_mock = MagicMock(spec=ReadableSpan)
            span_mock.name = f"span-{thread_id}-{i}"
            exportador.export([span_mock])

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        tarefas = [executor.submit(exportar_lote, t) for t in range(6)]
        concurrent.futures.wait(tarefas)

    # O buffer nunca deve ultrapassar a capacidade limite
    assert exportador.quantidade_spans() == capacidade
    spans_retidos = exportador.obter_spans_finalizados()
    assert len(spans_retidos) == capacidade

    # Testar limpeza
    exportador.limpar()
    assert exportador.quantidade_spans() == 0
    assert len(exportador.obter_spans_finalizados()) == 0


def test_propagacao_w3c_preserva_flags_do_span() -> None:
    """Verifica se obter_traceparent_w3c injeta e preserva as flags corretas do contexto W3C."""
    gerenciador = GerenciadorRastreamento(
        nome_servico="teste-w3c-flags",
        habilitado=True,
    )

    with gerenciador.iniciar_span("span_ativo"):
        tp = gerenciador.obter_traceparent_w3c()
        assert tp is not None
        partes = tp.split("-")
        assert len(partes) == 4
        assert partes[0] == "00"
        assert len(partes[1]) == 32
        assert len(partes[2]) == 16
        # Como o span padrão está sendo gravado (sampled), a flag deve conter o bit de amostragem
        assert int(partes[3], 16) & 0x01 == 1


def test_propagacao_w3c_traceparent_remoto_com_flags_00() -> None:
    """Verifica herança de traceparent remoto com flag 00 (não amostrado)."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        chave_api_mestre="chave-teste",
        otel_habilitado=True,
    )
    app = criar_aplicacao(configuracoes=config)
    client = TestClient(app)

    trace_id_remoto = "4bf92f3577b34da6a3ce929d0e0e4736"
    span_id_remoto = "00f067aa0ba902b7"
    traceparent_origem = f"00-{trace_id_remoto}-{span_id_remoto}-00"

    response = client.get("/health", headers={"traceparent": traceparent_origem})
    assert response.status_code == 200
    assert "traceparent" in response.headers

    traceparent_resposta = response.headers["traceparent"]
    partes = traceparent_resposta.split("-")
    assert len(partes) == 4
    assert partes[0] == "00"
    assert partes[1] == trace_id_remoto
    assert partes[2] != span_id_remoto


def test_sanitizar_mensagem_erro_regras_e_truncamento() -> None:
    """Testa unitariamente a função de sanitização com credenciais e limites."""
    # 1. Chaves OpenAI / Anthropic / Google
    msg_1 = (
        "Erro ao autenticar com sk-ant-api03-abcdef1234567890 e AIzaSyD3xYz987654321"
    )
    sanitizado_1 = sanitizar_mensagem_erro(msg_1)
    assert "sk-ant-api03-abcdef1234567890" not in sanitizado_1
    assert "AIzaSyD3xYz987654321" not in sanitizado_1
    assert "[CREDENTIAL_REDACTED]" in sanitizado_1

    # 2. Bearer tokens e URLs com query string
    msg_2 = "Falha em http://provedor.interno/v1?token=supersecret123&api_key=privado456 com Bearer tok_xyz"
    sanitizado_2 = sanitizar_mensagem_erro(msg_2)
    assert "supersecret123" not in sanitizado_2
    assert "privado456" not in sanitizado_2
    assert "tok_xyz" not in sanitizado_2

    # 3. Truncamento
    msg_longa = "A" * 1000
    sanitizado_3 = sanitizar_mensagem_erro(msg_longa, tamanho_maximo=200)
    assert len(sanitizado_3) <= 220
    assert "[TRUNCADO]" in sanitizado_3

    # 4. Mensagem sem segredos permanece intacta
    msg_limpa = "Erro de conexão timeout após 5.0 segundos"
    assert sanitizar_mensagem_erro(msg_limpa) == msg_limpa
