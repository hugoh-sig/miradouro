# MIRADOURO — regras para o agente

## Desenho de resposta: a ferramenta propõe, o dono do protocolo decide

Mudanças no **desenho de resposta** de um projeto (o bloco `campos` do `projeto.yaml`:
acrescentar ou remover campos, mudar o tipo, a obrigatoriedade, o `obrigatorio_se`, os
valores das opções ou as teclas) exigem **aprovação explícita do usuário ANTES de
implementar**. Vale para qualquer projeto em `exemplos/` e para os projetos reais que o
usuário aponte.

Por quê: o desenho de resposta é a parte humana do protocolo de validação (Olofsson et
al. 2014; ver `refs_paraopeba/protocolo_validacao.md` §2 e o guia de interpretação). Uma
mudança altera o que fica registrado por ponto e pode invalidar respostas já gravadas,
que passam a ser "incompletas" e saem da exportação para o AcATaMa e do relatório.

Como agir:
1. Descrever a mudança proposta, o motivo e o efeito sobre as respostas já gravadas
   (quantas deixariam de validar, o que seria perdido).
2. Esperar a decisão do usuário. Sem aprovação explícita, não editar `campos`.
3. Só então implementar, junto com a atualização do README e dos testes.

Mudanças no motor (novos tipos de campo no núcleo, validação, interface) não precisam
de aprovação prévia, desde que não alterem o `campos` de nenhum projeto.

Decisões já tomadas (2026-09-14): `fonte_principal` como `multiopcao` {hr, serie,
sazonal} e o campo `ano_confirmado_ndvi` no Paraopeba estão **aceitos**; não reverter.
