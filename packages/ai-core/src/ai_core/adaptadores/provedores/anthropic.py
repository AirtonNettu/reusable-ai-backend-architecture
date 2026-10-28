"""Adaptador para o provedor Anthropic (Claude)."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ai_core.adaptadores.provedores.base import AdaptadorProvedorHttpBase
from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta
from ai_core.dominio.modelos.geracao import (
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
    TipoFinalizacao,
    UsoTokens,
)


class AdaptadorAnthropic(AdaptadorProvedorHttpBase):
    """Adaptador para a API Anthropic Messages."""

    def __init__(
        self,
        chave_api: str,
        url_base: str = "https://api.anthropic.com/v1",
        versao_api: str = "2023-06-01",
        timeout_segundos: float = 60.0,
        cliente_http: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            nome_provedor="anthropic",
            url_base=url_base,
            chave_api=chave_api,
            timeout_segundos=timeout_segundos,
            cliente_http=cliente_http,
        )
        self._versao_api = versao_api

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return (
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        )

    def _obter_cabecalhos(self) -> dict[str, str]:
        cabecalhos = {
            "Content-Type": "application/json",
            "anthropic-version": self._versao_api,
        }
        if self._chave_api:
            cabecalhos["x-api-key"] = self._chave_api
        return cabecalhos

    def _preparar_mensagens(
        self, requisicao: RequisicaoGeracao
    ) -> tuple[str | None, list[dict[str, Any]]]:
        sistema: list[str] = []
        mensagens_convertidas: list[dict[str, Any]] = []

        for m in requisicao.mensagens:
            if m.papel == "sistema":
                sistema.append(m.conteudo)
                continue

            papel = "assistant" if m.papel == "assistente" else "user"

            if m.papel == "ferramenta":
                conteudo_ferramenta = [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.identificador_chamada_ferramenta
                        or "id_desconhecido",
                        "content": m.conteudo,
                    }
                ]
                mensagens_convertidas.append(
                    {"role": "user", "content": conteudo_ferramenta}
                )
                continue

            if m.chamadas_ferramentas:
                conteudo_assistente: list[dict[str, Any]] = []
                if m.conteudo:
                    conteudo_assistente.append({"type": "text", "text": m.conteudo})
                for cf in m.chamadas_ferramentas:
                    conteudo_assistente.append(
                        {
                            "type": "tool_use",
                            "id": cf.identificador,
                            "name": cf.nome_ferramenta,
                            "input": cf.argumentos,
                        }
                    )
                mensagens_convertidas.append(
                    {"role": "assistant", "content": conteudo_assistente}
                )
                continue

            mensagens_convertidas.append({"role": papel, "content": m.conteudo})

        texto_sistema = "\n\n".join(sistema) if sistema else None
        return texto_sistema, mensagens_convertidas

    def _converter_ferramentas(
        self, requisicao: RequisicaoGeracao
    ) -> list[dict[str, Any]] | None:
        if not requisicao.ferramentas:
            return None
        return [
            {
                "name": f.nome,
                "description": f.descricao,
                "input_schema": f.esquema_parametros
                if f.esquema_parametros
                else {"type": "object", "properties": {}},
            }
            for f in requisicao.ferramentas
        ]

    def _mapear_motivo_finalizacao(self, stop_reason: str | None) -> TipoFinalizacao:
        if stop_reason == "tool_use":
            return "chamada_ferramenta"
        if stop_reason == "max_tokens":
            return "limite_tokens"
        return "sucesso"

    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        cliente = self.obter_cliente()
        url = f"{self._url_base}/messages"

        texto_sistema, mensagens = self._preparar_mensagens(requisicao)

        max_tokens = (
            requisicao.configuracao.max_tokens
            if requisicao.configuracao.max_tokens is not None
            else 4096
        )

        corpo: dict[str, Any] = {
            "model": requisicao.modelo,
            "messages": mensagens,
            "max_tokens": max_tokens,
            "temperature": requisicao.configuracao.temperatura,
        }

        if texto_sistema:
            corpo["system"] = texto_sistema

        ferramentas = self._converter_ferramentas(requisicao)
        if ferramentas:
            corpo["tools"] = ferramentas

        try:
            resposta = await cliente.post(
                url, headers=self._obter_cabecalhos(), json=corpo
            )
            self.tratar_erro_resposta(resposta)
            dados = resposta.json()
        except Exception as erro:
            self.tratar_excecao_transporte(erro)
            raise

        textos: list[str] = []
        chamadas: list[ChamadaFerramenta] = []

        for bloco in dados.get("content", []):
            if bloco.get("type") == "text":
                textos.append(bloco.get("text", ""))
            elif bloco.get("type") == "tool_use":
                chamadas.append(
                    ChamadaFerramenta(
                        identificador=bloco.get("id", ""),
                        nome_ferramenta=bloco.get("name", ""),
                        argumentos=bloco.get("input", {}),
                    )
                )

        dados_uso = dados.get("usage", {})
        prompt_tokens = dados_uso.get("input_tokens", 0)
        saida_tokens = dados_uso.get("output_tokens", 0)

        motivo = self._mapear_motivo_finalizacao(dados.get("stop_reason"))

        return RespostaGeracao(
            texto="".join(textos),
            modelo=dados.get("model", requisicao.modelo),
            motivo_finalizacao=motivo,
            uso=UsoTokens(
                tokens_entrada=prompt_tokens,
                tokens_saida=saida_tokens,
                total_tokens=prompt_tokens + saida_tokens,
            ),
            chamadas_ferramentas=tuple(chamadas),
        )

    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        cliente = self.obter_cliente()
        url = f"{self._url_base}/messages"

        texto_sistema, mensagens = self._preparar_mensagens(requisicao)
        max_tokens = (
            requisicao.configuracao.max_tokens
            if requisicao.configuracao.max_tokens is not None
            else 4096
        )

        corpo: dict[str, Any] = {
            "model": requisicao.modelo,
            "messages": mensagens,
            "max_tokens": max_tokens,
            "temperature": requisicao.configuracao.temperatura,
            "stream": True,
        }
        if texto_sistema:
            corpo["system"] = texto_sistema

        try:
            async with cliente.stream(
                "POST", url, headers=self._obter_cabecalhos(), json=corpo
            ) as resposta:
                self.tratar_erro_resposta(resposta)
                async for linha in resposta.aiter_lines():
                    linha = linha.strip()
                    if not linha or not linha.startswith("data: "):
                        continue

                    dados_linha = linha[6:].strip()
                    dados = json.loads(dados_linha)
                    tipo_evento = dados.get("type")

                    if tipo_evento == "content_block_delta":
                        delta = dados.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield PedacoResposta(
                                texto=delta.get("text", ""),
                                finalizado=False,
                            )
                    elif tipo_evento == "message_stop":
                        yield PedacoResposta(
                            texto="",
                            finalizado=True,
                            motivo_finalizacao="sucesso",
                        )
                        break
        except Exception as erro:
            self.tratar_excecao_transporte(erro)
            raise

    async def validar_disponibilidade(self) -> bool:
        return bool(self._chave_api)
