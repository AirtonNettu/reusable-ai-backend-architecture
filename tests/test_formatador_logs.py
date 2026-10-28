"""Testes para o formatador de logs estruturados em JSON."""

import json
import logging

from ai_core.adaptadores.observabilidade.formatador_logs import FormatadorLogJson


def test_formatador_log_json_campos_padrao() -> None:
    """Verifica se o formatador produz JSON com campos canônicos."""
    formatador = FormatadorLogJson(servico="teste-servico")
    registro = logging.LogRecord(
        name="modulo.teste",
        level=logging.INFO,
        pathname="teste.py",
        lineno=42,
        msg="Operação realizada com sucesso",
        args=(),
        exc_info=None,
    )
    # Atribui campo extra
    registro.__dict__["id_requisicao"] = "req-999"

    saida_formatada = formatador.format(registro)
    dados = json.loads(saida_formatada)

    assert dados["servico"] == "teste-servico"
    assert dados["nivel"] == "INFO"
    assert dados["mensagem"] == "Operação realizada com sucesso"
    assert dados["linha"] == 42
    assert dados["id_requisicao"] == "req-999"
    assert "timestamp" in dados
