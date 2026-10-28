"""Rota de execução de agentes autônomos com raciocínio e ferramentas."""

from typing import Annotated

from ai_core.aplicacao.agentes.orquestrador import OrquestradorAgente
from ai_core.dominio.modelos.agente import ConfiguracaoAgente
from fastapi import APIRouter, Depends

from ai_gateway.dependencias import (
    obter_orquestrador_agente,
    obter_validador_autenticacao,
)
from ai_gateway.esquemas.agente import (
    EsquemaPassoAgente,
    EsquemaRequisicaoAgente,
    EsquemaRespostaAgente,
)
from ai_gateway.esquemas.chat import EsquemaUsoTokens

roteador_agentes = APIRouter(prefix="/v1/agentes", tags=["Agentes"])


@roteador_agentes.post("/executar", response_model=EsquemaRespostaAgente)
async def executar_agente(
    requisicao: EsquemaRequisicaoAgente,
    orquestrador: Annotated[OrquestradorAgente, Depends(obter_orquestrador_agente)],
    _autenticado: Annotated[str | None, Depends(obter_validador_autenticacao())] = None,
) -> EsquemaRespostaAgente:
    """Dispara a execução do ciclo de raciocínio e ferramentas de um agente."""
    config_dominio = ConfiguracaoAgente(
        nome=requisicao.nome_agente,
        instrucao_sistema=requisicao.instrucao_sistema,
        limite_passos=requisicao.limite_passos,
        ferramentas_permitidas=tuple(requisicao.ferramentas_permitidas),
    )

    resultado = await orquestrador.executar(
        objetivo=requisicao.objetivo,
        configuracao=config_dominio,
    )

    passos_esquema = [
        EsquemaPassoAgente(
            numero_passo=p.numero_passo,
            pensamento=p.pensamento,
            resposta_parcial=p.resposta_parcial,
        )
        for p in resultado.passos
    ]

    return EsquemaRespostaAgente(
        resposta_final=resultado.resposta_final,
        passos=passos_esquema,
        sucesso=resultado.sucesso,
        total_tokens=EsquemaUsoTokens(
            tokens_entrada=resultado.total_tokens.tokens_entrada,
            tokens_saida=resultado.total_tokens.tokens_saida,
            total_tokens=resultado.total_tokens.total_tokens,
        ),
        tempo_total_segundos=resultado.tempo_total_segundos,
        erro=resultado.erro,
    )
