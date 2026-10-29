# Reusable AI Backend Architecture

Plataforma corporativa desacoplada e reutilizável para aplicações de Inteligência Artificial moderna, orquestração de agentes autônomos e gateways de inferência de alta confiabilidade.

> 🌐 **English Version**: An equivalent English version of this documentation is available at [README.en.md](README.en.md).

<p align="center">
  <img src="docs/image/apresentacao.png" alt="Reusable AI Backend Architecture - Apresentação Executiva" width="100%" />
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.13-blue.svg" alt="Python 3.13" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.115+-009688.svg" alt="FastAPI" /></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-17-336791.svg" alt="PostgreSQL 17" /></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-Compose-2496ED.svg" alt="Docker Compose" /></a>
  <a href="https://docs.pytest.org/"><img src="https://img.shields.io/badge/Tests-159%20passed-success.svg" alt="Pytest" /></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff" /></a>
  <a href="https://pypi.org/project/pip-audit/"><img src="https://img.shields.io/badge/Security-0%20vulnerabilities-brightgreen.svg" alt="pip-audit" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue.svg" alt="License: Apache-2.0" /></a>
</p>

---

## 1. Visão Geral: Problema e Solução

Quando uma organização decide incorporar Inteligência Artificial Generativa em seus produtos digitais, o foco da equipe costuma convergir imediatamente para a seleção de modelos e a redação de prompts. No entanto, em ambientes corporativos de produção, as falhas mais críticas raramente se originam na qualidade da inferência do modelo; elas derivam da **ausência de engenharia de software defensiva no backend**.

### O Problema
Sistemas de IA construídos sem uma fundação arquitetural robusta enfrentam riscos severos:
- **Acoplamento Proprietário de SDKs (*Vendor Lock-in*)**: Código de aplicação amarrado a bibliotecas de provedores comerciais específicos, inviabilizando migrações rápidas ou contingências em caso de quedas de provedores externos.
- **Estouro Orçamentário Descontrolado (Condições de Corrida TOCTOU)**: Validação de saldos e cotas realizada após a chamada (*post-billing*), permitindo que requisições assíncronas concorrentes esgotem e ultrapassem o orçamento financeiro do locatário.
- **Falhas em Cascata e Indisponibilidade**: Ausência de disjuntores (*circuit breakers*) e retentativas exponenciais, fazendo com que instabilidades momentâneas de APIs externas derrubem os serviços de borda.
- **Vulnerabilidades Críticas de Borda**: Exposição de chaves mestras de API no navegador do usuário, ataques de falsificação de requisições (CSRF), injeção de scripts (DOM XSS) e vulnerabilidades de autorização direta em histórico (IDOR).

### A Solução
O **Reusable AI Backend Architecture** resolve esses desafios estruturais através de uma arquitetura de referência em **Monólito Modular**, construída sob os princípios da **Clean Architecture**, **Arquitetura Hexagonal (Portas e Adaptadores)** e **SOLID**:
- **Desacoplamento Total**: O domínio de IA (`AI Core`) é uma biblioteca Python pura, livre de frameworks de transporte HTTP e dependências de SDKs de nuvem.
- **Reserva Atômica de Tokens em Duas Fases**: A cota estimada é retida antes do envio da requisição e liquidada com o consumo real no encerramento, mitigando condições de corrida TOCTOU intraprocesso.
- **Resiliência e Tolerância a Falhas**: Disjuntor integrado, retentativa exponencial com jitter e fallback automático transparente entre modelos registrados.
- **Persistência Confiável e Anti-IDOR**: Histórico persistido de forma durável no **PostgreSQL 17**, com checagem relacional estrita de propriedade por usuário.
- **Observabilidade Contínua**: Métricas Prometheus padronizadas de baixa cardinalidade e rastreamento distribuído OpenTelemetry (W3C TraceContext).
- **Custo Zero para Desenvolvimento**: Operação e suíte de testes 100% executáveis localmente via `AdaptadorSimulado` ou inferência local com `Ollama`.

---

## 2. Funcionalidades Efetivamente Implementadas

Todas as capacidades listadas abaixo estão **implementadas no código-fonte, conteinerizadas e validadas por testes automatizados**:

- [x] **Monólito Modular Desacoplado**: Separação física e lógica entre domínio puro de IA (`packages/ai-core`) e serviço de borda HTTP (`services/ai-gateway`).
- [x] **Casos de Uso de Inferência de IA**:
  - Inferência síncrona com registro de latência e tokens.
  - Streaming assíncrono via **Server-Sent Events (SSE)** com tratamento de `BaseException` (`asyncio.CancelledError`) para liberação segura de reservas em caso de desconexão do cliente.
  - Geração estruturada com validação estrita de **JSON Schema**, resolução de referências `$defs`/`$ref` e autorreparo sintático de delimitadores de Markdown.
- [x] **Runtime de Agentes Autônomos (Padrão ReAct)**:
  - Loop cognitivo padronizado (*Thought &rarr; Action &rarr; Observation*).
  - Salvaguardas rigorosas: limite máximo de passos finitos (teto padrão de 10 iterações), controle de timeout global e verificação de autorização prévia de ferramentas.
- [x] **Suite de Resiliência de Domínio**:
  - **Disjuntor (*Circuit Breaker*)**: Estados *Closed*, *Open* e *Half-Open* com janela de recuperação automática e limiares configuráveis de falha.
  - **Retentativas Inteligentes**: Backoff exponencial com *jitter* estocástico para dispersão de picos de carga (*thundering herd*).
  - **Roteador de Modelos com Fallback**: Contingência automática para modelos alternativos em falhas transitórias.
- [x] **Controle Orçamentário e Reserva de Tokens**:
  - Protocolo em duas fases (retenção prévia e reconciliação definitiva) protegido por travas assíncronas intraprocesso (`asyncio.Lock`).
- [x] **Persistência Relacional Segura**:
  - Adaptador assíncrono para **PostgreSQL 17** com pool de conexões `asyncpg` e migrações idempotentes versionadas (`schema_migracoes`).
  - Adaptador leve para **SQLite** operando em modo WAL (*Write-Ahead Logging*) para concorrência local.
  - **Barramento Relacional Anti-IDOR**: Checagem obrigatória de posse (`id_usuario`) antes de qualquer leitura ou escrita de conversas.
- [x] **Segurança de Borda e Camada Intermediária BFF**:
  - Middlewares HTTP: injeção de cabeçalhos de segurança (`HSTS` estrito, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin` e `Permissions-Policy`).
  - Barramento **Anti-Spoofing**: Descarte e auditoria rigorosa de injeção indevida do cabeçalho `X-User-ID` por clientes externos diretos.
  - Camada **BFF (Backend-For-Frontend)**: Cookies de sessão assinados simetricamente com HMAC-SHA256 (`piloto_sessao`) e tokens anti-CSRF com validação em tempo constante via `hmac.compare_digest`.
- [x] **Telemetria e Observabilidade**:
  - Coletor Prometheus expondo métricas operacionais e contadores de segurança em `/metrics`.
  - Spans distribuídos OpenTelemetry compatíveis com a especificação W3C TraceContext.
- [x] **Aplicação Piloto Demonstrativa**:
  - SPA leve em HTML5/Vanilla JS servida pelo Gateway em `/piloto`, externalizada em `/piloto/app.js` para conformidade estrita com Content Security Policy (sem `'unsafe-inline'`).

---

## 3. Diagrama de Arquitetura

<p align="center">
  <img src="docs/image/arquitetura.png" alt="Diagrama de Arquitetura Técnica - Reusable AI Backend Architecture" width="100%" />
</p>

> ℹ️ **Nota de Engenharia**: O diagrama visual acima sintetiza a topologia dos blocos conceituais, fluxos de tráfego e fronteiras de isolamento. Para os diagramas C4 detalhados (Nível 1: Contexto e Nível 2: Contêineres) e fluxogramas de sequência técnicos, consulte a [Documentação de Arquitetura](docs/arquitetura.md).

---

## 4. Explicação dos Componentes

### 4.1 `AI Core` (`packages/ai-core`)
O núcleo da aplicação foi concebido como uma biblioteca Python de domínio puro. Seguindo a **Clean Architecture**, o pacote `ai_core.dominio` não possui nenhuma importação de frameworks web (`fastapi`, `starlette`) ou bibliotecas de transporte HTTP (`httpx`, `requests`).
- **Contratos Abstratos (*Ports*)**: `PortaProvedorLLM`, `PortaRepositorioMemoria`, `PortaExecutorFerramentas`, `PortaObservabilidade`.
- **Casos de Uso**: Encapsulam o fluxo de negócio de inferência síncrona, streaming assíncrono e validação estruturada.
- **Runtime de Agentes**: Executa o loop ReAct mantendo o isolamento de ferramentas e histórico segregado por sessão e locatário.

### 4.2 `AI Gateway` (`services/ai-gateway`)
O serviço de borda HTTP atua como o ponto de entrada da arquitetura, implementado sobre **FastAPI** e executado pelo servidor ASGI **Uvicorn**:
- **Endpoints Canônicos**: `/health`, `/metrics`, `/v1/modelos`, `/v1/chat/conclusoes`, `/v1/chat/estruturado`, `/v1/agentes/executar` e `/v1/conversas/{id_conversa}`.
- **Defesas de Borda**: Higienização de cabeçalhos de entrada, prevenção de adulteração de identidade e aplicação de políticas de rate limiting.
- **Camada Intermediária BFF**: Roteador dedicado (`/piloto/api`) que gerencia a autenticação segura do navegador via cookies `HttpOnly` com HMAC-SHA256 e validação CSRF.

### 4.3 Adaptadores de Provedores LLM
A comunicação com modelos de linguagem é realizada exclusivamente por adaptadores que satisfazem a porta abstrata `PortaProvedorLLM`:
- **`AdaptadorSimulado`**: Emula respostas imediatas e consumo determinístico de tokens, viabilizando desenvolvimento, homologação e CI sem custo financeiro.
- **`AdaptadorOllama`**: Permite inferência local completa com modelos abertos (ex: Llama, Mistral) sem envio de dados para a internet.
- **Provedores de Nuvem Comercial (`OpenAI`, `Google Gemini`, `Anthropic`, `DeepSeek`)**: Código de transporte estruturado e validado em testes unitários via `MockTransport` (HTTPX). A ativação em ambiente de produção real depende exclusivamente da inserção das respectivas chaves de API pelo operador no arquivo `.env`.

### 4.4 Persistência Relacional: PostgreSQL 17
O histórico de conversas e o estado das sessões são mantidos de forma durável no **PostgreSQL 17 Alpine**:
- Gerenciado via pool assíncrono de conexões de alto desempenho (`asyncpg`).
- Migrações de esquema aplicadas de forma idempotente e versionada na tabela de controle `schema_migracoes`.
- **Garantia Anti-IDOR**: Toda consulta de leitura ou gravação impõe a cláusula relacional de propriedade `WHERE id_conversa = $1 AND id_usuario = $2`.

### 4.5 Observabilidade e Telemetria
- **Prometheus (`/metrics`)**: Coleta contadores de requisições, taxas de erro, tempos de latência em milissegundos, consumo acumulado de tokens e contadores de segurança (tentativas de IDOR barradas).
- **OpenTelemetry**: Rastreamento distribuído com emissão de spans padronizados propagando o cabeçalho W3C `traceparent` e `X-Request-ID`.
- **Privacidade por Projeto**: Descarte explícito de dados pessoais (PII) e informações sensíveis dos atributos de telemetria.

### 4.6 Infraestrutura Conteinerizada (Docker Compose)
O ambiente local e de produção é orquestrado via `docker-compose.yml`:
- Imagem Docker multi-stage mínima e imutável baseada em Python 3.13 slim.
- Execução estrita sob usuário não-privilegiado (`appuser`, UID/GID 10001).
- Volumes nomeados externos mapeados para persistência (`dados_postgresql`).
- *Healthchecks* nativos configurados para verificação periódica de saúde dos nós.

### 4.7 Aplicação Piloto Demonstrativa
Disponível em `http://localhost:8000/piloto`, trata-se de uma interface SPA construída com tecnologias web padrão (HTML5, CSS3, Vanilla JS):
- Não requer ferramentas pesadas de compilação ou ecossistemas Node.js/npm.
- Demonstra visualmente o chat com IA, medição em tempo real de latência e tokens, persistência de banco e alternância controlada entre perfis (`usuario_alfa` e `usuario_beta`) para comprovação prática de isolamento multilocatário.

---

## 5. Segurança e Limitações Técnicas

Com transparência técnica de nível sênior, destacam-se os limites e premissas operacionais da implementação atual:

1. **Escopo Intraprocesso do Orçamento de Tokens**:
   - As travas assíncronas da `PoliticaOrcamentoTokens` e do `LimitadorTaxa` operam em memória local (`asyncio.Lock()`).
   - Suas garantias contra condições de corrida TOCTOU aplicam-se estritamente ao processo local da aplicação. Em topologias distribuídas escaladas horizontalmente (múltiplos workers Uvicorn ou réplicas de contêineres), um teto orçamentário consolidado exige um coordenador de estado externo distribuído (como Redis com scripts transacionais em Lua).
2. **Terminação TLS e Proxies Reversos de Borda**:
   - Conforme a RFC 6797 Seção 7.2 (*HSTS Spoofing*), o Gateway avalia a injeção do cabeçalho HSTS inspecionando `request.url.scheme == "https"`, sem confiar cegamente no cabeçalho `X-Forwarded-Proto` de clientes diretos.
   - Em implantações corporativas atrás de balanceadores/proxies (Cloudflare, AWS ALB, Nginx), o servidor Uvicorn deve ser explicitamente configurado com `--proxy-headers` e `--forwarded-allow-ips`.
3. **Escopo dos Testes e Auditoria de Segurança**:
   - O projeto possui 159 testes determinísticos aprovados, validação com banco PostgreSQL real e revisão estática defensiva estruturada através da Cloudflare Security Audit Skill.
   - Esse conjunto de evidências comprova a aplicação rigorosa de boas práticas defensivas, mas não constitui certificação formal de conformidade (ex: ISO 27001 ou SOC 2) nem substitui testes dinâmicos de penetração (*pentest* DAST) e testes de estresse em ambiente de homologação dedicado.

---

## 6. Tecnologias Utilizadas

| Categoria | Tecnologia | Justificativa Arquitetural |
| :--- | :--- | :--- |
| **Linguagem** | Python 3.13 | Suporte assíncrono nativo de alta performance, tipagem estática e maturidade de bibliotecas. |
| **API Framework** | FastAPI 0.115+ | Desempenho ASGI, validação declarativa com Pydantic v2 e suporte nativo a streaming SSE. |
| **Banco de Dados** | PostgreSQL 17 Alpine | Persistência relacional ACID, conformidade corporativa e driver assíncrono `asyncpg`. |
| **Banco Local** | SQLite (Modo WAL) | Persistência leve e rápida para execução em ambientes isolados e CLI. |
| **Conteinerização** | Docker & Docker Compose | Ambientes imutáveis, execução não-root e replicação exata entre desenvolvimento e produção. |
| **Métricas** | Prometheus Client | Exposição de métricas padronizadas em `/metrics` com cardinalidade controlada. |
| **Rastreamento** | OpenTelemetry | Spans distribuídos instrumentados com propagação W3C TraceContext. |
| **Qualidade & Lint** | Ruff | Linter e formatador de código ultrarrápido garantindo conformidade estilística estrita. |
| **Segurança SCA** | pip-audit | Auditoria contínua de vulnerabilidades conhecidas (CVEs) em dependências Python. |
| **Gerenciador** | Astral `uv` | Resolução determinística e sincronização ultrarrápida do monorrepositório. |

---

## 7. Execução Local

### Opção A: Execução Conteinerizada via Docker Compose (Recomendada)

1. **Copiar o arquivo de exemplo de variáveis de ambiente**:
   ```bash
   cp .env.example .env
   ```
2. **Subir os serviços centrais (AI Gateway + PostgreSQL 17)**:
   ```bash
   docker compose up -d
   ```
3. **Verificar a integridade dos nós e sondas de saúde (healthchecks)**:
   ```bash
   docker compose ps
   ```
   *Ambos os contêineres (`ia-gateway` e `ia-postgres`) devem apresentar status `healthy`.*
4. **Validar os endpoints canônicos**:
   ```bash
   # Verificação de vivacidade da API
   curl http://localhost:8000/health

   # Teste de métricas Prometheus
   curl http://localhost:8000/metrics
   ```
5. **Acessar a aplicação piloto no navegador**:
   Abra seu navegador em [http://localhost:8000/piloto](http://localhost:8000/piloto).
6. **Encerrar a infraestrutura preservando o volume de dados**:
   ```bash
   docker compose down
   ```

---

### Opção B: Execução Bare-Metal com `uv`

1. **Sincronizar dependências do workspace monorrepo**:
   ```bash
   uv sync --all-packages
   ```
2. **Executar a suíte de testes automatizados**:
   ```bash
   uv run pytest -v
   ```
3. **Executar linter e verificação de formatação**:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   ```
4. **Executar auditoria de vulnerabilidades em dependências (SCA)**:
   ```bash
   uv run --with pip-audit pip-audit
   ```
5. **Iniciar o gateway em modo de desenvolvimento**:
   ```bash
   uv run uvicorn ai_gateway.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## 8. Testes e Integração Contínua (CI)

A integridade técnica da base de código é fiscalizada por uma esteira determinística de CI no **GitHub Actions**:

- **Bateria de 159 Testes Automatizados**:
  - **155 testes unitários e de integração local** executados em isolamento de rede com mocks e SQLite.
  - **4 testes de integração física** executados contra uma instância de **PostgreSQL 17 real** provisionada em contêiner de serviço no GitHub Actions.
  - **Taxa de Aprovação de 100% dos testes coletados**: Todos os 159 cenários foram aprovados sem falhas (*155 passed, 4 skipped no ambiente sem banco, 159 passed no CI com PostgreSQL ativo*).
  - *Distinção Metrológica*: Essa métrica atesta o sucesso funcional completo dos cenários de teste especificados e não deve ser confundida com percentual de cobertura total de código por linhas/ramos via `pytest-cov`.
- **Análise Estática de Código**: Zero violações no `ruff check` e `ruff format`.
- **Análise de Composição de Software (SCA)**: Zero vulnerabilidades detectadas via `pip-audit`.

---

## 9. Documentação Especializada e Caderno dos Sete Pilares

A arquitetura está minuciosamente documentada no diretório [`docs/`](docs/):

- 📐 [Documentação de Arquitetura e Modelos C4](docs/arquitetura.md): Diagramas de contexto, contêineres e topologia de componentes.
- 🐳 [Guia de Infraestrutura e Docker](docs/infraestrutura.md): Parâmetros de contêineres, segurança não-root e mapeamento de volumes.
- 🛡️ [Guia de Segurança e AppSec](docs/seguranca.md): Defesas de borda, análise de ameaças e remediações SEC-001 a SEC-009 e REV-001 a REV-003.
- 📡 [Contratos de API e Rotas REST/SSE](docs/contratos_api.md): Especificação de payloads, headers e tratamento de erros.
- 🧪 [Estratégia de Testes Automatizados](docs/estrategia_testes.md): Pirâmide de testes, mocks e validação contra banco real.
- 🖥️ [Guia da Aplicação Piloto e Camada BFF](docs/aplicacao_piloto.md): Arquitetura do cliente web, fluxo de sessão HMAC e proteção CSRF.
- 📊 [Observabilidade e Telemetria](docs/observabilidade.md): Padrões de métricas Prometheus e spans OpenTelemetry W3C.
- 📚 [Caderno Técnico dos Sete Pilares](docs/caderno_tecnico.md): Tratado aprofundado cobrindo Conceito Fundamental, Explicação Progressiva, Aplicação Real, Decisões/Trade-offs, Exercícios Práticos e Perguntas de Revisão.
- 📜 [Registros de Decisão de Arquitetura (ADRs 0001 a 0011)](docs/adr/): Registro histórico imutável das escolhas técnicas e suas justificativas.

---

## 10. Transparência sobre o Desenvolvimento Assistido por IA

Este projeto foi construído na fronteira da **Engenharia de Software Assistida por Inteligência Artificial**:

- **Engenharia e Liderança Humana (Airton Neto)**: Concepção dos requisitos de negócio, definição da Clean Architecture, imposição das regras de governança e nomenclatura em português culto (`AGENTS.md`), *code review* rigoroso, identificação de falhas sutis de concorrência e autorização soberana de decisões de arquitetura e *merge*.
- **Implementação por Agentes Autônomos de IA (Antigravity)**: Geração do *scaffolding* de código, implementação dos adaptadores concretos, redação de testes automatizados e auxílio nas auditorias estáticas de segurança.

Para um estudo de caso aprofundado sobre governança e colaboração humano-IA na engenharia de software, consulte o **Pilar 7** do [Caderno Técnico](docs/caderno_tecnico.md).

---

## 11. Links Relevantes

- **Repositório**: [AirtonNettu/reusable-ai-backend-architecture](https://github.com/AirtonNettu/reusable-ai-backend-architecture)
- **Pull Requests e Histórico de Engenharia**: [Pull Requests no GitHub](https://github.com/AirtonNettu/reusable-ai-backend-architecture/pulls)
- **Pipeline de Integração Contínua**: [GitHub Actions Workflow Runs](https://github.com/AirtonNettu/reusable-ai-backend-architecture/actions)
- **Documentação Arquitetural Principal**: [docs/arquitetura.md](docs/arquitetura.md)
- **Caderno Técnico dos Sete Pilares**: [docs/caderno_tecnico.md](docs/caderno_tecnico.md)


---

## 12. Licença e Termos de Uso

Este projeto é um software de código aberto distribuído sob os termos da [**Apache License, Version 2.0**](LICENSE).

Você tem a liberdade de utilizar, reproduzir, modificar, distribuir e sublicenciar esta arquitetura e seus componentes, tanto para fins comerciais quanto não comerciais, desde que mantidos os avisos originais de direitos autorais e as condições estipuladas na licença.

Para detalhes completos sobre concessão de patentes, isenção de garantias e limitações de responsabilidade, consulte os arquivos [LICENSE](LICENSE) e [NOTICE](NOTICE).

```text
Copyright 2026 Airton Neto

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
