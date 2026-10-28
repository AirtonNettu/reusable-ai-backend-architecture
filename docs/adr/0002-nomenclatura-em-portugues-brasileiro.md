# ADR 0002: Padronização de Nomenclatura em Português Brasileiro

## Status
Aprovado

## Contexto
Em projetos corporativos multinacionais ou regionais, a mistura indiscriminada de idiomas (Spanglish/Portinglês) resulta em ambiguidade conceitual, nomes inconsistentes (`UserMessage`, `MensagemUsuario`, `ChatRequest`, `RequisicaoConversa`) e perda de clareza semântica. O projeto estabeleceu como diretriz explícita a utilização uniforme de português brasileiro para identificadores próprios.

## Decisão
Estabelecemos como padrão obrigatório:
- Todo identificador próprio criado no projeto (módulos, diretórios, arquivos, classes, funções, variáveis, parâmetros e métodos próprios) deve ser escrito em **português brasileiro culto e idiomático**.
- Palavras-chave originais da sintaxe do Python (`async`, `await`, `def`, `class`, `yield`, `import`, etc.) e contratos técnicos externos exigidos por bibliotecas e protocolos (`status_code`, `json`, `stream`, `headers`, `role`, `content`) são preservados onde estritamente exigido pelo compilador ou especificação externa.
- A documentação de referência é mantida bilíngue (Português e Inglês) para garantir alcance e governança global.

## Consequências
### Positivas
- Uniformidade e consistência semântica absoluta no codebase.
- Redução de erros de digitação e duplicidade conceitual.
- Domínio expressivo (*Ubiquitous Language*) em português alinhado com os requisitos funcionais.

### Negativas
- Exige atenção redobrada de engenheiros acostumados a escrever nomes comuns em inglês em projetos Python.
