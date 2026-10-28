"""Adaptador para o provedor Google Gemini."""

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


class AdaptadorGemini(AdaptadorProvedorHttpBase):
    """Adaptador para a API Google Gemini (Google AI Studio)."""

    def __init__(
        self,
        chave_api: str,
        url_base: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_segundos: float = 60.0,
        cliente_http: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            nome_provedor="gemini",
            url_base=url_base,
            chave_api=chave_api,
            timeout_segundos=timeout_segundos,
            cliente_http=cliente_http,
        )

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return (
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
        )

    def _obter_cabecalhos(self) -> dict[str, str]:
        cabecalhos = {"Content-Type": "application/json"}
        if self._chave_api:
            cabecalhos["x-goog-api-key"] = self._chave_api
        return cabecalhos

    def _converter_conteudos(
        self, requisicao: RequisicaoGeracao
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        instrucao_sistema: dict[str, Any] | None = None
        conteudos: list[dict[str, Any]] = []

        for m in requisicao.mensagens:
            if m.papel == "sistema":
                instrucao_sistema = {"parts": [{"text": m.conteudo}]}
                continue

            papel = "model" if m.papel == "assistente" else "user"
            partes: list[dict[str, Any]] = []

            if m.conteudo:
                partes.append({"text": m.conteudo})

            if m.chamadas_ferramentas:
                for cf in m.chamadas_ferramentas:
                    partes.append(
                        {
                            "functionCall": {
                                "name": cf.nome_ferramenta,
                                "args": cf.argumentos,
                            }
                        }
                    )

            if m.papel == "ferramenta":
                partes.append(
                    {
                        "functionResponse": {
                            "name": m.nome or "ferramenta",
                            "response": {"resultado": m.conteudo},
                        }
                    }
                )

            conteudos.append({"role": papel, "parts": partes})

        return instrucao_sistema, conteudos

    def _mapear_motivo_finalizacao(self, motivo_gemini: str | None) -> TipoFinalizacao:
        if motivo_gemini in ("STOP", None):
            return "sucesso"
        if motivo_gemini == "MAX_TOKENS":
            return "limite_tokens"
        if motivo_gemini in ("SAFETY", "RECITATION"):
            return "filtro_conteudo"
        return "sucesso"

    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        cliente = self.obter_cliente()
        url = f"{self._url_base}/models/{requisicao.modelo}:generateContent"

        instrucao_sistema, conteudos = self._converter_conteudos(requisicao)

        corpo: dict[str, Any] = {
            "contents": conteudos,
            "generationConfig": {
                "temperature": requisicao.configuracao.temperatura,
            },
        }

        if instrucao_sistema:
            corpo["systemInstruction"] = instrucao_sistema

        if requisicao.configuracao.max_tokens:
            corpo["generationConfig"]["maxOutputTokens"] = (
                requisicao.configuracao.max_tokens
            )

        if requisicao.configuracao.formato_json:
            corpo["generationConfig"]["responseMimeType"] = "application/json"

        if requisicao.ferramentas:
            corpo["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": f.nome,
                            "description": f.descricao,
                            "parameters": f.esquema_parametros,
                        }
                        for f in requisicao.ferramentas
                    ]
                }
            ]

        try:
            resposta = await cliente.post(
                url, headers=self._obter_cabecalhos(), json=corpo
            )
            self.tratar_erro_resposta(resposta)
            dados = resposta.json()
        except Exception as erro:
            self.tratar_excecao_transporte(erro)
            raise

        candidatos = dados.get("candidates", [])
        if not candidatos:
            return RespostaGeracao(
                texto="",
                modelo=requisicao.modelo,
                motivo_finalizacao="sucesso",
            )

        candidato = candidatos[0]
        partes = candidato.get("content", {}).get("parts", [])
        textos: list[str] = []
        chamadas: list[ChamadaFerramenta] = []

        for p in partes:
            if "text" in p:
                textos.append(p["text"])
            elif "functionCall" in p:
                fc = p["functionCall"]
                chamadas.append(
                    ChamadaFerramenta(
                        identificador=fc.get("name", "chamada"),
                        nome_ferramenta=fc.get("name", ""),
                        argumentos=fc.get("args", {}),
                    )
                )

        metadados_uso = dados.get("usageMetadata", {})
        prompt_tokens = metadados_uso.get("promptTokenCount", 0)
        saida_tokens = metadados_uso.get("candidatesTokenCount", 0)

        motivo = (
            "chamada_ferramenta"
            if chamadas
            else self._mapear_motivo_finalizacao(candidato.get("finishReason"))
        )

        return RespostaGeracao(
            texto="".join(textos),
            modelo=requisicao.modelo,
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
        url = (
            f"{self._url_base}/models/{requisicao.modelo}:streamGenerateContent?alt=sse"
        )

        instrucao_sistema, conteudos = self._converter_conteudos(requisicao)

        corpo: dict[str, Any] = {
            "contents": conteudos,
            "generationConfig": {
                "temperature": requisicao.configuracao.temperatura,
            },
        }
        if instrucao_sistema:
            corpo["systemInstruction"] = instrucao_sistema

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
                    candidatos = dados.get("candidates", [])
                    if not candidatos:
                        continue

                    candidato = candidatos[0]
                    partes = candidato.get("content", {}).get("parts", [])
                    texto_parte = "".join(
                        p.get("text", "") for p in partes if "text" in p
                    )
                    motivo = candidato.get("finishReason")
                    finalizado = motivo is not None

                    yield PedacoResposta(
                        texto=texto_parte,
                        finalizado=finalizado,
                        motivo_finalizacao=self._mapear_motivo_finalizacao(motivo)
                        if finalizado
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
