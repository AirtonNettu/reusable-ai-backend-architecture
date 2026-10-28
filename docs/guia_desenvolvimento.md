# Guia de Desenvolvimento e Integração

Este guia orienta engenheiros de software sobre como estender a plataforma com novos provedores de modelos, ferramentas de agentes, configurações e regras de resiliência.

---

## 1. Ambiente Local de Desenvolvimento

### 1.1 Pré-requisitos
- Python 3.13 ou superior.
- `uv` (gerenciador de dependências e ambientes virtuais).

### 1.2 Configuração Inicial
```bash
# Clone e navegação
cd reusable-ai-backend-architecture

# Sincronização do workspace monorepo
uv sync --all-packages

# Execução da suíte de testes
uv run pytest -v

# Checagem estática de tipos e linter
uv run ruff check .
```

---

## 2. Como Adicionar um Novo Provedor de LLM

Para integrar um novo provedor (ex: Cohere, Mistral API ou vLLM privado):

1. **Criar o Adaptador em `packages/ai-core/src/ai_core/adaptadores/provedores/`**:
   Herde de `AdaptadorProvedorHttpBase` ou implemente diretamente a `PortaProvedorLLM`.

```python
from collections.abc import AsyncIterator
from ai_core.adaptadores.provedores.base import AdaptadorProvedorHttpBase
from ai_core.dominio.modelos.geracao import (
    PedacoResposta,
    RequisicaoGeracao,
    RespostaGeracao,
    UsoTokens,
)


class AdaptadorNovoProvedor(AdaptadorProvedorHttpBase):
    def __init__(self, chave_api: str, url_base: str = "https://api.provedor.com"):
        super().__init__(
            nome_provedor="novo-provedor", url_base=url_base, chave_api=chave_api
        )

    @property
    def modelos_suportados(self) -> tuple[str, ...]:
        return ("novo-modelo-1", "novo-modelo-2")

    async def gerar(self, requisicao: RequisicaoGeracao) -> RespostaGeracao:
        cliente = self.obter_cliente()
        # Mapear requisição e disparar chamada HTTP
        ...
        return RespostaGeracao(...)

    async def gerar_fluxo(
        self, requisicao: RequisicaoGeracao
    ) -> AsyncIterator[PedacoResposta]:
        # Streaming com yield PedacoResposta(...)
        ...

    async def validar_disponibilidade(self) -> bool:
        return True
```

2. **Registrar o Provedor no Roteador**:
   Em `services/ai-gateway/src/ai_gateway/dependencias.py`, adicione o adaptador à instância do `RoteadorModelos`.

3. **Escrever Teste com `MockTransport`**:
   Adicione os testes em `tests/test_adaptadores_provedores.py` interceptando a rota sem custo financeiro.

---

## 3. Como Registrar uma Nova Ferramenta para Agentes

Para criar uma ferramenta executável por agentes:

1. Defina os metadados com `DefinicaoFerramenta`.
2. Implemente a função executora (síncrona ou assíncrona).
3. Registre no `RegistroFerramentas`:

```python
from ai_core.dominio.modelos.ferramenta import DefinicaoFerramenta
from ai_gateway.dependencias import obter_executor_ferramentas

registro = obter_executor_ferramentas()

registro.registrar(
    definicao=DefinicaoFerramenta(
        nome="consultar_clima",
        descricao="Obtém a previsão do tempo para a cidade informada.",
        esquema_parametros={
            "type": "object",
            "properties": {
                "cidade": {"type": "string", "description": "Nome da cidade"},
            },
            "required": ["cidade"],
        },
        requer_autorizacao=False,
    ),
    funcao=lambda cidade: f"O clima em {cidade} é ensolarado com 24°C.",
)
```

---

## 4. Como Configurar Variáveis de Ambiente

Crie um arquivo `.env` na raiz do projeto (não comitado):

```env
# Chave de autenticação para o AI Gateway (opcional no modo dev)
GATEWAY_API_KEY=segredo-producao-123456

# Modelo padrão do gateway
GATEWAY_MODELO_PADRAO=modelo-teste

# Chaves para provedores externos (quando em produção)
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIzaSy...
ANTHROPIC_API_KEY=sk-ant-...
DEEPSEEK_API_KEY=sk-...
```
