# ADR 0004: Validação Rigorosa de Esquemas, Defesas de Borda e Sanitização de Logs

## Status
Aprovado

## Contexto
Aplicações de Inteligência Artificial expostas via HTTP enfrentam vetores de ataque específicos:
1. **Injeção de Payloads Desproporcionais (DoS)**: Requisições com strings de dezenas de megabytes que esgotam a memória do gateway ou geram custos exorbitantes de inferência.
2. **Esquemas JSON Maliciosos ou Inválidos**: Tentativa de explorar a rota de saídas estruturadas com esquemas profundamente aninhados (ataques de recursão) ou tipos inválidos.
3. **Falsos Positivos de Validação Estruturada**: Aceitar respostas de LLMs apenas por serem JSON válido, mesmo quando não satisfazem os tipos e campos obrigatórios do esquema solicitado.
4. **Conflito de Concorrência em Banco**: SQLite operando sem modo WAL ou sem tempo limite de espera em concorrência multithread.
5. **Vazamento Acidental de Segredos em Telemetria**: Logs corporativos registrando tokens JWT ou chaves de API passadas em cabeçalhos ou campos extras.

## Decisão
Implementamos um pacote de salvaguardas coordenado:
1. **Defesas de Borda no Gateway**:
   - Limite estrito de 64 KB (`max_length=65_536`) por mensagem.
   - Limite de 200 mensagens por requisição.
   - Sanitização de `id_conversa` com regex restritivo (`^[a-zA-Z0-9_\-\.:]+$`).
2. **Serviço Puro de Validação de JSON Schema (`ValidadorEsquemaJson`)**:
   - Valida a definição do esquema limitando profundidade máxima a 5 níveis para prevenir ataques de recursão.
   - Valida a conformidade semântica dos dados gerados contra o esquema (tipos primitivos, arrays, objetos e campos obrigatórios).
3. **Persistência Concorrente no SQLite (`MemoriaSQLite`)**:
   - Ativação de `WAL` mode (`PRAGMA journal_mode = WAL;`) e `PRAGMA busy_timeout = 15000;`.
   - Timeout de conexão explícito de 15 segundos e transações atômicas seguras com locks.
4. **Sanitização Ativa de Logs (`FormatadorLogJson`)**:
   - Mascaramento por chave em dicionários extras (`api_key`, `token`, `authorization`, etc.).
   - Detecção por expressões regulares de padrões como `Bearer ...`, `sk-...` e `AIza...` no corpo da mensagem.
5. **Controle de Custos e Orçamento de Tokens (`PoliticaOrcamentoTokens`)**:
   - Verificação prévia de estimativa de tokens por requisição e acumulado por sessão, interrompendo abusos com `ErroLimiteOrcamentoTokens` (HTTP 429).

## Consequências
### Positivas
- Proteção robusta contra negação de serviço e estouro de memória.
- Garantia formal de integridade nas rotas de saídas estruturadas.
- Risco zero de vazamento de credenciais em logs de telemetria.
- SQLite apto a suportar concorrência real em ambientes de desenvolvimento e borda.

### Negativas
- Pequeno overhead computacional de validação sintática antes de delegar chamadas aos modelos.
