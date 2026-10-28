"""Gerenciamento de contexto, janela deslizante e contagem de tokens."""

from ai_core.dominio.modelos.mensagem import Mensagem


class GerenciadorContexto:
    """Aplica estratégias de retenção, janela deslizante e compressão de contexto."""

    def __init__(self, limite_maximo_tokens_padrao: int = 4096) -> None:
        self._limite_padrao = limite_maximo_tokens_padrao

    def estimar_tokens(self, texto: str) -> int:
        """Estima a contagem de tokens utilizando média padrão de 4 caracteres por token."""
        if not texto:
            return 0
        return max(1, len(texto) // 4)

    def estimar_tokens_mensagem(self, mensagem: Mensagem) -> int:
        """Calcula o custo aproximado de tokens de uma mensagem individual."""
        custo = self.estimar_tokens(mensagem.conteudo) + 4
        if mensagem.nome:
            custo += self.estimar_tokens(mensagem.nome)
        for cf in mensagem.chamadas_ferramentas:
            custo += (
                self.estimar_tokens(cf.nome_ferramenta) + len(str(cf.argumentos)) // 4
            )
        return custo

    def ajustar_janela(
        self,
        mensagens: tuple[Mensagem, ...],
        limite_tokens: int | None = None,
        max_mensagens: int | None = None,
    ) -> tuple[Mensagem, ...]:
        """Ajusta o histórico preservando a instrução de sistema e as mensagens mais recentes."""
        if not mensagens:
            return ()

        limite_efetivo = limite_tokens or self._limite_padrao

        mensagem_sistema: Mensagem | None = None
        mensagens_restantes: list[Mensagem] = []

        if mensagens[0].papel == "sistema":
            mensagem_sistema = mensagens[0]
            mensagens_restantes = list(mensagens[1:])
        else:
            mensagens_restantes = list(mensagens)

        if max_mensagens is not None and max_mensagens > 0:
            mensagens_restantes = mensagens_restantes[-max_mensagens:]

        tokens_gastos = (
            self.estimar_tokens_mensagem(mensagem_sistema) if mensagem_sistema else 0
        )
        mensagens_selecionadas: list[Mensagem] = []

        for m in reversed(mensagens_restantes):
            custo = self.estimar_tokens_mensagem(m)
            if tokens_gastos + custo > limite_efetivo:
                break
            mensagens_selecionadas.append(m)
            tokens_gastos += custo

        mensagens_selecionadas.reverse()

        resultado: list[Mensagem] = []
        if mensagem_sistema:
            resultado.append(mensagem_sistema)
        resultado.extend(mensagens_selecionadas)

        return tuple(resultado)
