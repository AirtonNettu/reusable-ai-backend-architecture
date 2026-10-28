"""Rota para geração de dados em formato JSON estritamente estruturado e validado."""

import json
from typing import Annotated

from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.geracao import (
    ConfiguracaoGeracao,
    RequisicaoGeracao,
)
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.servicos.validador_esquema import ValidadorEsquemaJson
from fastapi import APIRouter, Depends

from ai_gateway.dependencias import (
    obter_roteador,
    obter_validador_autenticacao,
)
from ai_gateway.esquemas.estruturado import (
    EsquemaRequisicaoChatEstruturado,
    EsquemaRespostaChatEstruturado,
)

roteador_estruturado = APIRouter(prefix="/v1/chat", tags=["Estruturado"])


@roteador_estruturado.post(
    "/estruturado", response_model=EsquemaRespostaChatEstruturado
)
async def gerar_saida_estruturada(
    requisicao: EsquemaRequisicaoChatEstruturado,
    roteador: Annotated[RoteadorModelos, Depends(obter_roteador)],
    _autenticado: Annotated[str | None, Depends(obter_validador_autenticacao())] = None,
) -> EsquemaRespostaChatEstruturado:
    """Gera resposta no formato JSON e valida a conformidade contra o JSON Schema fornecido."""
    validador = ValidadorEsquemaJson()

    instrucao_esquema = (
        f"Responda EXCLUSIVAMENTE com um objeto JSON válido correspondente ao "
        f"seguinte esquema JSON Schema: {json.dumps(requisicao.esquema_json, ensure_ascii=False)}. "
        f"Não inclua markdown nem textos fora do JSON."
    )

    mensagens_ciclo = [
        Mensagem(papel="sistema", conteudo=instrucao_esquema),
        *[
            Mensagem(papel=m.papel, conteudo=m.conteudo, nome=m.nome)
            for m in requisicao.mensagens
        ],
    ]

    ultimo_json = ""
    erros: list[str] = []

    for tentativa in range(1, requisicao.max_tentativas + 1):
        req_geracao = RequisicaoGeracao(
            modelo=requisicao.modelo,
            mensagens=tuple(mensagens_ciclo),
            configuracao=ConfiguracaoGeracao(temperatura=0.1, formato_json=True),
        )

        resposta = await roteador.gerar(req_geracao)
        ultimo_json = resposta.texto.strip()

        if ultimo_json.startswith("```"):
            linhas = ultimo_json.splitlines()
            if len(linhas) >= 2 and linhas[0].startswith("```"):
                ultimo_json = "\n".join(
                    linhas[1:-1] if linhas[-1].startswith("```") else linhas[1:]
                ).strip()

        try:
            dados_dict = json.loads(ultimo_json)
        except json.JSONDecodeError as erro_json:
            erro_str = f"Tentativa {tentativa} falhou na sintaxe JSON: {erro_json}"
            erros.append(erro_str)
            mensagens_ciclo.append(Mensagem(papel="assistente", conteudo=ultimo_json))
            mensagens_ciclo.append(
                Mensagem(
                    papel="usuario",
                    conteudo=(
                        f"O texto retornado não é um JSON válido: {erro_json}. "
                        f"Envie apenas o JSON puro corrigido."
                    ),
                )
            )
            continue

        # Validação semântica de conformidade com o esquema
        erros_conformidade = validador.validar_dado_contra_esquema(
            dados_dict, requisicao.esquema_json
        )
        if not erros_conformidade:
            return EsquemaRespostaChatEstruturado(
                sucesso=True,
                dados=dados_dict,
                tentativas=tentativa,
                json_bruto=ultimo_json,
            )

        # Dados JSON não cumprem o esquema: repassar erros para o modelo se corrigir
        detalhe_erros = "; ".join(erros_conformidade)
        erros.append(f"Tentativa {tentativa} violou o esquema: {detalhe_erros}")
        mensagens_ciclo.append(Mensagem(papel="assistente", conteudo=ultimo_json))
        mensagens_ciclo.append(
            Mensagem(
                papel="usuario",
                conteudo=(
                    f"O JSON não atende ao esquema exigido: {detalhe_erros}. "
                    f"Corrija os campos e devolva apenas o JSON corrigido."
                ),
            )
        )

    return EsquemaRespostaChatEstruturado(
        sucesso=False,
        dados=None,
        tentativas=requisicao.max_tentativas,
        json_bruto=ultimo_json,
        erros_validacao=erros,
    )
