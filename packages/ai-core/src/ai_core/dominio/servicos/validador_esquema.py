"""Serviço de domínio para validação segura de JSON Schema e conformidade de dados."""

from typing import Any

from ai_core.dominio.excecoes import ErroValidacao

TIPOS_JSON_VALIDOS = {"string", "number", "integer", "boolean", "array", "object"}
PALAVRAS_CHAVE_IGNORADAS_SEGURAS = {
    "$schema",
    "title",
    "description",
    "default",
    "examples",
    "additionalProperties",
    "format",
    "$comment",
}


class ValidadorEsquemaJson:
    """Valida a estrutura do JSON Schema e a conformidade dos dados recebidos.

    Oferece suporte a tipos aninhados, referências locais ($defs e definitions),
    restrições de enum, minLength/maxLength e minimum/maximum.
    """

    def __init__(self, profundidade_maxima: int = 7) -> None:
        self._profundidade_maxima = profundidade_maxima

    def _resolver_referencia(
        self, ref: str, esquema_raiz: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve referências locais URI-pointer como '#/$defs/Nome' ou '#/definitions/Nome'."""
        if not ref.startswith("#/"):
            raise ErroValidacao(
                f"Apenas referências locais iniciando com '#/' são permitidas: '{ref}'."
            )

        segmentos = ref[2:].split("/")
        cursor: Any = esquema_raiz
        for seg in segmentos:
            if not isinstance(cursor, dict) or seg not in cursor:
                raise ErroValidacao(
                    f"Referência '{ref}' não encontrada no esquema raiz."
                )
            cursor = cursor[seg]

        if not isinstance(cursor, dict):
            raise ErroValidacao(
                f"Referência '{ref}' não aponta para um sub-esquema válido."
            )
        return cursor

    def validar_definicao_esquema(
        self,
        esquema: dict[str, Any],
        profundidade_atual: int = 0,
        esquema_raiz: dict[str, Any] | None = None,
    ) -> None:
        """Assegura que o esquema seja um JSON Schema sintaticamente seguro e não recursivo."""
        if profundidade_atual > self._profundidade_maxima:
            raise ErroValidacao(
                f"Esquema JSON excede a profundidade máxima permitida ({self._profundidade_maxima})."
            )

        if not isinstance(esquema, dict):
            raise ErroValidacao(
                "A definição do esquema deve ser um objeto JSON (dicionário)."
            )

        raiz_efetiva = esquema_raiz if esquema_raiz is not None else esquema

        # Validação de $defs e definitions no nó raiz
        if profundidade_atual == 0:
            for chave_defs in ("$defs", "definitions"):
                defs = esquema.get(chave_defs)
                if defs is not None:
                    if not isinstance(defs, dict):
                        raise ErroValidacao(
                            f"O campo '{chave_defs}' deve ser um dicionário de definições."
                        )
                    for sub_def in defs.values():
                        self.validar_definicao_esquema(
                            sub_def,
                            profundidade_atual=profundidade_atual + 1,
                            esquema_raiz=raiz_efetiva,
                        )

        # Se houver referência $ref, valida resolução
        if "$ref" in esquema:
            ref = esquema["$ref"]
            if not isinstance(ref, str):
                raise ErroValidacao("O campo '$ref' deve ser uma string.")
            sub_esquema_resolvido = self._resolver_referencia(ref, raiz_efetiva)
            self.validar_definicao_esquema(
                sub_esquema_resolvido,
                profundidade_atual=profundidade_atual + 1,
                esquema_raiz=raiz_efetiva,
            )
            return

        # Checa tipo declarado ou presença de enum
        tipo = esquema.get("type")
        tem_enum = "enum" in esquema

        if not tipo and not tem_enum:
            raise ErroValidacao(
                "Definição de esquema deve declarar 'type', 'enum' ou '$ref'."
            )

        if tipo is not None and tipo not in TIPOS_JSON_VALIDOS:
            raise ErroValidacao(
                f"Tipo de esquema inválido: '{tipo}'. Tipos permitidos: {TIPOS_JSON_VALIDOS}"
            )

        if tem_enum and not isinstance(esquema["enum"], (list, tuple)):
            raise ErroValidacao("O campo 'enum' deve ser uma lista ou tupla.")

        # Validações de limites numéricos
        if "minimum" in esquema and not isinstance(esquema["minimum"], (int, float)):
            raise ErroValidacao("O campo 'minimum' deve ser um número.")
        if "maximum" in esquema and not isinstance(esquema["maximum"], (int, float)):
            raise ErroValidacao("O campo 'maximum' deve ser um número.")

        # Validações de tamanho de string
        if "minLength" in esquema and (
            not isinstance(esquema["minLength"], int) or esquema["minLength"] < 0
        ):
            raise ErroValidacao("O campo 'minLength' deve ser um inteiro não negativo.")
        if "maxLength" in esquema and (
            not isinstance(esquema["maxLength"], int) or esquema["maxLength"] < 0
        ):
            raise ErroValidacao("O campo 'maxLength' deve ser um inteiro não negativo.")

        if tipo == "object":
            propriedades = esquema.get("properties")
            if propriedades is not None:
                if not isinstance(propriedades, dict):
                    raise ErroValidacao("O campo 'properties' deve ser um dicionário.")
                for nome_prop, sub_esquema in propriedades.items():
                    if not isinstance(nome_prop, str) or not nome_prop:
                        raise ErroValidacao(
                            "Nomes de propriedades devem ser strings não vazias."
                        )
                    self.validar_definicao_esquema(
                        sub_esquema,
                        profundidade_atual=profundidade_atual + 1,
                        esquema_raiz=raiz_efetiva,
                    )

            obrigatorios = esquema.get("required")
            if obrigatorios is not None:
                if not isinstance(obrigatorios, (list, tuple)):
                    raise ErroValidacao(
                        "O campo 'required' deve ser uma lista de strings."
                    )
                for item in obrigatorios:
                    if not isinstance(item, str):
                        raise ErroValidacao(
                            "Itens do campo 'required' devem ser strings."
                        )

        elif tipo == "array":
            itens = esquema.get("items")
            if itens is not None:
                self.validar_definicao_esquema(
                    itens,
                    profundidade_atual=profundidade_atual + 1,
                    esquema_raiz=raiz_efetiva,
                )

    def validar_dado_contra_esquema(
        self,
        dado: Any,
        esquema: dict[str, Any],
        caminho: str = "$",
        esquema_raiz: dict[str, Any] | None = None,
    ) -> list[str]:
        """Verifica se o dado gerado satisfaz as restrições declaradas no esquema."""
        raiz_efetiva = esquema_raiz if esquema_raiz is not None else esquema
        erros: list[str] = []

        # Se houver $ref, resolve o esquema de destino
        if "$ref" in esquema:
            try:
                esquema_resolvido = self._resolver_referencia(
                    esquema["$ref"], raiz_efetiva
                )
                return self.validar_dado_contra_esquema(
                    dado, esquema_resolvido, caminho=caminho, esquema_raiz=raiz_efetiva
                )
            except ErroValidacao as e:
                erros.append(f"{caminho}: falha na resolução de $ref: {e.mensagem}")
                return erros

        # Validação de enum
        if "enum" in esquema and dado not in esquema["enum"]:
            erros.append(
                f"{caminho}: valor '{dado}' não pertence aos valores permitidos no enum: {esquema['enum']}."
            )

        tipo_esperado = esquema.get("type")

        # Checagem de tipos e restrições específicas
        if tipo_esperado == "string":
            if not isinstance(dado, str):
                erros.append(
                    f"{caminho}: esperado string, recebido {type(dado).__name__}."
                )
            else:
                if "minLength" in esquema and len(dado) < esquema["minLength"]:
                    erros.append(
                        f"{caminho}: tamanho da string ({len(dado)}) menor que minLength ({esquema['minLength']})."
                    )
                if "maxLength" in esquema and len(dado) > esquema["maxLength"]:
                    erros.append(
                        f"{caminho}: tamanho da string ({len(dado)}) maior que maxLength ({esquema['maxLength']})."
                    )

        elif tipo_esperado == "integer":
            if not isinstance(dado, int) or isinstance(dado, bool):
                erros.append(
                    f"{caminho}: esperado inteiro, recebido {type(dado).__name__}."
                )
            else:
                if "minimum" in esquema and dado < esquema["minimum"]:
                    erros.append(
                        f"{caminho}: valor ({dado}) menor que minimum ({esquema['minimum']})."
                    )
                if "maximum" in esquema and dado > esquema["maximum"]:
                    erros.append(
                        f"{caminho}: valor ({dado}) maior que maximum ({esquema['maximum']})."
                    )

        elif tipo_esperado == "number":
            if not isinstance(dado, (int, float)) or isinstance(dado, bool):
                erros.append(
                    f"{caminho}: esperado número, recebido {type(dado).__name__}."
                )
            else:
                if "minimum" in esquema and dado < esquema["minimum"]:
                    erros.append(
                        f"{caminho}: valor ({dado}) menor que minimum ({esquema['minimum']})."
                    )
                if "maximum" in esquema and dado > esquema["maximum"]:
                    erros.append(
                        f"{caminho}: valor ({dado}) maior que maximum ({esquema['maximum']})."
                    )

        elif tipo_esperado == "boolean" and not isinstance(dado, bool):
            erros.append(
                f"{caminho}: esperado booleano, recebido {type(dado).__name__}."
            )

        elif tipo_esperado == "array":
            if not isinstance(dado, list):
                erros.append(
                    f"{caminho}: esperado lista (array), recebido {type(dado).__name__}."
                )
            else:
                sub_esquema = esquema.get("items")
                if sub_esquema:
                    for i, item in enumerate(dado):
                        erros.extend(
                            self.validar_dado_contra_esquema(
                                item,
                                sub_esquema,
                                caminho=f"{caminho}[{i}]",
                                esquema_raiz=raiz_efetiva,
                            )
                        )

        elif tipo_esperado == "object":
            if not isinstance(dado, dict):
                erros.append(
                    f"{caminho}: esperado objeto (dict), recebido {type(dado).__name__}."
                )
            else:
                # Checa campos obrigatórios
                obrigatorios = esquema.get("required", [])
                for campo in obrigatorios:
                    if campo not in dado:
                        erros.append(
                            f"{caminho}: campo obrigatório '{campo}' está ausente."
                        )

                # Valida propriedades existentes contra sub-esquemas
                propriedades = esquema.get("properties", {})
                for chave, valor in dado.items():
                    if chave in propriedades:
                        erros.extend(
                            self.validar_dado_contra_esquema(
                                valor,
                                propriedades[chave],
                                caminho=f"{caminho}.{chave}",
                                esquema_raiz=raiz_efetiva,
                            )
                        )

        return erros
