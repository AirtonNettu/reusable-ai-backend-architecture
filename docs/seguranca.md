# Documentação de Segurança e AppSec

Este documento detalha a arquitetura de segurança da aplicação (**AppSec**), os controles defensivos de borda, a proteção criptográfica de credenciais e sessões, o isolamento multilocatário e as remediações implementadas a partir da auditoria de segurança (**SEC-001 a SEC-009** e **REV-001 a REV-003**).

---

## 1. Princípios Fundamentais de Segurança

1. **Defesa em Profundidade (*Defense in Depth*)**: A segurança é aplicada na borda HTTP (middlewares e cabeçalhos defensivos), na autenticação e autorização (anti-spoofing e tokens), na lógica de aplicação (orçamento em duas fases e validação de esquemas) e na camada de dados (isolamento multilocatário no PostgreSQL e SQLite).
2. **Privilégio Mínimo (*Least Privilege*)**:
   - Agentes autônomos recebem permissão apenas para invocar ferramentas explicitamente autorizadas para o seu contexto (`ferramentas_permitidas`).
   - Contêineres Docker executam sob usuário não-privilegiado (`appuser`, UID `10001`).
3. **Comportamento *Fail-Closed***:
   - Em caso de ambiguidade, ausência de credenciais obrigatórias ou configuração inconsistente em ambiente produtivo, o sistema aborta a execução imediatamente com erro descritivo em vez de operar de forma permissiva.
4. **Minimização de Dados (*Data Minimization*)**:
   - Dados Pessoais Identificáveis (PII) são estritamente omitidos de traces OpenTelemetry e mascarados em logs estruturados antes da gravação.

---

## 2. Governança de Credenciais e Modo *Fail-Closed* em Produção (SEC-001)

### 2.1 Validação de Credenciais Inseguras (`eh_credencial_insegura_producao`)
O módulo `configuracoes.py` centraliza a inspeção de credenciais:
- **Entropia Mínima**: Exige no mínimo 16 caracteres.
- **Bloqueio de Chaves Padrão do Docker Compose**: Rejeita terminantemente credenciais demonstrativas conhecidas como `dev-local-master-key-12345678`, `dev-service-m2m-key-12345678` e `dev-piloto-secret-key-12345678`.
- **Bloqueio por Prefixos e Termos Fracos**: Rejeita qualquer chave que inicie com prefixos como `dev-`, `dev_`, `teste-`, `demo-`, `exemplo-`, ou que contenha sequências triviais (`12345678`, `master-key`, `secret-key`).

### 2.2 Bloqueio no Bootstrap do AI Gateway (`validar_seguranca_producao`)
Ao inicializar com `GATEWAY_AMBIENTE=producao`:
- A ausência de credenciais administrativas (`GATEWAY_API_KEY`) ou o uso de chaves inseguras dispara `ValueError`, interrompendo a inicialização do contêiner.
- Ambientes desconhecidos ou com erros de digitação (ex: `prod_typo`) são rejeitados sem fallback silencioso para desenvolvimento.
- Em tempo de execução, o `ValidadorAutenticacao` intercepta requisições contendo chaves fracas e devolve `401 Unauthorized` imediato, sem expor a chave nos logs.

### 2.3 Procedimento para Geração de Chaves Criptográficas Seguras
Em produção, todas as chaves **devem** ser geradas por um gerador pseudoaleatório criptograficamente seguro (CSPRNG):
```bash
# Gerar chave segura com 256 bits de entropia (32 bytes em Base64 URL-safe):
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Alternativa via OpenSSL (hexadecimal de 256 bits):
openssl rand -hex 32
```

---

## 3. Proteções de Borda HTTP e Cabeçalhos Defensivos (SEC-005, SEC-009, REV-002)

O `MiddlewareCabecalhosSeguranca` intercepta todas as respostas HTTP e injeta defesas padronizadas:

| Cabeçalho | Valor Configurado | Proteção Oferecida |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Impede ataques de MIME sniffing pelo navegador. |
| `X-Frame-Options` | `DENY` | Previne ataques de Clickjacking e incorporação em `<iframe>`. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limita o vazamento de caminhos e parâmetros em links externos. |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` | Desativa APIs de hardware desnecessárias na aplicação. |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Força conexões HTTPS durante 1 ano. Injetado estritamente quando `request.url.scheme == "https"`. |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; ...` | Endurecida nas rotas `/piloto`, eliminando `'unsafe-inline'` para scripts (SEC-009). |

### 3.1 Prevenção de HSTS Spoofing (REV-002 e RFC 6797 Sec 7.2)
Para impedir que um cliente malicioso sobre HTTP puro force o cabeçalho HSTS enviando um cabeçalho forjado `X-Forwarded-Proto: https`, a aplicação **não** consulta esse cabeçalho diretamente. A validação depende estritamente de `request.url.scheme == "https"`, populado pelo servidor ASGI (Uvicorn) configurado com `--proxy-headers` e `--forwarded-allow-ips` apontando para os IPs dos proxies reversos autorizados.

---

## 4. Segurança da Aplicação Piloto e Camada Intermediária BFF (SEC-002, SEC-004, SEC-009)

A aplicação piloto adota o padrão BFF (Backend-For-Frontend) para proteger o navegador:

1. **Prevenção de DOM XSS (SEC-002)**:
   - A função cliente `escapeHtml()` sanitiza rigorosamente qualquer entrada interpolada via `innerHTML`, convertendo caracteres perigosos (`&`, `<`, `>`, `"`, `'`).
   - Rótulos de cabeçalho, mensagens de erro e indicadores utilizam estritamente nós DOM seguros via `textContent`.
2. **Desacoplamento do Segredo de Sessão (SEC-004)**:
   - O segredo de assinatura de cookies HMAC é obtido exclusivamente da variável `GATEWAY_PILOTO_SEGREDO_SESSAO`.
   - Eliminado o fallback para `GATEWAY_API_KEY`. Em produção, a ausência do segredo dedicado dispara interrupção *fail-closed* e HTTP 500 imediato caso acessado.
3. **Sessão Segura HMAC-SHA256 e Anti-CSRF**:
   - Cookie `piloto_sessao`: assinado criptograficamente no formato `id_usuario.timestamp.hmac` com flags `HttpOnly=True`, `SameSite="Lax"` e `Secure=True` (em HTTPS ou produção).
   - Cabeçalho `X-CSRF-Token`: obrigatório em mutações de estado (`POST /piloto/api/chat` e `POST /piloto/api/sessao`), validado em tempo constante com `hmac.compare_digest` contra ataques de temporização.
4. **Externalização do JavaScript da SPA (SEC-009)**:
   - Todo o script client-side foi extraído para a rota `/piloto/app.js`. Handlers inline legados (`onclick`, `onkeydown`) foram substituídos por ouvintes `addEventListener`, permitindo a remoção de `'unsafe-inline'` da CSP.

---

## 5. Isolamento Multilocatário e Prevenção IDOR (SEC-003, ADR 0005)

1. **Titularidade de Conversas**:
   - Cada conversa (`id_conversa`) criada possui um titular associado (`id_usuario`).
   - A posse é vinculada no momento da inserção da primeira mensagem, tanto no `MemoriaPostgresql` quanto no `MemoriaSQLite`.
2. **Prevenção de IDOR e Acesso Cruzado**:
   - Tentativas de consultar (`GET /v1/conversas/{id_conversa}`), continuar ou limpar (`DELETE /v1/conversas/{id_conversa}`) conversas registradas por outro usuário são bloqueadas com `ErroAcessoNaoAutorizadoConversa`, mapeado para **HTTP 403 Forbidden** (RFC 7807).
3. **Auditoria Anti-Spoofing de `X-User-ID`**:
   - Clientes comuns com chaves de API não podem declarar arbitrariamente o cabeçalho `X-User-ID` para personificar terceiros. Qualquer discrepância resulta em **HTTP 403 Forbidden**.
   - Apenas chaves M2M em `GATEWAY_CHAVES_CONFIAVEIS` possuem autorização para delegar identidades de usuários.

---

## 6. Governança Orçamentária e Prevenção de DoS (SEC-003, SEC-006, REV-001)

### 6.1 Protocolo de Reserva Atômica em Duas Fases (`PoliticaOrcamentoTokens`)
Para evitar estouro de cotas decorrente de requisições concorrentes (condições de corrida TOCTOU):
1. **Fase 1 (Pré-reserva Atômica)**: Antes de disparar a requisição ao modelo, a cota estimada (`tokens_entrada + max_tokens`) é retida sob lock (`asyncio.Lock()`). Se o teto for ultrapassado, rejeita com HTTP 429 (`ErroLimiteOrcamentoTokens`).
2. **Fase 2 (Confirmação Real)**: Após o modelo responder, a reserva estimada é liquidada pelo número exato de tokens consumidos.

### 6.2 Cancelamento Seguro em Streaming SSE (SEC-006 e REV-001)
- O gerador assíncrono em `CasoDeUsoGerarRespostaFluxo` é estruturado em `try...except BaseException...finally` com flag atômica `reserva_finalizada`.
- Cancelamentos por desconexão do cliente (`asyncio.CancelledError`), fechamento antecipado com `aclose()` (`GeneratorExit`) ou falhas do provedor LLM liberam imediatamente a reserva retida na `PoliticaOrcamentoTokens`, prevenindo esgotamento indevido do saldo do usuário.

### 6.3 Orçamento no Ciclo de Agentes ReAct (SEC-003)
- O `OrquestradorAgente` executa pré-reserva atômica de tokens a cada iteração do ciclo ReAct, debitando o consumo real após a chamada ao modelo e liberando a cota em caso de erro.

---

## 7. Segurança na Execução de Ferramentas (Tool Calling)

A execução autônoma de ferramentas por modelos de IA apresenta riscos de *Prompt Injection* e ações destrutivas. A plataforma mitiga esses riscos através de:
1. **Flag `requer_autorizacao=True`**: Ferramentas que realizam mutação de dados, deleção ou chamadas externas sensíveis devem ser marcadas com essa flag.
2. **`PoliticaAutorizacaoFerramenta`**: Avalia cada chamada antes da invocação. Ferramentas sensíveis exigem autorização prévia (`aprovar_ferramenta`), e ferramentas em lista negra são rejeitadas imediatamente com `ErroFerramentaNaoAutorizada` (HTTP 403).
3. **Tratamento de Exceções**: Falhas em ferramentas são capturadas e devolvidas como mensagem de erro controlada ao modelo (`ResultadoFerramenta(sucesso=False)`), sem comprometer o processo do backend.

---

## 8. Segurança na Observabilidade e Telemetria (SEC-008, REV-003)

1. **Autenticação Fail-Closed em `/metrics` (SEC-008)**:
   - Em produção, se nenhuma credencial estiver configurada, o endpoint responde `403 Forbidden`.
   - Se configurado `GATEWAY_METRICAS_TOKEN`, exige autenticação via `Authorization: Bearer <token>` com comparação em tempo constante (`hmac.compare_digest`).
2. **Minimização de Dados em Spans OpenTelemetry (REV-003)**:
   - O identificador do usuário (`agente.id_usuario`) foi completamente omitido dos spans OpenTelemetry, eliminando qualquer vazamento de PII (LGPD / GDPR) para plataformas de APM. Spans registram apenas metadados operacionais não identificáveis (`agente.nome`, `agente.modelo`, `agente.limite_passos`).
3. **Sanitização Ativa de Logs (`FormatadorLogJson`)**:
   - Dicionários de logs mascaram automaticamente chaves como `api_key`, `token`, `authorization`, `password`, `secret` e `bearer`.
   - Expressões regulares examinam o corpo de mensagens de erro, substituindo padrões como `sk-...`, `Bearer ...` e `AIza...` por `[CREDENTIAL_REDACTED]`.

---

## 9. Segurança da Infraestrutura e Cadeia de Suprimentos (SEC-007)

1. **Isolamento no `.dockerignore`**:
   - O arquivo `.dockerignore` exclui explicitamente o diretório `.agents/`, o arquivo `skills-lock.json` e relatórios de auditoria, impedindo sua inclusão acidental na imagem de produção.
2. **Análise de Vulnerabilidades de Dependências (SCA no CI)**:
   - O pipeline do GitHub Actions (`.github/workflows/ci.yml`) inclui step obrigatório de SCA executando `uv run --with pip-audit pip-audit`, garantindo a ausência de CVEs conhecidas nas bibliotecas utilizadas.

---

## 10. Limitações e Riscos Residuais Documentados

1. **Orçamento e Rate Limiting Confinados à Memória Local**:
   - A `PoliticaOrcamentoTokens` e o `LimitadorTaxa` utilizam locks em memória volátil (`asyncio.Lock()`). Em topologias com múltiplos pods ou múltiplos workers Uvicorn, as cotas são particionadas por processo, não garantindo um teto global unificado sem a adoção de um coordenador de estado distribuído (ex: Redis).
2. **Necessidade de Configuração de Proxies Reversos de Borda**:
   - Em produção sob balanceadores, o Uvicorn deve ser configurado com `--proxy-headers` e `--forwarded-allow-ips` para validar confiavelmente o esquema HTTPS para HSTS.
3. **Gestão de Segredos**:
   - As variáveis sensíveis devem ser injetadas por cofres gerenciados (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager).

4. **Escopo da Auditoria e Ausência de Certificação Formal**:
   - A revisão de segurança realizada baseou-se em auditoria estática e estrutural orientada pela Cloudflare Security Audit Skill. Não constitui certificação formal de conformidade (como ISO 27001 ou SOC 2) nem substitui testes de intrusão (*penetration tests* ou DAST) em ambiente de homologação dedicado.

---

## 11. Referências

- [ADR 0004: Validação Rigorosa e Defesas de Borda](adr/0004-validacao-rigorosa-e-defesas-de-borda.md)
- [ADR 0005: Isolamento Multilocatário e Autorização de Conversas](adr/0005-isolamento-multilocatario-e-autorizacao-conversas.md)
- [ADR 0006: Controle de Identidade Anti-Spoofing e Persistência PostgreSQL](adr/0006-controle-identidade-anti-spoofing-e-persistencia-postgresql.md)
- [ADR 0007: Protocolo de Reserva Atômica de Tokens em Duas Fases](adr/0007-reserva-atomica-de-tokens-em-duas-fases.md)
- [ADR 0010: Aplicação Piloto e Interface BFF Segura](adr/0010-aplicacao-piloto-e-interface-bff-segura.md)
- [ADR 0011: Auditoria Estática e Remediação Conclusiva de Segurança](adr/0011-auditoria-e-remediacao-de-seguranca.md)
