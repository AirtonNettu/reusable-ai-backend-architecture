# ADR 0003: Políticas de Resiliência: Disjuntor, Retentativa e Fallback Controlado

## Status
Aprovado

## Contexto
APIs de Modelos de Linguagem (LLMs) são serviços remotos de terceiros com latências variáveis, suscetíveis a oscilações de rede, quedas temporárias de servidores e limites estritos de taxa (*rate limits* / HTTP 429). Chamadas ingênuas sem políticas de tolerância a falhas resultam em travamento de requisições, custos inflados por retentativas cegas e degradação em cascata dos serviços consumidores.

## Decisão
Implementamos no módulo `ai_core.resiliencia` um conjunto formal de quatro salvaguardas cooperativas:
1. **Disjuntor (*Circuit Breaker*)**: Monitora taxas de falhas consecutivas. Ao atingir o limite configurado (ex: 5 falhas), o circuito transiciona para o estado `aberto`, rejeitando requisições subsequentes com `ErroDisjuntorAberto` imediatamente, sem realizar chamadas de rede inúteis. Após o intervalo de recuperação, permite requisições teste em estado `meio_aberto` até se restabelecer.
2. **Retentativas Inteligentes com Backoff Exponencial e Jitter**: Retenta falhas transitórias com atrasos crescentes somados a uma variação aleatória (*jitter*) para evitar o problema da manada (*thundering herd*). Erros irrecuperáveis (`ErroAutenticacaoProvedor`, `ErroModeloNaoSuportado`, `ErroValidacao`) abortam imediatamente na primeira tentativa.
3. **Limitador de Taxa e Semáforo**: Implementação do algoritmo *Token Bucket* assíncrono para controle de vazão de requisições por segundo, além de semáforo para limitar concorrência simultânea.
4. **Fallback Controlado**: Permite ao roteador encadear uma lista ordenada de modelos/provedores alternativos (ex: tentar modelo primário; se indisponível, chavear automaticamente para o modelo secundário ou local).

## Consequências
### Positivas
- Alta disponibilidade: indisponibilidade temporária de um fornecedor (ex: OpenAI fora do ar) aciona automaticamente outro provedor configurado (ex: DeepSeek ou Ollama local).
- Proteção da infraestrutura contra colapso sob alta demanda.
- Economia de recursos de computação e cotas de API.

### Negativas
- Maior número de classes e orquestração de dependências na camada de aplicação.
