# ADR 0009: Observabilidade Corporativa com Prometheus, OpenTelemetry e Logs Estruturados Correlacionados

## Status
Aprovado

## Data
2026-10-28

## Contexto
Com a transição para arquitetura conteinerizada em microsserviço (AI Gateway) e o suporte a múltiplos provedores LLM, persistência em PostgreSQL e agentes autônomos ReAct, tornou-se indispensável dispor de telemetria em tempo real para monitorar:
1. Volume, status e latência das requisições HTTP na borda da aplicação.
2. Tempo de resposta de inferências de inteligência artificial e consumo faturado de tokens por modelo.
3. Transições de estado de resiliência (Circuit Breakers e políticas de fallback).
4. Rastreamento fim-a-fim de requisições distribuídas cruzando gateway, casos de uso, agentes e persistência de banco de dados.
5. Logs estruturados padronizados em JSON contendo identificadores de correlação (`trace_id`, `span_id`, `request_id`) sem vazamento de dados sensíveis ou prompts.

## Decisão

1. **Prometheus para Métricas Operacionais**:
   - Implementar o adaptador `MetricasPrometheus` satisfazendo o contrato hexagonal `PortaObservabilidade`.
   - Expor o endpoint nativo `GET /metrics` no formato oficial texto (versão 0.0.4) do Prometheus.
   - Adotar estrita política de **baixa cardinalidade**, normalizando rotas HTTP em templates fixos e vedando identificadores de conversa ou de usuário em labels de métricas. Rotas não mapeadas ou 404 recebem a categoria fixa `/_desconhecida` para neutralizar ataques de negação de serviço por saturação de memória.
   - Fornecer mecanismo de proteção do endpoint `/metrics` mediante Bearer token (`METRICAS_TOKEN`) e flag de desativação (`METRICAS_HABILITADAS`).

2. **OpenTelemetry para Tracing Distribuído**:
   - Implementar o `GerenciadorRastreamento` baseado no OpenTelemetry Python SDK com suporte estrito ao padrão W3C `traceparent` (W3C Trace Context RFC 9151), utilizando injeção e extração oficial e preservando as flags de rastreamento reais.
   - Injetar os cabeçalhos `traceparent`, `X-Request-ID` e `X-Process-Time` nas respostas HTTP.
   - Proteger estritamente a privacidade: filtros automáticos eliminam prompts, respostas, mensagens e credenciais dos atributos de spans. A URL registrada (`http.url`) é sanitizada para excluir parâmetros de consulta (`query parameters`). Exceções capturadas são sanitizadas e truncadas antes de compor o status do span.
   - Resiliência operacional: operar por padrão com `ExportadorSpansMemoria` delimitado (`deque` thread-safe com capacidade de 1.000 spans) sem falhas de rede na ausência de coletores externos, suportando exportação HTTP OTLP quando configurada.

3. **Logs Estruturados JSON com Correlação**:
   - O `FormatadorLogJson` emite registros estruturados em JSON com campos em português brasileiro culto (`timestamp`, `servico`, `nivel`, `logger`, `mensagem`, `arquivo`, `linha`, `trace_id`, `span_id`, `request_id`).
   - Mascaramento por expressão regular de tokens, chaves `sk-...` e credenciais Bearer.

## Consequências

### Positivas
- Visibilidade operacional granular sobre consumo de tokens, latência de inferência e falhas de provedores.
- Facilidade de integração com dashboards Grafana e sistemas de alerta Prometheus (Alertmanager).
- Capacidade de depuração pontual através de correlacionamento direto entre trace distributed e entradas de log.
- Conformidade total com os princípios de segurança, Clean Architecture e nomenclatura em português brasileiro.

### Negativas / Mitigações
- Adição de dependências de telemetria (`prometheus-client`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`): mitigado pela pinagem estrita no `uv.lock`.
- Sobrecarga computacional mínima no caminho de requisição: mitigada pelo uso de contadores thread-safe em memória e exportação assíncrona OTLP em lote.
