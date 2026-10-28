# Estratégia de Testes Automatizados

Este documento descreve a pirâmide de testes, metodologia de garantia de qualidade e execução de testes automatizados da **Reusable AI Backend Architecture**.

---

## 1. Princípios de QA Adotados

1. **Zero Consumo de APIs Pagas**:
   - Nenhum teste automatizado dispara requisições externas para provedores comerciais (OpenAI, Gemini, Anthropic, etc.).
   - Utilizam-se objetos de simulação de domínio (`AdaptadorSimulado`) e transporte mock nativo do HTTPX (`httpx.MockTransport`) para testar o protocolo HTTP e a serialização JSON sem tráfego de rede real.

2. **Diferenciação Estrita: Testes Simulados vs. Integração Física Real**:
   - **Testes com Simulação (`test_memoria_postgresql.py`)**: Utilizam dublês de teste (`PoolPostgresSimulado`, `ConexaoPostgresSimulada`, `TransacaoSimulada`) para validar a lógica de migrações, isolamento de usuários e transações de forma determinística, rápida (milisegundos) e sem dependência de serviços externos.
   - **Testes de Integração Física Real (`test_integracao_postgresql_real.py`)**: Conectam-se a uma instância ativa de banco de dados PostgreSQL 17 via driver `asyncpg` real. Exercitam conexões físicas TCP, criação real de esquemas e tabelas (`schema_migracoes`, `conversas_proprietarios`, `mensagens_conversa`), rollback em falhas de transação, concorrência massiva com `asyncio.gather` e controle anti-IDOR.
   - **Garantia em CI**: No pipeline de CI, o teste físico é **obrigatório** (`POSTGRES_OBRIGATORIO=true`), alimentado por um contêiner de serviço PostgreSQL 17 oficial. Em desenvolvimento local, quando a porta 5432 não estiver ativa, os testes físicos são marcados como *skipped* informativamente, sem mascarar falhas no pipeline.

3. **Cobertura Multicamada**:
   - **Camada de Domínio**: Modelos imutáveis, dataclasses, contratos de ferramenta, exceções e validação JSON Schema com `$defs` e `$ref`.
   - **Camada de Resiliência**: Disjuntor (Circuit Breaker), retentativas com jitter, semáforo, limitador de taxa, reserva de tokens em duas fases e fallback.
   - **Camada de Adaptadores**: Provedores LLM, memória conversacional volátil, SQLite (WAL) e PostgreSQL assíncrono com pool e migrações versionadas, ferramentas, segurança e observabilidade.
   - **Camada de Aplicação**: Casos de uso e ciclo ReAct do agente autônomo.
   - **Camada de Interface (Gateway)**: Endpoints FastAPI, cabeçalhos, streaming SSE, tratamento global de erros RFC 7807, autenticação e autorização multilocatário anti-spoofing.
   - **Camada de Integração E2E**: Fluxo ponta a ponta unindo Gateway, Casos de Uso, Roteamento com Contingência, Persistência e Isolamento de Usuários.

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
| `tests/test_roteador_modelos.py` | Catálogo de modelos, seleção por capacidade e fallback automático entre provedores. | 2 |
| `tests/test_orquestrador_agente.py` | Ciclo ReAct completo com ferramentas, salvaguarda contra loops infinitos e limites. | 2 |
| `tests/test_saidas_estruturadas.py` | Geração com Pydantic, parsing com limpeza de markdown e autorreparo de JSON inválido. | 2 |
| `tests/test_compactador_contexto.py` | Limiar de ativação e sumarização de mensagens antigas preservando o sistema. | 2 |
| `tests/test_formatador_logs.py` | Formatação estruturada JSON de logs para ingestão em observability collectors. | 1 |
| `tests/test_validador_esquema.py` | Validação de JSON Schema com `$defs`, `$ref`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength` e conformidade de dados. | 5 |
| `tests/test_orcamento_tokens.py` | Limite orçamentário por requisição, sessão, usuário, reserva em duas fases e cancelamento de reserva em falhas. | 7 |
| `tests/test_seguranca_concorrencia_e_sanitizacao.py` | Concorrência massiva SQLite WAL, sanitização de logs, defesas DoS de borda e validação rigorosa de esquemas. | 6 |
| `tests/test_auditoria_identidade_e_seguranca.py` | Prevenção de falsificação de identidade (Anti-Spoofing de X-User-ID), delegação M2M e autenticação negativa. | 6 |
| `tests/test_gateway_api.py` | Rotas FastAPI: `/health`, `/v1/modelos`, `/v1/chat/conclusoes` (síncrono e SSE streaming), `/v1/chat/estruturado`, `/v1/agentes/executar`, autenticação e RFC 7807. | 8 |
| `tests/test_integracao_fluxo_completo.py` | Fluxo completo Gateway -> Caso de Uso -> Roteador -> SQLite; Isolamento Multilocatário (403 Forbidden); Resiliência e Fallback sob concorrência; Chat estruturado complexo. | 4 |
| **Total** | **Suíte Automatizada Completa** | **81 cenários** |

---

## 3. Comandos de Execução

```bash
# 1. Executar todos os testes locais (unitários e simulados com skip gracioso para o banco físico se inativo)
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
