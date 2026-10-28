"""Testes para os adaptadores de provedores LLM (Simulado e HTTP via MockTransport)."""

import json

import httpx
import pytest
from ai_core.adaptadores.provedores.anthropic import AdaptadorAnthropic
from ai_core.adaptadores.provedores.gemini import AdaptadorGemini
from ai_core.adaptadores.provedores.ollama import AdaptadorOllama
from ai_core.adaptadores.provedores.openai import AdaptadorOpenAI
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.dominio.excecoes import (
    ErroAutenticacaoProvedor,
    ErroModeloNaoSuportado,
)
from ai_core.dominio.modelos.ferramenta import DefinicaoFerramenta
from ai_core.dominio.modelos.geracao import RequisicaoGeracao
from ai_core.dominio.modelos.mensagem import Mensagem


@pytest.mark.asyncio
async def test_adaptador_simulado_geracao_e_fluxo() -> None:
    """Verifica geração síncrona e streaming no provedor simulado."""
    provedor = AdaptadorSimulado(
        resposta_padrao="IA conectada com sucesso",
        modelos_suportados=("modelo-teste",),
    )

    requisicao = RequisicaoGeracao(
        modelo="modelo-teste",
        mensagens=(Mensagem(papel="usuario", conteudo="Oi"),),
    )

    resposta = await provedor.gerar(requisicao)
    assert resposta.texto == "IA conectada com sucesso"
    assert resposta.motivo_finalizacao == "sucesso"
    assert resposta.uso.tokens_saida == 4

    pedacos = []
    async for p in provedor.gerar_fluxo(requisicao):
        pedacos.append(p.texto)
    assert "".join(pedacos) == "IA conectada com sucesso"

    # Teste de modelo não suportado
    req_invalida = RequisicaoGeracao(
        modelo="modelo-inexistente",
        mensagens=(Mensagem(papel="usuario", conteudo="Oi"),),
    )
    with pytest.raises(ErroModeloNaoSuportado):
        await provedor.gerar(req_invalida)


@pytest.mark.asyncio
async def test_adaptador_openai_sucesso_e_ferramentas() -> None:
    """Verifica chamada e conversão da resposta padrão OpenAI via MockTransport."""

    def handler_mock(request: httpx.Request) -> httpx.Response:
        corpo = json.loads(request.content.decode("utf-8"))
        assert corpo["model"] == "gpt-4o"
        resposta_mock = {
            "id": "chatcmpl-mock",
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Resultado da OpenAI",
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "calcular",
                                    "arguments": '{"x": 10}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            },
        }
        return httpx.Response(200, json=resposta_mock)

    transporte = httpx.MockTransport(handler_mock)
    cliente = httpx.AsyncClient(transport=transporte)

    provedor = AdaptadorOpenAI(
        chave_api="sk-teste-1234",
        cliente_http=cliente,
    )

    requisicao = RequisicaoGeracao(
        modelo="gpt-4o",
        mensagens=(Mensagem(papel="usuario", conteudo="Calcule x"),),
        ferramentas=(DefinicaoFerramenta(nome="calcular", descricao="Calcula algo"),),
    )

    resposta = await provedor.gerar(requisicao)
    assert resposta.texto == "Resultado da OpenAI"
    assert resposta.motivo_finalizacao == "chamada_ferramenta"
    assert len(resposta.chamadas_ferramentas) == 1
    assert resposta.chamadas_ferramentas[0].nome_ferramenta == "calcular"
    assert resposta.chamadas_ferramentas[0].argumentos == {"x": 10}


@pytest.mark.asyncio
async def test_adaptador_openai_erro_autenticacao() -> None:
    """Status 401 deve mapear para ErroAutenticacaoProvedor."""

    def handler_401(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler_401))
    provedor = AdaptadorOpenAI(chave_api="chave-invalida", cliente_http=cliente)

    req = RequisicaoGeracao(
        modelo="gpt-4o",
        mensagens=(Mensagem(papel="usuario", conteudo="Oi"),),
    )

    with pytest.raises(ErroAutenticacaoProvedor):
        await provedor.gerar(req)


@pytest.mark.asyncio
async def test_adaptador_ollama_sucesso() -> None:
    """Verifica comunicação com a API local do Ollama via MockTransport."""

    def handler_ollama(request: httpx.Request) -> httpx.Response:
        assert "/api/chat" in str(request.url)
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "Resposta local Ollama"},
                "prompt_eval_count": 8,
                "eval_count": 5,
            },
        )

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler_ollama))
    provedor = AdaptadorOllama(cliente_http=cliente)

    req = RequisicaoGeracao(
        modelo="llama3",
        mensagens=(Mensagem(papel="usuario", conteudo="Olá"),),
    )

    resposta = await provedor.gerar(req)
    assert resposta.texto == "Resposta local Ollama"
    assert resposta.uso.tokens_entrada == 8
    assert resposta.uso.tokens_saida == 5


@pytest.mark.asyncio
async def test_adaptador_gemini_sucesso() -> None:
    """Verifica comunicação e formatação do Google Gemini via MockTransport."""

    def handler_gemini(request: httpx.Request) -> httpx.Response:
        assert "generateContent" in str(request.url)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Resposta do Gemini 2.5"}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 15,
                    "candidatesTokenCount": 9,
                },
            },
        )

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler_gemini))
    provedor = AdaptadorGemini(chave_api="chave-gemini", cliente_http=cliente)

    req = RequisicaoGeracao(
        modelo="gemini-2.5-flash",
        mensagens=(Mensagem(papel="usuario", conteudo="Olá"),),
    )

    resposta = await provedor.gerar(req)
    assert resposta.texto == "Resposta do Gemini 2.5"
    assert resposta.uso.total_tokens == 24


@pytest.mark.asyncio
async def test_adaptador_anthropic_sucesso() -> None:
    """Verifica comunicação com a API Anthropic Messages via MockTransport."""

    def handler_anthropic(request: httpx.Request) -> httpx.Response:
        assert "/messages" in str(request.url)
        assert request.headers.get("anthropic-version") == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "model": "claude-3-5-sonnet-20241022",
                "content": [{"type": "text", "text": "Resposta do Claude"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 20, "output_tokens": 10},
            },
        )

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(handler_anthropic))
    provedor = AdaptadorAnthropic(chave_api="sk-ant-test", cliente_http=cliente)

    req = RequisicaoGeracao(
        modelo="claude-3-5-sonnet-20241022",
        mensagens=(Mensagem(papel="usuario", conteudo="Olá"),),
    )

    resposta = await provedor.gerar(req)
    assert resposta.texto == "Resposta do Claude"
    assert resposta.uso.tokens_entrada == 20
    assert resposta.uso.tokens_saida == 10
