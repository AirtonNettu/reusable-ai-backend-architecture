# ADR 0008: Conteinerização Multi-Stage, Orquestração com Docker Compose e Isolamento de Persistência

## Status
Aprovado

## Contexto
Na Fase 1 do projeto, homologamos a persistência relacional com PostgreSQL 17 através de contêineres temporários no pipeline de CI do GitHub Actions e com SQLite/memória no ambiente local.

Para a Fase 2, era necessário estabelecer um ambiente de desenvolvimento local e de homologação reproduzível, padronizado e seguro, atendendo aos seguintes requisitos:
1. Permitir que novos engenheiros inicializem toda a pilha (Gateway, PostgreSQL 17 e opcionalmente Ollama) com um único comando declarativo.
2. Garantir segurança em contêineres seguindo as melhores práticas corporativas (princípio do menor privilégio, usuário não-root, imagens mínimas sem ferramentas de compilação no runtime).
3. Assegurar que dados persistentes de conversas e migrações do PostgreSQL sobrevivam a reinicializações de contêineres sem corrupção.
4. Evitar a publicação desnecessária de portas de banco de dados diretamente na máquina hospedeira, prevenindo conflitos com instâncias locais pré-existentes de PostgreSQL e fechando vetores de ataque externos.
5. Suportar inferência local com Ollama de forma totalmente opcional (sob demanda) e sem download automático de gigabytes de modelos.

## Decisão
1. **Dockerfile Multi-Stage com Python 3.13 e uv**:
   - Estágio de compilação (`builder`) utilizando a imagem oficial `ghcr.io/astral-sh/uv:latest` para resolver e compilar o ambiente virtual do monorepo (`uv sync --frozen --no-dev`) com cache de camadas otimizado.
   - Estágio final (`runtime`) baseado em `python:3.13-slim` contendo apenas o virtualenv e o código-fonte, sem compiladores de sistema (`gcc`), rodando sob usuário sem privilégios (`appuser:appgroup` com UID/GID `10001`).
   - Sonda interna de prontidão (`HEALTHCHECK`) no `/health` sem requerer a instalação de pacotes externos (`curl`/`wget`).

2. **Orquestração com Docker Compose**:
   - `postgres`: PostgreSQL 17 Alpine com volume persistente nomeado (`ia_dados_postgresql`), healthcheck ativo via `pg_isready` e porta 5432 restrita à rede interna `ia_rede_interna`.
   - `ai-gateway`: Orquestrado com dependência estrita de prontidão do banco (`condition: service_healthy`) e porta 8000 mapeada para o host.
   - `ollama`: Configurado com o perfil do Compose `profiles: ["ollama"]`, impedindo inicialização acidental ou consumo excessivo de recursos em máquinas de desenvolvimento padrão.

3. **Ciclo de Vida com Migrações Idempotentes**:
   - Integração do `lifespan` assíncrono no FastAPI do Gateway para executar automaticamente as migrações versionadas no startup quando conectado ao PostgreSQL, garantindo que o esquema esteja sempre íntegro antes de receber requisições de clientes.
   - Criação do módulo utilitário `ai_gateway.migrar` para suporte a execuções manuais ou em rotinas de CI/CD.

## Consequências
### Positivas
- Ambiente local 100% reproduzível e idêntico ao ambiente de homologação.
- Redução substancial do tamanho da imagem final de produção e eliminação de vulnerabilidades decorrentes de privilégios de root.
- Dados conversacionais persistidos de forma confiável em volumes nomeados do Docker.
- Inexistência de conflitos de porta 5432 com instâncias locais do desenvolvedor.
- Suporte a inferência local com Ollama quando desejado pelo operador.

### Negativas / Mitigações
- Para depuração direta do banco de dados na máquina hospedeira com clientes gráficos (como DBeaver), o desenvolvedor deve descomentar o mapeamento de porta `127.0.0.1:5432:5432` no `docker-compose.yml`.
