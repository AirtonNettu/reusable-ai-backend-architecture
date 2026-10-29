# Contratos de API do AI Gateway

Este documento descreve as especificações técnicas, formatos de mensagens, cabeçalhos, códigos de retorno e exemplos reais de consumo dos endpoints expostos pelo **AI Gateway**.

---

## 1. Visão Geral dos Protocolos e Cabeçalhos

- **Formato REST Padrão**: `application/json; charset=utf-8`
- **Formato Streaming**: `text/event-stream; charset=utf-8` (Server-Sent Events)
- **Cabeçalhos de Resposta Obrigatórios**:
  - `X-Request-ID`: Identificador UUID exclusivo da requisição para rastreabilidade de ponta a ponta.
  - `X-Process-Time`: Duração total do processamento no servidor (em segundos decimais).
  - `traceparent`: Cabeçalho padrão W3C para rastreamento distribuído (OpenTelemetry).
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Strict-Transport-Security`: Injetado quando a requisição for HTTPS.

---

## 2. Autenticação e Identificação de Usuário / Locatário

Quando `GATEWAY_API_KEY` estiver configurada no ambiente:
- **Autenticação**: Cabeçalho `X-API-Key: <sua-chave>` ou `Authorization: Bearer <sua-chave>`.
- **Resposta se ausente ou inválida**: `401 Unauthorized` (RFC 7807).
- **Identificação do Usuário Final / Tenant (`X-User-ID`)**:
  - Cabeçalho opcional: `X-User-ID: <identificador-do-usuario>`.
  - **Proteção Anti-Spoofing**: Clientes comuns autenticados com API key têm seu identificador vinculado deterministicamente à sua credencial. Tentativas de falsificar o `X-User-ID` resultam em **`403 Forbidden`**. Apenas chaves de serviço configuradas em `GATEWAY_CHAVES_CONFIAVEIS` podem representar terceiros via delegação M2M.

---

## 3. Catálogo Completo de Endpoints

### 3.1 Verificação de Saúde
- **Rota**: `GET /health`
- **Autenticação**: Pública
- **Descrição**: Sonda de vivacidade e prontidão operacional do serviço.
- **Exemplo com `curl`**:
  ```bash
  curl -i http://localhost:8000/health
  ```
- **Resposta 200 OK**:
  ```json
  {
    "status": "ok"
  }
  ```

---

### 3.2 Listagem de Modelos Disponíveis
- **Rota**: `GET /v1/modelos`
- **Autenticação**: Requerida quando `GATEWAY_API_KEY` estiver configurada.
- **Descrição**: Retorna o catálogo de modelos registrados no roteador e suas capacidades.
- **Exemplo com `curl`**:
  ```bash
  curl -i -H "X-API-Key: dev-local-master-key-12345678" http://localhost:8000/v1/modelos
  ```
- **Resposta 200 OK**:
  ```json
  {
    "dados": [
      {
        "identificador": "modelo-teste",
        "nome_exibicao": "Modelo de Teste Simulado",
        "provedor": "simulado",
        "capacidades": ["texto", "chat", "streaming", "ferramentas"],
        "limite_contexto": 8192
      }
    ]
  }
  ```

---

### 3.3 Conclusão de Chat (Síncrona)
- **Rota**: `POST /v1/chat/conclusoes`
- **Autenticação**: Requerida
- **Descrição**: Gera resposta síncrona consolidada para diálogo conversacional.
- **Exemplo de Payload**:
  ```json
  {
    "modelo": "modelo-teste",
    "mensagens": [
      {"papel": "sistema", "conteudo": "Você é um assistente técnico."},
      {"papel": "usuario", "conteudo": "Explique o padrão Circuit Breaker."}
    ],
    "temperatura": 0.7,
    "max_tokens": 1024,
    "stream": false,
    "id_conversa": "sessao-usr-123"
  }
  ```
- **Exemplo com `curl`**:
  ```bash
  curl -X POST http://localhost:8000/v1/chat/conclusoes \
    -H "Content-Type: application/json" \
    -H "X-API-Key: dev-local-master-key-12345678" \
    -d '{
      "modelo": "modelo-teste",
      "mensagens": [{"papel": "usuario", "conteudo": "Olá!"}],
      "id_conversa": "sessao-usr-123"
    }'
  ```
- **Resposta 200 OK**:
  ```json
  {
    "identificador": "chatcmpl-a1b2c3d4",
    "modelo": "modelo-teste",
    "escolhas": [
      {
        "indice": 0,
        "mensagem": {
          "papel": "assistente",
          "conteudo": "Resposta simulada de teste."
        },
        "motivo_finalizacao": "sucesso"
      }
    ],
    "uso": {
      "tokens_entrada": 1,
      "tokens_saida": 4,
      "total_tokens": 5
    }
  }
  ```

---

### 3.4 Conclusão de Chat em Fluxo Contínuo (Streaming SSE)
- **Rota**: `POST /v1/chat/conclusoes` (com `"stream": true`)
- **Autenticação**: Requerida
- **Formato**: `text/event-stream`
- **Descrição**: Transmite fragmentos de resposta incrementalmente via Server-Sent Events, com protocolo de reserva atômica de tokens em duas fases e cancelamento seguro.
- **Exemplo com `curl`**:
  ```bash
  curl -N -X POST http://localhost:8000/v1/chat/conclusoes \
    -H "Content-Type: application/json" \
    -H "X-API-Key: dev-local-master-key-12345678" \
    -d '{
      "modelo": "modelo-teste",
      "mensagens": [{"papel": "usuario", "conteudo": "Conte uma breve história."}],
      "stream": true
    }'
  ```
- **Resposta 200 OK (`text/event-stream`)**:
  ```text
  data: {"texto": "Resposta ", "finalizado": false, "motivo_finalizacao": null}

  data: {"texto": "simulada ", "finalizado": false, "motivo_finalizacao": null}

  data: {"texto": "de teste.", "finalizado": true, "motivo_finalizacao": "sucesso"}

  data: [DONE]
  ```

---

### 3.5 Geração de Saída Estruturada (JSON Schema com Auto-Reparo)
- **Rota**: `POST /v1/chat/estruturado`
- **Autenticação**: Requerida
- **Descrição**: Valida e garante que a saída gerada pelo modelo esteja em estrita conformidade com o esquema JSON fornecido, aplicando autorreparo sintático e revalidação determinística.
- **Exemplo de Payload**:
  ```json
  {
    "modelo": "modelo-teste",
    "mensagens": [
      {"papel": "usuario", "conteudo": "Extraia os dados: Maria tem 28 anos e reside em Curitiba."}
    ],
    "esquema_json": {
      "type": "object",
      "properties": {
        "nome": {"type": "string"},
        "idade": {"type": "integer", "minimum": 0},
        "cidade": {"type": "string"}
      },
      "required": ["nome", "idade", "cidade"]
    },
    "max_tentativas": 2
  }
  ```
- **Resposta 200 OK**:
  ```json
  {
    "sucesso": true,
    "dados": {
      "nome": "Maria",
      "idade": 28,
      "cidade": "Curitiba"
    },
    "tentativas": 1,
    "json_bruto": "{\"nome\": \"Maria\", \"idade\": 28, \"cidade\": \"Curitiba\"}",
    "erros_validacao": []
  }
  ```

---

### 3.6 Execução de Agentes Autônomos (Loop ReAct)
- **Rota**: `POST /v1/agentes/executar`
- **Autenticação**: Requerida
- **Descrição**: Executa o runtime ReAct, permitindo ao agente raciocinar, planejar e invocar ferramentas autorizadas com salvaguardas orçamentárias e de timeout.
- **Exemplo de Payload**:
  ```json
  {
    "objetivo": "Calcular a soma dos valores 120 e 340 e reportar o resultado.",
    "nome_agente": "agente-calculador",
    "instrucao_sistema": "Você é um agente matemático que utiliza ferramentas.",
    "limite_passos": 5,
    "ferramentas_permitidas": ["somar_valores"]
  }
  ```
- **Resposta 200 OK**:
  ```json
  {
    "resposta_final": "O resultado da soma de 120 e 340 é 460.",
    "passos": [
      {
        "numero_passo": 1,
        "pensamento": "Vou invocar a ferramenta somar_valores com os argumentos 120 e 340.",
        "resposta_parcial": ""
      },
      {
        "numero_passo": 2,
        "pensamento": "A soma calculada foi 460.",
        "resposta_parcial": "O resultado da soma de 120 e 340 é 460."
      }
    ],
    "sucesso": true,
    "total_tokens": {
      "tokens_entrada": 45,
      "tokens_saida": 28,
      "total_tokens": 73
    },
    "tempo_total_segundos": 0.0824,
    "erro": null
  }
  ```

---

### 3.7 Consulta e Gestão Canônica de Conversas (Anti-IDOR)

#### Obter Histórico da Conversa
- **Rota**: `GET /v1/conversas/{id_conversa}`
- **Parâmetros**: `limite` (query opcional, de 1 a 500).
- **Autenticação**: Requerida. O usuário autenticado deve ser o legítimo proprietário da conversa. Caso contrário, retorna `403 Forbidden`.
- **Resposta 200 OK**:
  ```json
  {
    "id_conversa": "conv-piloto-01",
    "id_usuario": "usuario_alfa",
    "mensagens": [
      {"papel": "usuario", "conteudo": "Olá!", "nome": null},
      {"papel": "assistente", "conteudo": "Resposta simulada de teste.", "nome": null}
    ],
    "total_mensagens": 2
  }
  ```

#### Limpar Histórico da Conversa
- **Rota**: `DELETE /v1/conversas/{id_conversa}`
- **Autenticação**: Requerida. Apenas o proprietário da conversa pode excluí-la.
- **Resposta 200 OK**:
  ```json
  {
    "id_conversa": "conv-piloto-01",
    "id_usuario": "usuario_alfa",
    "mensagens_removidas": 2,
    "sucesso": true
  }
  ```

---

### 3.8 Métricas Prometheus
- **Rota**: `GET /metrics`
- **Autenticação**:
  - Em desenvolvimento: pública caso nenhum token seja configurado.
  - Em produção (SEC-008): **obrigatória**. Requer cabeçalho `Authorization: Bearer <GATEWAY_METRICAS_TOKEN>`. Se nenhum token ou chave mestra estiver configurada, responde **`403 Forbidden`** (*fail-closed*).
- **Resposta 200 OK (`text/plain; version=0.0.4; charset=utf-8`)**:
  ```text
  # HELP http_requisicoes_total Volume total de requisições HTTP recebidas
  # TYPE http_requisicoes_total counter
  http_requisicoes_total{metodo="GET",rota="/health",status_codigo="200"} 12
  # HELP llm_tokens_total Volume faturado de tokens consumidos por modelo
  # TYPE llm_tokens_total counter
  llm_tokens_total{modelo="modelo-teste",tipo="total"} 48
  ```

---

### 3.9 Endpoints da Aplicação Piloto e Camada Intermediária BFF (`/piloto`)

| Método | Rota | Autenticação / Segurança | Descrição |
|---|---|---|---|
| `GET` | `/piloto` | Sessão inicializada via Cookie HMAC | Entrega a página HTML5 da Single Page Application (SPA). |
| `GET` | `/piloto/app.js` | Pública / Cache-Control | Entrega o script client-side da SPA externalizado para conformidade com CSP (SEC-009). |
| `GET` | `/piloto/api/status` | Sessão Piloto | Retorna o status operacional do backend e configurações ativas. |
| `GET` | `/piloto/api/sessao` | Sessão Piloto | Retorna o identificador do usuário ativo e o token anti-CSRF. |
| `POST` | `/piloto/api/sessao` | Cookie HMAC + Header `X-CSRF-Token` | Alterna o perfil demonstrativo (`usuario_alfa` ou `usuario_beta`). Bloqueado com 403 em produção. |
| `POST` | `/piloto/api/chat` | Cookie HMAC + Header `X-CSRF-Token` | Envia mensagem pelo BFF, executa a inferência e retorna resposta com telemetria visual. |
| `GET` | `/piloto/api/conversas/{id_conversa}` | Cookie HMAC | Recupera mensagens persistidas do PostgreSQL garantindo isolamento por usuário. |

---

## 4. Formato de Erro Padronizado (RFC 7807)

Erros de domínio, validação e segurança utilizam a estrutura RFC 7807:

```json
{
  "tipo": "ErroAcessoNaoAutorizadoConversa",
  "mensagem": "Acesso não autorizado: a conversa 'conv-123' pertence a outro usuário.",
  "codigo_status": 403,
  "detalhes": {}
}
```

### Mapeamento de Exceções de Domínio para Códigos HTTP

| Exceção de Domínio | Código HTTP | Causa Raiz |
| :--- | :--- | :--- |
| `ErroValidacao` | **400 Bad Request** | Payload malformado, campo obrigatório ausente ou JSON Schema inválido. |
| `ErroAutenticacaoProvedor` | **401 Unauthorized** | Falha de autenticação do chamador ou credenciais do provedor LLM inválidas. |
| `ErroFerramentaNaoAutorizada` | **403 Forbidden** | Invocação de ferramenta restrita sem aprovação prévia ou presente em lista negra. |
| `ErroAcessoNaoAutorizadoConversa` | **403 Forbidden** | Tentativa de consultar, continuar ou excluir conversa pertencente a outro usuário (IDOR). |
| `ErroModeloNaoSuportado` | **404 Not Found** | Modelo solicitado não existe no catálogo de provedores registrados. |
| `ErroTimeoutProvedor` | **408 Request Timeout** | Provedor de inferência não respondeu dentro do limite configurado. |
| `ErroLimitePassosAgente` | **422 Unprocessable Entity** | O agente cognitivo atingiu o limite de iterações sem produzir resposta final. |
| `ErroLimiteTaxa` | **429 Too Many Requests** | Limitador de taxa (Token Bucket) atingido. Retorna cabeçalho `Retry-After`. |
| `ErroLimiteOrcamentoTokens` | **429 Too Many Requests** | Cota orçamentária por requisição, sessão ou usuário excedida na `PoliticaOrcamentoTokens`. |
| `ErroConexaoProvedor` | **502 Bad Gateway** | Falha física de rede ou indisponibilidade no endpoint remoto do provedor. |
| `ErroDisjuntorAberto` | **503 Service Unavailable** | O circuito do provedor está aberto para prevenir sobrecarga em cascata. |

---

## 5. Exemplo Completo de Consumo em Python (`httpx`)

```python
import httpx

GATEWAY_URL = "http://localhost:8000"
API_KEY = "dev-local-master-key-12345678"

headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}

# 1. Enviar mensagem síncrona
payload = {
    "modelo": "modelo-teste",
    "mensagens": [{"papel": "usuario", "conteudo": "Olá, assistente!"}],
    "id_conversa": "sessao-python-01",
}

with httpx.Client(base_url=GATEWAY_URL, headers=headers) as client:
    resposta = client.post("/v1/chat/conclusoes", json=payload)
    dados = resposta.json()
    print("Resposta:", dados["escolhas"][0]["mensagem"]["conteudo"])
    print("Tokens totais:", dados["uso"]["total_tokens"])

# 2. Consumir streaming SSE
with httpx.Client(base_url=GATEWAY_URL, headers=headers) as client:
    with client.stream(
        "POST",
        "/v1/chat/conclusoes",
        json={**payload, "stream": True},
    ) as response:
        for linha in response.iter_lines():
            if linha.startswith("data: ") and linha != "data: [DONE]":
                print(linha[6:], end="", flush=True)
```
