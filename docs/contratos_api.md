# Contratos de API do AI Gateway

Este documento descreve as especificações técnicas, formatos de mensagens, cabeçalhos e códigos de retorno dos endpoints expostos pelo **AI Gateway**.

---

## 1. Visão Geral

- **Formato Padrão**: `application/json; charset=utf-8`
- **Formato Streaming**: `text/event-stream; charset=utf-8`
- **Cabeçalhos de Resposta Obrigatórios**:
  - `X-Request-ID`: UUID exclusivo da requisição para rastreabilidade de ponta a ponta.
  - `X-Process-Time`: Duração total do processamento no servidor (em segundos decimais).

---

## 2. Autenticação e Identificação de Usuário / Locatário

Quando `GATEWAY_API_KEY` estiver configurada no ambiente:
- **Autenticação**: `X-API-Key: <sua-chave>` ou `Authorization: Bearer <sua-chave>`
- **Resposta de erro se ausente ou inválida**: `401 Unauthorized`
- **Identificação do Usuário Final / Tenant**:
  - Cabeçalho opcional: `X-User-ID: <identificador-do-usuario>`
  - Caso omitido, o identificador de autenticação ou token é assumido como identidade do chamador.
  - O `X-User-ID` é utilizado para segregação de conversas (`id_conversa`) e orçamentação individual de tokens. Tentativas de acesso a conversas de terceiros resultam em `403 Forbidden`.

---

## 3. Endpoints

### 3.1 Verificação de Saúde
- **Rota**: `GET /health`
- **Autenticação**: Pública
- **Resposta 200 OK**:
```json
{
  "status": "ok"
}
```

---

### 3.2 Listagem de Modelos Disponíveis
- **Rota**: `GET /v1/modelos`
- **Autenticação**: Requerida quando chave mestre configurada
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
- **Corpo da Requisição**:
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
        "conteudo": "O padrão Circuit Breaker previne falhas em cascata..."
      },
      "motivo_finalizacao": "sucesso"
    }
  ],
  "uso": {
    "tokens_entrada": 18,
    "tokens_saida": 35,
    "total_tokens": 53
  }
}
```

---

### 3.4 Conclusão de Chat em Fluxo Contínuo (Streaming SSE)
- **Rota**: `POST /v1/chat/conclusoes`
- **Corpo da Requisição**:
```json
{
  "modelo": "modelo-teste",
  "mensagens": [
    {"papel": "usuario", "conteudo": "Conte uma breve história."}
  ],
  "stream": true
}
```

- **Resposta 200 OK (`text/event-stream`)**:
```text
data: {"texto": "Era ", "finalizado": false, "motivo_finalizacao": null}

data: {"texto": "uma ", "finalizado": false, "motivo_finalizacao": null}

data: {"texto": "vez.", "finalizado": true, "motivo_finalizacao": "sucesso"}

data: [DONE]
```

---

### 3.5 Geração de Saída Estruturada (JSON Validado)
- **Rota**: `POST /v1/chat/estruturado`
- **Autenticação**: Requerida
- **Corpo da Requisição**:
```json
{
  "modelo": "modelo-teste",
  "mensagens": [
    {"papel": "usuario", "conteudo": "Extraia o nome e idade: Maria tem 25 anos."}
  ],
  "esquema_json": {
    "type": "object",
    "properties": {
      "nome": {"type": "string"},
      "idade": {"type": "integer"}
    },
    "required": ["nome", "idade"]
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
    "idade": 25
  },
  "tentativas": 1,
  "json_bruto": "{\"nome\": \"Maria\", \"idade\": 25}",
  "erros_validacao": []
}
```

---

### 3.6 Execução de Agente Autônomo
- **Rota**: `POST /v1/agentes/executar`
- **Corpo da Requisição**:
```json
{
  "objetivo": "Calcular a soma dos valores 120 e 340 e reportar.",
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
      "pensamento": "A soma é 460.",
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

## 4. Formato de Erro Padronizado (RFC 7807)

Em situações de erro de domínio ou validação, a resposta utiliza o esquema:

```json
{
  "tipo": "ErroModeloNaoSuportado",
  "mensagem": "Nenhum provedor registrado para o modelo 'modelo-inexistente'.",
  "codigo_status": 404,
  "detalhes": {}
}
```


### Tabela de Mapeamento de Status HTTP

| Exceção de Domínio | Código HTTP | Descrição |
| :--- | :--- | :--- |
| `ErroValidacao` | 400 Bad Request | Payload malformado, campo obrigatório ausente ou schema JSON inválido |
| `ErroAutenticacaoProvedor` | 401 Unauthorized | Falha de credenciais do provedor LLM ou ausência de chave de API mestre |
| `ErroFerramentaNaoAutorizada` | 403 Forbidden | Tentativa de invocar ferramenta restrita sem permissão explícita |
| `ErroAcessoNaoAutorizadoConversa` | 403 Forbidden | Tentativa de consultar, continuar ou limpar conversa pertencente a outro usuário |
| `ErroModeloNaoSuportado` | 404 Not Found | Modelo solicitado não consta no catálogo do roteador |
| `ErroTimeoutProvedor` | 408 Request Timeout | Tempo de resposta do provedor remoto excedeu o limite tolerado |
| `ErroLimitePassosAgente` | 422 Unprocessable Entity | Agente autônomo atingiu o teto máximo de passos sem conclusão |
| `ErroLimiteTaxa` | 429 Too Many Requests | Rate limit atingido com cabeçalho `Retry-After` quando informado |
| `ErroLimiteOrcamentoTokens` | 429 Too Many Requests | Cota ou orçamento de tokens por requisição, sessão ou usuário esgotado |
| `ErroConexaoProvedor` | 502 Bad Gateway | Falha de rede ou queda do provedor externo |
| `ErroDisjuntorAberto` | 503 Service Unavailable | Circuito do provedor está aberto para prevenir sobrecarga |
