# Documentação de Arquitetura

Este documento descreve detalhadamente os padrões estruturais, camadas lógicas, fluxos de dados e decisões de design implementados na **Reusable AI Backend Architecture**.

---

## 1. Visão Geral da Arquitetura Híbrida

O projeto adota uma arquitetura híbrida que combina os princípios da **Clean Architecture** (Arquitetura Limpa de Robert C. Martin), **Arquitetura Hexagonal (Portas e Adaptadores de Alistair Cockburn)** e o modelo de **Monólito Modular**:

```mermaid
graph TD
    subgraph ServicoGateway ["Camada de Interface: AI Gateway (FastAPI)"]
        Rotas["Rotas HTTP / SSE (/v1/chat, /v1/modelos, /v1/agentes)"]
        Middlewares["Middlewares: Rastreamento & Tratamento RFC 7807"]
        Esquemas["Esquemas Pydantic (Entrada / Saída)"]
        Auth["Validador de Autenticação (API Key / Bearer)"]
    end

    subgraph ModuloCore ["Biblioteca Reutilizável: AI Core"]
        subgraph Aplicacao ["Camada de Aplicação"]
            CasoGerar["CasoDeUsoGerarResposta"]
            CasoFluxo["CasoDeUsoGerarRespostaFluxo"]
            Orquestrador["OrquestradorAgente (ReAct)"]
        end

        subgraph Resiliencia ["Camada de Resiliência"]
            Disjuntor["Disjuntor (Circuit Breaker)"]
            Retentativa["PoliticaRetentativa (Backoff + Jitter)"]
            Limitador["LimitadorTaxa (Token Bucket) & Semáforo"]
            Fallback["PoliticaFallback (Retaguarda em Cadeia)"]
        end

        subgraph Dominio ["Camada de Domínio Puro"]
            Modelos["Entidades: Mensagem, Requisicao, Resposta, Ferramenta"]
            Portas["Portas: PortaProvedorLLM, PortaExecutorFerramentas, PortaRepositorioMemoria"]
            Excecoes["Exceções de Domínio (Sem acoplamento externo)"]
        end

        subgraph Adaptadores ["Camada de Infraestrutura / Adaptadores"]
            AdpProvedores["Adaptadores: Ollama, Gemini, OpenAI, DeepSeek, Anthropic, Simulado"]
            AdpFerramentas["RegistroFerramentas & PoliticaAutorizacao"]
            AdpMemoria["MemoriaEmMemoria & GerenciadorContexto"]
            AdpRoteador["RoteadorModelos"]
            AdpSeguranca["CofreCredenciais"]
            AdpObs["ObservabilidadeEmMemoria"]
        end
    end

    Rotas --> CasoGerar
    Rotas --> CasoFluxo
    Rotas --> Orquestrador
    
    CasoGerar --> Disjuntor
    CasoGerar --> Retentativa
    CasoGerar --> Limitador
    CasoGerar --> AdpRoteador
    
    AdpRoteador --> Portas
    Orquestrador --> Portas
    
    Portas <|.. AdpProvedores
    Portas <|.. AdpFerramentas
    Portas <|.. AdpMemoria
    Portas <|.. AdpObs
```

---

## 2. Separação de Responsabilidades por Camada

### 2.1 Camada de Domínio (`ai_core.dominio`)
- **Regras de Negócio e Contratos Fundamentais**: Contém as estruturas de dados imutáveis (`@dataclass(frozen=True, slots=True)`), como `Mensagem`, `DefinicaoFerramenta`, `ChamadaFerramenta`, `RequisicaoGeracao`, `RespostaGeracao` e `InformacoesModelo`.
- **Independência Tecnológica**: O domínio não conhece nem importa HTTPX, FastAPI, frameworks de banco ou SDKs comerciais.
- **Portas Abstratas**: As portas (`PortaProvedorLLM`, `PortaExecutorFerramentas`, `PortaRepositorioMemoria`, `PortaObservabilidade`) definem contratos abstratos puros com métodos `async` e tipos tipados estaticamente.

### 2.2 Camada de Aplicação (`ai_core.aplicacao`)
- **Casos de Uso**: Coordenam o fluxo de informações entre o roteador, as políticas de resiliência, a memória conversacional e a observabilidade.
- **Runtime de Agentes**: O `OrquestradorAgente` executa o loop ReAct, avaliando quando chamar ferramentas, validando autorização prévia e interrompendo execuções que atinjam o limite de passos ou timeout configurado.

### 2.3 Camada de Resiliência (`ai_core.resiliencia`)
- **Disjuntor (*Circuit Breaker*)**: Três estados (`fechado`, `aberto`, `meio_aberto`). Evita sobrecarga de serviços terceiros instáveis rejeitando imediatamente chamadas enquanto o circuito está aberto.
- **Retentativas com Backoff Exponencial e Jitter**: Retenta erros transitórios (conexão, timeout, rate limit) e aborta imediatamente em erros determinísticos irrecuperáveis (`ErroAutenticacaoProvedor`, `ErroModeloNaoSuportado`, `ErroValidacao`).
- **Limitador de Taxa**: Token Bucket thread-safe/asyncio-safe para controle fino de requisições por segundo.
- **Semáforo de Concorrência**: Limita execuções simultâneas paralelas.
- **Fallback Controlado**: Encadeamento ordenado de alternativas em caso de falha do provedor primário.

### 2.4 Camada de Adaptadores (`ai_core.adaptadores`)
- **Adaptadores de Provedores**: `AdaptadorOllama`, `AdaptadorGemini`, `AdaptadorOpenAI`, `AdaptadorDeepSeek`, `AdaptadorAnthropic` e `AdaptadorSimulado`. Todos implementam a `PortaProvedorLLM`.
- **Registro de Ferramentas**: Registra funções tipadas síncronas ou assíncronas e aplica a `PoliticaAutorizacaoFerramenta`.
- **Memória e Janela de Contexto**: `MemoriaEmMemoria` e `GerenciadorContexto` para preservar instrução de sistema e truncar mensagens antigas de acordo com o limite de tokens.
- **Segurança de Credenciais**: `CofreCredenciais` com mascaramento automático (`CofreCredenciais.mascarar_chave(...)`).

### 2.5 Camada de Interface HTTP (`ai_gateway`)
- **FastAPI**: Serviço assíncrono moderno com documentação OpenAPI/Swagger embutida.
- **Middlewares**: Injeção de `X-Request-ID`, cálculo de latência `X-Process-Time` e tratamento uniforme de exceções no formato RFC 7807.
- **Streaming**: Suporte nativo a Server-Sent Events (SSE) via `StreamingResponse` para respostas fragmentadas em tempo real.
