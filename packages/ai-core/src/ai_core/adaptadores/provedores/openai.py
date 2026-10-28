"""Adaptador para o provedor OpenAI e APIs compatíveis."""

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


class AdaptadorOpenAI(AdaptadorProvedorHttpBase):
    """Adaptador para a API OpenAI Chat Completions."""

    def __init__(
        self,
        chave_api: str,
        url_base: str = "https://api.openai.com/v1",
        timeout_segundos: float = 60.0,
        cliente_http: httpx.AsyncClient | None = None,
        nome_provedor: str = "openai",
    ) -> None:
        super().__init__(
            nome_provedor=nome_provedor,
            url_base=url_base,
            chave_api=chave_api,
            timeout_segundos=timeout_segundos,
            cliente_http=cliente_http,
        )

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return ("gpt-4o", "gpt-4o-mini", "o1", "o3-mini")

    def _obter_cabecalhos(self) -> dict[str, str]:
        cabecalhos = {"Content-Type": "application/json"}
        if self._chave_api:
            cabecalhos["Authorization"] = f"Bearer {self._chave_api}"
        return cabecalhos

    def _converter_mensagens(
        self, requisicao: RequisicaoGeracao
    ) -> list[dict[str, Any]]:
        mensagens_convertidas: list[dict[str, Any]] = []
        for m in requisicao.mensagens:
            papel = (
                "assistant"
                if m.papel == "assistente"
                else (
                    "system"
                    if m.papel == "sistema"
                    else ("tool" if m.papel == "ferramenta" else "user")
                )
            )
            item: dict[str, Any] = {"role": papel, "content": m.conteudo}

            if m.papel == "ferramenta" and m.identificador_chamada_ferramenta:
                item["tool_call_id"] = m.identificador_chamada_ferramenta

            if m.chamadas_ferramentas:
                item["tool_calls"] = [
                    {
                        "id": cf.identificador,
                        "type": "function",
                        "function": {
                            "name": cf.nome_ferramenta,
                            "arguments": json.dumps(cf.argumentos),
                        },
                    }
                    for cf in m.chamadas_ferramentas
                ]
            mensagens_convertidas.append(item)
        return mensagens_convertidas

    def _converter_ferramentas(
        self, requisicao: RequisicaoGeracao
    ) -> list[dict[str, Any]] | None:
        if not requisicao.ferramentas:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": f.nome,
                    "description": f.descricao,
                    "parameters": f.esquema_parametros,
                },
            }
            for f in requisicao.ferramentas
        ]

    def _mapear_motivo_finalizacao(self, motivo_openai: str | None) -> TipoFinalizacao:
        if motivo_openai == "tool_calls":
            return "chamada_ferramenta"
        if motivo_openai == "length":
            return "limite_tokens"
        if motivo_openai == "content_filter":
            return "filtro_conteudo"
        return "sucesso"

    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        cliente = self.obter_cliente()
        url = f"{self._url_base}/chat/completions"

        corpo: dict[str, Any] = {
            "model": requisicao.modelo,
            "messages": self._converter_mensagens(requisicao),
            "temperature": requisicao.configuracao.temperatura,
            "stream": False,
        }

        if requisicao.configuracao.max_tokens is not None:
            corpo["max_tokens"] = requisicao.configuracao.max_tokens

        if requisicao.configuracao.formato_json:
            corpo["response_format"] = {"type": "json_object"}

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

        escolha = dados["choices"][0]
        mensagem = escolha["message"]
        texto = mensagem.get("content") or ""
        motivo = self._mapear_motivo_finalizacao(escolha.get("finish_reason"))

        chamadas_ferramentas: list[ChamadaFerramenta] = []
        if mensagem.get("tool_calls"):
            for tc in mensagem["tool_calls"]:
                try:
                    argumentos = json.loads(tc["function"].get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    argumentos = {}
                chamadas_ferramentas.append(
                    ChamadaFerramenta(
                        identificador=tc["id"],
                        nome_ferramenta=tc["function"]["name"],
                        argumentos=argumentos,
                    )
                )

        dados_uso = dados.get("usage", {})
        uso = UsoTokens(
            tokens_entrada=dados_uso.get("prompt_tokens", 0),
            tokens_saida=dados_uso.get("completion_tokens", 0),
            total_tokens=dados_uso.get("total_tokens", 0),
        )

        return RespostaGeracao(
            texto=texto,
            modelo=dados.get("model", requisicao.modelo),
            motivo_finalizacao=motivo,
            uso=uso,
            chamadas_ferramentas=tuple(chamadas_ferramentas),
        )

    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        cliente = self.obter_cliente()
        url = f"{self._url_base}/chat/completions"

        corpo: dict[str, Any] = {
            "model": requisicao.modelo,
            "messages": self._converter_mensagens(requisicao),
            "temperature": requisicao.configuracao.temperatura,
            "stream": True,
        }

        ferramentas = self._converter_ferramentas(requisicao)
        if ferramentas:
            corpo["tools"] = ferramentas

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
                    if dados_linha == "[DONE]":
                        yield PedacoResposta(
                            finalizado=True, motivo_finalizacao="sucesso"
                        )
                        break

                    dados = json.loads(dados_linha)
                    escolha = dados["choices"][0]
                    delta = escolha.get("delta", {})
                    texto_delta = delta.get("content") or ""
                    motivo = self._mapear_motivo_finalizacao(
                        escolha.get("finish_reason")
                    )

                    yield PedacoResposta(
                        texto=texto_delta,
                        finalizado=motivo != "sucesso"
                        or bool(escolha.get("finish_reason")),
                        motivo_finalizacao=motivo
                        if escolha.get("finish_reason")
                        else None,
                    )
        except Exception as erro:
            self.tratar_excecao_transporte(erro)
            raise

    async def validar_disponibilidade(self) -> bool:
        if not self._chave_api:
            return False
        cliente = self.obter_cliente()
        try:
            resposta = await cliente.get(
                f"{self._url_base}/models", headers=self._obter_cabecalhos()
            )
            return resposta.is_success
        except (httpx.HTTPError, OSError):
            return False
