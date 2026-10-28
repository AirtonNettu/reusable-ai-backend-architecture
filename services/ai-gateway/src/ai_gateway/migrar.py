"""Utilitário de linha de comando para execução de migrações PostgreSQL idempotentes."""

import asyncio
import logging
import sys

from ai_core.adaptadores.memoria.memoria_postgresql import MemoriaPostgresql

from ai_gateway.dependencias import obter_configuracoes, obter_repositorio_memoria

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_gateway.migrar")


async def executar_migracoes_cli() -> int:
    """Executa as migrações versionadas no PostgreSQL com saída estruturada."""
    config = obter_configuracoes()

    if config.tipo_memoria != "postgresql" or not config.url_conexao_postgresql:
        logger.info(
            "Persistência configurada como '%s'. Nenhuma migração PostgreSQL necessária.",
            config.tipo_memoria,
        )
        return 0

    logger.info(
        "Conectando ao PostgreSQL em '%s' para aplicar migrações...",
        config.url_conexao_postgresql.split("@")[-1],  # Oculta credenciais no log
    )

    repositorio = obter_repositorio_memoria()
    if not isinstance(repositorio, MemoriaPostgresql):
        logger.error(
            "O repositório instanciado não é compatível com MemoriaPostgresql."
        )
        return 1

    try:
        await repositorio.executar_migracoes()
        logger.info(
            "Migrações de esquema versionadas aplicadas com sucesso no PostgreSQL."
        )
        return 0
    except Exception:
        logger.exception("Falha durante a aplicação das migrações.")
        return 1
    finally:
        await repositorio.fechar()


def main() -> None:
    """Ponto de entrada síncrono para execução via CLI."""
    codigo_saida = asyncio.run(executar_migracoes_cli())
    sys.exit(codigo_saida)


if __name__ == "__main__":
    main()
