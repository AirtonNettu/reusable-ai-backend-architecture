# ADR 0001: Adoção de Arquitetura Híbrida Hexagonal e Monólito Modular

## Status
Aprovado

## Contexto
O projeto **Reusable AI Backend Architecture** foi concebido como uma base reutilizável corporativa para múltiplas aplicações de Inteligência Artificial, indo além de simples scripts ou wrappers ad-hoc. Precisávamos de uma estrutura que:
1. Permitisse reutilizar o núcleo lógico e de orquestração de IA em diferentes contextos (aplicações CLI, workers assíncronos, bots, lambdas) sem acoplamento forçado com o protocolo HTTP ou com o FastAPI.
2. Isolasse a camada de domínio das constantes mudanças e particularidades dos SDKs dos provedores de LLM (OpenAI, Anthropic, Google, Ollama).
3. Mantivesse simplicidade de desenvolvimento, versionamento unificado e deploy ágil sem a complexidade de múltiplos microsserviços distribuídos precocemente.

## Decisão
Adotamos uma **Arquitetura Híbrida** composta por:
- **`AI Core`**: Uma biblioteca Python modularizada em `packages/ai-core`, organizada segundo a Clean Architecture e Arquitetura Hexagonal. Seu domínio é 100% puro (sem dependência de frameworks web ou clientes HTTP).
- **`AI Gateway`**: Um serviço HTTP implementado em `services/ai-gateway` sobre FastAPI, responsável estritamente por serialização, validação, streaming SSE, autenticação e tratamento de exceções.
- **Monólito Modular gerenciado pelo `uv workspace`**: Ambas as partes residem no mesmo repositório, compartilhando ferramentas de qualidade (`ruff`, `pytest`), mas com fronteiras de dependência estritamente declaradas.

## Consequências
### Positivas
- Testabilidade isolada: o núcleo pode ser testado integralmente sem necessidade de levantar servidores HTTP ou mocks de FastAPI.
- Independência de fornecedores: provedores de LLM podem ser trocados ou atualizados sem alterar nenhuma linha de código do domínio.
- Reutilização real: o `ai-core` pode ser empacotado como biblioteca independente ou importado por outros serviços.

### Negativas
- Requer disciplina estrita na escrita de código para não importar classes da infraestrutura ou do gateway dentro do domínio.
- Criação de adaptadores de mapeamento entre objetos de domínio e esquemas Pydantic/HTTP.
