"""Política de segurança e autorização para execução de ferramentas."""

from ai_core.dominio.excecoes import ErroFerramentaNaoAutorizada
from ai_core.dominio.modelos.ferramenta import ChamadaFerramenta, DefinicaoFerramenta


class PoliticaAutorizacaoFerramenta:
    """Valida e autoriza chamadas a ferramentas de acordo com regras de segurança."""

    def __init__(
        self,
        ferramentas_bloqueadas: set[str] | None = None,
        ferramentas_aprovadas: set[str] | None = None,
    ) -> None:
        self._bloqueadas = ferramentas_bloqueadas or set()
        self._aprovadas = ferramentas_aprovadas or set()

    def autorizar(
        self, definicao: DefinicaoFerramenta, chamada: ChamadaFerramenta
    ) -> None:
        """Verifica se a ferramenta está liberada para execução imediata."""
        if chamada.nome_ferramenta in self._bloqueadas:
            raise ErroFerramentaNaoAutorizada(
                f"A ferramenta '{chamada.nome_ferramenta}' está explicitamente bloqueada."
            )

        if (
            definicao.requer_autorizacao
            and chamada.nome_ferramenta not in self._aprovadas
        ):
            raise ErroFerramentaNaoAutorizada(
                f"A ferramenta '{chamada.nome_ferramenta}' requer aprovação humana ou token de autorização."
            )

    def aprovar_ferramenta(self, nome_ferramenta: str) -> None:
        """Concede aprovação a uma ferramenta que requer autorização prévia."""
        self._aprovadas.add(nome_ferramenta)

    def revogar_aprovacao(self, nome_ferramenta: str) -> None:
        """Revoga aprovação previamente concedida."""
        self._aprovadas.discard(nome_ferramenta)
