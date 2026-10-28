"""Testes negativos e auditoria de identidade, prevenção de spoofing e isolamento multilocatário."""

import pytest
from ai_core.adaptadores.memoria.memoria_sqlite import MemoriaSQLite
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.aplicacao.casos_de_uso.caso_gerar_resposta import CasoDeUsoGerarResposta
from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.dependencias import obter_caso_gerar_resposta, obter_roteador
from ai_gateway.main import criar_aplicacao_gateway
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def aplicacao_segura():
    """Configura o Gateway com chave mestre de serviço e chaves de clientes regulares vinculadas."""
    config = ConfiguracoesGateway(
        chave_api_mestre="chave-servico-confiavel-m2m",
        mapeamento_chaves_usuarios={
            "chave-joao-123": "usuario_joao",
            "chave-maria-456": "usuario_maria",
        },
    )
    app = criar_aplicacao_gateway(configuracoes=config)

    roteador = RoteadorModelos()
    provedor = AdaptadorSimulado(modelos_suportados=("gpt-4o",))
    roteador.registrar_provedor(provedor)

    memoria = MemoriaSQLite(caminho_banco=":memory:")
    caso_resposta = CasoDeUsoGerarResposta(
        roteador=roteador,
        repositorio_memoria=memoria,
    )

    app.dependency_overrides[obter_roteador] = lambda: roteador
    app.dependency_overrides[obter_caso_gerar_resposta] = lambda: caso_resposta

    return app


@pytest.mark.asyncio
async def test_rejeicao_spoofing_x_user_id_cliente_regular(aplicacao_segura) -> None:
    """Verifica que cliente com chave vinculada é impedido de forjar X-User-ID de outro usuário (Anti-Spoofing)."""
    transporte = ASGITransport(app=aplicacao_segura)

    # João tenta enviar mensagem dizendo que é a 'maria' ou o 'administrador'
    cabecalhos_adulterados = {
        "X-API-Key": "chave-joao-123",
        "X-User-ID": "usuario_maria",  # Tentativa de falsificação
    }

    corpo = {
        "modelo": "gpt-4o",
        "mensagens": [{"papel": "usuario", "conteudo": "Transferir dinheiro da maria"}],
        "id_conversa": "conv-maria-privada",
    }

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.post(
            "/v1/chat/conclusoes", json=corpo, headers=cabecalhos_adulterados
        )
        assert resposta.status_code == 403
        detalhe = resposta.json()["detail"]
        assert "tentativa de personificação detectada" in detalhe.lower()
        assert "usuario_joao" in detalhe


@pytest.mark.asyncio
async def test_servico_confiavel_autorizado_representar_usuario(
    aplicacao_segura,
) -> None:
    """Serviço corporativo M2M com credencial confiável pode atuar legitimamente em nome de um usuário."""
    transporte = ASGITransport(app=aplicacao_segura)

    cabecalhos_m2m = {
        "X-API-Key": "chave-servico-confiavel-m2m",
        "X-User-ID": "cliente_final_atendido",
    }

    corpo = {
        "modelo": "gpt-4o",
        "mensagens": [{"papel": "usuario", "conteudo": "Consulta legítima via BFF"}],
        "id_conversa": "conv-bff-001",
    }

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.post(
            "/v1/chat/conclusoes", json=corpo, headers=cabecalhos_m2m
        )
        assert resposta.status_code == 200
        dados = resposta.json()
        assert len(dados["escolhas"]) == 1


@pytest.mark.asyncio
async def test_credenciais_invalidas_ou_ausentes_retornam_401(aplicacao_segura) -> None:
    """Verifica que requisições com credenciais inválidas ou sem cabeçalhos são barradas com 401."""
    transporte = ASGITransport(app=aplicacao_segura)

    corpo = {
        "modelo": "gpt-4o",
        "mensagens": [{"papel": "usuario", "conteudo": "Teste sem credencial"}],
    }

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        # Sem cabeçalho
        resp_sem_header = await cliente.post("/v1/chat/conclusoes", json=corpo)
        assert resp_sem_header.status_code == 401

        # Chave espúria / não cadastrada
        resp_chave_invalida = await cliente.post(
            "/v1/chat/conclusoes",
            json=corpo,
            headers={"X-API-Key": "chave-falsa-ataque"},
        )
        assert resp_chave_invalida.status_code == 401


@pytest.mark.asyncio
async def test_cliente_regular_com_identidade_legitima_autorizado(
    aplicacao_segura,
) -> None:
    """Cliente regular usando sua chave sem adulteração opera com sucesso."""
    transporte = ASGITransport(app=aplicacao_segura)

    cabecalhos_joao_legitimo = {
        "X-API-Key": "chave-joao-123",
        # Opcionalmente passando o próprio ID ou omitindo
        "X-User-ID": "usuario_joao",
    }

    corpo = {
        "modelo": "gpt-4o",
        "mensagens": [{"papel": "usuario", "conteudo": "Olá, sou o João legítimo"}],
        "id_conversa": "conv-joao-01",
    }

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.post(
            "/v1/chat/conclusoes", json=corpo, headers=cabecalhos_joao_legitimo
        )
        assert resposta.status_code == 200


@pytest.mark.asyncio
async def test_rejeicao_x_user_id_com_caracteres_invalidos_ou_nulos(
    aplicacao_segura,
) -> None:
    """Verifica bloqueio de cabeçalhos X-User-ID maliciosos com caracteres ilegais."""
    transporte = ASGITransport(app=aplicacao_segura)

    cabecalhos_injetados = {
        "X-API-Key": "chave-servico-confiavel-m2m",
        "X-User-ID": "admin\x00malicioso",
    }

    corpo = {
        "modelo": "gpt-4o",
        "mensagens": [{"papel": "usuario", "conteudo": "Tentativa de injeção"}],
    }

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.post(
            "/v1/chat/conclusoes", json=corpo, headers=cabecalhos_injetados
        )
        assert resposta.status_code == 400
        assert "formato inválido" in resposta.json()["detail"].lower()


@pytest.mark.asyncio
async def test_bloqueio_delegacao_m2m_quando_desabilitada() -> None:
    """Valida bloqueio quando a delegação via X-User-ID estiver desativada na instância."""
    config = ConfiguracoesGateway(
        chave_api_mestre="chave-servico-m2m",
        permitir_delegacao_m2m=False,  # Delegação desabilitada
    )
    app = criar_aplicacao_gateway(configuracoes=config)
    transporte = ASGITransport(app=app)

    cabecalhos = {
        "X-API-Key": "chave-servico-m2m",
        "X-User-ID": "cliente_qualquer",
    }

    corpo = {
        "modelo": "gpt-4o",
        "mensagens": [{"papel": "usuario", "conteudo": "Teste"}],
    }

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        resposta = await cliente.post(
            "/v1/chat/conclusoes", json=corpo, headers=cabecalhos
        )
        assert resposta.status_code == 403
        assert "desabilitada" in resposta.json()["detail"].lower()
