"""Testes de segurança, concorrência sob carga, sanitização de logs e defesas de borda."""

import asyncio
import json
import logging
import os
import tempfile

import pytest
from ai_core.adaptadores.memoria.compactador_contexto import CompactadorContexto
from ai_core.adaptadores.memoria.memoria_sqlite import MemoriaSQLite
from ai_core.adaptadores.observabilidade.formatador_logs import FormatadorLogJson
from ai_core.adaptadores.provedores.simulado import AdaptadorSimulado
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.excecoes import ErroValidacao
from ai_core.dominio.modelos.mensagem import Mensagem
from ai_gateway.main import criar_aplicacao
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_concorrencia_massiva_sqlite_arquivo() -> None:
    """Verifica ausência de erros de bloqueio (database is locked) sob múltiplos acessos simultâneos."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as arquivo_temp:
        caminho_banco = arquivo_temp.name

    memoria = MemoriaSQLite(caminho_banco=caminho_banco, timeout_segundos=20.0)

    try:
        # 15 tarefas concorrentes gravando e lendo simultaneamente
        async def _tarefa_concorrente(indice: int) -> None:
            id_conv = f"sessao-concorrente-{indice % 3}"
            msg = Mensagem(papel="usuario", conteudo=f"Mensagem da tarefa {indice}")
            await memoria.salvar_mensagem(id_conv, msg)
            historico = await memoria.recuperar_historico(id_conv)
            assert len(historico) >= 1

        tarefas = [_tarefa_concorrente(i) for i in range(15)]
        await asyncio.gather(*tarefas)

        # Histórico consolidado em cada sessão
        hist_0 = await memoria.recuperar_historico("sessao-concorrente-0")
        assert len(hist_0) >= 5
    finally:
        memoria.fechar()
        if os.path.exists(caminho_banco):
            os.remove(caminho_banco)


def test_validacao_id_conversa_sqlite() -> None:
    """Valida rejeição de identificadores de conversa nulos, vazios ou excessivamente longos."""
    memoria = MemoriaSQLite(caminho_banco=":memory:")
    msg = Mensagem(papel="usuario", conteudo="Oi")

    with pytest.raises(ErroValidacao, match="não pode ser vazio"):
        memoria._salvar_sincrono("", msg)

    with pytest.raises(ErroValidacao, match="excede o limite"):
        memoria._salvar_sincrono("a" * 150, msg)

    with pytest.raises(ErroValidacao, match="caracteres nulos"):
        memoria._salvar_sincrono("id\x00malicioso", msg)

    memoria.fechar()


def test_sanitizacao_logs_credenciais_e_tokens() -> None:
    """Verifica se chaves e tokens são mascarados no payload JSON do log."""
    formatador = FormatadorLogJson(servico="seguranca-app")
    registro = logging.LogRecord(
        name="auth.modulo",
        level=logging.INFO,
        pathname="teste.py",
        lineno=10,
        msg="Chamada realizada com Bearer eyJhbGciOiJIUzI1NiJ9 e chave sk-1234567890abcdef",
        args=(),
        exc_info=None,
    )
    # Extras contendo segredos explícitos
    registro.__dict__["api_key"] = "sk-secreta-999999"
    registro.__dict__["token_autorizacao"] = "jwt.token.secreto"

    saida = formatador.format(registro)
    dados = json.loads(saida)

    # Texto da mensagem não deve ter a chave pura
    assert "sk-1234567890abcdef" not in dados["mensagem"]
    assert "[CREDENTIAL_REDACTED]" in dados["mensagem"]

    # Extras devem estar mascarados
    assert dados["api_key"] != "sk-secreta-999999"
    assert "..." in dados["api_key"] or "****" in dados["api_key"]


def test_rejeicao_payload_excessivo_gateway() -> None:
    """O gateway deve rejeitar mensagens que excedam 64 KB com status HTTP 422."""
    app = criar_aplicacao()
    client = TestClient(app)

    # Mensagem com mais de 65.536 caracteres
    conteudo_gigante = "A" * 70_000
    corpo = {
        "modelo": "modelo-teste",
        "mensagens": [{"papel": "usuario", "conteudo": conteudo_gigante}],
    }

    response = client.post("/v1/chat/conclusoes", json=corpo)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_compactador_com_preservacao_de_fatos_obrigatorios() -> None:
    """Verifica se fatos essenciais obrigatórios são passados na diretriz do compactador."""
    provedor = AdaptadorSimulado(
        modelos_suportados=("mod-sumarizador",),
        resposta_padrao="O usuário possui conta 9988 e requer respostas em JSON.",
    )
    roteador = RoteadorModelos()
    roteador.registrar_provedor(provedor)

    fatos = ("Número de conta: 9988", "Preferência: respostas em JSON")
    compactador = CompactadorContexto(
        roteador=roteador,
        modelo_sumarizacao="mod-sumarizador",
        limiar_tokens_ativacao=10,
        manter_ultimas_mensagens=1,
        fatos_essenciais_obrigatorios=fatos,
    )

    mensagens = (
        Mensagem(papel="usuario", conteudo="Mensagem longa " * 15),
        Mensagem(papel="assistente", conteudo="Resposta longa " * 15),
        Mensagem(papel="usuario", conteudo="Obrigado!"),
    )

    resultado = await compactador.compactar(mensagens)
    assert len(resultado) == 2
    msg_resumo = resultado[0]
    assert msg_resumo.metadados.get("compactado") is True
    assert msg_resumo.metadados.get("mensagens_compactadas") == 2
    assert "9988" in msg_resumo.conteudo


def test_rota_chat_estruturado_validacao_rigorosa_e_rejeicao_schema_invalido() -> None:
    """Verifica rejeição imediata se esquema_json for inválido e autocorreção se modelo desviar."""
    from ai_gateway.dependencias import obter_roteador

    app = criar_aplicacao()
    client = TestClient(app)

    # 1. Esquema JSON inválido (tipo desconhecido) -> rejeitado com 422 pelo Pydantic
    corpo_invalido = {
        "modelo": "modelo-teste",
        "mensagens": [{"papel": "usuario", "conteudo": "Gere dados"}],
        "esquema_json": {"type": "tipo_inexistente"},
    }
    resp_schema_invalido = client.post("/v1/chat/estruturado", json=corpo_invalido)
    assert resp_schema_invalido.status_code == 422

    # 2. Modelo que devolve dado fora do schema (ex: string em campo que exige inteiro)
    roteador = obter_roteador()
    provedor_desviante = AdaptadorSimulado(
        modelos_suportados=("modelo-fora-schema",),
        resposta_padrao='{"codigo": "nao_e_inteiro", "status": "ok"}',  # codigo deve ser integer
    )
    roteador.registrar_provedor(provedor_desviante)

    corpo_teste = {
        "modelo": "modelo-fora-schema",
        "mensagens": [{"papel": "usuario", "conteudo": "Status"}],
        "esquema_json": {
            "type": "object",
            "properties": {
                "codigo": {"type": "integer"},
                "status": {"type": "string"},
            },
            "required": ["codigo", "status"],
        },
        "max_tentativas": 1,
    }

    resp_desvio = client.post("/v1/chat/estruturado", json=corpo_teste)
    assert resp_desvio.status_code == 200
    dados = resp_desvio.json()
    assert dados["sucesso"] is False
    assert len(dados["erros_validacao"]) >= 1
    assert any("esperado inteiro" in e for e in dados["erros_validacao"])
