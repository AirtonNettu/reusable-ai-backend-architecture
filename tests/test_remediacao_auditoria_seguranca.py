"""Testes automatizados específicos para validação das remediações da auditoria de segurança (SEC-001 a SEC-007)."""

import pytest
from ai_core.adaptadores.ferramentas.registro import RegistroFerramentas
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.aplicacao.agentes.orquestrador import OrquestradorAgente
from ai_core.aplicacao.casos_de_uso.caso_gerar_fluxo import CasoDeUsoGerarRespostaFluxo
from ai_core.dominio.modelos.agente import ConfiguracaoAgente
from ai_core.dominio.modelos.geracao import RequisicaoGeracao
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.resiliencia.orcamento import (
    ErroLimiteOrcamentoTokens,
    PoliticaOrcamentoTokens,
)
from ai_gateway.configuracoes import (
    ConfiguracoesGateway,
    eh_credencial_insegura_producao,
)
from ai_gateway.main import criar_aplicacao
from ai_gateway.rotas.piloto import (
    HTML_PAGINA_PILOTO,
    JAVASCRIPT_SPA_PILOTO,
    obter_segredo_piloto,
)
from fastapi.testclient import TestClient

# ==============================================================================
# SEC-001: Validação de Credenciais Inseguras e Padrão em Produção
# ==============================================================================


def test_sec001_eh_credencial_insegura_detecta_chaves_padrao_e_prefixos() -> None:
    """Garante que a função detecte chaves padrão do docker-compose e prefixos inseguros."""
    assert eh_credencial_insegura_producao("dev-local-master-key-12345678") is True
    assert eh_credencial_insegura_producao("dev-service-m2m-key-12345678") is True
    assert (
        eh_credencial_insegura_producao("dev-qualquer-chave-longa-com-mais-de-16")
        is True
    )
    assert (
        eh_credencial_insegura_producao("teste-chave-longa-suficiente-123456") is True
    )
    assert eh_credencial_insegura_producao("chave-curta") is True
    assert eh_credencial_insegura_producao(None) is True

    # Chave segura de produção
    assert eh_credencial_insegura_producao("sk_prod_998877665544332211aabbcc") is False


def test_sec001_producao_rejeita_chaves_padrao_docker_compose_fail_closed() -> None:
    """Garante que instanciar o Gateway em produção com chaves do docker-compose levante ValueError."""
    with pytest.raises(ValueError, match="Configuração insegura"):
        ConfiguracoesGateway(
            ambiente="producao",
            chave_api_mestre="dev-local-master-key-12345678",
        ).validar_seguranca_producao()

    with pytest.raises(ValueError, match="Configuração insegura"):
        ConfiguracoesGateway(
            ambiente="producao",
            chave_api_mestre="sk_prod_valida_com_mais_de_16_caracteres_ok",
            chaves_servicos_confiaveis=("dev-service-m2m-key-12345678",),
        ).validar_seguranca_producao()


# ==============================================================================
# SEC-002: Mitigação de DOM XSS na Interface Web do Piloto
# ==============================================================================


def test_sec002_interface_piloto_aplica_escape_html_no_dom() -> None:
    """Garante que a SPA do piloto utilize escapeHtml() na interpolação do DOM em innerHTML."""
    assert "${escapeHtml(idConversaAtual)}" in JAVASCRIPT_SPA_PILOTO
    assert "${escapeHtml(usuarioAtual)}" in JAVASCRIPT_SPA_PILOTO
    assert "${escapeHtml(autor)}" in JAVASCRIPT_SPA_PILOTO

    # Garante que não há concatenações cruas de idConversaAtual em tags b
    assert "<b>${idConversaAtual}</b>" not in JAVASCRIPT_SPA_PILOTO
    assert '<script src="/piloto/app.js"></script>' in HTML_PAGINA_PILOTO


# ==============================================================================
# SEC-003: Isolamento Multilocatário e Orçamento no Runtime de Agentes
# ==============================================================================


@pytest.mark.asyncio
async def test_sec003_orquestrador_agente_aplica_orcamento_tokens() -> None:
    """Garante que o orquestrador submeta as chamadas à PoliticaOrcamentoTokens e bloqueie excessos."""
    roteador = RoteadorModelos()
    adaptador = AdaptadorSimulado(nome_provedor="simulado", atraso_segundos=0.0)
    roteador.registrar_provedor(adaptador)

    orcamento = PoliticaOrcamentoTokens(
        limite_tokens_por_requisicao=500,
        limite_tokens_total_sessao=1000,
    )

    registro = RegistroFerramentas()
    orquestrador = OrquestradorAgente(
        roteador=roteador,
        executor_ferramentas=registro,
        modelo_padrao="modelo-teste",
        politica_orcamento=orcamento,
    )

    config_agente = ConfiguracaoAgente(
        nome="agente-seguro",
        instrucao_sistema="Instrução do sistema de teste",
        limite_passos=3,
    )

    # Execução dentro do orçamento deve ter sucesso
    resultado = await orquestrador.executar(
        objetivo="Objetivo simples",
        configuracao=config_agente,
        id_usuario="usuario_teste",
    )
    assert resultado.sucesso is True

    # Orçamento estourado deve levantar ErroLimiteOrcamentoTokens
    orcamento_esgotado = PoliticaOrcamentoTokens(
        limite_tokens_por_requisicao=100,  # abaixo da estimativa mínima (256+)
    )
    orquestrador_bloqueado = OrquestradorAgente(
        roteador=roteador,
        executor_ferramentas=registro,
        modelo_padrao="modelo-teste",
        politica_orcamento=orcamento_esgotado,
    )

    with pytest.raises(ErroLimiteOrcamentoTokens):
        await orquestrador_bloqueado.executar(
            objetivo="Objetivo que ultrapassa o limite configurado de tokens",
            configuracao=config_agente,
            id_usuario="usuario_teste",
        )


# ==============================================================================
# SEC-004: Segredo Exclusivo para Sessões do Piloto
# ==============================================================================


def test_sec004_piloto_em_producao_exige_segredo_exclusivo() -> None:
    """Garante que ativar o piloto em produção sem segredo dedicado resulte em erro fail-closed."""
    with pytest.raises(ValueError, match="GATEWAY_PILOTO_SEGREDO_SESSAO"):
        ConfiguracoesGateway(
            ambiente="producao",
            chave_api_mestre="sk_prod_valida_com_mais_de_16_caracteres_ok",
            piloto_habilitado=True,
            piloto_segredo_sessao=None,
        ).validar_seguranca_producao()


def test_sec004_obter_segredo_piloto_nao_reutiliza_chave_mestre() -> None:
    """Garante que a função obter_segredo_piloto nunca retorne a chave mestra como fallback."""
    config_dev = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        chave_api_mestre="chave-mestre-administrativa-gateway",
        piloto_segredo_sessao=None,
    )
    segredo_obtido = obter_segredo_piloto(config_dev)
    assert segredo_obtido != "chave-mestre-administrativa-gateway"
    assert segredo_obtido == "segredo-sessao-piloto-desenvolvimento-local-32chars"


# ==============================================================================
# SEC-005: Cabeçalhos HTTP Defensivos (OWASP)
# ==============================================================================


def test_sec005_cabecalhos_http_defensivos_presentes() -> None:
    """Verifica se as respostas HTTP possuem os cabeçalhos de proteção de borda."""
    config = ConfiguracoesGateway(ambiente="desenvolvimento")
    app = criar_aplicacao(configuracoes=config)
    cliente = TestClient(app)

    # Rota de API comum
    resp_health = cliente.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp_health.headers.get("X-Frame-Options") == "DENY"
    assert (
        resp_health.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    )

    # Rota SPA do Piloto
    resp_piloto = cliente.get("/piloto")
    assert resp_piloto.status_code == 200
    assert "Content-Security-Policy" in resp_piloto.headers
    assert "frame-ancestors 'none'" in resp_piloto.headers["Content-Security-Policy"]


# ==============================================================================
# SEC-006: Controle Orçamentário no Streaming (SSE)
# ==============================================================================


@pytest.mark.asyncio
async def test_sec006_streaming_reserva_e_consome_tokens_no_orcamento() -> None:
    """Garante que o caso de uso de streaming reserve e debite tokens na PoliticaOrcamentoTokens."""
    roteador = RoteadorModelos()
    adaptador = AdaptadorSimulado(nome_provedor="simulado", atraso_segundos=0.0)
    roteador.registrar_provedor(adaptador)

    orcamento = PoliticaOrcamentoTokens(
        limite_tokens_por_requisicao=1000,
        limite_tokens_por_usuario=270,  # permite 1ª requisição (reserva 261), mas bloqueia a 2ª
    )

    caso_fluxo = CasoDeUsoGerarRespostaFluxo(
        roteador=roteador,
        politica_orcamento=orcamento,
    )

    req = RequisicaoGeracao(
        modelo="modelo-teste",
        mensagens=(Mensagem(papel="usuario", conteudo="Oi"),),
    )

    # Primeira requisição dentro do limite
    pedacos = [p async for p in caso_fluxo.executar(req, id_usuario="usr_stream")]
    assert len(pedacos) > 0

    # Segunda requisição estourando o saldo do usuário
    with pytest.raises(ErroLimiteOrcamentoTokens):
        _ = [p async for p in caso_fluxo.executar(req, id_usuario="usr_stream")]


# ==============================================================================
# SEC-007: Higiene de Contêiner e Supply Chain
# ==============================================================================


def test_sec007_dockerignore_ignora_artefatos_de_auditoria() -> None:
    """Garante que .agents/ e skills-lock.json estejam devidamente isolados no .dockerignore."""
    with open(".dockerignore", encoding="utf-8") as f:
        conteudo = f.read()

    assert ".agents/" in conteudo
    assert "skills-lock.json" in conteudo


# ==============================================================================
# SEC-008: Proteção Estrita e Fail-Closed do Endpoint de Métricas Prometheus
# ==============================================================================


def test_sec008_metricas_producao_sem_token_retorna_403_fail_closed() -> None:
    """Garante que em produção sem chave mestra e sem token de métricas, /metrics retorne 403 Forbidden."""
    config = ConfiguracoesGateway(
        ambiente="producao",
        chave_api_mestre=None,
        mapeamento_chaves_usuarios={"sk_prod_usuario_valida_16caracteres": "usuario_1"},
        metricas_habilitadas=True,
        metricas_token=None,
    )
    app = criar_aplicacao(configuracoes=config)
    cliente = TestClient(app)

    resposta = cliente.get("/metrics")
    assert resposta.status_code == 403
    assert "Acesso negado" in resposta.json()["detail"]


def test_sec008_metricas_producao_com_token_valido_retorna_200() -> None:
    """Garante que em produção com token de métricas configurado, o scraper autenticado receba 200 OK."""
    config = ConfiguracoesGateway(
        ambiente="producao",
        chave_api_mestre="sk_prod_mestre_valida_16caracteres",
        metricas_habilitadas=True,
        metricas_token="token_metricas_super_seguro_16chars",
    )
    app = criar_aplicacao(configuracoes=config)
    cliente = TestClient(app)

    # 1. Bearer token válido
    resp_bearer = cliente.get(
        "/metrics",
        headers={"Authorization": "Bearer token_metricas_super_seguro_16chars"},
    )
    assert resp_bearer.status_code == 200
    assert "http_requisicoes_total" in resp_bearer.text

    # 2. X-API-Key válida
    resp_apikey = cliente.get(
        "/metrics",
        headers={"X-API-Key": "token_metricas_super_seguro_16chars"},
    )
    assert resp_apikey.status_code == 200


def test_sec008_metricas_producao_token_invalido_retorna_401() -> None:
    """Garante que token incorreto em produção receba 401 Unauthorized com cabeçalho WWW-Authenticate."""
    config = ConfiguracoesGateway(
        ambiente="producao",
        chave_api_mestre="sk_prod_mestre_valida_16caracteres",
        metricas_habilitadas=True,
        metricas_token="token_metricas_super_seguro_16chars",
    )
    app = criar_aplicacao(configuracoes=config)
    cliente = TestClient(app)

    resp_sem_token = cliente.get("/metrics")
    assert resp_sem_token.status_code == 401

    resp_token_errado = cliente.get(
        "/metrics", headers={"Authorization": "Bearer token_incorreto"}
    )
    assert resp_token_errado.status_code == 401
    assert "WWW-Authenticate" in resp_token_errado.headers


def test_sec008_metricas_desabilitadas_retornam_404() -> None:
    """Garante que com metricas_habilitadas=False a rota retorne 404 Not Found."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        metricas_habilitadas=False,
    )
    app = criar_aplicacao(configuracoes=config)
    cliente = TestClient(app)

    assert cliente.get("/metrics").status_code == 404


def test_sec008_metricas_desenvolvimento_local_sem_token_retorna_200() -> None:
    """Garante que em ambiente de desenvolvimento local sem token configurado o acesso seja livre."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        metricas_habilitadas=True,
        metricas_token=None,
    )
    app = criar_aplicacao(configuracoes=config)
    cliente = TestClient(app)

    resposta = cliente.get("/metrics")
    assert resposta.status_code == 200
    assert "http_requisicoes_total" in resposta.text


# ==============================================================================
# SEC-009: Content-Security-Policy (CSP) Defensiva e Eliminação de unsafe-inline
# ==============================================================================


def test_sec009_csp_elimina_unsafe_inline_em_scripts() -> None:
    """Garante que a CSP emitida para /piloto não contenha 'unsafe-inline' na diretiva script-src."""
    config = ConfiguracoesGateway(ambiente="desenvolvimento")
    app = criar_aplicacao(configuracoes=config)
    cliente = TestClient(app)

    resposta = cliente.get("/piloto")
    assert resposta.status_code == 200
    csp = resposta.headers.get("Content-Security-Policy", "")
    assert "script-src 'self'" in csp
    assert "script-src 'self' 'unsafe-inline'" not in csp


def test_sec009_endpoint_script_estatico_piloto_retorna_javascript() -> None:
    """Verifica que o script externo /piloto/app.js seja entregue com tipo MIME correto e cache."""
    config = ConfiguracoesGateway(ambiente="desenvolvimento")
    app = criar_aplicacao(configuracoes=config)
    cliente = TestClient(app)

    resposta = cliente.get("/piloto/app.js")
    assert resposta.status_code == 200
    assert "application/javascript" in resposta.headers["content-type"]
    assert "function escapeHtml" in resposta.text
    assert "addEventListener" in resposta.text


def test_sec009_html_piloto_sem_atributos_inline_de_eventos() -> None:
    """Garante ausência de onclick, onkeydown e onchange inline no HTML da SPA do piloto."""
    assert "onclick=" not in HTML_PAGINA_PILOTO
    assert "onkeydown=" not in HTML_PAGINA_PILOTO
    assert "onchange=" not in HTML_PAGINA_PILOTO
