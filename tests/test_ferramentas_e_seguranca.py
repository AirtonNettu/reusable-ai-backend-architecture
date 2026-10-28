"""Testes para o registro de ferramentas, segurança e controle de credenciais."""

import pytest
from ai_core.adaptadores.ferramentas.registro import RegistroFerramentas
from ai_core.adaptadores.ferramentas.seguranca import PoliticaAutorizacaoFerramenta
from ai_core.adaptadores.seguranca.cofre_credenciais import CofreCredenciais
from ai_core.dominio.modelos.ferramenta import (
    ChamadaFerramenta,
    DefinicaoFerramenta,
)


@pytest.mark.asyncio
async def test_registro_e_execucao_ferramenta() -> None:
    """Verifica execução de ferramentas síncronas e assíncronas registradas."""
    registro = RegistroFerramentas()

    def _soma_sync(a: int, b: int) -> int:
        return a + b

    async def _multiplica_async(x: int, y: int) -> int:
        return x * y

    registro.registrar(
        DefinicaoFerramenta(nome="somar", descricao="Soma números"),
        _soma_sync,
    )
    registro.registrar(
        DefinicaoFerramenta(nome="multiplicar", descricao="Multiplica números"),
        _multiplica_async,
    )

    chamada_soma = ChamadaFerramenta(
        identificador="c1", nome_ferramenta="somar", argumentos={"a": 10, "b": 20}
    )
    resultado_soma = await registro.executar(chamada_soma)
    assert resultado_soma.sucesso is True
    assert resultado_soma.resultado == 30

    chamada_mult = ChamadaFerramenta(
        identificador="c2",
        nome_ferramenta="multiplicar",
        argumentos={"x": 5, "y": 6},
    )
    resultado_mult = await registro.executar(chamada_mult)
    assert resultado_mult.sucesso is True
    assert resultado_mult.resultado == 30


@pytest.mark.asyncio
async def test_seguranca_autorizacao_ferramentas() -> None:
    """Valida bloqueio de ferramentas sensíveis sem aprovação prévia."""
    politica = PoliticaAutorizacaoFerramenta()
    registro = RegistroFerramentas(politica_autorizacao=politica)

    registro.registrar(
        DefinicaoFerramenta(
            nome="deletar_banco",
            descricao="Deleta banco de dados",
            requer_autorizacao=True,
        ),
        lambda: "banco deletado",
    )

    chamada = ChamadaFerramenta(identificador="c_del", nome_ferramenta="deletar_banco")

    # Bloqueada inicialmente
    resultado_bloqueado = await registro.executar(chamada)
    assert resultado_bloqueado.sucesso is False
    assert "requer aprovação" in (resultado_bloqueado.erro or "")

    # Liberada após concessão de aprovação
    politica.aprovar_ferramenta("deletar_banco")
    resultado_aprovado = await registro.executar(chamada)
    assert resultado_aprovado.sucesso is True
    assert resultado_aprovado.resultado == "banco deletado"


def test_cofre_credenciais() -> None:
    """Verifica leitura de ambiente e mascaramento seguro de credenciais."""
    ambiente = {
        "OPENAI_API_KEY": "sk-1234567890abcdef1234567890",
        "CURTA_KEY": "12345",
    }
    cofre = CofreCredenciais(fonte_ambiente=ambiente)

    assert cofre.obter_chave("OPENAI_API_KEY") == "sk-1234567890abcdef1234567890"
    assert cofre.obter_chave("CHAVE_INEXISTENTE") is None

    with pytest.raises(ValueError, match="obrigatória"):
        cofre.obter_chave("CHAVE_INEXISTENTE", obrigatoria=True)

    # Mascaramento
    assert CofreCredenciais.mascarar_chave(None) == "[NÃO CONFIGURADA]"
    assert CofreCredenciais.mascarar_chave("12345") == "****"
    assert (
        CofreCredenciais.mascarar_chave("sk-1234567890abcdef1234567890")
        == "sk-1...7890"
    )
