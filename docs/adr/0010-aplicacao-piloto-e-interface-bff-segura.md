# ADR 0010: Aplicação Piloto e Camada Intermediária BFF Segura (Backend-For-Frontend)

## Status
Aprovado

## Data
2026-10-28

## Contexto
Com a consolidação do núcleo reutilizável (`packages/ai-core`), da infraestrutura conteinerizada com PostgreSQL 17 (`services/ai-gateway`) e da observabilidade com Prometheus e OpenTelemetry, tornou-se necessário demonstrar a utilização prática da arquitetura em um cenário de consumo real, interativo e com custo financeiro zero.

Os desafios de segurança e arquiteturais incluíam:
1. **Proteção de Credenciais**: Não expor chaves mestras (`GATEWAY_API_KEY`) ou credenciais privilegiadas de serviço no navegador.
2. **Integridade de Sessão**: Prevenir adulteração e falsificação de identidade (impersonation/spoofing) no navegador, garantindo que usuários não possam forjar identificadores arbitrários.
3. **Proteção Anti-CSRF**: Mitigar vulnerabilidades de Cross-Site Request Forgery nos endpoints de mutação de estado (`/piloto/api/chat` e `/piloto/api/sessao`).
4. **Isolamento de Banco e Prevenção IDOR**: Impedir conexões SQL diretas e garantir que acessos cruzados a dados de outros usuários sejam terminantemente bloqueados com `403 Forbidden`.
5. **Governança em Produção**: Assegurar comportamento *fail-closed*, desabilitando por padrão rotas demonstrativas em ambiente produtivo.
6. **Métricas Confiáveis**: Garantir que as métricas de tokens (`llm_tokens_total`) e requisições (`llm_requisicoes_total`) reportem grandezas reais sem ambiguidades ou incrementos unitários incorretos.
7. **Simplicidade de Execução**: Não introduzir frameworks pesados de frontend (como React, Angular, Vue) que demandassem ambientes Node.js, Webpack, npm ou pipelines complexos de compilação.
8. **Custo Zero**: Operar inteiramente com o adaptador simulado e infraestrutura local (Docker Compose).

## Decisão

1. **Padrão Backend-For-Frontend (BFF) em `/piloto/api`**:
   - O AI Gateway provê endpoints intermediários dedicados (`/piloto/api/chat`, `/piloto/api/sessao`, `/piloto/api/conversas/{id_conversa}` e `/piloto/api/status`).
   - A autenticação do navegador com o BFF utiliza cookies de sessão assinados com **HMAC-SHA256** (`piloto_sessao`), contendo `id_usuario`, `timestamp` e assinatura criptográfica.
   - Atributos de segurança dos cookies: `HttpOnly=True`, `SameSite="Lax"` e `Secure=True` (em HTTPS ou produção).
   - O BFF atua como agente intermediário seguro, validando a integridade da sessão e derivando a identidade legítima sem expor chaves privilegiadas ao cliente web.

2. **Proteção Anti-CSRF Estruturada**:
   - Todas as requisições de alteração de estado (`POST /piloto/api/chat` e `POST /piloto/api/sessao`) exigem a presença do cabeçalho `X-CSRF-Token`.
   - O token anti-CSRF é derivado criptograficamente da sessão via HMAC e validado em tempo constante (`hmac.compare_digest`) para prevenir ataques de temporização.

3. **Restrição Estrita de Perfis de Demonstração e Governança de Produção**:
   - A alternância demonstrativa de perfis é restrita a uma lista estrita de demonstração: `{"usuario_alfa", "usuario_beta"}`.
   - Qualquer tentativa de assumir usuários arbitrários fora da lista é rejeitada com `400 Bad Request`.
   - Em ambiente de produção (`config.e_producao`):
     - A alternância de perfis é bloqueada com `403 Forbidden`.
     - Por padrão, a aplicação piloto opera em modo *fail-closed* (`piloto_habilitado=False`), retornando `404 Not Found` em todas as rotas `/piloto` caso não seja explicitamente autorizada.

4. **Single Page Application (SPA) Leve em HTML5/CSS3/Vanilla JS**:
   - O endpoint `GET /piloto` entrega uma interface moderna, responsiva e com suporte a modo escuro diretamente via FastAPI.
   - Nenhuma ferramenta externa ou runtime adicional (Node/npm) é exigido na imagem Docker do Gateway ou na máquina de desenvolvimento.

5. **Endpoint Canônico de Histórico (`GET /v1/conversas/{id_conversa}`) e Prevenção IDOR**:
   - Criado endpoint oficial na API do AI Gateway permitindo aos clientes autorizados consultar o histórico de mensagens armazenado na `PortaRepositorioMemoria` (PostgreSQL / SQLite).
   - O endpoint valida estritamente a posse do recurso, rejeitando tentativas de consulta ou remoção de conversas alheias com `403 Forbidden` RFC 7807 padronizado.

6. **Correção e Segregação da Telemetria de Modelos**:
   - Criado contador `llm_requisicoes_total` no Prometheus para medir a quantidade de requisições de inferência por modelo.
   - O contador `llm_tokens_total` foi corrigido para acumular a quantidade REAL de tokens consumidos:
     - `tipo="entrada"`: tokens de entrada.
     - `tipo="saida"`: tokens de saída.
     - `tipo="total"`: soma real (`tokens_entrada + tokens_saida`), eliminando contagem indevida de requisições como tokens.

## Consequências

### Positivas
- Demonstração funcional imediata através de `http://localhost:8000/piloto` logo após `docker compose up -d`.
- Segurança por padrão (*Secure by Design*): chaves e credenciais do banco restritas ao servidor; proteção contra CSRF, adulteração de cookies e personificação (anti-spoofing).
- Prevenção comprovada de IDOR no PostgreSQL 17 relacional.
- Isolamento estrito entre ambientes com proteção *fail-closed* em produção.
- Telemetria fidedigna de métricas de tokens e requisições no Prometheus.
- Zero acréscimo de custo de infraestrutura ou complexidade de build.

### Negativas / Mitigações
- Para produtos em escala corporativa comercial com centenas de telas, um framework SPA desacoplado pode ser preferível; para fins de aplicação piloto e validação arquitetural, a SPA leve atende com máxima fidelidade e menor atrito.
