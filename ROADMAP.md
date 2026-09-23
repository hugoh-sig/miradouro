# ROADMAP — MIRADOURO

Pendências registradas, sem implementação. Cada item nasce de uma necessidade sentida
em uso real; a origem fica anotada para que a prioridade seja discutível depois.
Regra: nada aqui altera o desenho de resposta (`campos` do `projeto.yaml`) — ver
`CLAUDE.md`. Itens que tocarem em `campos` passam pela aprovação prévia de lá.

## Fase 2 (não iniciada)

Origem dos três itens: necessidades sentidas no uso real do caso Paraopeba
(validação do mapa 2023, piloto 3), 16/09/2026. Registrados em 23/09/2026.

### 2.1 Salto direto por PLOTID
Campo "ir para o ponto N" na interface, disponível em qualquer modo (pendentes, todos,
revisão, segunda passada). Hoje a navegação é só sequencial (`←` `→`, `Enter`), o que
torna custoso localizar um ponto específico quando se tem o PLOTID em mãos (ex.: ponto
citado em relatório, em diário ou em lista de discrepâncias do s08).

### 2.2 Modo de revisão dirigida (lista externa de PLOTIDs)
O app aceita uma lista externa de PLOTIDs (arquivo texto, um por linha, ou CSV com
coluna `PLOTID`) e navega **somente** por ela. A interface **não exibe nem conhece o
critério** que gerou a lista: recebe apenas os identificadores. A cegueira do
intérprete fica preservada por construção, e não por disciplina.

Casos de uso reais:
- **releitura de critério**: reler um subconjunto de pontos para confirmar se o rótulo
  atribuído seguiu o critério da legenda (ex.: Paraopeba, 23/09/2026 — 32 pontos com
  `classe_ref = 8` nos estratos pastagem e urbano; todos mantidos);
- **passadas de anotação pós-interpretação**: percorrer uma lista para preencher um
  campo adicional sem reabrir a interpretação inteira.

Requisitos mínimos a decidir na implementação: o modo grava com `modo` próprio no
`meta` da resposta (rastreabilidade no `respostas.json`); a lista de entrada e seu
hash entram no relatório de sessão; edições nesse modo contam como `revisoes`, nunca
sobrescrevem silenciosamente. A lista não é interpretada nem filtrada pelo app.

### 2.3 Comando de backup embutido
`miradouro backup <projeto.yaml> --destino <pasta>`: cópia íntegra e datada de
`respostas.json` (e, opcionalmente, da pasta `respostas/`) para um destino escolhido
pelo usuário, independente da rotação automática de `respostas/backups/` que ocorre
na abertura de sessão. Motivo: a rotação automática vive ao lado do arquivo original e
guarda o estado *anterior* à sessão; um backup manual para fora do projeto (disco
externo, pasta sincronizada) antes de operações sensíveis não existe hoje.

Nota (23/09/2026): este item era tido como "já registrado", mas não constava em nenhum
arquivo nem no histórico do repositório. Registrado aqui pela primeira vez.
