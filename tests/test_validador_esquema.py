"""Testes para o validador de domínio de JSON Schema e conformidade de dados."""

import pytest
from ai_core.dominio.excecoes import ErroValidacao
from ai_core.dominio.servicos.validador_esquema import ValidadorEsquemaJson


def test_validacao_definicao_esquema_correta() -> None:
    """Verifica aceitação de esquemas estruturados regulares."""
    validador = ValidadorEsquemaJson(profundidade_maxima=3)
    esquema_valido = {
        "type": "object",
        "properties": {
            "nome": {"type": "string"},
            "idade": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["nome", "idade"],
    }
    # Não deve levantar exceção
    validador.validar_definicao_esquema(esquema_valido)


def test_rejeicao_esquema_invalido_ou_profundidade_excessiva() -> None:
    """Verifica rejeição de tipos desconhecidos e profundidades perigosas."""
    validador = ValidadorEsquemaJson(profundidade_maxima=2)

    with pytest.raises(ErroValidacao, match="Tipo de esquema inválido"):
        validador.validar_definicao_esquema({"type": "desconhecido"})

    # Esquema aninhado além de profundidade_maxima (3 níveis > 2)
    esquema_muito_fundo = {
        "type": "object",
        "properties": {
            "nivel1": {
                "type": "object",
                "properties": {
                    "nivel2": {
                        "type": "object",
                        "properties": {"nivel3": {"type": "string"}},
                    }
                },
            }
        },
    }
    with pytest.raises(ErroValidacao, match="profundidade máxima"):
        validador.validar_definicao_esquema(esquema_muito_fundo)


def test_validacao_conformidade_dados_contra_esquema() -> None:
    """Valida identificação de erros de tipo e campos ausentes."""
    validador = ValidadorEsquemaJson()
    esquema = {
        "type": "object",
        "properties": {
            "codigo": {"type": "integer"},
            "ativo": {"type": "boolean"},
            "email": {"type": "string"},
        },
        "required": ["codigo", "email"],
    }

    # Caso 1: Dado correto
    dados_validos = {"codigo": 100, "ativo": True, "email": "teste@empresa.com"}
    erros = validador.validar_dado_contra_esquema(dados_validos, esquema)
    assert len(erros) == 0

    # Caso 2: Campo obrigatório faltando e tipo errado
    dados_invalidos = {"codigo": "nao_sou_inteiro", "ativo": "sim"}
    erros = validador.validar_dado_contra_esquema(dados_invalidos, esquema)
    assert any("campo obrigatório 'email' está ausente" in e for e in erros)
    assert any("esperado inteiro" in e for e in erros)


def test_validacao_esquema_com_defs_e_ref() -> None:
    """Verifica resolução de $defs e $ref locais e conformidade dos dados."""
    validador = ValidadorEsquemaJson()
    esquema = {
        "$defs": {
            "Endereco": {
                "type": "object",
                "properties": {
                    "rua": {"type": "string"},
                    "numero": {"type": "integer", "minimum": 1},
                },
                "required": ["rua", "numero"],
            }
        },
        "type": "object",
        "properties": {
            "cliente": {"type": "string"},
            "endereco": {"$ref": "#/$defs/Endereco"},
        },
        "required": ["cliente", "endereco"],
    }

    validador.validar_definicao_esquema(esquema)

    dado_valido = {
        "cliente": "Empresa XPTO",
        "endereco": {"rua": "Av. Paulista", "numero": 1000},
    }
    erros = validador.validar_dado_contra_esquema(dado_valido, esquema)
    assert len(erros) == 0

    dado_invalido = {
        "cliente": "Empresa XPTO",
        "endereco": {"rua": "Av. Paulista", "numero": 0},  # menor que minimum=1
    }
    erros_inv = validador.validar_dado_contra_esquema(dado_invalido, esquema)
    assert any("menor que minimum" in e for e in erros_inv)


def test_validacao_enum_e_restricoes_string_e_numero() -> None:
    """Verifica enum, minLength/maxLength e minimum/maximum."""
    validador = ValidadorEsquemaJson()
    esquema = {
        "title": "PerfilUsuario",
        "description": "Esquema com metadados e restrições detalhadas",
        "type": "object",
        "properties": {
            "status": {"enum": ["ativo", "inativo", "pendente"]},
            "apelido": {"type": "string", "minLength": 3, "maxLength": 10},
            "nota": {"type": "number", "minimum": 0.0, "maximum": 10.0},
        },
        "required": ["status", "apelido", "nota"],
    }

    validador.validar_definicao_esquema(esquema)

    dado_correto = {"status": "ativo", "apelido": "pedro", "nota": 9.5}
    assert len(validador.validar_dado_contra_esquema(dado_correto, esquema)) == 0

    dado_enum_invalido = {"status": "banido", "apelido": "joao", "nota": 5.0}
    erros_enum = validador.validar_dado_contra_esquema(dado_enum_invalido, esquema)
    assert any("não pertence aos valores permitidos no enum" in e for e in erros_enum)

    dado_string_curta = {"status": "inativo", "apelido": "al", "nota": 7.0}
    erros_str = validador.validar_dado_contra_esquema(dado_string_curta, esquema)
    assert any("menor que minLength" in e for e in erros_str)

    dado_nota_alta = {"status": "pendente", "apelido": "mariana", "nota": 15.0}
    erros_num = validador.validar_dado_contra_esquema(dado_nota_alta, esquema)
    assert any("maior que maximum" in e for e in erros_num)
