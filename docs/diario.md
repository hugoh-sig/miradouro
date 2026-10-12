# Diário — MIRADOURO

## 2026-10-12 — Artigo 3 (paper de ferramenta, SBSR, 4 páginas, autor único)

Entregáveis: `docs/artigo/texto.md` (fonte em markdown restrito), `docs/artigo/rascunho.docx`
(modo normal), `docs/artigo/final/artigo3_sbsr.pdf` + `artigo3_sbsr.docx` (diagramação final no
template SBSR). Scripts: `scripts/build_docx_sbsr.py` (cópia adaptada do build do repositório
`paraopeba_r3_quintais`, 12/10/2026; só os caminhos padrão mudaram e entrou a marca
`[quebra de coluna]`), `scripts/artigo/fig1_interprete.py`, `scripts/artigo/fig2_eficiencia.py`.

### Linha e estrutura
Qualidade da referência como elo fraco da validação; salvaguardas colocadas na ferramenta por
construção (cegueira, subsídio pré-computado, validação da resposta, auditoria, segunda passada/
consenso/revisão dirigida); caso de uso = referência de 458 pontos do Paraopeba (artigo 1, citado
como "Submetido ao XXII SBSR, 2027"). Sem menção a dano ou reparação. Corpo: 2.842 palavras;
Resumo 144 e Abstract 132 (limite 150). Título adotado: "MIRADOURO: ferramenta aberta para
interpretação de referência com cegueira por construção e auditoria embutida"; alternativas
registradas no relatório ao autor.

### Números do caso de uso (fontes)
- 458 pontos; 1.374 chips (458 × 3 provedores), `chips/erros.log` vazio.
- Primeira passada: relatório `relatorio_20260916T003324.md` (gerado ao fim da passada): quatro
  sessões produtivas 13–15/09 (15/155/107/181 respostas; medianas 25,8/16,0/11,1/8,8 s; 141,6/
  158,3/175,8/246,8 pontos/h; 8.737,2 s = 2 h 25 min 37 s) e uma sessão aberta sem gravação.
  O relatório de 01/10 reatribui respostas revisadas às sessões de revisão, por isso difere.
- Distribuições (relatório de 01/10): confiança alta 395 / média 63 / baixa 0; três fontes
  combinadas em 419 (91,5 %); alta resolução em 437, confirmada pela série em 435.
- Revisões dirigidas 23/09: lista de 32 (22 corrigidos, 10 mantidos) e lista de 55 (9 "em
  mosaico", sem mudança de classe) — diário do caso, sessões 11.
- Segunda passada cega 30/09: 46 pontos, 10 min 50 s; concordância PRÉ-consenso 38/46 = 82,6 %
  (kappa 0,787); 33/38 = 86,8 % sem os 8 sobrepostos às listas; 8 arbitragens em 2 min 28 s;
  450 registros idênticos ao backup — diário do caso, sessão 12 (`s08b_passada_cega.py`).
  O "45/46 (97,8 %)" do relatório do app é pós-consenso (circular); o artigo o declara como
  limitação e item de roteiro.
- Testes: `pytest tests -q` → 245 coletados (244 passam, 1 pulado), contados nos pontos da saída
  (o `addopts = -q` do pyproject suprime a linha-resumo no terminal não interativo).
- `__version__ = 0.1.0`; licença MIT.

### Figuras
- Fig. 1 (largura dupla, 170 mm): chips reais do ponto de demonstração d3 (Serra do Cipó,
  `exemplos/demo`), sem coordenadas do Paraopeba. (a)(b) recortes das áreas de imagem do chip
  `s2_sazonal` (seca, cor verdadeira e falsa-cor), (c) recorte do `esri_basemap` zoom 18, com
  barras de 100 m redesenhadas; os textos internos dos chips ficariam < 4 pt e foram recortados.
  (d) série NDVI redesenhada no tamanho de impressão a partir das mesmas observações do provedor
  `ndvi_serie` (uma chamada `getRegion`, sem export; dados em `docs/artigo/dados_fig1_ndvi_d3.json`,
  507 observações, 498 datas). Fontes ≥ 7 pt.
- Fig. 2 (coluna, 70 mm × 42 mm): mediana s/ponto por sessão produtiva, com n e pontos/h nos
  rótulos; preto e branco.
- Tab. 1 salvaguardas × mecanismo × registro; Tab. 2 números do caso.

### Referências (verificadas no Crossref, 12/10/2026)
Olofsson 2014 (10.1016/j.rse.2014.02.015); Stehman & Foody 2019, RSE 231, 111199; Foody 2010,
RSE 114(10) 2271–2285; Pengra et al. 2020, RSE 238, 111261; Saah et al. 2019, Env. Modelling &
Software 118, 166–171; Bey et al. 2016, Remote Sensing 8(10) 807; Llano et al. 2026, Applied
Computing and Geosciences 31, 100389 (citação indicada no README do AcATaMa). Software: URL do
README (`github.com/hugosalis/miradouro`) respondeu **404** em 12/10 — repositório privado ou não
publicado; conferir antes da submissão.

### Diagramação (modo `--final`, LibreOffice → PDF)
1º build: 5 páginas (17 linhas a mais) e dois vales por cabeçalho de seção que não cabia no fim da
coluna. Resolvido com aparas de fraseado (sem números), Tabela 2 movida para antes do §3.4,
Fig. 2 reduzida de 46 para 42 mm de altura e uma linha a menos no Resumo e no Abstract (o cabeçalho
"1. INTRODUÇÃO" precisava de 3 mm). Última página: o LibreOffice não equilibra as colunas da seção
final (a seção contínua extra gerou página vazia); solução adotada: marca `[quebra de coluna]` no
`texto.md`, antes da penúltima frase das conclusões → colunas a 232 e 215 mm (4 linhas de
diferença, o melhor na granularidade de frase). Conferido página a página (100 dpi; figuras e
tabelas a 200 dpi): 4 páginas Letter, colunas a 19,1–104,9 e 111,0–196,8 mm, título a 34,8 mm,
Times New Roman embutida, sem numeração, sem sobreposição. O `.venv` deste repositório não tem
python-docx; o build rodou com o `.venv` do `paraopeba_r3_quintais`.

## 2026-10-12 — Publicação do repositório (pré-requisito da ref. [8] do artigo 3)

### Auditoria pré-publicação
- Histórico completo (`git log -p --all`, 12 commits) varrido por chave/token/credencial/conta de
  serviço/e-mail/caminho pessoal: **nenhum segredo**. Acertos de "secret" são sentinelas de teste
  (`MOTIVO_SECRETO`, `coluna_secreta`); `ee-hugohcsalis2` é o id do projeto Earth Engine nos YAMLs
  (não é credencial). E-mails: autor dos commits e afiliação do artigo. Nenhum `/Users/...`.
- Caso real fora do git: `exemplos/*/respostas/`, `exemplos/*/chips/`, `exemplos/*/listas/` e
  `refs_paraopeba/` ignorados e nunca commitados; sob `exemplos/` só os dois `projeto.yaml` e o
  `pontos.csv` da demo.
- LICENSE MIT, "Copyright (c) 2026 Hugo Salis". README ganhou a seção **Citação** (artigo
  "Submetido ao XXII SBSR, 2027" e software).

### Publicação
- O repositório não tinha remote, e o owner `hugosalis` (README, pyproject, ref. [8]) não existe
  no GitHub. Decisão do autor: publicar sob a conta pessoal **hugoh-sig**.
- `gh auth switch --user hugoh-sig`; `gh repo create hugoh-sig/miradouro --public --source . --push`
  (commit e2e09ba). URL atualizada em README, pyproject e ref. [8] do artigo; docx/PDF do artigo
  reconstruídos (4 páginas, última página 232/219 mm).
- Verificação: `gh repo view` → PUBLIC, branch main; `curl https://github.com/hugoh-sig/miradouro`
  → HTTP 200. Ref. [8] confere com a URL.

## 2026-10-12 — Artigo 3: título final, escopo ampliado e revisão de espaçamentos

- **Título**: "MIRADOURO: rotulagem auditável de pontos para dados de referência em validação de mapas
  de uso e cobertura da terra". Coerência com o termo "rotulagem": Resumo passou a "ferramenta aberta
  (Python, MIT) de rotulagem de pontos de referência"; Abstract, "for labelling reference points".
  Resumo 146 / Abstract 132 palavras.
- **Conclusões**: frase final estendida a outras tarefas de rotulagem de pontos (amostras de treinamento
  para classificadores; subsídio uniforme e trilha de auditoria mitigando o ruído de rótulo). Nada
  mais mudou na discussão.
- **Espaçamentos no build (`--final`)**, contra o template medido (passo de linha do corpo 10 pt =
  4,1 mm ≈ 11,6 pt; uma linha em branco entre afiliações e Resumo e em volta de cada cabeçalho):
  linha em branco dos cabeçalhos 11 → 11,5 pt; respiro uniforme de 6 pt (`RESPIRO`) antes da figura e
  depois da legenda, antes da legenda da tabela e depois da tabela (parágrafo de 1 pt + 6 pt no lugar
  do parágrafo vazio de ~13 pt, que dava respiro desigual entre figuras e tabelas); bloco do título com
  10 pt título → autores e 6 pt autores → afiliações (≈ 5 mm no template). Espaçamento simples e
  recuo de 0,63 cm conferidos (já estavam corretos).
- **Marca `[quebra de coluna]`**: agora inserida no início do parágrafo seguinte (antes era anexada ao
  anterior e deixava uma linha vazia no topo da coluna). Posicionada antes de "Numa referência real de
  458 pontos…": última página com colunas a 236,6 e 227,2 mm.
- **Reflow**: os espaçamentos maiores custaram ~8 linhas; 1º build com 5 páginas e o cabeçalho
  "1. INTRODUÇÃO" fora do pé da página 1. Resolvido com uma linha a menos no Abstract ("median time
  per point" → "median per point"; "an intra-interpreter" → "intra-interpreter"), uma linha a menos no
  §3.4 ("A acurácia do mapa estimada sobre essa referência" → "A acurácia do mapa sobre essa
  referência") e Fig. 2 de 42 para 38 mm de altura (legibilidade conferida a 200 dpi).
- **Verificação página a página** (100 dpi): 4 páginas; p. 1 cabeçalho da introdução no pé da coluna
  esquerda com 2 linhas; p. 2 Fig. 1 com respiro de 6 pt; p. 3 cheia, Tabela 1, Fig. 2, Tabela 2 e o
  cabeçalho da discussão no pé; p. 4 discussão, conclusões, referências; nenhum marcador visível,
  nenhuma sobreposição. `rascunho.docx` reconstruído.
