"""Testes de integração para os endpoints e middlewares do AI Gateway."""

from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.main import criar_aplicacao
from fastapi.testclient import TestClient


def test_endpoint_saude() -> None:
    """Verifica se o endpoint /health responde com sucesso."""
    app = criar_aplicacao()
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response.headers
    assert "X-Process-Time" in response.headers


def test_endpoint_listar_modelos() -> None:
    """Verifica listagem de modelos disponíveis no catálogo."""
    app = criar_aplicacao()
    client = TestClient(app)

    response = client.get("/v1/modelos")
    assert response.status_code == 200
    dados = response.json().get("dados", [])
    assert len(dados) >= 2
    nomes = [m["identificador"] for m in dados]
    assert "modelo-teste" in nomes


def test_endpoint_chat_conclusao_sincrona() -> None:
    """Verifica geração síncrona através de POST /v1/chat/conclusoes."""
    app = criar_aplicacao()
    client = TestClient(app)

    corpo = {
        "modelo": "modelo-teste",
        "mensagens": [{"papel": "usuario", "conteudo": "Olá, tudo bem?"}],
        "stream": False,
    }

    response = client.post("/v1/chat/conclusoes", json=corpo)
    assert response.status_code == 200
    dados = response.json()
    assert "identificador" in dados
    assert len(dados["escolhas"]) == 1
    assert (
        "Reusable AI Backend Architecture"
        in dados["escolhas"][0]["mensagem"]["conteudo"]
    )
    assert dados["uso"]["total_tokens"] > 0


def test_endpoint_chat_conclusao_streaming() -> None:
    """Verifica geração em fluxo contínuo via SSE (stream=True)."""
    app = criar_aplicacao()
    client = TestClient(app)

    corpo = {
        "modelo": "modelo-teste",
        "mensagens": [{"papel": "usuario", "conteudo": "Olá!"}],
        "stream": True,
    }

    response = client.post("/v1/chat/conclusoes", json=corpo)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    conteudo = response.text
    assert "data: " in conteudo
    assert "[DONE]" in conteudo


def test_endpoint_execucao_agente() -> None:
    """Verifica chamada ao runtime de agente através de /v1/agentes/executar."""
    app = criar_aplicacao()
    client = TestClient(app)

    corpo = {
        "objetivo": "Calcular 10 + 20",
        "nome_agente": "agente-teste",
        "instrucao_sistema": "Você é um assistente prestativo.",
        "limite_passos": 3,
    }

    response = client.post("/v1/agentes/executar", json=corpo)
    assert response.status_code == 200
    dados = response.json()
    assert dados["sucesso"] is True
    assert "resposta_final" in dados
    assert len(dados["passos"]) >= 1


def test_autenticacao_api_key() -> None:
    """Verifica exigência e validação da chave de API quando configurada."""
    config = ConfiguracoesGateway(chave_api_mestre="chave-secreta-123")
    app = criar_aplicacao(configuracoes=config)
    client = TestClient(app)

    # 1. Sem cabeçalho: 401
    resp_sem_chave = client.get("/v1/modelos")
    assert resp_sem_chave.status_code == 401

    # 2. Com chave incorreta: 401
    resp_chave_errada = client.get("/v1/modelos", headers={"X-API-Key": "chave-errada"})
    assert resp_chave_errada.status_code == 401

    # 3. Com chave correta via X-API-Key: 200
    resp_sucesso_x = client.get(
        "/v1/modelos", headers={"X-API-Key": "chave-secreta-123"}
    )
    assert resp_sucesso_x.status_code == 200

    # 4. Com chave correta via Bearer Token: 200
    resp_sucesso_bearer = client.get(
        "/v1/modelos", headers={"Authorization": "Bearer chave-secreta-123"}
    )
    assert resp_sucesso_bearer.status_code == 200


def test_tratamento_erro_modelo_nao_encontrado() -> None:
    """Verifica mapeamento de ErroModeloNaoSuportado para status HTTP 404."""
    app = criar_aplicacao()
    client = TestClient(app)

    corpo = {
        "modelo": "modelo-fantasma-inexistente",
        "mensagens": [{"papel": "usuario", "conteudo": "Olá"}],
    }

    response = client.post("/v1/chat/conclusoes", json=corpo)
    assert response.status_code == 404
    dados = response.json()
    assert dados["codigo_status"] == 404
    assert "ErroModeloNaoSuportado" in dados["tipo"]


def test_endpoint_chat_estruturado() -> None:
    """Verifica geração e validação de saída estruturada via POST /v1/chat/estruturado."""
    from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
    from ai_gateway.dependencias import obter_roteador

    app = criar_aplicacao()
    # Injeta provedor que retorna JSON válido
    roteador = obter_roteador()
    provedor_json = AdaptadorSimulado(
        modelos_suportados=("modelo-json-teste",),
        resposta_padrao='{"codigo": 200, "status": "operacional"}',
    )
    roteador.registrar_provedor(provedor_json)

    client = TestClient(app)
    corpo = {
        "modelo": "modelo-json-teste",
        "mensagens": [{"papel": "usuario", "conteudo": "Status do sistema"}],
        "esquema_json": {
            "type": "object",
            "properties": {
                "codigo": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": ["codigo", "status"],
        },
        "max_tentativas": 2,
    }

    response = client.post("/v1/chat/estruturado", json=corpo)
    assert response.status_code == 200
    dados = response.json()
    assert dados["sucesso"] is True
    assert dados["dados"]["codigo"] == 200
    assert dados["dados"]["status"] == "operacional"
