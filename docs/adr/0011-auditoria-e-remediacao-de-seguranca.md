# ADR 0011: Auditoria Estática e Remediação Conclusiva de Segurança

## Status
Aprovado

## Data
2026-10-29

## Contexto
Após a conclusão da aplicação piloto e da camada intermediária BFF no PR #4, foi iniciada uma auditoria de segurança estática independente e aprofundada orientada pelo repositório oficial da **Cloudflare Security Audit Skill** (`cloudflare/security-audit-skill@1.0.0`).

A auditoria mapeou dez superfícies de ataque em toda a base de código (autenticação, identidade, cookies, CSRF, PostgreSQL, rotas do Gateway, serialização, resiliência de memória, infraestrutura e cadeia de suprimentos), identificando nove achados iniciais (**SEC-001 a SEC-009**) e três riscos complementares identificados durante o code review técnico (**REV-001 a REV-003**):

1. **SEC-001 (Alta)**: Chaves padrão de desenvolvimento no `docker-compose.yml` (`dev-local-master-key-12345678`) eram aceitas em ambiente de produção porque possuíam mais de 16 caracteres e não estavam na lista de bloqueio estático.
2. **SEC-002 (Média)**: A interface web da aplicação piloto (`/piloto`) interpolava diretamente variáveis dinâmicas (`idConversaAtual`, `usuarioAtual`) em nós HTML via `innerHTML`, criando vetor potencial de DOM XSS.
3. **SEC-003 (Média)**: A rota de execução de agentes autônomos (`/v1/agentes/executar`) descartava o usuário autenticado, e o `OrquestradorAgente` executava passos cognitivos ReAct sem consultar ou debitar cotas na `PoliticaOrcamentoTokens`.
4. **SEC-004 (Média)**: A camada BFF da aplicação piloto reutilizava a chave mestra (`GATEWAY_API_KEY`) para assinar cookies HMAC de sessão caso o segredo específico estivesse ausente.
5. **SEC-005 (Baixa)**: As respostas HTTP do AI Gateway não continham cabeçalhos de borda defensivos contra MIME sniffing, clickjacking e incorporação não autorizada.
6. **SEC-006 (Baixa)**: O endpoint de streaming SSE (`CasoDeUsoGerarRespostaFluxo`) iterava pedaços de resposta sem pré-reserva de tokens ou débito orçamentário.
7. **SEC-007 (Informativa)**: O arquivo `.dockerignore` não excluía arquivos da skill de auditoria (`.agents/`, `skills-lock.json`), e a esteira de CI do GitHub Actions não executava verificação de vulnerabilidades em dependências (SCA).
8. **SEC-008 (Baixa)**: O endpoint `/metrics` em produção podia ficar exposto anonimamente caso `GATEWAY_API_KEY` não estivesse definida e `GATEWAY_METRICAS_TOKEN` fosse nulo.
9. **SEC-009 (Informativa)**: A Content Security Policy (CSP) continha `'unsafe-inline'` para scripts devido ao código JavaScript incorporado diretamente na página HTML da SPA.
10. **REV-001 (Baixa)**: O gerador assíncrono de SSE tratava apenas `except Exception`, ignorando subclasses de `BaseException` (`asyncio.CancelledError` e `GeneratorExit` em `aclose()`), causando retenção permanente de reservas atômicas de tokens.
11. **REV-002 (Baixa)**: A emissão de HSTS confiava diretamente no cabeçalho `X-Forwarded-Proto` fornecido pelo cliente sobre conexões HTTP não autenticadas, violando a RFC 6797 Seção 7.2.
12. **REV-003 (Baixa)**: O `OrquestradorAgente` exportava o identificador do usuário em texto claro nos spans OpenTelemetry, gerando risco de vazamento de dados pessoais (PII) para sistemas de APM externos.

---

## Decisão

Implementou-se a remediação integral e conclusiva dos doze pontos através dos seguintes padrões arquiteturais:

### 1. Bloqueio Estrito de Credenciais Inseguras (SEC-001)
- Criada a função de validação centralizada `eh_credencial_insegura_producao()` em `configuracoes.py`, inspecionando entropia mínima (16 caracteres), termos proibidos e prefixos fracos (`dev-`, `dev_`, `teste-`, `demo-`, etc.).
- Comportamento estritamente *fail-closed* na inicialização do serviço via `validar_seguranca_producao()` e rejeição em runtime no `ValidadorAutenticacao` com HTTP 401.

### 2. Sanitização Estrita de DOM contra XSS (SEC-002)
- Criada e aplicada a função `escapeHtml()` na SPA, sanitizando qualquer dado dinâmico interpolado em `innerHTML` e priorizando `textContent` para mensagens de status e cabeçalhos.

### 3. Governança Orçamentária no Runtime de Agentes (SEC-003)
- Propagação do `id_usuario` autenticado da rota `/v1/agentes/executar` até `OrquestradorAgente.executar()`.
- Pré-reserva atômica de cota por iteração cognitiva com liquidação em sucesso e liberação imediata em falhas.

### 4. Desacoplamento e Isolamento de Segredos de Sessão (SEC-004)
- Eliminado o fallback de segredos de sessão para a chave mestre. Em produção, a ausência de `GATEWAY_PILOTO_SEGREDO_SESSAO` dispara interrupção *fail-closed* no bootstrap do Gateway e HTTP 500 imediato caso acessado.

### 5. Middleware de Cabeçalhos Defensivos de Borda (SEC-005)
- Implementado `MiddlewareCabecalhosSeguranca` injetando `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` e `Referrer-Policy: strict-origin-when-cross-origin` em todas as rotas.

### 6. Protocolo de Reserva em Duas Fases para Streaming SSE (SEC-006 e REV-001)
- `CasoDeUsoGerarRespostaFluxo` injeta `PoliticaOrcamentoTokens`, executa pré-reserva antes do disparo ao modelo e liquida o consumo real ao término.
- Encapsulado em bloco `try...except BaseException...finally` com flag atômica `reserva_finalizada`. Trata `asyncio.CancelledError`, `aclose()` e exceções de provedor, garantindo liberação atômica da reserva sem operações duplicadas.

### 7. Higiene de Imagens Docker e SCA no CI (SEC-007)
- Diretório `.agents/` e arquivo `skills-lock.json` explicitamente ignorados no `.dockerignore`.
- Adicionada etapa no GitHub Actions (`.github/workflows/ci.yml`) executando `uv run --with pip-audit pip-audit`.

### 8. Autenticação Fail-Closed em Métricas (SEC-008)
- Em produção, se não houver token configurado (`GATEWAY_METRICAS_TOKEN`) nem chave mestre, o endpoint `/metrics` retorna HTTP 403 Forbidden.
- Validação de tokens via `hmac.compare_digest` imune a ataques de temporização.

### 9. Content Security Policy sem 'unsafe-inline' (SEC-009)
- JavaScript da SPA externalizado para o endpoint dedicado `/piloto/app.js`.
- Handlers inline de eventos removidos do HTML e substituídos por `addEventListener`.
- Diretiva CSP endurecida para `script-src 'self'`.

### 10. Prevenção de HSTS Spoofing (REV-002)
- Removida a consulta direta a `request.headers.get("x-forwarded-proto")`.
- Emissão de HSTS restrita a `request.url.scheme == "https"`. Em ambiente corporativo com proxies reversos, o Uvicorn deve ser configurado com `--proxy-headers` e `--forwarded-allow-ips`.

### 11. Minimização de Dados e Privacidade em Telemetria (REV-003)
- Omissão completa de identificadores de usuários nos atributos de spans OpenTelemetry. O span registra apenas metadados operacionais não identificáveis (`agente.nome`, `agente.modelo`, `agente.limite_passos`), cumprindo o princípio de minimização de dados da LGPD e GDPR.

---

## Consequências

### Positivas
- Eliminação completa de brechas de segurança de injeção, XSS, HSTS spoofing e vazamento de identificadores de sessão.
- Isolamento multilocatário e governança orçamentária estendidos para streaming (SSE) e agentes autônomos (ReAct).
- Proteção nativa da esteira de CI com análise contínua de vulnerabilidades de dependências (SCA via `pip-audit`).
- Conformidade total com normas de OWASP e RFCs de transporte seguro (RFC 6797, RFC 7807).
- Suíte automatizada com 25 testes específicos em `tests/test_remediacao_auditoria_seguranca.py`.

### Negativas / Limitações Registradas
1. **Ambiente Host Windows vs Validadores Node.js**:
   - Os scripts executáveis oficiais da skill (`validate-findings.cjs` e `validate-coverage-ledger.cjs`) dependem de primitivas exclusivas de sistemas POSIX (`O_NOFOLLOW` e descritores de arquivo não bloqueantes). No ambiente host Windows, esses validadores não operam, sendo substituídos por testes automatizados Pytest e inspeção estática contínua.
2. **Escopo Predominantemente Estático**:
   - A auditoria realizada foi focada em revisão de código-fonte, arquitetura e testes estáticos. Testes dinâmicos de carga, penetração de rede (DAST) e estresse devem ser conduzidos em ambiente de homologação dedicado.
3. **Orçamento Confinado à Memória Local**:
   - As cotas da `PoliticaOrcamentoTokens` utilizam `asyncio.Lock()` em memória local. Em ambientes com múltiplos workers ou instâncias horizontais, deve-se adotar uma camada de coordenação distribuída (ex: Redis).
