"""Caso de uso para geração e validação de saídas estruturadas com autorreparo."""

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.estruturado import ResultadoSaidaEstruturada
from ai_core.dominio.modelos.geracao import (
    ConfiguracaoGeracao,
    RequisicaoGeracao,
)
from ai_core.dominio.modelos.mensagem import Mensagem

T = TypeVar("T", bound=BaseModel)


class CasoDeUsoGerarSaidaEstruturada:
    """Garante a entrega de dados estritamente em conformidade com esquemas tipados."""

    def __init__(self, roteador: RoteadorModelos) -> None:
        self._roteador = roteador

    async def executar(
        self,
        modelo: str,
        mensagens: tuple[Mensagem, ...],
        classe_modelo: type[T],
        max_tentativas_reparo: int = 2,
    ) -> ResultadoSaidaEstruturada[T]:
        """Gera e valida a saída estruturada, realizando reparos caso o JSON seja inválido."""
        esquema_json = classe_modelo.model_json_schema()
        instrucao_esquema = (
            f"Responda EXCLUSIVAMENTE com um objeto JSON válido correspondente ao "
            f"seguinte esquema JSON Schema: {json.dumps(esquema_json, ensure_ascii=False)}. "
            f"Não inclua blocos de markdown, comentários ou texto fora do JSON."
        )

        mensagens_ciclo: list[Mensagem] = [
            Mensagem(papel="sistema", conteudo=instrucao_esquema),
            *mensagens,
        ]

        ultimo_json_bruto = ""
        erros_acumulados: list[str] = []

        for tentativa in range(1, max_tentativas_reparo + 2):
            requisicao = RequisicaoGeracao(
                modelo=modelo,
                mensagens=tuple(mensagens_ciclo),
                configuracao=ConfiguracaoGeracao(
                    temperatura=0.1,
                    formato_json=True,
                ),
            )

            resposta = await self._roteador.gerar(requisicao)
            ultimo_json_bruto = resposta.texto.strip()

            # Remove delimitadores de código markdown se o modelo tiver incluído
            if ultimo_json_bruto.startswith("```"):
                linhas = ultimo_json_bruto.splitlines()
                if len(linhas) >= 2 and linhas[0].startswith("```"):
                    ultimo_json_bruto = "\n".join(
                        linhas[1:-1] if linhas[-1].startswith("```") else linhas[1:]
                    ).strip()

            try:
                dados_dicionario = json.loads(ultimo_json_bruto)
                instancia_validada = classe_modelo.model_validate(dados_dicionario)
                return ResultadoSaidaEstruturada(
                    dados=instancia_validada,
                    sucesso=True,
                    tentativas=tentativa,
                    json_bruto=ultimo_json_bruto,
                )
            except (json.JSONDecodeError, ValidationError) as erro:
                erro_texto = f"Erro na tentativa {tentativa}: {erro}"
                erros_acumulados.append(erro_texto)

                # Notifica o modelo sobre a falha para que ele corrija na próxima iteração
                mensagens_ciclo.append(
                    Mensagem(papel="assistente", conteudo=ultimo_json_bruto)
                )
                mensagens_ciclo.append(
                    Mensagem(
                        papel="usuario",
                        conteudo=(
                            f"O JSON fornecido é inválido ou não cumpre os requisitos: {erro}. "
                            f"Por favor, corrija o objeto e envie apenas o JSON corrigido."
                        ),
                    )
                )

        return ResultadoSaidaEstruturada(
            dados=None,
            sucesso=False,
            tentativas=max_tentativas_reparo + 1,
            json_bruto=ultimo_json_bruto,
            erros_validacao=tuple(erros_acumulados),
        )
