"""Adaptador para o provedor Ollama (modelos locais)."""

import json
from collections.abc import AsyncIterator

import httpx

from ai_core.adaptadores.provedores.base import AdaptadorProvedorHttpBase
from ai_core.dominio.modelos.geracao import (
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
    UsoTokens,
)


class AdaptadorOllama(AdaptadorProvedorHttpBase):
    """Adaptador de integração com a API local do Ollama."""

    def __init__(
        self,
        url_base: str = "http://localhost:11434",
        timeout_segundos: float = 60.0,
        cliente_http: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            nome_provedor="ollama",
            url_base=url_base,
            chave_api=None,
            timeout_segundos=timeout_segundos,
            cliente_http=cliente_http,
        )

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return ("llama3", "llama3.2", "mistral", "qwen2.5", "phi3")

    def _converter_mensagens(
        self, requisicao: RequisicaoGeracao
    ) -> list[dict[str, str]]:
        mensagens_convertidas: list[dict[str, str]] = []
        for m in requisicao.mensagens:
            papel = (
                "assistant"
                if m.papel == "assistente"
                else ("system" if m.papel == "sistema" else "user")
            )
            mensagens_convertidas.append({"role": papel, "content": m.conteudo})
        return mensagens_convertidas

    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        cliente = self.obter_cliente()
        url = f"{self._url_base}/api/chat"

        corpo = {
            "model": requisicao.modelo,
            "messages": self._converter_mensagens(requisicao),
            "stream": False,
            "options": {
                "temperature": requisicao.configuracao.temperatura,
            },
        }

        if requisicao.configuracao.formato_json:
            corpo["format"] = "json"

        try:
            resposta = await cliente.post(url, json=corpo)
            self.tratar_erro_resposta(resposta)
            dados = resposta.json()
        except Exception as erro:
            self.tratar_excecao_transporte(erro)
            raise

        mensagem_conteudo = dados.get("message", {}).get("content", "")
        tokens_entrada = dados.get("prompt_eval_count", 0)
        tokens_saida = dados.get("eval_count", 0)

        return RespostaGeracao(
            texto=mensagem_conteudo,
            modelo=requisicao.modelo,
            motivo_finalizacao="sucesso",
            uso=UsoTokens(
                tokens_entrada=tokens_entrada,
                tokens_saida=tokens_saida,
                total_tokens=tokens_entrada + tokens_saida,
            ),
        )

    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        cliente = self.obter_cliente()
        url = f"{self._url_base}/api/chat"

        corpo = {
            "model": requisicao.modelo,
            "messages": self._converter_mensagens(requisicao),
            "stream": True,
            "options": {
                "temperature": requisicao.configuracao.temperatura,
            },
        }

        try:
            async with cliente.stream("POST", url, json=corpo) as resposta:
                self.tratar_erro_resposta(resposta)
                async for linha in resposta.aiter_lines():
                    if not linha.strip():
                        continue
                    dados = json.loads(linha)
                    pedaco = dados.get("message", {}).get("content", "")
                    concluido = dados.get("done", False)

                    uso: UsoTokens | None = None
                    if concluido:
                        prompt_tokens = dados.get("prompt_eval_count", 0)
                        eval_tokens = dados.get("eval_count", 0)
                        uso = UsoTokens(
                            tokens_entrada=prompt_tokens,
                            tokens_saida=eval_tokens,
                            total_tokens=prompt_tokens + eval_tokens,
                        )

                    yield PedacoResposta(
                        texto=pedaco,
                        finalizado=concluido,
                        motivo_finalizacao="sucesso" if concluido else None,
                        uso=uso,
                    )
        except Exception as erro:
            self.tratar_excecao_transporte(erro)
            raise

    async def validar_disponibilidade(self) -> bool:
        cliente = self.obter_cliente()
        try:
            resposta = await cliente.get(f"{self._url_base}/api/tags")
            return resposta.is_success
        except (httpx.HTTPError, OSError):
            return False
