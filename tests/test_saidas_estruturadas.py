"""Testes para geração e autorreparo de saídas estruturadas com Pydantic."""

import json
from collections.abc import AsyncIterator

import pytest
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.aplicacao.casos_de_uso.caso_gerar_saida_estruturada import (
    CasoDeUsoGerarSaidaEstruturada,
)
from ai_core.dominio.modelos.geracao import (
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
    UsoTokens,
)
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_core.dominio.portas.porta_provedor import PortaProvedorLLM
from pydantic import BaseModel, Field


class PerfilUsuario(BaseModel):
    """Modelo Pydantic alvo para validação estruturada."""

    nome: str = Field(description="Nome completo")
    idade: int = Field(ge=0, description="Idade em anos")
    habilidades: list[str] = Field(description="Lista de competências")


class ProvedorMockEstruturado(PortaProvedorLLM):
    """Provedor para testar respostas JSON perfeitas ou com falha seguida de autocorreção."""

    def __init__(self, respostas_sequenciais: list[str]) -> None:
        self.respostas = list(respostas_sequenciais)
        self.indice = 0

    @property
    def nome_provedor(self) -> str:
        return "mock-estruturado"

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return ("modelo-json",)

    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        if self.indice < len(self.respostas):
            texto = self.respostas[self.indice]
            self.indice += 1
        else:
            texto = "{}"

        return RespostaGeracao(
            texto=texto,
            modelo=requisicao.modelo,
            motivo_finalizacao="sucesso",
            uso=UsoTokens(tokens_entrada=10, tokens_saida=10, total_tokens=20),
        )

    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        yield PedacoResposta(texto="")

    async def validar_disponibilidade(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_saida_estruturada_sucesso_imediato() -> None:
    """Verifica extração direta quando o modelo retorna JSON válido de primeira."""
    dados_esperados = {
        "nome": "Carlos Silva",
        "idade": 32,
        "habilidades": ["Python", "FastAPI"],
    }
    json_valido = json.dumps(dados_esperados)

    provedor = ProvedorMockEstruturado([f"```json\n{json_valido}\n```"])
    roteador = RoteadorModelos()
    roteador.registrar_provedor(provedor)

    caso_uso = CasoDeUsoGerarSaidaEstruturada(roteador=roteador)
    resultado = await caso_uso.executar(
        modelo="modelo-json",
        mensagens=(Mensagem(papel="usuario", conteudo="Gere o perfil de Carlos."),),
        classe_modelo=PerfilUsuario,
    )

    assert resultado.sucesso is True
    assert resultado.tentativas == 1
    assert resultado.dados is not None
    assert resultado.dados.nome == "Carlos Silva"
    assert resultado.dados.idade == 32
    assert "FastAPI" in resultado.dados.habilidades


@pytest.mark.asyncio
async def test_saida_estruturada_com_autocorrecao() -> None:
    """Verifica autocorreção quando a primeira resposta tem erro de validação."""
    # Tentativa 1: idade como string inválida ou campo faltando
    resposta_1 = '{"nome": "Ana", "idade": -5, "habilidades": []}'  # viola ge=0
    # Tentativa 2: corrigida
    resposta_2 = '{"nome": "Ana", "idade": 28, "habilidades": ["Go"]}'

    provedor = ProvedorMockEstruturado([resposta_1, resposta_2])
    roteador = RoteadorModelos()
    roteador.registrar_provedor(provedor)

    caso_uso = CasoDeUsoGerarSaidaEstruturada(roteador=roteador)
    resultado = await caso_uso.executar(
        modelo="modelo-json",
        mensagens=(Mensagem(papel="usuario", conteudo="Perfil de Ana"),),
        classe_modelo=PerfilUsuario,
        max_tentativas_reparo=2,
    )

    assert resultado.sucesso is True
    assert resultado.tentativas == 2
    assert resultado.dados is not None
    assert resultado.dados.idade == 28
