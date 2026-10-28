# ADR 0007: Reserva Atômica de Tokens em Duas Fases (Two-Phase Token Reservation)

## Status
Aprovado e Implementado

## Contexto
Em cenários de alto volume de requisições concorrentes disparadas pelo mesmo usuário ou sessão, checagens orçamentárias prévias simples sofrem de condições de corrida (Time-of-Check to Time-of-Use - TOCTOU).
Múltiplas chamadas simultâneas verificam saldo suficiente no mesmo instante e disparam chamadas caras a modelos LLM, resultando em estouro severo da cota permitida quando todas concluem.
Além disso, se uma requisição falhar (timeout, erro 502 do provedor ou cancelamento do cliente HTTP), os tokens não devem ser cobrados do usuário.

## Decisão
Implementamos o padrão de **Reserva em Duas Fases (Two-Phase Reservation)** na `PoliticaOrcamentoTokens`:
1. **Fase 1: Reserva Atômica Pré-Execução (`reservar_tokens`)**:
   - Executada sob trava atômica assíncrona (`async with self._bloqueio:`).
   - O comprometimento projetado é calculado como `tokens_consumidos + tokens_reservados + estimativa`.
   - Se o total exceder o limite individual por requisição, o teto da sessão ou a cota do usuário, a requisição é bloqueada imediatamente com `ErroLimiteOrcamentoTokens` (HTTP 429) **antes** de qualquer requisição ser enviada ao provedor LLM.
   - Sendo aprovada, gera uma `ReservaTokens` rastreada por `id_reserva` e aloca a estimativa em `tokens_reservados`.
2. **Fase 2: Confirmação ou Cancelamento**:
   - **Sucesso (`confirmar_reserva`)**: Deduz a estimativa dos tokens reservados e computa os tokens reais consumidos na cota acumulada do usuário.
   - **Falha / Cancelamento (`cancelar_reserva`)**: Caso o provedor remoto falhe, sofra timeout ou o cliente encerre a conexão, o caso de uso captura a exceção e libera instantaneamente os tokens reservados, devolvendo a cota integralmente ao usuário.

## Consequências
- **Positivas**:
  - Impossibilidade matemática de estouro de orçamento por requisições concorrentes.
  - Justiça na cobrança: requisições com falha técnica não penalizam a cota do cliente.
  - Visibilidade de telemetria em tempo real entre tokens reservados vs consumidos.
- **Negativas / Desafios**:
  - Requer gerenciamento explícito do ciclo de vida da reserva nos casos de uso via blocos estruturados `try ... except`.
