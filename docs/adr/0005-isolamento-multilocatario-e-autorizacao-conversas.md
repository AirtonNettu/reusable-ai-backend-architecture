# ADR 0005: Isolamento Multilocatário e Autorização de Conversas

## Status
Aprovado e Implementado

## Contexto
Em plataformas de backend para IA que atendem a múltiplos clientes, times ou usuários finais (multilocatário), o armazenamento e a recuperação de históricos conversacionais (`id_conversa`) representam um vetor crítico de segurança de dados.
Sem controle estrito de posse, um usuário mal-intencionado ou com conhecimento de identificadores de conversa (`id_conversa`) poderia consultar ou adulterar o histórico de outros usuários, expondo dados confidenciais ou induzindo alucinações via injeção de contexto.

## Decisão
Implementamos o controle de posse e isolamento de conversas em todas as camadas:
1. **Domínio Puro**:
   - Criação da exceção de domínio `ErroAcessoNaoAutorizadoConversa(ErroDominio)`.
   - Atualização do contrato abstrato `PortaRepositorioMemoria` para receber o identificador de posse opcional `id_usuario: str | None = None` nos métodos `salvar_mensagem`, `recuperar_historico` e `limpar_historico`.
2. **Adaptadores de Memória**:
   - `MemoriaEmMemoria`: Mapeamento thread-safe/async `_proprietarios: dict[str, str]` associando o criador da conversa ao identificador. Tentativas de acesso por outro usuário disparam imediatamente `ErroAcessoNaoAutorizadoConversa`.
   - `MemoriaSQLite`: Criação da tabela `conversas_proprietarios` com chave primária `id_conversa` e coluna `id_usuario`. Transações verificam a titularidade e bloqueiam leituras ou escritas ilegítimas.
3. **Casos de Uso e Roteamento**:
   - `CasoDeUsoGerarResposta` e `CasoDeUsoGerarRespostaFluxo` propagam a identidade do usuário (`id_usuario`) tanto para a recuperação da janela de contexto quanto para a persistência das mensagens resultantes.
4. **Resiliência e Políticas de Retentativa**:
   - Inclusão de `ErroAcessoNaoAutorizadoConversa` e `ErroFerramentaNaoAutorizada` na lista de exceções irrecuperáveis (`excecoes_irrecuperaveis`) da `PoliticaRetentativa`, abortando imediatamente tentativas desnecessárias.
5. **Gateway e Mapeamento HTTP**:
   - Injeção da dependência `ValidadorAutenticacao` suportando o cabeçalho `X-User-ID` e tokens de autenticação.
   - Mapeamento uniforme via middleware de erros para a resposta padrão **HTTP 403 Forbidden** com formato RFC 7807.

## Consequências
- **Positivas**:
  - Impossibilidade de vazamento de contexto ou injeção de mensagens entre usuários distintos.
  - Compatibilidade garantida com ambientes de desenvolvimento anônimos e ambientes corporativos autenticados.
  - Conformidade com os princípios de Menor Privilégio e Segregação de Dados da LGPD/GDPR.
- **Negativas / Desafios**:
  - Requer persistência explícita do proprietário da conversa na inicialização.
