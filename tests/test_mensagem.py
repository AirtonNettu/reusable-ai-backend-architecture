"""Testes unitários do modelo de mensagem do AI Core."""

from dataclasses import FrozenInstanceError

import pytest
from ai_core.dominio.modelos.mensagem import Mensagem


def test_criar_mensagem() -> None:
    """Verifica se uma mensagem preserva os dados recebidos."""
    mensagem = Mensagem(
        papel="usuario",
        conteudo="Olá, IA!",
    )

    assert mensagem.papel == "usuario"
    assert mensagem.conteudo == "Olá, IA!"


def test_mensagem_imutavel() -> None:
    """Verifica se uma mensagem não permite alterar seus atributos."""
    mensagem = Mensagem(
        papel="usuario",
        conteudo="Olá, IA!",
    )

    with pytest.raises(FrozenInstanceError):
        mensagem.conteudo = "Mensagem alterada"
