# Documentação de Segurança e AppSec

Este documento detalha os controles de segurança de aplicação (AppSec), proteção de credenciais, autorização de execução de ferramentas e mitigação de vulnerabilidades implementados no projeto.

---

## 1. Princípios de Segurança da Arquitetura

1. **Defesa em Profundidade (*Defense in Depth*)**: A segurança é aplicada na borda (Gateway HTTP), na orquestração (Agente) e no acesso a ferramentas externas.
2. **Privilégio Mínimo (*Least Privilege*)**: Agentes autônomos recebem acesso apenas às ferramentas estritamente permitidas para o seu contexto (`ferramentas_permitidas`).
3. **Não-Repúdio e Rastreabilidade**: Cada requisição recebe um `X-Request-ID` único, propagado nos logs e métricas.

---

## 2. Proteção de Credenciais e Segredos

- **`CofreCredenciais`**:
  - Centraliza a recuperação de segredos de variáveis de ambiente.
  - Provê método de mascaramento de credenciais (`mascarar_chave(...)`), garantindo que apenas os 4 primeiros e 4 últimos caracteres sejam visíveis em logs (ex: `sk-1...7890`), prevenindo vazamentos acidentais em dumps de telemetria.
  - Bloqueio imediato caso credenciais obrigatórias não estejam presentes em ambientes de produção.

- **Sanitização Ativa de Logs (`FormatadorLogJson`)**:
  - Dicionários e campos extras que contenham termos sensíveis (`api_key`, `token`, `authorization`, `password`, `secret`, `bearer`) são mascarados automaticamente antes da gravação.
  - Expressões regulares examinam o corpo de cada mensagem de log, mascarando padrões comuns de tokens (`Bearer ...`, `sk-...`, `AIza...`) para prevenir vazamentos acidentais durante depuração ou falhas de provedores.

---

## 3. Segurança na Execução de Ferramentas (Tool Calling)

A execução autônoma de ferramentas por modelos de IA apresenta riscos de *Prompt Injection* e ações destrutivas inadvertidas. A plataforma mitiga esses riscos através de:

1. **Flag `requer_autorizacao=True`**:
   - Ferramentas que executam operações de escrita, exclusão ou acesso a dados sensíveis são marcadas com essa flag.
2. **`PoliticaAutorizacaoFerramenta`**:
   - Avalia cada chamada antes da invocação.
   - Ferramentas bloqueadas na lista negra são rejeitadas imediatamente.
   - Ferramentas sensíveis exigem que a aplicação ou operador humano invoque previamente `aprovar_ferramenta(...)`, caso contrário a execução é barrada com `ErroFerramentaNaoAutorizada`.
3. **Isolamento de Erros**:
   - Falhas ou exceções levantadas dentro de funções de ferramentas são tratadas internamente e devolvidas como mensagem de erro ao modelo (`ResultadoFerramenta(sucesso=False)`), sem derrubar o processo do backend.

---

## 4. Proteção Contra Esgotamento de Recursos e DoS

1. **Defesas de Borda e Validação de Payloads**:
   - Cada mensagem individual possui teto máximo de 64 KB (`65_536` caracteres).
   - O histórico de mensagens é limitado a 200 itens por chamada.
   - O identificador de conversa `id_conversa` é validado estritamente (`^[a-zA-Z0-9_\-\.:]+$`), bloqueando caracteres nulos e ataques de injeção.
2. **Proteção Contra Bombas de Esquema JSON**:
   - Esquemas submetidos à rota `/v1/chat/estruturado` são inspecionados pelo `ValidadorEsquemaJson`, que limita a profundidade de aninhamento a no máximo 5 níveis e restringe tipos permitidos.
3. **Controle Orçamentário de Tokens (`PoliticaOrcamentoTokens`)**:
   - Impõe tetos configuráveis de tokens por requisição individual e acumulado por sessão, interrompendo precocemente chamadas abusivas com HTTP 429 (`ErroLimiteOrcamentoTokens`).
4. **Salvaguarda de Loops Infinitos**:
   - O `OrquestradorAgente` impõe um teto estrito de iterações (`limite_passos`) e `timeout_segundos`. Caso o modelo entre em ciclo repetitivo, a execução é interrompida com segurança.
5. **Controle de Concorrência e Taxa**:
   - `LimitadorTaxa` (Token Bucket) e `SemaforoConcorrencia` protegem os provedores de exaustão de cotas e ataques de negação de serviço.
6. **Disjuntor (*Circuit Breaker*)**:
   - Em caso de instabilidade grave de um provedor remoto, o circuito é aberto, rejeitando chamadas no próprio servidor em microssegundos sem esperar timeouts de rede.


---

## 5. Isolamento Multilocatário e Segregação de Histórico Conversacional

1. **Titularidade de Conversas**:
   - Cada conversa (`id_conversa`) criada possui um titular associado (`id_usuario`).
   - A posse é vinculada no momento da inserção da primeira mensagem, tanto na `MemoriaEmMemoria` quanto no `MemoriaSQLite`.
2. **Prevenção contra Acesso Cruzado e IDOR**:
   - Tentativas de consultar, continuar ou limpar o histórico de uma conversa registrada por outro identificador de usuário são bloqueadas imediatamente com `ErroAcessoNaoAutorizadoConversa`.
   - O AI Gateway mapeia essa exceção para **HTTP 403 Forbidden** no formato RFC 7807, impedindo qualquer vazamento ou adulteração de contexto conversacional.
3. **Limitação Orçamentária por Usuário**:
   - A `PoliticaOrcamentoTokens` suporta quotas individuais (`limite_tokens_por_usuario`), garantindo que nenhum usuário ou tenant monopolize a cota global da aplicação.


---

## 6. Prevenção de Falsificação de Identidade (Anti-Spoofing de X-User-ID)

1. **Separação de Privilégios M2M vs Cliente**:
   - Clientes regulares autenticados via token ou chave de API possuem seu identificador de usuário vinculado de forma determinística à sua credencial (`mapeamento_chaves_usuarios` ou hash seguro da chave).
   - O cabeçalho `X-User-ID` fornecido pelo cliente é auditado rigorosamente: se um cliente regular tentar informar um identificador divergente daquele associado à sua chave, o Gateway intercepta a tentativa de personificação e responde com **HTTP 403 Forbidden**.
   - Apenas serviços corporativos confiáveis (chaves em `chaves_servicos_confiaveis` ou chave mestre sem vínculo restrito) possuem permissão para delegar/representar identidades de terceiros via `X-User-ID`.
2. **Reserva Atômica de Cotas (Anti-Race Condition)**:
   - A `PoliticaOrcamentoTokens` impede que múltiplos disparos simultâneos explorem janelas de concorrência (TOCTOU).
   - Os tokens são reservados atimicamente sob lock antes da invocação do modelo, e liberados automaticamente caso a requisição falhe por timeout ou erro do provedor externo.

---

## 7. Governança de Credenciais e Modo Fail-Closed em Produção

1. **Inicialização Segura (Fail-Closed)**:
   - Quando configurado com `ambiente="producao"` (`GATEWAY_AMBIENTE=producao`), o Gateway executa validação estrita no startup (`validar_seguranca_producao`).
   - A inicialização é abortada imediatamente caso não haja credenciais configuradas ou caso sejam fornecidas chaves padrão/demonstração (como `chave-teste-padrao`, `chave-servico-confiavel`, `admin`, `secret`, etc.) ou com entropia insuficiente (< 16 caracteres), tanto para chaves mestres quanto para serviços confiáveis M2M.
2. **Rejeição de Ambientes Desconhecidos (Sem Fallback Silencioso)**:
   - A configuração inspeciona `GATEWAY_AMBIENTE`, `ENVIRONMENT` ou `APP_ENV` contra a lista restrita de ambientes permitidos (`producao`, `desenvolvimento`, `teste`, `homologacao`).
   - Qualquer valor divergente, não reconhecido ou com erros de digitação (ex: `prod_typo`) aborta imediatamente a carga com `ValueError`, impedindo o fallback silencioso para o modo permissivo de desenvolvimento.
3. **Validação em Tempo de Execução**:
   - Toda requisição recebida em ambiente de produção é inspecionada: chaves de demonstração são rejeitadas com HTTP 401 Unauthorized, sem expor o valor da chave em mensagens de erro ou logs de auditoria.
4. **Procedimento de Geração Criptográfica Segura de Credenciais**:
   - As credenciais de produção **devem** ser geradas através de gerador de números pseudoaleatórios criptograficamente seguro (CSPRNG).
   - Comandos recomendados para geração (sem expor segredos no repositório):
     ```bash
     # Gerar chave com 256 bits de entropia (32 bytes em formato URL-safe base64)
     python -c "import secrets; print(secrets.token_urlsafe(32))"

     # Alternativa via OpenSSL (hexadecimal de 256 bits)
     openssl rand -hex 32
     ```
   - As chaves geradas devem ser injetadas exclusivamente por variáveis de ambiente (`GATEWAY_API_KEY`, `GATEWAY_CHAVES_CONFIAVEIS`) ou cofres de segredos gerenciados (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager), nunca salvas no código-fonte.
5. **Preservação do Modo de Desenvolvimento**:
   - Em `ambiente="desenvolvimento"`, o Gateway mantém tolerância a chaves locais demonstrativas para permitir testes rápidos sem complexidade desnecessária.

---

## 8. Riscos Operacionais Documentados e Limitações de Escala

1. **Orçamento e Rate Limiting Confinados à Memória Local**:
   - A `PoliticaOrcamentoTokens` e o `LimitadorTaxa` utilizam estruturas atômicas locais sincronizadas via `asyncio.Lock()`.
   - **Atenção**: Esta implementação protege com exatidão a concorrência intraprocesso em monólito com uma réplica. Em topologias com **múltiplas réplicas/pods ou múltiplos workers**, as cotas e limites são particionados por processo, não garantindo um teto orçamentário global consolidado entre nós distintos.
   - Para assegurar quotas rígidas em clusters horizontais, deve-se planejar a adoção de uma porta de coordenação de estado distribuído (ex: Redis ou advisory locks em PostgreSQL) no roadmap de escala.
2. **Limites Configuráveis do Pool de Conexões PostgreSQL**:
   - A persistência assíncrona (`MemoriaPostgresql`) utiliza limites configuráveis: `min_conexoes` (padrão: 2) e `max_conexoes` (padrão: 10, parametrizável via `GATEWAY_POSTGRES_POOL_SIZE` ou construtor).
   - Ao dimensionar o número de réplicas do AI Gateway em produção, o arquiteto de infraestrutura deve calcular: `Total Conexões = Réplicas * GATEWAY_POSTGRES_POOL_SIZE` para evitar esgotamento de `max_connections` no servidor PostgreSQL, sendo recomendado o uso de PgBouncer em implantações de grande porte.
