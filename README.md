# MIRADOURO

Ferramenta open-source de **fotointerpretação de pontos de validação** para mapeamento
de uso e cobertura da terra. Você traz um `projeto.yaml` (legenda, campos de resposta,
provedores de chips) e um `pontos.csv` (`PLOTID, LON, LAT` + o que quiser); o MIRADOURO
pré-computa os painéis de imagem de cada ponto e guarda as respostas do intérprete com
gravação atômica, backups e metadados de auditoria.

O núcleo é agnóstico: nada de legendas, regiões ou projetos dentro do pacote. O projeto
[Paraopeba](exemplos/paraopeba/projeto.yaml) é apenas o primeiro cliente.

> Sprint 1: contrato de dados, motor de chips e CLI.
> Sprint 2 (este): interface Streamlit de interpretação por teclado.
> Sprint 3: exportador AcATaMa, relatório de sessão, modo revisão completo.

## Quickstart

```bash
git clone https://github.com/hugosalis/miradouro && cd miradouro
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[chips,app,dev]"

# Earth Engine (uma vez por máquina):
earthengine authenticate
export EARTHENGINE_PROJECT=seu-projeto-gee   # ou `projeto_gee:` no yaml

# Valida yaml + csv e resume o projeto
python -m miradouro projeto validar exemplos/demo/projeto.yaml

# Pré-computa os chips (5 pontos × 3 provedores ≈ 2–3 min)
python -m miradouro chips gerar exemplos/demo/projeto.yaml

# Quantos chips já existem por provedor
python -m miradouro chips status exemplos/demo/projeto.yaml
```

Os painéis ficam em `exemplos/demo/chips/<provedor>/<PLOTID>.png`. Rodar `chips gerar`
de novo não baixa nada que já exista (`--forcar` regera). Cada chip guarda a versão do
provedor que o gerou (chunk de texto do PNG); quando o layout de um provedor muda e sua
`versao` sobe, os chips antigos são regerados automaticamente. Um ponto que falhar é
registrado em `chips/erros.log` e pulado; o lote nunca cai por causa de um ponto.

Opções úteis de `chips gerar`: `--paralelo 4`, `--limite 20`, `--plotid 12 37`,
`--provedor s2_sazonal`, `--sem-barra` (CI/logs). Código de saída `3` sinaliza falhas parciais.

## O `projeto.yaml`

Versão comentada campo a campo em [exemplos/paraopeba/projeto.yaml](exemplos/paraopeba/projeto.yaml).
Resumo:

```yaml
nome: Meu projeto
ano_referencia: 2023

pontos:
  arquivo: pontos.csv                 # relativo à pasta do yaml
  colunas_ocultas: [estrato_classe]   # o intérprete NUNCA vê (rotulagem cega)

legenda:                              # codigo, nome, rotulo, descricao, tecla, cor
  - {codigo: 1, nome: veg_nativa, rotulo: Vegetação nativa, tecla: "1", cor: "#1a9850",
     descricao: "Dossel irregular, textura couve-flor..."}
  - {codigo: 2, nome: pastagem, tecla: "2", cor: "#fee08b"}

campos:                               # tipos: classe | opcao | texto | numero | booleano
  - {nome: classe_ref, tipo: classe, obrigatorio: true}
  - nome: confianca
    tipo: opcao
    obrigatorio: true
    opcoes: [{valor: alta, tecla: A}, {valor: media, tecla: M}, {valor: baixa, tecla: B}]
  - {nome: fonte_principal, tipo: opcao, obrigatorio: true, opcoes: [hr, serie, s2]}
  - nome: classe_alternativa
    tipo: classe
    obrigatorio_se: {campo: confianca, diferente_de: alta}   # condicional
  - {nome: data_imagem_hr, tipo: texto, padrao: "[0-9]{4}-[0-9]{2}",
     obrigatorio_se: {campo: fonte_principal, igual_a: hr}}  # regex opcional
  - {nome: observacao, tipo: texto}

chips:
  pasta: chips
  provedores:
    s2_sazonal:   {projeto_gee: meu-projeto, estacoes: [{nome: seca, inicio: "05-01", fim: "09-30"}]}
    ndvi_serie:   {projeto_gee: meu-projeto, ano_inicio: 2019, ano_fim: 2025}
    esri_basemap: {zooms: [17, 19]}

saida:
  pasta: respostas
  backups: 10
```

O CSV precisa de `PLOTID`, `LON`, `LAT` (qualquer caixa; `,` ou `;`). Colunas extras
são preservadas e mostradas ao intérprete, exceto as `colunas_ocultas`.

## Provedores de chips

| nome | o que gera |
|---|---|
| `s2_sazonal` | Sentinel-2 SR (GEE): mediana sem nuvens por estação, cor verdadeira + falsa-cor NIR, janela alinhada à grade UTM de 10 m com o **pixel alvo** e a **janela 3×3** contornados |
| `ndvi_serie` | Série NDVI multianual do pixel de 10 m (gráfico), ano de referência destacado |
| `esri_basemap` | Esri World Imagery em um ou mais zooms, com o footprint real do pixel de 10 m projetado, barra de escala e atribuição. Recua o zoom automaticamente onde não há cobertura (consulta o `tilemap` e ainda detecta o tile cinza "Map data not yet available" servido com HTTP 200) |

Interface comum (`miradouro/chips/base.py`): um provedor recebe `PedidoChip(plotid, lon,
lat, ano_referencia, config)` e devolve os bytes de um PNG. Para adicionar um provedor:

```python
from miradouro.chips import ProvedorChip, registrar

@registrar
class MeuProvedor(ProvedorChip):
    nome = "meu_provedor"
    versao = "1"          # suba ao mudar o painel: invalida o cache
    def gerar(self, pedido):
        ...
        return png_bytes
```

e habilite `meu_provedor:` em `chips.provedores` do yaml.

## Interpretando

```bash
python -m miradouro app exemplos/demo/projeto.yaml --interprete hugo
```

Abre a interface no navegador (porta 8501; `--porta N` muda, `--sem-navegador` não
abre a janela). Sem `--interprete`, a interface pede o id na entrada. Os chips do ponto
atual ocupam a tela; o formulário fica na barra lateral.

**Teclado primeiro.** O mouse funciona, mas nunca é necessário:

| tecla | ação |
|---|---|
| teclas da legenda (ex.: `1`–`8`) | classe de referência |
| `⇧` + tecla da legenda | classe alternativa (segundo campo do tipo `classe`) |
| teclas das opções (ex.: `A`/`M`/`B`, `H`/`N`/`S`) | campos de opção (confiança, fonte...) |
| `Enter` | valida, grava e avança para o próximo ponto |
| `←` `→` | ponto anterior / próximo (dentro do modo atual) |
| `U` | desfaz a última confirmação e volta ao ponto |
| `Backspace` | limpa o rascunho do ponto |
| `T` | foca o campo de texto (observação); `Esc` sai dele; `Enter` grava e confirma |

As teclas vêm do `projeto.yaml`; a barra lateral mostra `[tecla] rótulo` em cada opção e
avisa se alguma tecla conflita com outra ou com as reservadas.

**Campos condicionais** (`obrigatorio_se`) só aparecem, e só são exigidos, quando a
condição vale: no Paraopeba, `data_imagem_hr` surge ao escolher fonte = alta resolução e
`classe_alternativa` quando a confiança não é alta. `Enter` recusa a resposta e lista o que
falta.

**Modos.** *Pendentes* (padrão) percorre só os pontos sem resposta e abre no primeiro
deles, também ao reabrir a interface. *Todos* permite rever qualquer ponto. *Revisão*
lista os pontos respondidos com confiança baixa (configurável em `interface.revisao` do
yaml) para a segunda passada; a resposta anterior aparece e o rascunho já vem preenchido.

**Autosave e auditoria.** Cada `Enter` grava via o núcleo (arquivo atômico + backup por
sessão). Além dos metadados do Sprint 1, a interface registra em `meta`: `duracao_s`
(cronômetro por ponto, somando visitas), `modo`, `interface` e, quando faltou chip,
`sem_subsidio` com os provedores ausentes. Um ponto sem chip mostra aviso e pode ser
pulado (`→`) ou respondido mesmo assim.

**Cegueira.** As `colunas_ocultas` nunca chegam ao navegador: nem na tela, nem em
tooltip, título ou URL. Há teste automatizado disso (`tests/test_app.py`) que varre tudo o
que o front-end receberia, e um teste ponta a ponta opcional em Chrome real
(`MIRADOURO_E2E=1 pytest tests/test_e2e_teclado.py`, requer `pip install playwright`).

## Respostas (núcleo)

```python
from miradouro.core import carregar_projeto, carregar_pontos, Armazenamento

projeto = carregar_projeto("exemplos/demo/projeto.yaml")
pontos = carregar_pontos(projeto.caminho_pontos)

arm = Armazenamento(projeto, interprete="hugo")
arm.abrir_sessao()                       # backup rotativo do arquivo atual
arm.gravar("d1", {"classe_ref": "7", "confianca": "alta"})
arm.pendentes(pontos.ids)                # o que falta
```

`respostas/respostas.json` é reescrito inteiro a cada gravação via temporário + `rename`
(nunca fica meio escrito). Cada resposta guarda intérprete, sessão, timestamps de
criação/atualização, número de revisões, versão do MIRADOURO e o SHA-256 do yaml em vigor.
Se o arquivo corromper, `Armazenamento.recuperar_de_backup(pasta)` restaura o backup
legível mais recente.

## Desenvolvimento

```bash
pytest --cov=miradouro       # núcleo, motor e interface (AppTest) 100 % offline
ruff check .
MIRADOURO_E2E=1 pytest tests/test_e2e_teclado.py   # opcional: teclado num Chrome real
```

O CI (GitHub Actions) roda lint, testes e um smoke da CLI em Python 3.11 e 3.12.

Estrutura:

```
miradouro/
  core/       contrato de dados: projeto.yaml, pontos.csv, respostas (atômico + auditoria)
  chips/      motor de lote, cache, geometria, painéis e provedores plugáveis
  interface/  logica.py (puro, testado), app.py (Streamlit), teclado (componente JS)
  cli.py      python -m miradouro ...
exemplos/
  demo/      5 pontos públicos em MG para testar os provedores
  paraopeba/ primeiro cliente real (8 classes, 458 pontos)
```

## Licença

MIT — ver [LICENSE](LICENSE). Imagens Sentinel-2 © Copernicus/ESA; basemap © Esri e
parceiros (atribuição impressa em cada chip).
