# Documento de Requisitos do Sistema

Este documento formaliza os requisitos funcionais, não funcionais e restrições técnicas do projeto **Reusable AI Backend Architecture**.

---

## 1. Requisitos Funcionais (RF)

| ID | Descrição | Componente Responsável |
| :--- | :--- | :--- |
| **RF-01** | Normalizar contratos agnósticos de mensagens (`Mensagem`), configurações e saídas de LLMs. | `ai_core.dominio` |
| **RF-02** | Suportar integração com múltiplos provedores: Ollama, Google Gemini, OpenAI, DeepSeek, Anthropic e Simulado. | `ai_core.adaptadores.provedores` |
| **RF-03** | Permitir envio de conclusões em modo síncrono e em fluxo contínuo (*streaming*) via Server-Sent Events (SSE). | `ai_core.aplicacao`, `ai_gateway.rotas` |
| **RF-04** | Prover roteamento dinâmico de modelos por capacidades, preferência de provedores e suporte a fallback em cadeia. | `ai_core.adaptadores.roteamento` |
| **RF-05** | Disponibilizar registro de ferramentas (*tool calling*) com validação de assinatura e verificação de permissões. | `ai_core.adaptadores.ferramentas` |
| **RF-06** | Orquestrar ciclo cognitivo ReAct de agentes autônomos com execução de ferramentas e salvaguardas de loops. | `ai_core.aplicacao.agentes` |
| **RF-07** | Gerenciar janela de contexto e histórico conversacional em memória com preservação de instruções de sistema. | `ai_core.adaptadores.memoria` |
| **RF-08** | Implementar políticas de confiabilidade: Disjuntor (*Circuit Breaker*), retentativas com *jitter*, limitador de taxa e semáforo. | `ai_core.resiliencia` |
| **RF-09** | Expor endpoints HTTP REST/SSE para saúde (`/health`), modelos (`/v1/modelos`), chat (`/v1/chat/conclusoes`) e agentes (`/v1/agentes/executar`). | `ai_gateway.rotas` |
| **RF-10** | Fornecer autenticação configurável via cabeçalho `X-API-Key` ou `Authorization: Bearer`. | `ai_gateway.seguranca` |

---

## 2. Requisitos Não Funcionais (RNF)

| ID | Descrição | Métrica / Critério de Aceitação |
| :--- | :--- | :--- |
| **RNF-01** | **Desacoplamento de Domínio**: O domínio do `AI Core` não possui dependência de HTTPX, FastAPI ou SDKs externos. | Verificado estaticamente via imports. |
| **RNF-02** | **Padronização Idiomática**: Identificadores próprios em português brasileiro culto. | Auditoria de código e linter. |
| **RNF-03** | **Resiliência e Tolerância a Falhas**: Falhas transitórias no provedor primário não derrubam a aplicação. | Disjuntor abre em 5 falhas; fallback assume; cobertura em testes. |
| **RNF-04** | **Observabilidade**: Todas as requisições geram `X-Request-ID` e métricas de tempo em `X-Process-Time`. | Validado nos testes de integração. |
| **RNF-05** | **Zero Custo de Testes**: A suíte automatizada roda 100% com fakes e `MockTransport` sem consumir APIs pagas. | Suíte unitária e de integração em < 2s sem rede externa. |

---

## 3. Restrições Técnicas

- Python 3.13 ou superior.
- FastAPI e Pydantic v2.
- Gerenciamento unificado via workspace `uv`.
- Não utilizar chamadas a serviços externos tarifados durante desenvolvimento ou testes.
