# Infraestrutura Local e Orquestração

Este documento define a arquitetura de infraestrutura da **Reusable AI Backend Architecture**, detalhando os procedimentos de execução conteinerizada via Docker Compose, o empacotamento multi-stage seguro e o guia de execução nativa bare-metal com `uv`.

---

## 1. Visão Geral da Infraestrutura Conteinerizada

A infraestrutura foi concebida sob os princípios de **reprodutibilidade estrita**, isolamento de rede e segurança por padrão (*Secure by Default*):

```mermaid
flowchart TD
    subgraph Host["Máquina Hospedeira (Desenvolvimento ou Servidor)"]
        ClienteREST["Cliente API / curl / SDK"]
        Navegador["Navegador Web (SPA do Piloto)"]
    end

    subgraph DockerBridge["Rede Interna Docker: ia_rede_interna (Bridge Isolada)"]
        direction TB
        Gateway["AI Gateway (ia-gateway)<br/>Python 3.13 + uv | Porta: 8000<br/>Usuário: appuser (não-root, UID 10001)<br/>Middlewares de Borda e Lifespan Assíncrono"]
        Postgres["PostgreSQL 17 Alpine (ia-postgres)<br/>Porta Interna: 5432 (Não exposta ao host)<br/>Banco: ia_conversas"]
        Ollama["Ollama (ia-ollama) [Perfil Opcional: ollama]<br/>Porta: 11434<br/>Inferência Local Offline"]
    end

    subgraph VolumesArmazenamento["Volumes Persistentes Gerenciados"]
        VolPG[("ia_dados_postgresql<br/>Retenção de histórico e migrações")]
        VolOllama[("ia_dados_ollama<br/>Pesos de modelos locais")]
    end

    ClienteREST -->|HTTP REST / SSE na Porta 8000| Gateway
    Navegador -->|HTTP GET /piloto e BFF| Gateway
    Gateway -->|Conexão TCP asyncpg + Pool Seguro| Postgres
    Gateway -.->|Inferência Local (se perfil ativo)| Ollama
    Postgres --- VolPG
    Ollama --- VolOllama
```

---

## 2. Componentes da Infraestrutura

### 2.1 Serviço `ai-gateway`
- **Construção (`Dockerfile`)**:
  - Compilação *multi-stage* utilizando a imagem oficial `ghcr.io/astral-sh/uv:latest` para sincronização ultrarrápida do workspace.
  - Imagem de execução enxuta baseada em `python:3.13-slim`.
  - **Segurança de Contêiner**: Execução restrita sob o usuário de sistema `appuser` (UID/GID `10001`), sem privilégios de root, eliminando vetores de escalada de privilégios.
- **Porta Exposta**: `8000:8000` (mapeada para a variável `${GATEWAY_PORTA:-8000}`).
- **Healthcheck Automático**: Sonda HTTP executada a cada 10s via Python puro (`urllib.request.urlopen('http://127.0.0.1:8000/health')`), sem depender do binário `curl` na imagem de produção.
- **Ordem de Inicialização Declarativa**: Depende do serviço `postgres` estar em estado estritamente saudável (`condition: service_healthy`).
- **Migrações Automáticas**: No *lifespan* assíncrono do FastAPI, o Gateway conecta ao PostgreSQL e aplica de forma idempotente todas as migrações SQL versionadas antes de liberar a porta para tráfego.

### 2.2 Serviço `postgres` (PostgreSQL 17)
- **Imagem Oficial**: `postgres:17-alpine`.
- **Isolamento de Borda**: A porta `5432` **não é publicada na máquina hospedeira por padrão**, impedindo qualquer exposição externa não autorizada. Apenas contêineres na rede `ia_rede_interna` podem comunicar com o banco.
  > [!TIP]
  > Para inspecionar o banco diretamente na máquina hospedeira durante o desenvolvimento local (usando DBeaver ou psql), descomente a diretiva `ports: - "127.0.0.1:5432:5432"` no `docker-compose.yml`.
- **Persistência**: Mapeado para o volume nomeado `ia_dados_postgresql`, retendo conversas, usuários e auditorias mesmo após comandos `docker compose down`.
- **Healthcheck**: Verificação nativa via utilitário `pg_isready`.

### 2.3 Serviço `ollama` (Inferência Local Opcional)
- **Perfil do Compose**: Ativado exclusivamente com `profiles: ["ollama"]`.
- **Comportamento Consciente**: Não é iniciado por padrão no comando básico `docker compose up`, evitando consumo ocioso de memória RAM e GPU.
- **Gerenciamento de Modelos**: Não executa download automático de pesos de modelos sem ação deliberada do operador (`docker compose exec ollama ollama pull <modelo>`).
- **Volume**: Mapeado para `ia_dados_ollama`.

---

## 3. Gestão de Configurações e Variáveis de Ambiente

Copie o arquivo de exemplo antes da primeira execução:
```bash
cp .env.example .env
```

### Tabela Completa de Variáveis de Ambiente

| Variável | Padrão no Compose | Módulo Correspondente | Descrição Operacional |
| :--- | :--- | :--- | :--- |
| `GATEWAY_AMBIENTE` | `desenvolvimento` | `configuracoes.py` | Ambiente de execução (`desenvolvimento`, `teste`, `homologacao`, `producao`). Em produção, opera fail-closed. |
| `GATEWAY_PORTA` | `8000` | `docker-compose.yml` | Porta TCP publicada no host para o AI Gateway. |
| `GATEWAY_API_KEY` | `dev-local-master-key-12345678` | `configuracoes.py` | Chave mestre de autenticação da API (headers `X-API-Key` ou `Bearer`). |
| `GATEWAY_CHAVES_CONFIAVEIS` | `dev-service-m2m-key-12345678` | `configuracoes.py` | Chaves de serviço M2M autorizadas a delegar identidades via `X-User-ID`. |
| `GATEWAY_PERMITIR_DELEGACAO_M2M` | `true` | `configuracoes.py` | Habilita ou desabilita a representação de identidades de terceiros por serviços M2M. |
| `GATEWAY_MODELO_PADRAO` | `modelo-teste` | `configuracoes.py` | Modelo de IA selecionado por padrão nas chamadas que omitem o parâmetro. |
| `GATEWAY_TIMEOUT_SEGUNDOS` | `60.0` | `configuracoes.py` | Timeout global em segundos para respostas de inferência e casos de uso. |
| `GATEWAY_MEMORIA_TIPO` | `postgresql` | `configuracoes.py` | Mecanismo de persistência conversacional (`memoria`, `sqlite`, `postgresql`). |
| `GATEWAY_SQLITE_PATH` | `:memory:` | `configuracoes.py` | Caminho do arquivo SQLite (quando `GATEWAY_MEMORIA_TIPO=sqlite`). |
| `POSTGRES_DB` | `ia_conversas` | `docker-compose.yml` | Nome do banco de dados relacional PostgreSQL. |
| `POSTGRES_USER` | `usuario_ia` | `docker-compose.yml` | Usuário do banco de dados PostgreSQL. |
| `POSTGRES_PASSWORD` | `senha_ia_local` | `docker-compose.yml` | Senha local de desenvolvimento do banco de dados. |
| `GATEWAY_POSTGRES_POOL_SIZE` | `10` | `configuracoes.py` | Limite máximo de conexões simultâneas no pool `asyncpg`. |
| `GATEWAY_POSTGRES_URL` | *Automática* | `configuracoes.py` | URL de conexão asyncpg montada pelo Compose ou injetada manualmente. |
| `GATEWAY_PILOTO_HABILITADO` | `true` | `configuracoes.py` | Habilita a aplicação piloto e a camada BFF (`/piloto/*`). |
| `GATEWAY_PILOTO_SEGREDO_SESSAO` | `dev-piloto-secret-key-12345678` | `configuracoes.py` | Segredo para assinatura HMAC dos cookies de sessão da SPA. Obrigatório em produção. |
| `GATEWAY_METRICAS_HABILITADAS` | `true` | `configuracoes.py` | Habilita o endpoint de métricas Prometheus `GET /metrics`. |
| `GATEWAY_METRICAS_TOKEN` | `dev-metrics-token-12345678` | `configuracoes.py` | Token dedicado para autenticação do coletor Prometheus. Em produção, protege /metrics com 403. |
| `OTEL_HABILITADO` | `true` | `configuracoes.py` | Habilita instrumentação OpenTelemetry e injeção do cabeçalho W3C `traceparent`. |
| `OTEL_SERVICE_NAME` | `ai-gateway` | `configuracoes.py` | Nome do serviço reportado nos traces OpenTelemetry. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | *Nulo (Memória)* | `configuracoes.py` | URL do coletor OTLP externo HTTP Protobuf (ex: `http://localhost:4318/v1/traces`). |
| `OLLAMA_BASE_URL` | `http://ollama:11434` | `docker-compose.yml` | Endpoint de rede do serviço local de inferência Ollama. |
| `POSTGRES_OBRIGATORIO` | `false` | `tests` | Variável de controle da suíte de testes. Em CI, é definida como `true`. |

---

## 4. Guia de Execução Local

### 4.1 Opção A: Stack Completo com Docker Compose (Recomendada)

1. **Iniciar os Serviços em Segundo Plano**:
   ```bash
   docker compose up -d
   ```
2. **Inspecionar a Saúde dos Contêineres**:
   ```bash
   docker compose ps
   ```
   *Ambos os contêineres (`ia-postgres` e `ia-gateway`) devem exibir o status `healthy`.*
3. **Acompanhar os Logs Estruturados em Tempo Real**:
   ```bash
   docker compose logs -f ai-gateway
   ```
4. **Verificar os Endpoints Operacionais**:
   ```bash
   # Verificação de saúde da aplicação
   curl http://localhost:8000/health

   # Verificação de métricas Prometheus
   curl -H "Authorization: Bearer dev-metrics-token-12345678" http://localhost:8000/metrics

   # Acessar a aplicação piloto no navegador
   # Abra: http://localhost:8000/piloto
   ```
5. **Encerrar a Execução Preservando os Dados**:
   ```bash
   docker compose down
   ```
   *Para apagar explicitamente os volumes de banco e modelos, utilize `docker compose down -v`.*

---

### 4.2 Opção B: Execução Nativa Bare-Metal com `uv`

Para depuração de baixo nível sem contêineres:

1. **Pré-requisitos**:
   - Python 3.13 instalado.
   - Gerenciador de pacotes `uv` instalado.
2. **Sincronizar o Workspace**:
   ```bash
   uv sync --all-packages
   ```
3. **Executar a Suíte Completa de Testes**:
   ```bash
   uv run pytest -v
   ```
4. **Validar Linter e Formatação de Código**:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   ```
5. **Auditar Vulnerabilidades de Dependências (SCA)**:
   ```bash
   uv run --with pip-audit pip-audit
   ```
6. **Iniciar o Servidor em Modo de Desenvolvimento com Recarregamento Automático**:
   ```bash
   uv run uvicorn ai_gateway.main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## 5. Referências

- [ADR 0008: Conteinerização, Docker Compose e Orquestração Local](file:///C:/Users/Airton/reusable-ai-backend-architecture/docs/adr/0008-conteinerizacao-docker-compose-e-orquestracao-local.md)
- [ADR 0011: Auditoria Estática e Remediação Conclusiva de Segurança](file:///C:/Users/Airton/reusable-ai-backend-architecture/docs/adr/0011-auditoria-e-remediacao-de-seguranca.md)
- [Guia de Observabilidade e Monitoramento](file:///C:/Users/Airton/reusable-ai-backend-architecture/docs/observabilidade.md)
