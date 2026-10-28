"""Testes automatizados para o roteador de conversas e a aplicação piloto (BFF)."""

import pytest
from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.main import criar_aplicacao
from fastapi.testclient import TestClient


@pytest.fixture
def cliente_teste() -> TestClient:
    """Instancia um TestClient com configuração em memória segura para testes locais."""
    config = ConfiguracoesGateway(
        ambiente="desenvolvimento",
        chave_api_mestre="chave-mestre-teste-12345678",
        tipo_memoria="em_memoria",
        modelo_padrao="modelo-teste",
    )
    app = criar_aplicacao(configuracoes=config)
    return TestClient(app)


def test_obter_historico_conversa_vazia(cliente_teste: TestClient) -> None:
    """Verifica que uma conversa sem mensagens retorna lista vazia e total 0."""
    resposta = cliente_teste.get(
        "/v1/conversas/conv-inexistente",
        headers={"Authorization": "Bearer chave-mestre-teste-12345678"},
    )
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["id_conversa"] == "conv-inexistente"
    assert dados["total_mensagens"] == 0
    assert dados["mensagens"] == []


def test_salvar_e_obter_historico_conversa_autenticada(
    cliente_teste: TestClient,
) -> None:
    """Verifica que mensagens geradas via /v1/chat/conclusoes são gravadas e recuperadas em /v1/conversas."""
    # 1. Enviar mensagem na conversa
    payload_chat = {
        "modelo": "modelo-teste",
        "mensagens": [{"papel": "usuario", "conteudo": "Primeira mensagem de teste"}],
        "id_conversa": "conv-teste-01",
    }
    resp_chat = cliente_teste.post(
        "/v1/chat/conclusoes",
        json=payload_chat,
        headers={"Authorization": "Bearer chave-mestre-teste-12345678"},
    )
    assert resp_chat.status_code == 200

    # 2. Recuperar histórico da conversa
    resp_hist = cliente_teste.get(
        "/v1/conversas/conv-teste-01",
        headers={"Authorization": "Bearer chave-mestre-teste-12345678"},
    )
    assert resp_hist.status_code == 200
    dados_hist = resp_hist.json()
    assert dados_hist["id_conversa"] == "conv-teste-01"
    assert (
        dados_hist["total_mensagens"] == 2
    )  # Mensagem do usuário + resposta do assistente
    assert dados_hist["mensagens"][0]["papel"] == "usuario"
    assert dados_hist["mensagens"][0]["conteudo"] == "Primeira mensagem de teste"
    assert dados_hist["mensagens"][1]["papel"] == "assistente"


def test_conversas_isolamento_multilocatario_rejeita_outro_usuario(
    cliente_teste: TestClient,
) -> None:
    """Garante que um usuário não consegue ler o histórico de conversa pertencente a outro usuário (403 Forbidden)."""
    # Usuário Alfa cria a conversa
    cliente_teste.post(
        "/v1/chat/conclusoes",
        json={
            "modelo": "modelo-teste",
            "mensagens": [{"papel": "usuario", "conteudo": "Segredo do Usuário Alfa"}],
            "id_conversa": "conv-alfa-privada",
        },
        headers={
            "Authorization": "Bearer chave-mestre-teste-12345678",
            "X-User-ID": "usuario_alfa",
        },
    )

    # Usuário Alfa consegue ler com sucesso
    resp_alfa = cliente_teste.get(
        "/v1/conversas/conv-alfa-privada",
        headers={
            "Authorization": "Bearer chave-mestre-teste-12345678",
            "X-User-ID": "usuario_alfa",
        },
    )
    assert resp_alfa.status_code == 200
    assert resp_alfa.json()["total_mensagens"] == 2

    # Usuário Beta tenta ler a conversa do Usuário Alfa -> 403 Forbidden
    resp_beta = cliente_teste.get(
        "/v1/conversas/conv-alfa-privada",
        headers={
            "Authorization": "Bearer chave-mestre-teste-12345678",
            "X-User-ID": "usuario_beta",
        },
    )
    assert resp_beta.status_code == 403
    assert (
        "Acesso negado" in resp_beta.text
        or "pertence a outro usuário" in resp_beta.text
    )


def test_limpar_historico_conversa(cliente_teste: TestClient) -> None:
    """Verifica a limpeza de histórico via DELETE /v1/conversas/{id_conversa}."""
    cliente_teste.post(
        "/v1/chat/conclusoes",
        json={
            "modelo": "modelo-teste",
            "mensagens": [{"papel": "usuario", "conteudo": "Mensagem para limpar"}],
            "id_conversa": "conv-limpar-01",
        },
        headers={"Authorization": "Bearer chave-mestre-teste-12345678"},
    )

    resp_del = cliente_teste.delete(
        "/v1/conversas/conv-limpar-01",
        headers={"Authorization": "Bearer chave-mestre-teste-12345678"},
    )
    assert resp_del.status_code == 200
    assert resp_del.json()["sucesso"] is True

    # Consulta subsequente retorna histórico vazio
    resp_depois = cliente_teste.get(
        "/v1/conversas/conv-limpar-01",
        headers={"Authorization": "Bearer chave-mestre-teste-12345678"},
    )
    assert resp_depois.status_code == 200
    assert resp_depois.json()["total_mensagens"] == 0


def test_interface_piloto_retorna_html(cliente_teste: TestClient) -> None:
    """Verifica se o endpoint GET /piloto entrega a SPA em HTML5 sem erros e emite cookies de sessão e CSRF."""
    resposta = cliente_teste.get("/piloto")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]
    assert "Aplicação Piloto" in resposta.text
    assert "Reusable AI Backend" in resposta.text
    assert "X-Request-ID" in resposta.text
    assert "Métricas Prometheus" in resposta.text
    # Confirma emissão de cookies na visita inicial
    assert "piloto_sessao" in resposta.cookies
    assert "piloto_csrf_token" in resposta.cookies


def test_piloto_api_status(cliente_teste: TestClient) -> None:
    """Verifica se o endpoint BFF GET /piloto/api/status expõe dados operacionais seguros."""
    resposta = cliente_teste.get("/piloto/api/status")
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["status"] == "operacional"
    assert dados["ambiente"] == "desenvolvimento"
    assert dados["modelo_padrao"] == "modelo-teste"


def test_piloto_api_sessao_e_alternancia(cliente_teste: TestClient) -> None:
    """Verifica consulta e alternância de sessão de usuário via BFF sob proteção HMAC e CSRF."""
    # 1. Obter sessão inicial (gera cookie assinado e token CSRF)
    resp_padrao = cliente_teste.get("/piloto/api/sessao")
    assert resp_padrao.status_code == 200
    dados_padrao = resp_padrao.json()
    assert dados_padrao["id_usuario"] == "usuario_alfa"
    csrf_token = dados_padrao["csrf_token"]
    assert csrf_token is not None and len(csrf_token) == 64

    # 2. Alternar para usuario_beta enviando cabeçalho X-CSRF-Token
    resp_alt = cliente_teste.post(
        "/piloto/api/sessao",
        json={"id_usuario": "usuario_beta"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp_alt.status_code == 200
    assert resp_alt.json()["id_usuario"] == "usuario_beta"
    assert "piloto_sessao" in resp_alt.cookies


def test_piloto_api_chat_duas_requisicoes_mesma_conversa_e_historico(
    cliente_teste: TestClient,
) -> None:
    """Demonstra duas requisições consecutivas na mesma conversa e persistência pelo BFF."""
    # Inicializa sessão e obtém token CSRF
    resp_sessao = cliente_teste.get("/piloto/api/sessao")
    csrf_token = resp_sessao.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf_token}

    id_conversa = "conv-piloto-teste-01"

    # 1ª Requisição
    resp1 = cliente_teste.post(
        "/piloto/api/chat",
        json={
            "mensagem": "Primeira pergunta do piloto",
            "id_conversa": id_conversa,
        },
        headers=headers,
    )
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert d1["id_conversa"] == id_conversa
    assert d1["resposta"] != ""
    assert d1["request_id"] != ""
    assert d1["duracao_ms"] > 0
    assert d1["tokens"]["total_tokens"] > 0

    # 2ª Requisição na mesma conversa
    resp2 = cliente_teste.post(
        "/piloto/api/chat",
        json={
            "mensagem": "Segunda pergunta do piloto",
            "id_conversa": id_conversa,
        },
        headers=headers,
    )
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["id_conversa"] == id_conversa
    assert d2["resposta"] != ""

    # Recuperação do histórico via BFF
    resp_hist = cliente_teste.get(f"/piloto/api/conversas/{id_conversa}")
    assert resp_hist.status_code == 200
    hist = resp_hist.json()
    assert hist["id_conversa"] == id_conversa
    # Deve conter 4 mensagens no banco: 2 do usuário e 2 do assistente
    assert hist["total_mensagens"] == 4
    assert hist["mensagens"][0]["conteudo"] == "Primeira pergunta do piloto"
    assert hist["mensagens"][2]["conteudo"] == "Segunda pergunta do piloto"


def test_piloto_api_isolamento_multilocatario_rejeita_outro_usuario(
    cliente_teste: TestClient,
) -> None:
    """Verifica se o BFF protege contra IDOR quando um usuário diferente tenta acessar a conversa."""
    id_conversa = "conv-alfa-secreta"

    # Criar como usuario_alfa (padrão)
    resp_init = cliente_teste.get("/piloto/api/sessao")
    csrf_alfa = resp_init.json()["csrf_token"]

    resp = cliente_teste.post(
        "/piloto/api/chat",
        json={"mensagem": "Dados confidenciais de Alfa", "id_conversa": id_conversa},
        headers={"X-CSRF-Token": csrf_alfa},
    )
    assert resp.status_code == 200

    # Alterna legitimamente para usuario_beta
    resp_alt = cliente_teste.post(
        "/piloto/api/sessao",
        json={"id_usuario": "usuario_beta"},
        headers={"X-CSRF-Token": csrf_alfa},
    )
    assert resp_alt.status_code == 200

    # Usuario_beta tenta ler a conversa confidencial de usuario_alfa -> 403 Forbidden
    resp_beta = cliente_teste.get(f"/piloto/api/conversas/{id_conversa}")
    assert resp_beta.status_code == 403
    assert (
        "Acesso negado" in resp_beta.text
        or "pertence a outro usuário" in resp_beta.text
    )


# ------------------------------------------------------------------------------
# Testes de Segurança Rigorosos: Sessão, Assinatura HMAC, CSRF e Produção
# ------------------------------------------------------------------------------


def test_piloto_rejeita_post_sem_sessao(cliente_teste: TestClient) -> None:
    """Garante que requisições de mutação POST sem sessão ativa são rejeitadas com 401."""
    # Limpa cookies para garantir ausência de sessão
    cliente_teste.cookies.clear()
    resp = cliente_teste.post(
        "/piloto/api/chat",
        json={"mensagem": "Tentativa sem sessão", "id_conversa": "conv-sem-sessao"},
    )
    assert resp.status_code == 401
    assert "Sessão ausente" in resp.json()["detail"]


def test_piloto_rejeita_post_sem_csrf_token(cliente_teste: TestClient) -> None:
    """Garante que mutações com sessão válida mas sem o cabeçalho X-CSRF-Token retornam 403."""
    # Inicializa sessão para ter o cookie HMAC
    cliente_teste.get("/piloto/api/sessao")

    # Envia POST sem cabeçalho X-CSRF-Token
    resp = cliente_teste.post(
        "/piloto/api/chat",
        json={"mensagem": "Tentativa sem CSRF", "id_conversa": "conv-sem-csrf"},
    )
    assert resp.status_code == 403
    assert "Falha de validação CSRF" in resp.json()["detail"]


def test_piloto_rejeita_post_com_csrf_token_invalido(cliente_teste: TestClient) -> None:
    """Garante que um cabeçalho X-CSRF-Token adulterado é rejeitado com 403 Forbidden."""
    cliente_teste.get("/piloto/api/sessao")

    resp = cliente_teste.post(
        "/piloto/api/chat",
        json={
            "mensagem": "Tentativa CSRF adulterado",
            "id_conversa": "conv-csrf-invalido",
        },
        headers={"X-CSRF-Token": "token-forjado-de-ataque-csrf-1234567890abcdef"},
    )
    assert resp.status_code == 403
    assert "Falha de validação CSRF" in resp.json()["detail"]


def test_piloto_rejeita_cookie_sessao_adulterado(cliente_teste: TestClient) -> None:
    """Garante que modificações manuais no cookie de sessão sem HMAC válido são rejeitadas."""
    cliente_teste.get("/piloto/api/sessao")

    # Adulterar cookie para se passar por outro usuário sem assinatura válida
    cliente_teste.cookies.set(
        "piloto_sessao", "usuario_beta.1700000000.assinatura_falsa_12345"
    )

    resp = cliente_teste.post(
        "/piloto/api/chat",
        json={"mensagem": "Tentativa personificação", "id_conversa": "conv-spoof"},
        headers={"X-CSRF-Token": "qualquer_coisa"},
    )
    assert resp.status_code == 401


def test_piloto_rejeita_usuario_fora_da_whitelist(cliente_teste: TestClient) -> None:
    """Garante que a API do piloto não permite definir usuário fora de usuario_alfa/usuario_beta."""
    resp_init = cliente_teste.get("/piloto/api/sessao")
    csrf_token = resp_init.json()["csrf_token"]

    resp = cliente_teste.post(
        "/piloto/api/sessao",
        json={"id_usuario": "usuario_administrador_invasor"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 400
    assert "Identificador de usuário não permitido" in resp.json()["detail"]


def test_piloto_bloqueia_alternancia_em_producao() -> None:
    """Garante que a troca de perfis de demonstração é estritamente proibida em produção (403)."""
    config_prod = ConfiguracoesGateway(
        ambiente="producao",
        chave_api_mestre="prod-super-segredo-de-alta-entropia-123456",
        piloto_habilitado=True,
        piloto_segredo_sessao="segredo-sessao-prod-com-mais-de-16-caracteres",
    )
    app = criar_aplicacao(configuracoes=config_prod)
    cliente = TestClient(app, base_url="https://testserver")

    # Inicializa sessão e obtém CSRF
    resp_sessao = cliente.get("/piloto/api/sessao")
    assert resp_sessao.status_code == 200
    csrf_token = resp_sessao.json()["csrf_token"]

    # Tentativa de alternar perfil em produção -> 403 Forbidden
    resp = cliente.post(
        "/piloto/api/sessao",
        json={"id_usuario": "usuario_beta"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp.status_code == 403
    assert "estritamente desabilitada em ambiente de produção" in resp.json()["detail"]


def test_piloto_desabilitado_em_producao_retorna_404() -> None:
    """Garante política fail-closed: em produção, sem piloto_habilitado=True, rotas respondem 404."""
    config_prod_padrao = ConfiguracoesGateway(
        ambiente="producao",
        chave_api_mestre="prod-super-segredo-de-alta-entropia-123456",
        # piloto_habilitado é None por padrão, portanto piloto_ativo == False
    )
    app = criar_aplicacao(configuracoes=config_prod_padrao)
    cliente = TestClient(app)

    # Rotas do piloto devem responder 404
    resp_ui = cliente.get("/piloto")
    assert resp_ui.status_code == 404
    assert "Aplicação piloto desabilitada" in resp_ui.json()["detail"]

    resp_status = cliente.get("/piloto/api/status")
    assert resp_status.status_code == 404

    resp_sessao = cliente.get("/piloto/api/sessao")
    assert resp_sessao.status_code == 404
