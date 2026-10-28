# Estratégia de Testes Automatizados

Este documento descreve a pirâmide de testes, metodologia de garantia de qualidade e execução de testes automatizados da **Reusable AI Backend Architecture**.

---

## 1. Princípios de QA Adotados

1. **Zero Consumo de APIs Pagas**:
   - Nenhum teste automatizado dispara requisições externas para provedores comerciais (OpenAI, Gemini, Anthropic, etc.).
   - Utilizam-se objetos de simulação de domínio (`AdaptadorSimulado`) e transporte mock nativo do HTTPX (`httpx.MockTransport`) para testar o protocolo HTTP e a serialização JSON sem tráfego de rede real.

2. **Isolamento e Determinismo**:
   - Cada teste é independente, sem efeitos colaterais em arquivos ou banco de dados físico.
   - O tempo de execução da suíte completa de testes unitários e de integração permanece em torno de 2 a 3 segundos.

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
| `tests/test_memoria_postgresql.py` | Persistência assíncrona PostgreSQL com pool, transações ACID, migrações versionadas e isolamento de usuários. | 5 |
| `tests/test_roteador_modelos.py` | Catálogo de modelos, seleção por capacidade e fallback automático entre provedores. | 2 |
| `tests/test_orquestrador_agente.py` | Ciclo ReAct completo com ferramentas, salvaguarda contra loops infinitos e limites. | 2 |
| `tests/test_saidas_estruturadas.py` | Geração com Pydantic, parsing com limpeza de markdown e autorreparo de JSON inválido. | 2 |
| `tests/test_compactador_contexto.py` | Limiar de ativação e sumarização de mensagens antigas preservando o sistema. | 2 |
| `tests/test_formatador_logs.py` | Formatação estruturada JSON de logs para ingestão em observability collectors. | 1 |
| `tests/test_validador_esquema.py` | Validação de JSON Schema com `$defs`, `$ref`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength` e conformidade de dados. | 5 |
| `tests/test_orcamento_tokens.py` | Limite orçamentário por requisição, sessão, usuário, reserva em duas fases e cancelamento de reserva em falhas. | 6 |
| `tests/test_seguranca_concorrencia_e_sanitizacao.py` | Concorrência massiva SQLite WAL, sanitização de logs, defesas DoS de borda e validação rigorosa de esquemas. | 6 |
| `tests/test_auditoria_identidade_e_seguranca.py` | Prevenção de falsificação de identidade (Anti-Spoofing de X-User-ID), delegação M2M e autenticação negativa. | 4 |
| `tests/test_gateway_api.py` | Rotas FastAPI: `/health`, `/v1/modelos`, `/v1/chat/conclusoes` (síncrono e SSE streaming), `/v1/chat/estruturado`, `/v1/agentes/executar`, autenticação e RFC 7807. | 8 |
| `tests/test_integracao_fluxo_completo.py` | Fluxo completo Gateway -> Caso de Uso -> Roteador -> SQLite; Isolamento Multilocatário (403 Forbidden); Resiliência e Fallback sob 20 requisições simultâneas; Chat estruturado complexo. | 4 |
| **Total** | **Suíte Automatizada Completa** | **74 testes (100% aprovados)** |

---

## 3. Comandos de Execução

```bash
# Executar todos os 74 testes com saída verbosa
uv run pytest -v

# Executar testes de auditoria de identidade e segurança
uv run pytest tests/test_auditoria_identidade_e_seguranca.py -v

# Executar testes do adaptador PostgreSQL
uv run pytest tests/test_memoria_postgresql.py -v

# Executar lint e verificação de formatação estrita
uv run ruff check .
uv run ruff format --check .
```
