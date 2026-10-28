"""Testes unitários para as entidades e contratos do domínio."""

from ai_core.dominio.excecoes import (
    ErroAutenticacaoProvedor,
    ErroDisjuntorAberto,
    ErroDominio,
    ErroLimiteTaxa,
    ErroModeloNaoSuportado,
)
from ai_core.dominio.modelos.agente import (
    ConfiguracaoAgente,
    PassoAgente,
    ResultadoExecucaoAgente,
)
from ai_core.dominio.modelos.ferramenta import (
    ChamadaFerramenta,
    DefinicaoFerramenta,
    ResultadoFerramenta,
)
from ai_core.dominio.modelos.geracao import (
    ConfiguracaoGeracao,
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
    UsoTokens,
)
from ai_core.dominio.modelos.mensagem import Mensagem


def test_modelos_ferramenta() -> None:
    """Verifica instanciação e integridade das entidades de ferramentas."""
    definicao = DefinicaoFerramenta(
        nome="calcular_taxa",
        descricao="Calcula taxa financeira",
        esquema_parametros={"type": "object"},
        requer_autorizacao=True,
    )
    assert definicao.nome == "calcular_taxa"
    assert definicao.requer_autorizacao is True

    chamada = ChamadaFerramenta(
        identificador="call_123",
        nome_ferramenta="calcular_taxa",
        argumentos={"valor": 100},
    )
    assert chamada.identificador == "call_123"
    assert chamada.argumentos["valor"] == 100

    resultado = ResultadoFerramenta(
        identificador_chamada="call_123",
        nome_ferramenta="calcular_taxa",
        resultado=15.0,
        sucesso=True,
    )
    assert resultado.sucesso is True
    assert resultado.resultado == 15.0


def test_modelos_geracao() -> None:
    """Verifica contratos de geração, requisição e resposta."""
    mensagem = Mensagem(papel="usuario", conteudo="Teste de geração")
    config = ConfiguracaoGeracao(temperatura=0.5, formato_json=True)
    requisicao = RequisicaoGeracao(
        modelo="modelo-teste",
        mensagens=(mensagem,),
        configuracao=config,
    )

    assert requisicao.modelo == "modelo-teste"
    assert requisicao.configuracao.formato_json is True

    resposta = RespostaGeracao(
        texto="Resposta gerada",
        modelo="modelo-teste",
        motivo_finalizacao="sucesso",
        uso=UsoTokens(tokens_entrada=10, tokens_saida=5, total_tokens=15),
    )
    assert resposta.texto == "Resposta gerada"
    assert resposta.uso.total_tokens == 15

    pedaco = PedacoResposta(texto="Parte", finalizado=False)
    assert pedaco.texto == "Parte"
    assert pedaco.finalizado is False


def test_modelos_agente() -> None:
    """Verifica modelos de configuração e resultado de agentes."""
    config_agente = ConfiguracaoAgente(
        nome="agente-pesquisa",
        instrucao_sistema="Você é um pesquisador.",
        limite_passos=5,
    )
    assert config_agente.nome == "agente-pesquisa"
    assert config_agente.limite_passos == 5

    passo = PassoAgente(
        numero_passo=1,
        pensamento="Analisando o problema",
        resposta_parcial="Prévia",
    )
    assert passo.numero_passo == 1

    resultado_agente = ResultadoExecucaoAgente(
        resposta_final="Conclusão alcançada",
        passos=(passo,),
        sucesso=True,
    )
    assert resultado_agente.sucesso is True
    assert len(resultado_agente.passos) == 1


def test_excecoes_dominio() -> None:
    """Verifica hierarquia e atributos das exceções de domínio."""
    erro_base = ErroDominio("Falha genérica", detalhes={"cod": 1})
    assert erro_base.mensagem == "Falha genérica"
    assert erro_base.detalhes["cod"] == 1

    erro_auth = ErroAutenticacaoProvedor(
        "Chave inválida", provedor="openai", codigo_status=401
    )
    assert erro_auth.provedor == "openai"
    assert erro_auth.codigo_status == 401

    erro_taxa = ErroLimiteTaxa("Rate limit", provedor="gemini", segundos_espera=30.0)
    assert erro_taxa.segundos_espera == 30.0

    erro_circuito = ErroDisjuntorAberto("circuito-ollama")
    assert erro_circuito.nome_circuito == "circuito-ollama"
    assert "aberto" in str(erro_circuito)

    erro_modelo = ErroModeloNaoSuportado("Modelo xyz indisponível")
    assert isinstance(erro_modelo, ErroDominio)
