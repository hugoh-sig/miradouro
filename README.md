# MIRADOURO

Ferramenta open-source de **fotointerpretação de pontos de validação** para mapeamento
de uso e cobertura da terra. Você traz um `projeto.yaml` (legenda, campos de resposta,
provedores de chips) e um `pontos.csv` (`PLOTID, LON, LAT` + o que quiser); o MIRADOURO
pré-computa os painéis de imagem de cada ponto e guarda as respostas do intérprete com
gravação atômica, backups e metadados de auditoria.

O núcleo é agnóstico: nada de legendas, regiões ou projetos dentro do pacote. O projeto
[Paraopeba](exemplos/paraopeba/projeto.yaml) é apenas o primeiro cliente.

> Sprint 1: contrato de dados, motor de chips e CLI.
> Sprint 2: interface Streamlit de interpretação por teclado.
> Sprint 3: exportador AcATaMa, relatório de sessão, segunda passada cega e consenso.

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

campos:                               # tipos: classe | opcao | multiopcao | texto | numero | booleano
  - {nome: classe_ref, tipo: classe, obrigatorio: true}
  - nome: confianca
    tipo: opcao
    obrigatorio: true
    opcoes: [{valor: alta, tecla: A}, {valor: media, tecla: M}, {valor: baixa, tecla: B}]
  - nome: fonte_principal                # multiopcao: uma ou mais; a tecla liga/desliga
    tipo: multiopcao
    obrigatorio: true
    opcoes: [{valor: hr, tecla: H}, {valor: serie, tecla: N}, {valor: sazonal, tecla: S}]
  - nome: classe_alternativa
    tipo: classe
    obrigatorio_se: {campo: confianca, diferente_de: alta}   # condicional
  - nome: ano_confirmado_ndvi                                 # num multiopcao, igual_a = "contém"
    tipo: opcao
    opcoes: [{valor: sim, tecla: C}, {valor: nao, tecla: X}]
    obrigatorio_se: {campo: fonte_principal, igual_a: hr}
  - {nome: data_imagem_hr, tipo: texto, padrao: "[0-9]{4}-[0-9]{2}"}   # regex opcional
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
| teclas das opções (ex.: `A`/`M`/`B`) | campos de opção (escolha única) |
| teclas de um `multiopcao` (ex.: `H`/`N`/`S`) | ligam/desligam cada valor (fontes da decisão) |
| `Enter` | valida, grava e avança para o próximo ponto |
| `←` `→` | ponto anterior / próximo (dentro do modo atual) |
| `U` | desfaz a última confirmação e volta ao ponto |
| `Backspace` | limpa o rascunho do ponto |
| `T` | foca o campo de texto (observação); `Esc` sai dele; `Enter` grava e confirma |

As teclas vêm do `projeto.yaml`; a barra lateral mostra `[tecla] rótulo` em cada opção e
avisa se alguma tecla conflita com outra ou com as reservadas.

**Campos condicionais** (`obrigatorio_se`) só aparecem, e só são exigidos, quando a
condição vale, e ficam logo abaixo do campo que os dispara: no Paraopeba,
`ano_confirmado_ndvi` surge ao ligar a fonte alta resolução e `classe_alternativa` quando a
confiança não é alta. `Enter` recusa a resposta, lista o que falta e rola até o primeiro
campo faltante. Como o basemap não informa a data da imagem, `data_imagem_hr` é opcional:
o que se audita é se a cobertura foi confirmada para o ano de referência pela série NDVI.

**Modos.** *Pendentes* (padrão) percorre só os pontos sem resposta e abre no primeiro
deles, também ao reabrir a interface. *Todos* permite rever qualquer ponto. *Revisão*
lista os pontos respondidos com confiança baixa (configurável em `interface.revisao` do
yaml) para a segunda passada; a resposta anterior aparece e o rascunho já vem preenchido.

**Ir para o ponto.** O campo *Ir para o ponto* da barra lateral abre o PLOTID digitado
(`Enter`) em qualquer modo. Um ponto que existe mas está fora do filtro atual (ex.: já
respondido, no modo pendentes) abre com aviso; um ponto fora do universo do modo (não
sorteado na segunda passada, fora da lista na revisão dirigida) não abre. Nesse campo,
`Enter` só entrega o valor: não confirma a resposta do ponto atual.

**Autosave e auditoria.** Cada `Enter` grava via o núcleo (arquivo atômico). Além dos
metadados do Sprint 1, a interface registra em `meta`: `duracao_s` (cronômetro por ponto,
somando visitas; pausa quando nenhum ponto está carregado), `modo`, `interface` e, quando
faltou chip, `sem_subsidio` com os provedores ausentes. Um ponto sem chip mostra aviso e
pode ser pulado (`→`) ou respondido mesmo assim. Quando a lista do modo se esvazia (último
pendente ou última revisão gravada), a interface descarrega o ponto e avisa.

**Cegueira.** As `colunas_ocultas` nunca chegam ao navegador: nem na tela, nem em
tooltip, título ou URL. Há teste automatizado disso (`tests/test_app.py`) que varre tudo o
que o front-end receberia, e um teste ponta a ponta opcional em Chrome real
(`MIRADOURO_E2E=1 pytest tests/test_e2e_teclado.py`, requer `pip install playwright`).

## Segunda passada e consenso

O protocolo pede uma segunda interpretação independente dos pontos de confiança baixa e
resolução das divergências por consenso.

```bash
# 1) Sorteio da amostra (opcional, mas recomendado): persiste em respostas/segunda/amostra.json
#    quem entra — confiança baixa + fração aleatória de controle — sem abrir a interface.
python -m miradouro sortear exemplos/paraopeba/projeto.yaml --fracao-controle 0.10 --interprete hugo2p

# 2) Segunda passada CEGA: só os pontos sorteados. Grava em respostas/segunda/.
#    Sem amostra.json, o primeiro início sorteia (com --fracao-controle) e grava o arquivo.
python -m miradouro app exemplos/paraopeba/projeto.yaml --interprete hugo2p --segunda-passada

# 3) Consenso: lista as divergências na classe entre as duas passadas, mostra as duas
#    respostas lado a lado e grava a decisão final no arquivo principal.
python -m miradouro app exemplos/paraopeba/projeto.yaml --interprete hugo --consenso
```

Na segunda passada a interface nunca mostra a resposta da primeira; a amostra de controle é
determinística (semente = hash do yaml) e marcada com `meta.controle`. Sorteie depois de
concluir a primeira passada, pois o conjunto depende das respostas existentes. A amostra
persistida (`amostra.json`: ids, fração, semente, hash do `respostas.json` de origem, data)
é reutilizada tal qual nas sessões seguintes, mesmo que a primeira passada mude depois;
`sortear` recusa refazê-la sem `--forcar` e nunca depois que a segunda passada começou. A
segunda passada serve tanto a um segundo intérprete (inter-observador) quanto ao mesmo
intérprete sob outro id, tempos depois (intra-observador). No consenso, cada decisão guarda
em `meta.consenso` as duas respostas originais com seus intérpretes; o modo *Todos da
segunda passada* permite rever os concordantes também.

## Revisão dirigida por lista externa

Para reler um subconjunto de pontos (releitura de critério, passada de anotação de um campo
novo) sem que a ferramenta saiba *por que* eles foram escolhidos:

```bash
python -m miradouro app exemplos/paraopeba/projeto.yaml --interprete hugo --lista releitura.txt
```

O arquivo é texto com um PLOTID por linha (`#` comenta) ou CSV com coluna `PLOTID`; de um
CSV **só essa coluna é lida** — as demais (o critério) são descartadas na leitura e nunca
chegam à interface, ao `respostas.json` ou ao relatório. A cegueira fica garantida por
construção, não por disciplina. PLOTIDs inexistentes no projeto abortam antes de abrir;
repetidos são ignorados. A navegação segue a ordem do arquivo, nos modos *Da lista, ainda
não revistos* e *Toda a lista*; a resposta anterior aparece e o rascunho vem preenchido.

Rastreabilidade: a sessão é registrada com `modo: dirigida` e `lista: {arquivo, sha256, n}`;
cada confirmação grava no arquivo principal com `meta.modo = dirigida`, `meta.filtro` e
`meta.lista`, e conta como revisão (`revisoes + 1`) mesmo sem mudança de valor — é isso que
torna auditável um "todos mantidos". O relatório de sessão lista as revisões dirigidas por
sessão, com o arquivo, o hash e quantos pontos foram gravados.

## Exportando

```bash
# Tabela plana de referência (uma linha por ponto, com auditoria e colunas ocultas reanexadas)
python -m miradouro exportar csv exemplos/paraopeba/projeto.yaml

# AcATaMa: yml restaurável + camada de pontos + CSV. --filtro seleciona por coluna do CSV.
python -m miradouro exportar acatama exemplos/paraopeba/projeto.yaml --mapa /caminho/mapa_2023.tif \
    --filtro conjunto=classe --nome geral --versao-acatama 26.7
python -m miradouro exportar acatama exemplos/paraopeba/projeto.yaml --mapa /caminho/mapa_2023.tif \
    --filtro "faixa_rio=0-1 km" --nome rio
```

O AcATaMa não importa rótulos de CSV; ele restaura o seu próprio arquivo de configuração.
Por isso a exportação gera, em `respostas/exportacao/<nome>/`:

| arquivo | conteúdo |
|---|---|
| `<nome>.yml` | configuração para *AcATaMa → Restore configuration*: botões = legenda (`thematic_class` = código da classe, comparado ao pixel do raster), `samples` = respostas completas casadas pelo `id` |
| `<nome>_pontos.geojson` | camada de amostras com campo `id` inteiro (PLOTID quando numérico, senão sequencial com `acatama_id` no CSV), em WGS84 ou no `--crs` pedido |
| `<nome>_referencia.csv` | tabela plana completa para versionar |

A classe do mapa o AcATaMa lê do raster no pixel de cada ponto; pontos fora do raster ele
descarta. Se a sua instalação exigir a camada no CRS do raster, reexporte com `--crs`.

**Versão-alvo e origem do formato.** O yml reproduz o formato do **AcATaMa 26.7**, derivado
do código-fonte do plugin (`AcATaMa/core/config.py`, funções `save` e `restore`, release
26.7 em https://github.com/SMByC/AcATaMa): o `save` é a especificação e o `restore` define
o que é obrigatório. O golden file `tests/golden/acatama_26.7.yml` documenta, chave a
chave, a função e a linha do plugin que a grava ou lê, e `tests/test_exportacao.py` valida
a estrutura gerada contra ele. Três pontos aprendidos no smoke test com o 26.7:

* `sampling_layer` e `thematic_map.path` saem como caminhos **absolutos** (o plugin não
  carregou a camada de amostras dada como caminho relativo ao yml);
* `thematic_map.nodata` nunca é nulo (o restore faz `float(nodata)`): o valor vem da tag
  do raster passado em `--mapa` (requer `pip install 'miradouro[acatama]'`, i.e. rasterio);
  sem tag, `--nodata` é obrigatório; `--nodata` explícito prevalece, com aviso se divergir;
* o restore lê `dialog_size`, `fit_to_sample` e `is_completed` sem checar existência; sem
  elas ele aborta depois de carregar raster e pontos e antes dos rótulos ("0 / N samples
  labeled"). O exportador grava todas as chaves obrigatórias na ordem do `save`.

**Risco de quebra.** Versões futuras do plugin podem renomear chaves ou tornar outras
obrigatórias. Ao atualizar o AcATaMa, reconfira `save`/`restore` no fonte da nova versão,
atualize o golden file e passe `--versao-acatama` correspondente. Sintoma típico de formato
desatualizado: raster e pontos carregam, mas o painel mostra "Sampling file not labeled".

## Relatório de sessão

```bash
python -m miradouro relatorio exemplos/paraopeba/projeto.yaml            # Markdown + JSON em respostas/relatorios/
python -m miradouro relatorio exemplos/paraopeba/projeto.yaml --com-mapa # + cruzamento com a classe do mapa
```

Traz progresso, sessões (respostas, tempo interpretando, mediana por ponto, pontos por
hora), distribuições dos campos, sinais para a segunda passada (confiança baixa, sem
subsídio, revisões, desfeitos, incompletos, observações, yaml divergente), as sessões de
revisão dirigida (arquivo da lista, hash, gravadas) e, quando existe
`respostas/segunda/`, a concordância entre passadas e as divergências sem consenso. O
cruzamento com a classe do mapa só entra com `--com-mapa` e é preliminar: a matriz oficial
é a do AcATaMa.

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

**Backups.** São criados **na abertura de cada sessão** (`abrir_sessao()`), não a cada
gravação, e contêm o estado *anterior* à sessão, em `respostas/backups/`. A primeira sessão
de um projeto não gera backup porque ainda não existe arquivo; a rotação mantém os
`saida.backups` mais recentes. Se o arquivo corromper,
`Armazenamento.recuperar_de_backup(pasta)` restaura o backup legível mais recente.

**Compatibilidade de formato.** Os valores são normalizados pelo tipo do campo no yaml em
vigor, tanto ao ler quanto ao gravar. Um campo que virou `multiopcao` lê respostas antigas
com string (`"hr"`) como lista (`["hr"]`) e sempre grava lista; o arquivo não precisa de
migração.

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
  core/        contrato de dados: projeto.yaml, pontos.csv, respostas (atômico + auditoria)
  chips/       motor de lote, cache, geometria, painéis e provedores plugáveis
  interface/   logica.py (puro, testado), app.py (Streamlit), teclado (componente JS)
  exportacao/  tabela de referência, exportador AcATaMa, relatório de sessão
  cli.py       python -m miradouro ...
exemplos/
  demo/      5 pontos públicos em MG para testar os provedores
  paraopeba/ primeiro cliente real (8 classes, 458 pontos)
```

## Licença

MIT — ver [LICENSE](LICENSE). Imagens Sentinel-2 © Copernicus/ESA; basemap © Esri e
parceiros (atribuição impressa em cada chip).
