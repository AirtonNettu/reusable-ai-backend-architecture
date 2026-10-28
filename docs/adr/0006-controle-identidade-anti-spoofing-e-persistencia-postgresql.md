# ADR 0006: Controle de Identidade Anti-Spoofing e Persistência PostgreSQL Assíncrona

## Status
Aprovado e Implementado

## Contexto
1. **Vulnerabilidade de Header Spoofing (IDOR)**:
   Em arquiteturas HTTP multilocatárias, permitir que clientes forneçam arbitrariamente cabeçalhos como `X-User-ID` sem vinculação criptográfica ou autorização de delegação permite que um usuário autenticado se passe por outro (User Impersonation / IDOR).
2. **Escalabilidade Horizontal de Persistência**:
   Enquanto o SQLite atende perfeitamente a execuções locais, edge computing e ambientes monolíticos isolados, cenários corporativos distribuídos exigem um banco relacional escalável horizontalmente como o PostgreSQL, com pool de conexões gerenciado e migrações de esquema versionadas.

## Decisão
1. **Identidade Criptograficamente Derivada e Prevenção de Spoofing**:
   - Criação da classe `IdentidadeAutenticada(str)`, que preserva retrocompatibilidade com assinaturas baseadas em string enquanto transporta atributos de segurança (`id_usuario`, `id_locatario`, `e_servico_confiavel`).
   - Apenas credenciais classificadas expressamente como **Serviços Confiáveis (M2M)** têm autorização para repassar `X-User-ID` em nome de terceiros.
   - Chaves de clientes regulares vinculadas a um usuário específico que tentarem injetar um `X-User-ID` divergente são bloqueadas imediatamente na borda com **HTTP 403 Forbidden**.
2. **Adaptador PostgreSQL Assíncrono (`MemoriaPostgresql`)**:
   - Implementa `PortaRepositorioMemoria`.
   - Gerencia pool assíncrono de conexões (`min_conexoes`, `max_conexoes`, `timeout_segundos`).
   - Implementa migrações de esquema versionadas (`schema_migracoes`) com idempotência para criação das tabelas `conversas_proprietarios` e `mensagens_conversa`.
   - Executa todas as inserções e deleções em transações seguras (`transaction()`).
   - Verifica titularidade de conversas prevenindo que qualquer usuário leia ou modifique conversas alheias.

## Consequências
- **Positivas**:
  - Eliminação de vulnerabilidades de falsificação de identidade na borda do Gateway.
  - Habilitação de persistência corporativa em PostgreSQL com alta vazão e transações ACID.
  - Zero dependência forçada em tempo de desenvolvimento: o SQLite continua disponível como opção padrão local.
- **Negativas / Desafios**:
  - Em produção com PostgreSQL, o pool de conexões requer dimensionamento adequado conforme a concorrência esperada.
