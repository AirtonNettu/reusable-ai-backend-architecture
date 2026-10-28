"""Rota de verificação de integridade (health check)."""

from fastapi import APIRouter

roteador_saude = APIRouter(tags=["Saúde"])


@roteador_saude.get("/health")
def verificar_saude() -> dict[str, str]:
    """Retorna o status operacional do gateway."""
    return {"status": "ok"}
