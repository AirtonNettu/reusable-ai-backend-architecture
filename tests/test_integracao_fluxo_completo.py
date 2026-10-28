"""Testes de integração ponta a ponta cobrindo Gateway, Casos de Uso, Roteamento, SQLite e Concorrência."""

import asyncio
from typing import Any

import pytest
from ai_core.adaptadores.memoria.gerenciador_contexto import GerenciadorContexto
from ai_core.adaptadores.memoria.memoria_sqlite import MemoriaSQLite
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.aplicacao.casos_de_uso.caso_gerar_fluxo import CasoDeUsoGerarRespostaFluxo
from ai_core.aplicacao.casos_de_uso.caso_gerar_resposta import CasoDeUsoGerarResposta
from ai_core.aplicacao.casos_de_uso.caso_gerar_saida_estruturada import (
    CasoDeUsoGerarSaidaEstruturada,
)
from ai_core.dominio.excecoes import ErroConexaoProvedor
from ai_core.dominio.modelos.geracao import (
    RequisicaoGeracao,
    RespostaGeracao,
    UsoTokens,
)
from ai_gateway.configuracoes import ConfiguracoesGateway
from ai_gateway.dependencias import (
    obter_caso_gerar_fluxo,
    obter_caso_gerar_resposta,
    obter_caso_gerar_saida_estruturada,
    obter_roteador,
)
from ai_gateway.main import criar_aplicacao_gateway
from httpx import ASGITransport, AsyncClient


class ProvedorFlutuante(AdaptadorSimulado):
    """Provedor para teste de resiliência que falha para um modelo e funciona no fallback."""

    def __init__(self, modelo_falho: str, modelo_fallback: str) -> None:
        super().__init__(modelos_suportados=(modelo_falho, modelo_fallback))
        self._modelo_falho = modelo_falho
        self._modelo_fallback = modelo_fallback

    async def gerar(
        self, requisicao: RequisicaoGeracao, timeout_segundos: float = 30.0
    ) -> RespostaGeracao:
        if requisicao.modelo == self._modelo_falho:
            raise ErroConexaoProvedor(
                f"Serviço primário '{self._modelo_falho}' temporariamente indisponível.",
                provedor="flutuante",
            )
        return RespostaGeracao(
            texto=f"Resposta gerada via contingência pelo modelo {requisicao.modelo}",
            modelo=requisicao.modelo,
            motivo_finalizacao="stop",
            uso=UsoTokens(tokens_entrada=10, tokens_saida=15, total_tokens=25),
        )


@pytest.fixture
def ambiente_integrado() -> dict[str, Any]:
    """Prepara a malha integrada com persistência SQLite em memória e adaptadores."""
    memoria = MemoriaSQLite(caminho_banco=":memory:")
    roteador = RoteadorModelos()

    provedor_padrao = AdaptadorSimulado(modelos_suportados=("gpt-4o", "gemini-1.5-pro"))
    roteador.registrar_provedor(provedor_padrao)

    gerenciador = GerenciadorContexto(limite_maximo_tokens_padrao=2048)
    caso_resposta = CasoDeUsoGerarResposta(
        roteador=roteador,
        repositorio_memoria=memoria,
        gerenciador_contexto=gerenciador,
    )
    caso_fluxo = CasoDeUsoGerarRespostaFluxo(
        roteador=roteador,
        repositorio_memoria=memoria,
        gerenciador_contexto=gerenciador,
    )
    caso_estruturado = CasoDeUsoGerarSaidaEstruturada(roteador=roteador)

    configuracoes = ConfiguracoesGateway(chave_api_mestre="chave-secreta-integracao")
    app = criar_aplicacao_gateway(configuracoes=configuracoes)

    # Injeta dependências reais de integração
    app.dependency_overrides[obter_roteador] = lambda: roteador
    app.dependency_overrides[obter_caso_gerar_resposta] = lambda: caso_resposta
    app.dependency_overrides[obter_caso_gerar_fluxo] = lambda: caso_fluxo
    app.dependency_overrides[obter_caso_gerar_saida_estruturada] = lambda: (
        caso_estruturado
    )

    return {
        "app": app,
        "memoria": memoria,
        "roteador": roteador,
        "caso_resposta": caso_resposta,
    }


@pytest.mark.asyncio
async def test_fluxo_completo_conclusao_chat_e_persistencia_sqlite(
    ambiente_integrado: dict[str, Any],
) -> None:
    """Verifica requisição completa via Gateway persistindo no SQLite e recuperando contexto."""
    app = ambiente_integrado["app"]
    memoria: MemoriaSQLite = ambiente_integrado["memoria"]

    cabecalhos = {
        "X-API-Key": "chave-secreta-integracao",
        "X-User-ID": "usuario_financeiro",
    }
    transporte = ASGITransport(app=app)

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        # 1. Primeira mensagem do usuário na conversa conv-001
        corpo_1 = {
            "modelo": "gpt-4o",
            "mensagens": [{"papel": "usuario", "conteudo": "Olá, qual meu saldo?"}],
            "id_conversa": "conv-001",
        }
        resp_1 = await cliente.post(
            "/v1/chat/conclusoes", json=corpo_1, headers=cabecalhos
        )
        assert resp_1.status_code == 200
        dados_1 = resp_1.json()
        assert dados_1["modelo"] == "gpt-4o"
        assert len(dados_1["escolhas"]) == 1

        # 2. Verifica se a memória SQLite gravou a mensagem do usuário e a resposta do assistente
        historico = await memoria.recuperar_historico(
            "conv-001", id_usuario="usuario_financeiro"
        )
        assert len(historico) == 2
        assert historico[0].papel == "usuario"
        assert historico[0].conteudo == "Olá, qual meu saldo?"
        assert historico[1].papel == "assistente"

        # 3. Segunda mensagem na mesma conversa mantendo contexto
        corpo_2 = {
            "modelo": "gpt-4o",
            "mensagens": [
                {"papel": "usuario", "conteudo": "E quanto posso transferir hoje?"}
            ],
            "id_conversa": "conv-001",
        }
        resp_2 = await cliente.post(
            "/v1/chat/conclusoes", json=corpo_2, headers=cabecalhos
        )
        assert resp_2.status_code == 200

        # Histórico deve agora conter 4 mensagens
        historico_atualizado = await memoria.recuperar_historico(
            "conv-001", id_usuario="usuario_financeiro"
        )
        assert len(historico_atualizado) == 4


@pytest.mark.asyncio
async def test_isolamento_multilocatario_retorna_403_em_acesso_cruzado(
    ambiente_integrado: dict[str, Any],
) -> None:
    """Verifica que o Gateway bloqueia e retorna HTTP 403 quando outro usuário tenta acessar conversa alheia."""
    app = ambiente_integrado["app"]
    transporte = ASGITransport(app=app)

    cabecalhos_usuario_legitimo = {
        "X-API-Key": "chave-secreta-integracao",
        "X-User-ID": "cliente_legitimo_1",
    }
    cabecalhos_invasor = {
        "X-API-Key": "chave-secreta-integracao",
        "X-User-ID": "cliente_intruso_2",
    }

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        # Usuário legítimo cria conversa privada
        corpo_inicial = {
            "modelo": "gpt-4o",
            "mensagens": [
                {"papel": "usuario", "conteudo": "Dados confidenciais da minha conta"}
            ],
            "id_conversa": "conversa-privada-999",
        }
        resp_ok = await cliente.post(
            "/v1/chat/conclusoes",
            json=corpo_inicial,
            headers=cabecalhos_usuario_legitimo,
        )
        assert resp_ok.status_code == 200

        # Usuário invasor tenta enviar mensagem ou interagir com a mesma conversa privada
        corpo_invasor = {
            "modelo": "gpt-4o",
            "mensagens": [{"papel": "usuario", "conteudo": "Tentar espionar conversa"}],
            "id_conversa": "conversa-privada-999",
        }
        resp_bloqueada = await cliente.post(
            "/v1/chat/conclusoes", json=corpo_invasor, headers=cabecalhos_invasor
        )

        assert resp_bloqueada.status_code == 403
        corpo_erro = resp_bloqueada.json()
        assert corpo_erro["tipo"] == "ErroAcessoNaoAutorizadoConversa"
        assert "pertence a outro usuário" in corpo_erro["mensagem"]


@pytest.mark.asyncio
async def test_resiliencia_e_fallback_sob_alta_concorrencia() -> None:
    """Dispara múltiplas requisições simultâneas testando chaveamento de fallback sob falha do modelo primário."""
    memoria = MemoriaSQLite(caminho_banco=":memory:")
    roteador = RoteadorModelos()

    # Registra provedor que falha propositalmente para 'modelo-instavel' e responde em 'modelo-reserva'
    provedor = ProvedorFlutuante(
        modelo_falho="modelo-instavel", modelo_fallback="modelo-reserva"
    )
    roteador.registrar_provedor(provedor)

    caso_resposta = CasoDeUsoGerarResposta(
        roteador=roteador,
        repositorio_memoria=memoria,
    )

    app = criar_aplicacao_gateway(
        configuracoes=ConfiguracoesGateway(chave_api_mestre="chave-teste")
    )
    app.dependency_overrides[obter_roteador] = lambda: roteador
    app.dependency_overrides[obter_caso_gerar_resposta] = lambda: caso_resposta

    cabecalhos = {"X-API-Key": "chave-teste", "X-User-ID": "usuario_concorrente"}
    transporte = ASGITransport(app=app)

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        # Configura fallback no roteador
        roteador.definir_fallback("modelo-instavel", ("modelo-reserva",))

        async def _disparar_requisicao(indice: int) -> int:
            corpo = {
                "modelo": "modelo-instavel",
                "mensagens": [
                    {"papel": "usuario", "conteudo": f"Consulta paralela {indice}"}
                ],
            }
            resposta = await cliente.post(
                "/v1/chat/conclusoes", json=corpo, headers=cabecalhos
            )
            return resposta.status_code

        # Dispara 20 requisições simultâneas
        tarefas = [_disparar_requisicao(i) for i in range(20)]
        resultados = await asyncio.gather(*tarefas)

        # Todas as 20 chamadas devem ter sido atendidas via contingência (200 OK)
        assert len(resultados) == 20
        assert all(codigo == 200 for codigo in resultados)


@pytest.mark.asyncio
async def test_chat_estruturado_com_schema_complexo_e_defs(
    ambiente_integrado: dict[str, Any],
) -> None:
    """Verifica /v1/chat/estruturado aceitando JSON Schema com $defs, enum e restrições numéricas."""
    app = ambiente_integrado["app"]
    roteador: RoteadorModelos = ambiente_integrado["roteador"]

    # Simula provedor que devolve JSON aderente
    json_esperado = '{"codigo": 42, "classificacao": "alta", "taxa": 2.5}'
    provedor_estruturado = AdaptadorSimulado(
        modelos_suportados=("gpt-4o",),
        resposta_padrao=json_esperado,
    )
    roteador.registrar_provedor(provedor_estruturado)

    esquema_complexo = {
        "$defs": {
            "MetadadosAnalise": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "integer", "minimum": 1},
                    "classificacao": {"enum": ["baixa", "media", "alta"]},
                    "taxa": {"type": "number", "minimum": 0.0, "maximum": 10.0},
                },
                "required": ["codigo", "classificacao", "taxa"],
            }
        },
        "type": "object",
        "properties": {
            "resultado": {"$ref": "#/$defs/MetadadosAnalise"},
        },
        "required": ["resultado"],
    }

    # Atualiza o mock do provedor para devolver o envelope completo esperado pelo esquema
    json_completo = (
        '{"resultado": {"codigo": 42, "classificacao": "alta", "taxa": 2.5}}'
    )
    provedor_estruturado_completo = AdaptadorSimulado(
        modelos_suportados=("gpt-4o",),
        resposta_padrao=json_completo,
    )
    roteador.registrar_provedor(provedor_estruturado_completo)

    cabecalhos = {"X-API-Key": "chave-secreta-integracao"}
    transporte = ASGITransport(app=app)

    async with AsyncClient(transport=transporte, base_url="http://teste") as cliente:
        corpo = {
            "modelo": "gpt-4o",
            "mensagens": [
                {
                    "papel": "usuario",
                    "conteudo": "Gere a análise em formato estruturado.",
                }
            ],
            "esquema_json": esquema_complexo,
        }
        resp = await cliente.post(
            "/v1/chat/estruturado", json=corpo, headers=cabecalhos
        )
        assert resp.status_code == 200
        dados = resp.json()
        assert dados["sucesso"] is True
        assert dados["dados"]["resultado"]["codigo"] == 42
        assert dados["dados"]["resultado"]["classificacao"] == "alta"
        assert dados["dados"]["resultado"]["taxa"] == 2.5
