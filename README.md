# Reusable AI Backend Architecture

Plataforma corporativa desacoplada e reutilizável para aplicações de Inteligência Artificial moderna, orquestração de agentes autônomos e gateways de inferência de alta confiabilidade.

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL 17](https://img.shields.io/badge/PostgreSQL-17-336791.svg)](https://www.postgresql.org/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)
[![Pytest](https://img.shields.io/badge/Tests-159%20passed-success.svg)](https://docs.pytest.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pip-audit](https://img.shields.io/badge/Security-0%20vulnerabilities-brightgreen.svg)](https://pypi.org/project/pip-audit/)

> 🌐 **English Version**: An equivalent English version of this documentation is available at [README.en.md](README.en.md).

---

## 1. Visão Geral Executiva

O **Reusable AI Backend Architecture** é uma arquitetura de referência corporativa concebida para resolver os principais gargalos e riscos de segurança da indústria de Inteligência Artificial: **acoplamento proprietário de SDKs**, **estouro orçamentário descontrolado de tokens**, **falhas em cascata de provedores instáveis** e **vulnerabilidades de borda (DOM XSS, IDOR e injeção de credenciais)**.

Construído sob os princípios de **Clean Architecture**, **Arquitetura Hexagonal (Portas e Adaptadores)**, **SOLID** e **Monólito Modular**, o projeto é composto por dois módulos principais:

1. **`AI Core` (`packages/ai-core`)**:
   - Biblioteca Python de domínio puro, desacoplada de frameworks HTTP e SDKs proprietários.
   - Contratos abstratos agnósticos (`PortaProvedorLLM`, `PortaRepositorioMemoria`, `PortaExecutorFerramentas`, `PortaObservabilidade`).
   - Adaptadores concretos para **Simulado (Mock)**, **Ollama (local)**, **OpenAI**, **Google Gemini**, **Anthropic** e **DeepSeek**.
   - Persistência conversacional assíncrona em **PostgreSQL 17** (com pool `asyncpg` e migrações versionadas) e **SQLite (modo WAL)** com **isolamento multilocatário e proteção anti-IDOR**.
   - Validador rigoroso de **JSON Schema** com suporte a referências locais (`$defs`, `$ref`) e autorreparo sintático.
   - Suite de resiliência: **Disjuntor (*Circuit Breaker*)**, **Retentativas com Backoff Exponencial e Jitter**, **Protocolo de Reserva de Tokens em Duas Fases** (prevenção contra estouro de cota por requisições concorrentes TOCTOU) e **Fallback Controlado**.
   - Runtime de **Agentes Autônomos (Padrão ReAct)** com limites de passos, timeout e governança de autorização de ferramentas.

2. **`AI Gateway` (`services/ai-gateway`)**:
   - Serviço HTTP/REST/SSE desenvolvido sobre **FastAPI**.
   - Endpoints canônicos: `/health`, `/metrics` (Prometheus), `/v1/modelos`, `/v1/chat/conclusoes` (síncrono e streaming SSE com cancelamento seguro), `/v1/chat/estruturado`, `/v1/agentes/executar` e `/v1/conversas/{id_conversa}`.
   - Middlewares defensivos de borda: injeção de cabeçalhos de segurança (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `HSTS` estrito).
   - Autenticação de alta entropia e **Proteção Anti-Spoofing** via auditoria rigorosa de `X-User-ID`.
   - Camada intermediária **BFF (Backend-For-Frontend)** para a aplicação piloto web com sessão assinada criptograficamente (HMAC-SHA256) e tokens anti-CSRF.

---

## 2. Diagrama de Arquitetura

```mermaid
flowchart TD
    Cliente([Cliente HTTP / SPA do Piloto / Mobile]) -->|REST / SSE na porta 8000| Gateway[AI Gateway - FastAPI]
    
    subgraph GatewayCamada ["AI Gateway (services/ai-gateway)"]
        MidSec["Middleware de Borda: HSTS, CSP, Anti-Sniffing"]
        MidTrace["Middleware Rastreamento: W3C traceparent, Request-ID, Latência"]
        MidAuth["Validador de Autenticação e Anti-Spoofing (X-User-ID)"]
        Rotas["Rotas (/v1/chat, /v1/agentes, /v1/conversas, /piloto, /metrics)"]
        BFF["Camada Intermediária BFF (Sessão HMAC e Anti-CSRF)"]
    end

    Gateway --> MidSec --> MidTrace --> MidAuth --> Rotas
    Rotas --> BFF
    
    subgraph CoreCamada ["AI Core (packages/ai-core)"]
        CasosUso["Casos de Uso (GerarResposta, GerarFluxo SSE, SaidaEstruturada)"]
        Resiliencia["Resiliência (Disjuntor, Retentativa, Token Bucket, Reserva 2-Fases)"]
        Roteador["Roteador de Modelos com Contingência Fallback"]
        Orquestrador["Orquestrador de Agentes (Ciclo Cognitivo ReAct)"]
        ObsCore["Observabilidade (Prometheus, OpenTelemetry & Logs JSON)"]
    end

    Rotas --> CasosUso & Orquestrador
    CasosUso --> Resiliencia --> Roteador
    Orquestrador --> Roteador
    CasosUso --> ObsCore
    Orquestrador --> ObsCore
    
    subgraph AdaptadoresCamada ["Adaptadores de Infraestrutura"]
        Provedores["Adaptadores LLM (Simulado, Ollama, OpenAI, Gemini, Claude, DeepSeek)"]
        Postgres["MemoriaPostgresql (PostgreSQL 17 Alpine + Pool asyncpg)"]
        SQLite["MemoriaSQLite (Modo WAL Concorrente)"]
        Prometheus["Prometheus Scraper (/metrics)"]
    end

    Roteador --> Provedores
    CasosUso --> Postgres & SQLite
    ObsCore --> Prometheus
```

---

## 3. Demonstração Prática: Aplicação Piloto (BFF)

A arquitetura inclui uma aplicação piloto responsiva servida diretamente pelo AI Gateway em:
```text
http://localhost:8000/piloto
```

Principais capacidades demonstradas na prática com **custo financeiro zero**:
- **Interface SPA Leve**: Construída em HTML5, CSS3 moderno e Vanilla JavaScript (sem dependências de Node.js/npm e com JavaScript externalizado em `/piloto/app.js` para conformidade com CSP).
- **Camada Intermediária Segura (BFF)**: O navegador nunca manipula chaves mestras nem credenciais SQL. Toda comunicação com o backend ocorre através de cookies de sessão assinados com HMAC-SHA256 (`piloto_sessao`) e tokens `X-CSRF-Token`.
- **Persistência Relacional Real**: Diálogos mantidos no **PostgreSQL 17**, sobrevivendo à reinicialização de contêineres.
- **Comprovação Anti-IDOR**: Alternador demonstrativo de perfis (`usuario_alfa` e `usuario_beta`), comprovando que o acesso cruzado ao histórico de outro usuário é bloqueado relacionalmente com **HTTP 403 Forbidden**.
- **Telemetria Visível**: Exibição em tempo real de `X-Request-ID`, tempo de latência em milissegundos e contagem real de tokens processados.

---

## 4. Guia de Início Rápido (Comandos Verificados)

### Opção A: Execução Conteinerizada via Docker Compose (Recomendada)

1. **Copiar o arquivo de exemplo de ambiente**:
   ```bash
   cp .env.example .env
   ```
2. **Iniciar os serviços centrais (AI Gateway + PostgreSQL 17)**:
   ```bash
   docker compose up -d
   ```
3. **Verificar o status dos serviços e das sondas de saúde (healthchecks)**:
   ```bash
   docker compose ps
   ```
   *Ambos os contêineres (`ia-gateway` e `ia-postgres`) devem apresentar status `healthy`.*
4. **Validar a API e inspecionar métricas**:
   ```bash
   # Teste de vivacidade do Gateway
   curl http://localhost:8000/health

   # Teste de métricas Prometheus autenticadas
   curl -H "Authorization: Bearer dev-metrics-token-12345678" http://localhost:8000/metrics
   ```
5. **Acessar a interface web**:
   Abra seu navegador em [http://localhost:8000/piloto](http://localhost:8000/piloto).
6. **Encerrar a execução preservando os dados**:
   ```bash
   docker compose down
   ```

---

### Opção B: Execução Nativa Bare-Metal com `uv`

1. **Sincronizar dependências do monorrepositório**:
   ```bash
   uv sync --all-packages
   ```
2. **Executar a suíte completa de testes automatizados**:
   ```bash
   uv run pytest -v
   ```
3. **Validar linter e formatação estrita**:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   ```
4. **Auditar vulnerabilidades de dependências (SCA)**:
   ```bash
   uv run --with pip-audit pip-audit
   ```
5. **Iniciar o servidor de desenvolvimento**:
   ```bash
   uv run uvicorn ai_gateway.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## 5. Garantia de Qualidade, Testes e CI

A confiabilidade da base de código é validada por **159 testes automatizados determinísticos** e integração contínua rigorosa:

- **Bateria Pytest**:
  - **155 testes aprovados** localmente em modo unitário/isolado.
  - **4 testes de integração física** com o banco PostgreSQL 17 real (executados com contêiner descartável).
  - **159 testes aprovados (100%)** na esteira de CI do GitHub Actions com PostgreSQL 17 real como serviço.
- **Análise Estática e Linter**: 100% aprovado pelo `ruff` sem alertas.
- **Segurança da Cadeia de Suprimentos (SCA)**: `pip-audit` executado no CI com **0 vulnerabilidades conhecidas**.
- **Higiene Docker**: `.dockerignore` configurado para impedir o envio acidental de arquivos de auditoria ou testes para o contêiner de produção.

---

## 6. Limitações e Escopo Operacional

1. **Controle Orçamentário em Processo Local**:
   - A `PoliticaOrcamentoTokens` e o `LimitadorTaxa` utilizam locks em memória volátil (`asyncio.Lock()`). Em implantações horizontais com múltiplos contêineres/pods ou múltiplos workers, as quotas são aplicadas por processo, não garantindo teto consolidado sem um coordenador de estado distribuído (ex: Redis).
2. **Terminação TLS e Reverse Proxies de Borda**:
   - Para prevenir *HSTS Spoofing* (RFC 6797 Sec 7.2), o Gateway não confia cegamente no cabeçalho `X-Forwarded-Proto` de clientes diretos. Em topologias corporativas atrás de balanceadores/proxies (Cloudflare, AWS ALB, Nginx), o servidor Uvicorn deve ser configurado com `--proxy-headers` e `--forwarded-allow-ips`.
3. **Escopo dos Testes**:
   - A qualidade é comprovada por testes determinísticos, testes de integração e auditoria estática com a Cloudflare Security Audit Skill. Testes dinâmicos de carga (DAST) e testes de estresse distribuídos devem ser conduzidos em ambiente de homologação dedicado.

---

## 7. Documentação Especializada e Caderno Técnico

Explore os guias detalhados no diretório [`docs/`](docs/):

- 📐 [Documentação de Arquitetura e Modelos C4](docs/arquitetura.md)
- 🐳 [Guia de Infraestrutura, Docker e Execução Bare-Metal](docs/infraestrutura.md)
- 🛡️ [Guia de Segurança, AppSec e Remediação Conclusiva](docs/seguranca.md)
- 📡 [Contratos de API, Rotas REST, Streaming e BFF](docs/contratos_api.md)
- 🧪 [Estratégia de Testes Automatizados e CI](docs/estrategia_testes.md)
- 🖥️ [Guia da Aplicação Piloto e Camada Intermediária](docs/aplicacao_piloto.md)
- 📊 [Observabilidade, Métricas Prometheus e Tracing OpenTelemetry](docs/observabilidade.md)
- 📚 [Caderno Técnico nos Sete Pilares da Engenharia](docs/caderno_tecnico.md)
- 📜 [Registros de Decisão de Arquitetura (ADRs 0001 a 0011)](docs/adr/)

---

## 8. Transparência sobre o Desenvolvimento Assistido por IA

Este projeto foi construído na fronteira da **Engenharia de Software Assistida por Inteligência Artificial**. 

- **Engenharia e Liderança Humana (Airton Neto)**: Concepção dos requisitos de negócio, definição da Clean Architecture, imposição das regras de governança e nomenclatura em português culto (`AGENTS.md`), code review rigoroso, detecção de falhas sutis de concorrência e autorização das decisões de merge.
- **Implementação por Agentes Autônomos de IA (Antigravity)**: Geração do scaffolding de código, implementação dos adaptadores, redação de 159 testes unitários/integração e execução do roteiro de auditoria estática com a Cloudflare Security Audit Skill.

Para uma análise detalhada sobre o modelo de parceria humano-IA, consulte o **Pilar 7** do [Caderno Técnico](docs/caderno_tecnico.md).
