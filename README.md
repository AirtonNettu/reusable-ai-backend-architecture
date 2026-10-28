# Reusable AI Backend Architecture

Plataforma corporativa desacoplada e reutilizável para aplicações de Inteligência Artificial moderna, orquestração de agentes e gateways HTTP de alto desempenho.

---

## 🇧🇷 Português

### 1. Visão Geral

O **Reusable AI Backend Architecture** não é um mero *wrapper* de chamadas HTTP. É uma arquitetura de nível corporativo projetada segundo os princípios de **Clean Architecture**, **Arquitetura Hexagonal (Portas e Adaptadores)**, **SOLID** e **Monólito Modular**, composta por dois módulos principais:

1. **`AI Core`** (`packages/ai-core`):
   - Núcleo de domínio e biblioteca Python independente de HTTP, transportes ou SDKs externos.
   - Contratos agnósticos para LLMs (`PortaProvedorLLM`), ferramentas (`PortaExecutorFerramentas`), memória (`PortaRepositorioMemoria`) e observabilidade (`PortaObservabilidade`).
   - Adaptadores concretos para **Ollama**, **Google Gemini**, **OpenAI**, **DeepSeek**, **Anthropic** e **Simulado (Fake/Mock)**.
   - Persistência conversacional assíncrona em **PostgreSQL** (com pool de conexões e migrações versionadas), **SQLite (modo WAL)** e volátil em memória, com **isolamento multilocatário por usuário** e proteção contra IDOR.
   - Validador seguro de **JSON Schema** com suporte a referências locais (`$defs`, `$ref`), `enum`, limites numéricos e de strings.
   - Políticas completas de confiabilidade: **Disjuntor (Circuit Breaker)**, **Retentativas com Backoff Exponencial e Jitter**, **Limitador de Taxa (Token Bucket)**, **Semáforo de Concorrência**, **Protocolo de Reserva de Tokens em Duas Fases** (prevenção contra race condition TOCTOU e cancelamento em falhas) e **Fallback Controlado**.
   - Runtime e orquestração de **Agentes Autônomos (Padrão ReAct)** com salvaguardas contra loops infinitos e controle rigoroso de permissões de ferramentas.

2. **`AI Gateway`** (`services/ai-gateway`):
   - Serviço HTTP/REST/SSE desenvolvido sobre **FastAPI**.
   - Endpoints com validação Pydantic e defesas contra DoS: `/health`, `/v1/modelos`, `/v1/chat/conclusoes` (com streaming SSE), `/v1/chat/estruturado` (JSON Schema rigoroso com autorreparo) e `/v1/agentes/executar`.
   - Middlewares globais para rastreamento (`X-Request-ID`, `X-Process-Time`) e mapeamento de exceções de domínio para respostas padronizadas (RFC 7807).
   - Autenticação e identificação multilocatário com **Proteção Anti-Spoofing** via `X-API-Key`, `Authorization: Bearer` e `X-User-ID` auditado.

---

### 2. Arquitetura

```mermaid
flowchart TD
    Cliente([Cliente HTTP / SPA / Mobile]) -->|REST / SSE| Gateway[AI Gateway - FastAPI]
    
    subgraph GatewayCamada ["AI Gateway (services/ai-gateway)"]
        Rotas["Rotas (/v1/chat, /v1/chat/estruturado, /v1/modelos, /v1/agentes)"]
        AuthMiddleware["Middleware Anti-Spoofing e Identidade (X-User-ID)"]
        ErroMiddleware["Tratamento Global de Erros (RFC 7807)"]
        Injecao["Injeção de Dependências"]
    end
    
    Gateway --> Rotas
    Rotas --> Injecao
    
    subgraph CoreCamada ["AI Core (packages/ai-core)"]
        CasosUso["Casos de Uso (GerarResposta, GerarFluxo, GerarSaidaEstruturada)"]
        Roteador["Roteador de Modelos com Contingência Fallback"]
        Resiliencia["Resiliência (Disjuntor, Retentativa, Token Bucket, Reserva 2-Fases)"]
        Orquestrador["Orquestrador de Agentes (ReAct)"]
        
        subgraph PortasContratos ["Portas do Domínio"]
            PProvedor["PortaProvedorLLM"]
            PFerramenta["PortaExecutorFerramentas"]
            PMemoria["PortaRepositorioMemoria (com id_usuario)"]
            PObserva["PortaObservabilidade"]
        end
        
        subgraph AdaptadoresConcretos ["Adaptadores de Infraestrutura"]
            AdpOllama["AdaptadorOllama"]
            AdpGemini["AdaptadorGemini"]
            AdpOpenAI["AdaptadorOpenAI"]
            AdpDeepSeek["AdaptadorDeepSeek"]
            AdpAnthropic["AdaptadorAnthropic"]
            AdpSimulado["AdaptadorSimulado"]
            RegFerramentas["RegistroFerramentas"]
            MemoriaVolatil["MemoriaEmMemoria"]
            MemoriaSQLite["MemoriaSQLite (WAL)"]
            MemoriaPG["MemoriaPostgresql (Pool & Migrações)"]
        end
    end
    
    Injecao --> CasosUso
    Injecao --> Orquestrador
    CasosUso --> Roteador
    CasosUso --> Resiliencia
    Roteador --> PProvedor
    Orquestrador --> PFerramenta
    Orquestrador --> PMemoria
    
    PProvedor -.-> AdpOllama
    PProvedor -.-> AdpGemini
    PProvedor -.-> AdpOpenAI
    PProvedor -.-> AdpDeepSeek
    PProvedor -.-> AdpAnthropic
    PProvedor -.-> AdpSimulado
    PFerramenta -.-> RegFerramentas
    PMemoria -.-> MemoriaVolatil
    PMemoria -.-> MemoriaSQLite
    PMemoria -.-> MemoriaPG
```

---

### 3. Stack Tecnológico

- **Python**: 3.13
- **FastAPI**: 0.159+
- **Pydantic**: 2.14+
- **HTTPX**: 0.28+
- **uv**: Gerenciador de workspaces e pacotes
- **pytest & pytest-asyncio**: Suíte automatizada de testes (78 testes implementados: 77 aprovados e 1 de integração real com PostgreSQL aguardando Docker)
- **Ruff**: Linter e formatador de código estático

---

### 4. Instalação e Execução

```bash
# 1. Sincronizar workspace e dependências
uv sync --all-packages

# 2. Executar suíte de testes (77 testes unitários e de integração)
uv run pytest -v

# 3. Executar verificações de linter e formatação
uv run ruff check .
uv run ruff format --check .

# 4. Iniciar o AI Gateway em desenvolvimento
uv run uvicorn ai_gateway.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🇺🇸 English

### 1. Overview

**Reusable AI Backend Architecture** is a production-grade, enterprise backend platform for Artificial Intelligence applications. Designed around **Clean Architecture**, **Hexagonal Architecture (Ports and Adapters)**, **SOLID**, and **Modular Monolith** principles, it consists of two distinct components:

1. **`AI Core`** (`packages/ai-core`):
   - Transport-agnostic Python domain library decoupled from HTTP frameworks and provider SDKs.
   - Pure domain abstractions for LLM providers (`PortaProvedorLLM`), tool execution (`PortaExecutorFerramentas`), conversational memory (`PortaRepositorioMemoria`), and observability (`PortaObservabilidade`).
   - Production adapters for **Ollama**, **Google Gemini**, **OpenAI**, **DeepSeek**, **Anthropic**, and **Mock/Simulated**.
   - Asynchronous **PostgreSQL memory (with connection pool & versioned migrations)**, **SQLite (WAL mode)**, and in-memory storage, featuring **multi-tenant user isolation** and IDOR protection.
   - Resilient **JSON Schema validator** supporting `$defs`, `$ref`, `enum`, min/max constraints, and safe metadata keywords.
   - Full resilience suite: **Circuit Breaker**, **Exponential Backoff Retries with Jitter**, **Token Bucket Rate Limiter**, **Concurrency Semaphore**, **Two-Phase Token Reservation Protocol** (preventing TOCTOU race conditions and cancellation rollbacks), and **Configured Fallback Routing**.
   - **Autonomous Agent Runtime (ReAct pattern)** with loop protection and permission-based tool security.

2. **`AI Gateway`** (`services/ai-gateway`):
   - Fast and reliable HTTP/REST/SSE service built with **FastAPI**.
   - Endpoints: `/health`, `/v1/modelos` (catalog), `/v1/chat/conclusoes` (synchronous & SSE streaming), `/v1/chat/estruturado` (JSON Schema with auto-repair), and `/v1/agentes/executar`.
   - Global tracking middleware (`X-Request-ID`, `X-Process-Time`) and RFC 7807 problem detail handlers.
   - Multi-tenant authentication with **Anti-Spoofing Security** (`X-API-Key`, `Authorization: Bearer`, audited `X-User-ID`).

### 2. Quickstart

```bash
# Install and synchronize
uv sync --all-packages

# Run full test suite (78 tests: 77 passed, 1 real PostgreSQL test awaiting Docker)
uv run pytest -v

# Check linter and formatting
uv run ruff check .
uv run ruff format --check .

# Start development server
uv run uvicorn ai_gateway.main:app --port 8000 --reload
```
