# Estratégia de Testes e Garantia de Qualidade

Este documento define a pirâmide de testes, as convenções de qualidade, o catálogo de testes automatizados e a esteira de validação contínua (CI) da **Reusable AI Backend Architecture**.

---

## 1. Princípios da Estratégia de Testes

1. **Testes Unitários Rápidos e Determinísticos**:
   - Não realizam chamadas externas de rede para provedores LLM reais (OpenAI, Anthropic, Gemini, Ollama), eliminando custos financeiros e instabilidades de conexão.
   - Utilizam o `MockTransport` do `httpx` ou o `AdaptadorSimulado` determinístico.
   - Execução em menos de 10 segundos para toda a suíte unitária.
2. **Testes de Contratos e Domínio Puro**:
   - Garantem que entidades de domínio (`Mensagem`, `DefinicaoFerramenta`, `ChamadaFerramenta`, `RequisicaoGeracao`, `RespostaGeracao`) sejam imutáveis (`frozen=True`) e validem regras invariantes de negócio sem dependências externas.
3. **Resiliência e Tolerância a Falhas**:
   - Cenários exaustivos testam o comportamento da máquina de estados do `Disjuntor` (fechado, aberto, meio-aberto), retentativas com jitter, semáforo de concorrência, limitador de taxa (Token Bucket) e protocolo de reserva de tokens em duas fases.
4. **Isolamento Multilocatário e Prevenção IDOR**:
   - Testes automatizados verificam sistematicamente se requisições para conversas pertencentes a outros usuários retornam `403 Forbidden` RFC 7807, tanto no SQLite quanto no PostgreSQL.
5. **Integração Física com PostgreSQL 17 Real**:
   - Bateria de testes que valida migrações DDL versionadas idempotentes, transações ACID com rollback e concorrência massiva de conexões assíncronas.
   - **Mecanismo de Skip Gracioso**: Em ambiente local de desenvolvimento, se o contêiner do banco estiver desligado, os 4 testes de integração física são ignorados (`pytest.skip`). Na esteira de CI (`.github/workflows/ci.yml`), a variável `POSTGRES_OBRIGATORIO=true` é injetada, forçando a aprovação mandatória com um contêiner oficial do PostgreSQL 17 Alpine em execução.

---

## 2. Mapa Completo dos Testes Automatizados (159 Cenários)

A base de testes conta com **25 arquivos de teste** cobrindo todas as camadas da arquitetura:

| Arquivo de Teste | Escopo / Responsabilidade | Quantidade de Cenários |
| :--- | :--- | :---: |
| `tests/test_mensagem.py` | Entidade `Mensagem`, imutabilidade (`FrozenInstanceError`) e criação. | 2 |
| `tests/test_health.py` | Endpoint inicial de vivacidade `/health`. | 1 |
| `tests/test_dominio_modelos.py` | Entidades de ferramentas, geração, agentes e hierarquia de exceções. | 4 |
| `tests/test_resiliencia.py` | Transições do `Disjuntor`, retentativa com backoff, `LimitadorTaxa`, `SemaforoConcorrencia`, `PoliticaFallback` e `RastreadorConsumoTokens`. | 7 |
| `tests/test_adaptadores_provedores.py` | `AdaptadorSimulado`, `AdaptadorOpenAI`, `AdaptadorOllama`, `AdaptadorGemini`, `AdaptadorAnthropic` com `MockTransport` e cenários de erro HTTP (401, 429). | 6 |
| `tests/test_ferramentas_e_seguranca.py` | `RegistroFerramentas` (síncrono e assíncrono), `PoliticaAutorizacaoFerramenta` e `CofreCredenciais`. | 3 |
| `tests/test_memoria_e_contexto.py` | `MemoriaEmMemoria` (salvar, limite, limpar) e `GerenciadorContexto` (janela deslizante e preservação de sistema). | 2 |
| `tests/test_memoria_sqlite.py` | Persistência assíncrona SQLite em memória e em arquivo físico WAL com fechamento seguro. | 2 |
| `tests/test_memoria_postgresql.py` | Persistência assíncrona PostgreSQL com pool simulado, transações ACID, migrações versionadas e isolamento de usuários. | 5 |
| `tests/test_integracao_postgresql_real.py` | Testes de integração física com PostgreSQL 17 real: gravação/leitura, rollback em transação, concorrência massiva e idempotência de migrações. | 4 |
| `tests/test_infraestrutura_e_migracoes.py` | Validação de especificações do Dockerfile, Compose, `.dockerignore`, ciclo de vida FastAPI e CLI de migração. | 7 |
| `tests/test_roteador_modelos.py` | Catálogo de modelos, seleção por capacidade e fallback automático entre provedores. | 2 |
| `tests/test_orquestrador_agente.py` | Ciclo ReAct completo com ferramentas, salvaguarda contra loops infinitos e limites. | 2 |
| `tests/test_saidas_estruturadas.py` | Geração com Pydantic, parsing com limpeza de markdown e autorreparo de JSON inválido. | 2 |
| `tests/test_compactador_contexto.py` | Limiar de ativação e sumarização de mensagens antigas preservando o sistema. | 2 |
| `tests/test_formatador_logs.py` | Formatação estruturada JSON de logs para ingestão em observability collectors. | 1 |
| `tests/test_validador_esquema.py` | Validação de JSON Schema com `$defs`, `$ref`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength` e conformidade de dados. | 5 |
| `tests/test_orcamento_tokens.py` | Limite orçamentário por requisição, sessão, usuário, reserva em duas fases e cancelamento de reserva em falhas. | 7 |
| `tests/test_seguranca_concorrencia_e_sanitizacao.py` | Concorrência massiva SQLite WAL, sanitização de logs, defesas DoS de borda e validação rigorosa de esquemas. | 6 |
| `tests/test_auditoria_identidade_e_seguranca.py` | Prevenção de falsificação de identidade (Anti-Spoofing de X-User-ID), delegação M2M, validação fail-closed em produção, rejeição de ambientes desconhecidos e autenticação negativa. | 12 |
| `tests/test_gateway_api.py` | Rotas FastAPI: `/health`, `/v1/modelos`, `/v1/chat/conclusoes` (síncrono e SSE streaming), `/v1/chat/estruturado`, `/v1/agentes/executar`, autenticação e RFC 7807. | 8 |
| `tests/test_observabilidade_e_metricas.py` | Métricas Prometheus (/metrics, contadores, histogramas, gauges), autorização Bearer token, tracing OpenTelemetry (propagação W3C traceparent remoto com preservação de flags e modo não-amostrado, spans síncronos/assíncronos, sanitização de query strings em http.url, sanitização de exceções em spans sem sobrescrita, mitigação de cardinalidade com ROTA_NAO_RECONHECIDA, buffer em memória delimitado com deque e trava de concorrência), logs correlacionados com trace/span_id, regras e truncamento de sanitização, concorrência de métricas e telemetria em Disjuntor, PoliticaFallback e MemoriaSQLite. | 24 |
| `tests/test_integracao_fluxo_completo.py` | Fluxo completo Gateway -> Caso de Uso -> Roteador -> SQLite; Isolamento Multilocatário (403 Forbidden); Resiliência e Fallback sob concorrência; Chat estruturado complexo. | 4 |
| `tests/test_aplicacao_piloto_e_conversas.py` | Aplicação Piloto e rotas BFF (`/piloto`, `/piloto/api/*`), integridade de sessões com HMAC, proteção anti-CSRF, isolamento multilocatário demonstrativo, prevenção IDOR e persistência no PostgreSQL. | 16 |
| `tests/test_remediacao_auditoria_seguranca.py` | Validação estrita das remediações da auditoria de segurança (SEC-001 a SEC-009) e das revisões técnicas de code review (REV-001 a REV-003): validação fail-closed de credenciais, mitigação DOM XSS, orçamento de tokens em agentes e streaming SSE, desacoplamento de segredos, cabeçalhos defensivos, higiene Docker, autenticação em `/metrics`, CSP rígida sem `unsafe-inline`, prevenção de HSTS spoofing e omissão de PII em spans. | 25 |
| **Total Geral** | **Suíte Automatizada Completa Coletada** | **159 cenários** |

---

## 3. Contabilização da Execução da Suíte

- **Execução Local Padrão (sem PostgreSQL real ativo)**:
  - **Coletados**: 159 testes.
  - **Aprovados**: 155 testes.
  - **Ignorados (*Skipped*)**: 4 testes (`test_integracao_postgresql_real.py`).
  - **Falhas**: 0.
- **Execução no GitHub Actions (com serviço PostgreSQL 17 Alpine)**:
  - **Coletados**: 159 testes.
  - **Aprovados**: 159 testes (100% de taxa de aprovação dos testes coletados).
  - **Ignorados**: 0.
  - **Falhas**: 0.

> [!NOTE]
> **Esclarecimento sobre Métricas de Qualidade**: O percentual de 100% de aprovação refere-se estritamente à proporção de testes coletados pelo Pytest que obtiveram sucesso na execução. Essa métrica de taxa de sucesso funcional comprova a validade de todos os cenários especificados, mas não deve ser equiparada a métricas de cobertura de código por linhas/ramos (*code coverage* medido via `pytest-cov`), que exigem instrumentação e relatórios adicionais.

---

## 4. Ferramental de Qualidade de Código e Segurança (CI)

A esteira de integração contínua (`.github/workflows/ci.yml`) executa quatro validações complementares:

1. **Verificação de Formatação de Código (`ruff format`)**:
   ```bash
   uv run ruff format --check .
   ```
   *Garante conformidade de estilo e indentação em 100% dos arquivos Python.*
2. **Linter Estático e Regras de Segurança (`ruff check`)**:
   ```bash
   uv run ruff check .
   ```
   *Verifica boas práticas, importações não utilizadas, conformidade com PEPs e regras do Flake8.*
3. **Auditoria de Vulnerabilidades de Dependências (SCA via `pip-audit`)**:
   ```bash
   uv run --with pip-audit pip-audit
   ```
   *Verifica se alguma biblioteca do `uv.lock` possui vulnerabilidade conhecida (CVE) no banco PyPI/OSV.*
4. **Execução de Testes Automatizados (`pytest`)**:
   ```bash
   uv run pytest -v
   ```

---

## 5. Comandos Úteis para o Desenvolvedor

```bash
# Executar toda a suíte de testes em modo verboso
uv run pytest -v

# Executar exclusivamente os testes de segurança e remediação
uv run pytest tests/test_remediacao_auditoria_seguranca.py -v

# Executar os testes da aplicação piloto e camada BFF
uv run pytest tests/test_aplicacao_piloto_e_conversas.py -v

# Executar os testes exigindo obrigatoriamente a presença do PostgreSQL 17 real
POSTGRES_OBRIGATORIO=true uv run pytest tests/test_integracao_postgresql_real.py -v

# Executar linter com correção automática
uv run ruff check --fix .
uv run ruff format .
```

---

## 6. Referências

- [ADR 0004: Validação Rigorosa e Defesas de Borda](adr/0004-validacao-rigorosa-e-defesas-de-borda.md)
- [ADR 0006: Controle de Identidade Anti-Spoofing e Persistência PostgreSQL](adr/0006-controle-identidade-anti-spoofing-e-persistencia-postgresql.md)
- [ADR 0010: Aplicação Piloto e Interface BFF Segura](adr/0010-aplicacao-piloto-e-interface-bff-segura.md)
- [ADR 0011: Auditoria Estática e Remediação Conclusiva de Segurança](adr/0011-auditoria-e-remediacao-de-seguranca.md)
