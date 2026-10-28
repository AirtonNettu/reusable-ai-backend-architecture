# Estratégia de Testes e Garantia de Qualidade

Este documento define a pirâmide de testes, as convenções e a cobertura automatizada da **Reusable AI Backend Architecture**.

---

## 1. Princípios da Estratégia de Testes

1. **Testes Unitários Rápidos e Determinísticos**:
   - Não realizam chamadas de rede externas para provedores LLM reais (OpenAI, Anthropic, Gemini, Ollama). Utilizam o `MockTransport` do `httpx` ou o `AdaptadorSimulado`.
   - Execução em menos de 10 segundos para toda a suíte.

2. **Testes de Contratos e Domínio Puro**:
   - Garantem que entidades (`Mensagem`, `DefinicaoFerramenta`, `ChamadaFerramenta`, `InformacoesModelo`) sejam imutáveis (`frozen=True`) e validem regras invariantes de domínio.

3. **Confiabilidade e Resiliência Testadas Sob Falha**:
   - **Camada de Resiliência**: Disjuntor (Circuit Breaker), retentativas com jitter, semáforo, limitador de taxa, reserva de tokens em duas fases e fallback.
   - **Camada de Persistência**: SQLite em memória e em arquivo WAL com concorrência massiva de threads, PostgreSQL com pool, transações ACID e migrações idempotentes.

4. **Isolamento de Ambientes**:
   - Testes de integração física com o PostgreSQL 17 utilizam transações com rollback automático ou schemas isolados.
   - Variável de controle `POSTGRES_OBRIGATORIO`: quando ausente, a bateria de PostgreSQL real é ignorada graciosamente (`pytest.skip`), permitindo a execução rápida em ambientes de desenvolvimento sem contêineres ativos. No pipeline de CI, `POSTGRES_OBRIGATORIO=true` é imposto, garantindo a execução mandatória.

---

## 2. Mapa dos Arquivos de Teste

| Arquivo | Escopo / Responsabilidade | Quantidade de Cenários |
| :--- | :--- | :--- |
| `tests/test_mensagem.py` | Entidade `Mensagem`, imutabilidade (`FrozenInstanceError`) e criação. | 2 |
| `tests/test_health.py` | Endpoint inicial `/health` (preservado). | 1 |
| `tests/test_dominio_modelos.py` | Entidades de ferramentas, geração, agentes e hierarquia de exceções. | 4 |
| `tests/test_resiliencia.py` | Transições do `Disjuntor`, retentativa com backoff, `LimitadorTaxa`, `SemaforoConcorrencia`, `PoliticaFallback` e `RastreadorConsumoTokens`. | 7 |
| `tests/test_adaptadores_provedores.py` | `AdaptadorSimulado`, `AdaptadorOpenAI`, `AdaptadorOllama`, `AdaptadorGemini`, `AdaptadorAnthropic` com `MockTransport` e cenários de erro HTTP (401, 429). | 6 |
| `tests/test_ferramentas_e_seguranca.py` | `RegistroFerramentas` (síncrono e assíncrono), `PoliticaAutorizacaoFerramenta` e `CofreCredenciais`. | 3 |
| `tests/test_memoria_e_contexto.py` | `MemoriaEmMemoria` (salvar, limite, limpar) e `GerenciadorContexto` (janela deslizante e preservação de sistema). | 2 |
| `tests/test_memoria_sqlite.py` | Persistência assíncrona SQLite em memória e em arquivo físico com fechamento seguro. | 2 |
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
| `tests/test_observabilidade_e_metricas.py` | Métricas Prometheus (/metrics, contadores, histogramas, gauges), autorização Bearer token, tracing OpenTelemetry (propagação W3C traceparent remoto com preservação de flags e modo não-amostrado, spans síncronos/assíncronos, sanitização de query strings em http.url, sanitização de exceções em spans sem sobrescrita, mitigação de cardinalidade com ROTA_NAO_RECONHECIDA, buffer em memória delimitado com deque e trava de concorrência), logs correlacionados com trace/span_id, regras e truncamento de sanitização, concorrência de métricas e telemetria em Disjuntor, PoliticaFallback e MemoriaSQLite. | 23 |
| `tests/test_integracao_fluxo_completo.py` | Fluxo completo Gateway -> Caso de Uso -> Roteador -> SQLite; Isolamento Multilocatário (403 Forbidden); Resiliência e Fallback sob concorrência; Chat estruturado complexo. | 4 |
| **Total** | **Suíte Automatizada Completa** | **126 cenários** |

---

## 3. Comandos de Execução

```bash
# 1. Executar todos os testes locais (unitários, infraestrutura e simulados com skip gracioso para o banco físico se inativo)
uv run pytest -v

# 2. Executar contêiner PostgreSQL 17 local descartável para testes de integração física
docker run -d --name pg-teste -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:17-alpine

# 3. Executar exclusivamente a bateria de integração física com o PostgreSQL real
uv run pytest tests/test_integracao_postgresql_real.py -v

# 4. Executar exigindo obrigatoriamente a presença do PostgreSQL (mesmo modo do GitHub Actions)
POSTGRES_OBRIGATORIO=true uv run pytest tests/test_integracao_postgresql_real.py -v

# 5. Destruir o contêiner de teste descartável após o término
docker rm -f pg-teste

# 6. Executar lint e verificação de formatação estrita
uv run ruff check .
uv run ruff format --check .
```
