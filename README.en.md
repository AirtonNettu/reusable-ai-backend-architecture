# Reusable AI Backend Architecture

Enterprise, decoupled, and reusable backend platform for modern Artificial Intelligence applications, autonomous agent orchestration, and high-reliability inference gateways.

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL 17](https://img.shields.io/badge/PostgreSQL-17-336791.svg)](https://www.postgresql.org/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)
[![Pytest](https://img.shields.io/badge/Tests-159%20passed-success.svg)](https://docs.pytest.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pip-audit](https://img.shields.io/badge/Security-0%20vulnerabilities-brightgreen.svg)](https://pypi.org/project/pip-audit/)

> 🇧🇷 **Versão em Português**: A versão principal desta documentação em português brasileiro está disponível em [README.md](README.md).

---

## 1. Executive Overview

**Reusable AI Backend Architecture** is an enterprise reference architecture designed to solve key bottlenecks and security vulnerabilities in modern AI applications: **proprietary SDK lock-in**, **uncontrolled token budget spills**, **cascading failures from unstable providers**, and **edge vulnerabilities (DOM XSS, IDOR, and default credential leaks)**.

Engineered around **Clean Architecture**, **Hexagonal Architecture (Ports and Adapters)**, **SOLID**, and **Modular Monolith** principles, the platform is composed of two primary modules:

1. **`AI Core` (`packages/ai-core`)**:
   - Transport-agnostic, pure Python domain library decoupled from HTTP frameworks and external vendor SDKs.
   - Abstract contracts (`PortaProvedorLLM`, `PortaRepositorioMemoria`, `PortaExecutorFerramentas`, `PortaObservabilidade`).
   - Concrete production-ready adapters for **Mock/Simulated**, **Ollama (local)**, **OpenAI**, **Google Gemini**, **Anthropic**, and **DeepSeek**.
   - Asynchronous conversational persistence in **PostgreSQL 17** (via `asyncpg` pool and versioned migrations) and **SQLite (WAL mode)** featuring **multi-tenant isolation and anti-IDOR checks**.
   - Resilient **JSON Schema validator** supporting `$defs`, `$ref`, and syntactic auto-repair.
   - Full resilience suite: **Circuit Breaker**, **Exponential Backoff Retries with Jitter**, **Two-Phase Token Reservation Protocol** (preventing TOCTOU race conditions and cancellation leaks), and **Managed Fallback**.
   - Autonomous **ReAct Agent Runtime** with loop safeguards, execution timeouts, and permission-based tool authorization.

2. **`AI Gateway` (`services/ai-gateway`)**:
   - HTTP/REST/SSE service built on **FastAPI**.
   - Canonical endpoints: `/health`, `/metrics` (Prometheus), `/v1/modelos`, `/v1/chat/conclusoes` (synchronous & SSE streaming with cancellation safety), `/v1/chat/estruturado`, `/v1/agentes/executar`, and `/v1/conversas/{id_conversa}`.
   - Defensive edge middlewares: security headers injection (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, strict `HSTS`).
   - High-entropy authentication and **Anti-Spoofing Identity Governance** via audited `X-User-ID`.
   - Dedicated **Backend-For-Frontend (BFF)** layer for the web pilot application with HMAC-SHA256 session cookies and anti-CSRF token verification.

---

## 2. Architecture Diagram

```mermaid
flowchart TD
    Client([HTTP Client / Web SPA / Mobile]) -->|REST / SSE on Port 8000| Gateway[AI Gateway - FastAPI]
    
    subgraph GatewayLayer ["AI Gateway (services/ai-gateway)"]
        MidSec["Edge Middleware: HSTS, CSP, Anti-Sniffing"]
        MidTrace["Tracing Middleware: W3C traceparent, Request-ID, Latency"]
        MidAuth["Authentication & Anti-Spoofing Validator (X-User-ID)"]
        Routes["Routes (/v1/chat, /v1/agentes, /v1/conversas, /piloto, /metrics)"]
        BFF["BFF Intermediate Layer (HMAC Sessions & Anti-CSRF)"]
    end

    Gateway --> MidSec --> MidTrace --> MidAuth --> Routes
    Routes --> BFF
    
    subgraph CoreLayer ["AI Core (packages/ai-core)"]
        UseCases["Use Cases (GenerateResponse, GenerateStream SSE, StructuredOutput)"]
        Resilience["Resilience (Circuit Breaker, Retries, Token Bucket, 2-Phase Reserve)"]
        Router["Model Router with Fallback Contingency"]
        Orchestrator["Agent Orchestrator (ReAct Cognitive Loop)"]
        ObsCore["Observability (Prometheus, OpenTelemetry & JSON Logs)"]
    end

    Routes --> UseCases & Orchestrator
    UseCases --> Resilience --> Router
    Orchestrator --> Router
    UseCases --> ObsCore
    Orchestrator --> ObsCore
    
    subgraph AdaptersLayer ["Infrastructure Adapters"]
        Providers["LLM Adapters (Simulated, Ollama, OpenAI, Gemini, Claude, DeepSeek)"]
        Postgres["MemoriaPostgresql (PostgreSQL 17 Alpine + asyncpg Pool)"]
        SQLite["MemoriaSQLite (Concurrent WAL Mode)"]
        Prometheus["Prometheus Scraper (/metrics)"]
    end

    Router --> Providers
    UseCases --> Postgres & SQLite
    ObsCore --> Prometheus
```

---

## 3. Reference Pilot Application (BFF Pattern)

The platform provides a responsive, interactive reference application served directly by the AI Gateway at:
```text
http://localhost:8000/piloto
```

Key features demonstrated with **zero financial cost**:
- **Lightweight Vanilla SPA**: Built with HTML5, modern CSS, and Vanilla JavaScript (zero Node.js/npm dependencies and client-side JavaScript externalized to `/piloto/app.js` for CSP compliance).
- **Secure BFF Architecture**: The browser never manipulates database credentials or master API keys. Communication relies on cryptographically signed HMAC-SHA256 cookies (`piloto_sessao`) and `X-CSRF-Token` headers.
- **True Relational Persistence**: Dialogues stored in **PostgreSQL 17**, surviving container restarts.
- **Anti-IDOR Verification**: Tenant switcher (`usuario_alfa` and `usuario_beta`), proving that cross-tenant access to another user's conversation is blocked relationally with **HTTP 403 Forbidden**.
- **Real-Time Telemetry**: Displays `X-Request-ID`, latency in milliseconds, and token consumption metrics.

---

## 4. Quickstart Guide (Verified Commands)

### Option A: Local Container Stack with Docker Compose (Recommended)

1. **Copy the example environment configuration**:
   ```bash
   cp .env.example .env
   ```
2. **Start the core services (AI Gateway + PostgreSQL 17)**:
   ```bash
   docker compose up -d
   ```
3. **Verify container status and healthchecks**:
   ```bash
   docker compose ps
   ```
   *Both containers (`ia-gateway` and `ia-postgres`) must report `healthy` status.*
4. **Inspect health and scrape authenticated metrics**:
   ```bash
   # Liveness healthcheck
   curl http://localhost:8000/health

   # Authenticated Prometheus metrics
   curl -H "Authorization: Bearer dev-metrics-token-12345678" http://localhost:8000/metrics
   ```
5. **Open the pilot application**:
   Open your browser at [http://localhost:8000/piloto](http://localhost:8000/piloto).
6. **Stop services while preserving database volumes**:
   ```bash
   docker compose down
   ```

---

### Option B: Native Bare-Metal Execution with `uv`

1. **Synchronize monorepo dependencies**:
   ```bash
   uv sync --all-packages
   ```
2. **Execute the automated test suite**:
   ```bash
   uv run pytest -v
   ```
3. **Run code formatter and strict linter**:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   ```
4. **Audit dependency vulnerabilities (SCA)**:
   ```bash
   uv run --with pip-audit pip-audit
   ```
5. **Start local development server with auto-reload**:
   ```bash
   uv run uvicorn ai_gateway.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## 5. Quality Assurance, Testing, and CI

Codebase reliability is backed by **159 deterministic automated tests** and continuous integration:

- **Pytest Suite**:
  - **155 passing tests** locally in isolated unit mode.
  - **4 physical integration tests** with live PostgreSQL 17 (run via disposable container).
  - **159 passing tests (100%)** in the GitHub Actions CI pipeline with live PostgreSQL 17 service.
- **Static Analysis & Linting**: 100% compliant with `ruff`.
- **Software Supply Chain Security (SCA)**: `pip-audit` runs on every CI push reporting **0 known vulnerabilities**.
- **Docker Hygiene**: `.dockerignore` excludes internal audit artifacts and skills from production images.

---

## 6. Operational Scope and Architectural Limitations

1. **In-Memory Budgeting and Rate Limiting**:
   - `PoliticaOrcamentoTokens` and `LimitadorTaxa` use in-memory asynchronous locks (`asyncio.Lock()`). In multi-replica or multi-worker deployments, quotas apply per process. Distributed clustering requires an external coordinator (e.g., Redis).
2. **Reverse Proxy Configuration for HSTS**:
   - To prevent *HSTS Spoofing* (RFC 6797 Sec 7.2), the Gateway does not trust raw `X-Forwarded-Proto` headers from direct clients. When deployed behind load balancers (Cloudflare, AWS ALB, Nginx), Uvicorn must be configured with `--proxy-headers` and `--forwarded-allow-ips`.
3. **Testing Scope**:
   - Current verification relies on deterministic unit and integration tests and static security audits with the Cloudflare Security Audit Skill. Dynamic application security testing (DAST) and distributed load tests should be conducted in staging environments prior to public exposure.

---

## 7. Specialized Documentation and Technical Ledger

Explore comprehensive engineering documentation in the [`docs/`](docs/) directory:

- 📐 [Architecture Documentation and C4 Models](docs/arquitetura.md)
- 🐳 [Infrastructure, Docker Compose, and Bare-Metal Guide](docs/infraestrutura.md)
- 🛡️ [Security, AppSec, and Conclusive Remediation](docs/seguranca.md)
- 📡 [API Contracts, REST Routes, Streaming, and BFF](docs/contratos_api.md)
- 🧪 [Automated Testing Strategy and CI Pipeline](docs/estrategia_testes.md)
- 🖥️ [Pilot Application and Intermediate BFF Layer](docs/aplicacao_piloto.md)
- 📊 [Observability, Prometheus Metrics, and OpenTelemetry Tracing](docs/observabilidade.md)
- 📚 [Technical Ledger: The Seven Engineering Pillars](docs/caderno_tecnico.md)
- 📜 [Architectural Decision Records (ADRs 0001 to 0011)](docs/adr/)

---

## 8. Transparency on AI-Assisted Development

This project was built on the frontier of **Artificial Intelligence-Assisted Software Engineering**.

- **Human Leadership & Engineering (Airton Neto)**: Business requirement definition, Clean Architecture design, governance guardrails in `AGENTS.md` (cultivated Brazilian Portuguese domain naming), rigorous code review, identification of subtle concurrency/cancellation bugs, and final merge authorization.
- **Autonomous AI Agent Implementation (Antigravity)**: Code scaffolding, concrete adapter implementations, authoring of 159 unit and integration tests, and static security audit workflows via the Cloudflare Security Audit Skill.

For an in-depth analysis of the human-AI engineering partnership, see **Pillar 7** in the [Technical Ledger](docs/caderno_tecnico.md).
