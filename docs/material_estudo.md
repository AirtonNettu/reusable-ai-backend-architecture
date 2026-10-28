# Material de Estudo da Arquitetura

Este documento foi elaborado para desenvolvedores, arquitetos e engenheiros de IA que desejam compreender a fundo cada classe, função, parâmetro e fluxo da **Reusable AI Backend Architecture**.

---

## 1. Módulo de Domínio (`ai_core.dominio`)

### 1.1 `Mensagem` (`ai_core.dominio.modelos.mensagem`)
- **Responsabilidade**: Representa a unidade básica de comunicação textual e contextual em um diálogo com modelos de inteligência artificial.
- **Assinatura**:
  ```python
  @dataclass(frozen=True, slots=True)
  class Mensagem:
      papel: PapelMensagem  # 'sistema' | 'usuario' | 'assistente' | 'ferramenta'
      conteudo: str
      nome: str | None = None
      metadados: dict[str, Any] = field(default_factory=dict)
      chamadas_ferramentas: tuple[ChamadaFerramenta, ...] = ()
      identificador_chamada_ferramenta: str | None = None
```
- **Por que `frozen=True` e `slots=True`?**
  Garante imutabilidade de dados (evita efeitos colaterais em concorrência assíncrona) e reduz o consumo de memória alocando slots fixos no interpretador Python em vez de um dicionário dinâmico `__dict__`.

### 1.2 `RequisicaoGeracao` e `RespostaGeracao` (`ai_core.dominio.modelos.geracao`)
- **Responsabilidade**: Contratos agnósticos de entrada e saída para qualquer modelo ou provedor.
- **Campos Principais**:
  - `modelo`: Identificador textual do modelo solicitado.
  - `mensagens`: Tupla contendo o histórico a ser enviado.
  - `configuracao`: `ConfiguracaoGeracao` (temperatura, max_tokens, formato_json).
  - `ferramentas`: Tupla de `DefinicaoFerramenta` disponíveis para o modelo.
  - `motivo_finalizacao`: `TipoFinalizacao` ('sucesso', 'limite_tokens', 'chamada_ferramenta', 'filtro_conteudo', 'erro').
  - `uso`: `UsoTokens` com contagem de tokens de entrada, saída e total.

### 1.3 `PortaProvedorLLM` (`ai_core.dominio.portas.porta_provedor`)
- **Responsabilidade**: Interface abstrata (porta na Arquitetura Hexagonal) que desacopla o restante do sistema da forma como cada fornecedor de IA atende às requisições.
- **Métodos Exigidos**:
  - `gerar(requisicao: RequisicaoGeracao) -> RespostaGeracao` (síncrono/consolidado).
  - `gerar_fluxo(requisicao: RequisicaoGeracao) -> AsyncIterator[PedacoResposta]` (streaming).
  - `validar_disponibilidade() -> bool`.

---

## 2. Módulo de Resiliência (`ai_core.resiliencia`)

### 2.1 `Disjuntor` (`ai_core.resiliencia.disjuntor`)
- **Conceito**: Inspirado no livro *Release It!* de Michael Nygard. Evita que o sistema continue enviando requisições a um serviço externo que está comprovadamente fora do ar.
- **Estados**:
  - `fechado`: Operação normal. Se atingir `limite_falhas` (ex: 5 falhas), vai para `aberto`.
  - `aberto`: Rejeita chamadas imediatamente com `ErroDisjuntorAberto` sem tocar na rede.
  - `meio_aberto`: Após `tempo_recuperacao_segundos`, permite um número limitado de testes. Se bem-sucedidos, volta a `fechado`; se falharem, retorna a `aberto`.

### 2.2 `PoliticaRetentativa` (`ai_core.resiliencia.retentativa`)
- **Conceito**: Retenta operações que falham devido a erros transitórios (perda momentânea de pacote de rede ou rate limit temporário).
- **Cálculo de Atraso**:
  $$\text{atraso} = \min(\text{atraso\_maximo}, \text{atraso\_inicial} \times \text{fator}^{(\text{tentativa} - 1)}) \times \text{jitter}$$
- **Salvaguarda**: Exceções presentes em `excecoes_irrecuperaveis` (como `ErroAutenticacaoProvedor` ou `ErroModeloNaoSuportado`) nunca são retentadas, pois não teriam sucesso em tentativas subsequentes.

### 2.3 `LimitadorTaxa` (`ai_core.resiliencia.limitador`)
- **Conceito**: Algoritmo *Token Bucket* assíncrono. Permite rajadas controladas até a capacidade máxima e recarrega tokens de forma contínua a uma taxa por segundo predefinida.

---

## 3. Módulo de Agentes Autônomos (`ai_core.aplicacao.agentes`)

### 3.1 `OrquestradorAgente` (Loop ReAct)
O padrão ReAct (*Reasoning + Acting*) permite ao modelo intercalar raciocínio verbal com a invocação de ferramentas. O fluxo executa os seguintes passos:

1. Monta a lista inicial de mensagens com a instrução do sistema (`configuracao.instrucao_sistema`) e o objetivo do usuário.
2. Filtra do catálogo as ferramentas que o agente tem permissão de usar (`configuracao.ferramentas_permitidas`).
3. Dispara a chamada para o modelo.
4. Se o modelo responder diretamente sem invocar ferramentas, o ciclo termina e a resposta final é entregue.
5. Se o modelo emitir chamadas de ferramenta:
   - Para cada chamada, o orquestrador aciona a `PortaExecutorFerramentas`.
   - A resposta da ferramenta é anexada ao histórico com papel `'ferramenta'`.
   - O orquestrador incrementa o contador de passos e repete o loop a partir do passo 3.
6. Se o número de iterações atingir `configuracao.limite_passos` sem que o modelo conclua, o ciclo é interrompido com `sucesso=False` e erro descritivo.

---

## 4. AI Gateway (`services/ai-gateway`)

### 4.1 Injeção de Dependências com `Annotated` e `Depends`
O FastAPI utiliza a árvore de dependências para resolver instâncias em tempo de execução:
```python
@roteador_conclusoes.post("/conclusoes")
async def criar_conclusao_chat(
    requisicao: EsquemaRequisicaoChat,
    caso_resposta: Annotated[
        CasoDeUsoGerarResposta, Depends(obter_caso_gerar_resposta)
    ],
    caso_fluxo: Annotated[CasoDeUsoGerarRespostaFluxo, Depends(obter_caso_gerar_fluxo)],
    _autenticado: Annotated[str | None, Depends(obter_validador_autenticacao())] = None,
) -> EsquemaRespostaChat | StreamingResponse: ...
```
Essa abordagem permite que testes sobrescrevam provedores ou configurações via `app.state.configuracoes` ou `dependency_overrides` sem alterar a assinatura das rotas.

### 4.2 Streaming com Server-Sent Events (SSE)
O streaming SSE utiliza o protocolo HTTP/1.1 persistente (`Transfer-Encoding: chunked` e `Content-Type: text/event-stream`), enviando eventos no formato:
```text
data: {"texto": "palavra", "finalizado": false}

data: [DONE]
```
Esse formato é universalmente compatível com frontends modernos, web browsers (`EventSource` ou `fetch` com leitor de stream) e bibliotecas de SDK.

---

## 5. Saídas Estruturadas com Autorreparo (`CasoDeUsoGerarSaidaEstruturada`)

Modelos de linguagem generativos podem ocasionalmente produzir saídas com pequenas quebras sintáticas (ex: esquecer uma vírgula no JSON ou violar restrições numéricas do schema). A arquitetura resolve isso com um ciclo iterativo de autorreparo:
1. O modelo recebe a requisição juntamente com a instrução estrita contendo o JSON Schema gerado pela classe Pydantic via `model_json_schema()`.
2. O sistema realiza limpeza de delimitadores de código markdown (` ```json ... ``` `).
3. Ao tentar `json.loads` ou `classe_modelo.model_validate(...)`, se ocorrer erro:
   - O erro detalhado é capturado.
   - O orquestrador reinjeta no diálogo a resposta imperfeita do modelo e adiciona uma mensagem de usuário explicando exatamente onde a validação falhou e solicitando a versão corrigida.
   - O modelo reprocessa com o feedback da validação e entrega o JSON corrigido sem que o chamador final precise lidar com a falha.

---

## 6. Persistência Conversacional em SQLite (`MemoriaSQLite`)

Para permitir retenção de histórico além da memória volátil da máquina sem depender de infraestruturas pesadas em desenvolvimento ou borda, implementou-se o `MemoriaSQLite`:
- Utiliza a biblioteca nativa `sqlite3` do Python com índices otimizados por `(id_conversa, id)`.
- É thread-safe através de `threading.Lock()`.
- Delega operações de I/O em disco para threads secundárias via `asyncio.to_thread(...)`, evitando qualquer bloqueio do loop de eventos assíncrono do FastAPI.

