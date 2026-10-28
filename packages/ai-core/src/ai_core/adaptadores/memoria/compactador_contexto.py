"""Compactação e sumarização inteligente de histórico com preservação de fatos essenciais."""

from ai_core.adaptadores.memoria.gerenciador_contexto import GerenciadorContexto
from ai_core.adaptadores.roteamento.roteador import RoteadorModelos
from ai_core.dominio.modelos.geracao import (
    ConfiguracaoGeracao,
    RequisicaoGeracao,
)
from ai_core.dominio.modelos.mensagem import Mensagem


class CompactadorContexto:
    """Sumariza mensagens antigas de forma inteligente para preservar a janela de contexto sem perda de fatos."""

    def __init__(
        self,
        roteador: RoteadorModelos,
        modelo_sumarizacao: str,
        limiar_tokens_ativacao: int = 2000,
        manter_ultimas_mensagens: int = 4,
        fatos_essenciais_obrigatorios: tuple[str, ...] = (),
        gerenciador_contexto: GerenciadorContexto | None = None,
    ) -> None:
        self._roteador = roteador
        self._modelo_sumarizacao = modelo_sumarizacao
        self._limiar_tokens = limiar_tokens_ativacao
        self._manter_ultimas = max(1, manter_ultimas_mensagens)
        self._fatos_essenciais = fatos_essenciais_obrigatorios
        self._gerenciador = gerenciador_contexto or GerenciadorContexto()

    async def compactar(
        self,
        mensagens: tuple[Mensagem, ...],
        fatos_adicionais: tuple[str, ...] = (),
    ) -> tuple[Mensagem, ...]:
        """Avalia e compacta o histórico preservando decisões, entidades e restrições chave."""
        if not mensagens or len(mensagens) <= self._manter_ultimas:
            return mensagens

        tokens_totais = sum(
            self._gerenciador.estimar_tokens_mensagem(m) for m in mensagens
        )
        if tokens_totais <= self._limiar_tokens:
            return mensagens

        mensagem_sistema_original: Mensagem | None = None
        mensagens_restantes = list(mensagens)

        if mensagens_restantes[0].papel == "sistema":
            mensagem_sistema_original = mensagens_restantes.pop(0)

        if len(mensagens_restantes) <= self._manter_ultimas:
            return mensagens

        mensagens_para_sumarizar = mensagens_restantes[: -self._manter_ultimas]
        mensagens_recentes = mensagens_restantes[-self._manter_ultimas :]

        texto_historico_antigo = "\n".join(
            f"{m.papel.capitalize()}: {m.conteudo}" for m in mensagens_para_sumarizar
        )

        todos_fatos = (*self._fatos_essenciais, *fatos_adicionais)
        diretriz_fatos = ""
        if todos_fatos:
            lista_fatos = "\n".join(f"- {f}" for f in todos_fatos)
            diretriz_fatos = (
                f"\nATENÇÃO: Os seguintes fatos essenciais DEVEM ser preservados explicitamente "
                f"no resumo final:\n{lista_fatos}\n"
            )

        instrucao_sintese = (
            "Você é um sintetizador especializado de contexto conversacional. "
            "Sua missão é produzir um resumo analítico preservando obrigatoriamente:\n"
            "1. Todas as decisões tomadas e regras estipuladas pelo usuário.\n"
            "2. Entidades nomeadas, identificadores, números de conta e valores acordados.\n"
            "3. Ferramentas que já foram executadas e seus resultados numéricos/fatuais relevantes.\n"
            "4. Descarte saudações e redundâncias conversacionais sem valor informativo."
            f"{diretriz_fatos}"
        )

        requisicao_sumarizacao = RequisicaoGeracao(
            modelo=self._modelo_sumarizacao,
            mensagens=(
                Mensagem(papel="sistema", conteudo=instrucao_sintese),
                Mensagem(
                    papel="usuario",
                    conteudo=f"Sintetize o seguinte histórico preservando os fatos essenciais:\n\n{texto_historico_antigo}",
                ),
            ),
            configuracao=ConfiguracaoGeracao(temperatura=0.1, max_tokens=600),
        )

        resposta = await self._roteador.gerar(requisicao_sumarizacao)
        resumo_gerado = resposta.texto.strip()

        novo_historico: list[Mensagem] = []
        if mensagem_sistema_original:
            novo_historico.append(mensagem_sistema_original)

        novo_historico.append(
            Mensagem(
                papel="sistema",
                conteudo=f"Contexto resumido da conversa anterior:\n{resumo_gerado}",
                metadados={
                    "compactado": True,
                    "mensagens_compactadas": len(mensagens_para_sumarizar),
                    "tokens_estimados_originais": tokens_totais,
                },
            )
        )
        novo_historico.extend(mensagens_recentes)

        return tuple(novo_historico)
