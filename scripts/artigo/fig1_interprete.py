"""Fig. 1 do artigo do MIRADOURO: o que o intérprete vê, com os chips reais do ponto de
demonstração d3 (exemplos/demo; Serra do Cipó, MG, coordenada pública aproximada).

(a) e (b): recortes das áreas de imagem do chip `s2_sazonal` (estação seca, cor verdadeira e
falsa-cor NIR), sem as faixas de texto do chip, que ficariam ilegíveis na largura da página.
(c): recorte da área de imagem do chip `esri_basemap` (zoom 18).
(d): série NDVI do mesmo pixel, redesenhada no tamanho de impressão a partir das mesmas
observações que o provedor `ndvi_serie` usa (docs/artigo/dados_fig1_ndvi_d3.json, obtidas pelo
próprio provedor), com a mesma mediana móvel de 3 observações e o ano de referência marcado.
Desenhada a 178 mm de largura, fontes ≥ 7,5 pt no tamanho final, preto e branco nos rótulos.
"""
import json
from datetime import date
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
CHIPS = REPO / "exemplos/demo/chips"
OUT = REPO / "docs/artigo/fig1_interprete_dupla.png"
DADOS = REPO / "docs/artigo/dados_fig1_ndvi_d3.json"

# recortes (px) das áreas de imagem, quadrados centrados no pixel alvo
s2 = Image.open(CHIPS / "s2_sazonal/d3.png")
a = s2.crop((50, 100, 345, 395))      # seca, cor verdadeira (painel superior esquerdo)
b = s2.crop((430, 100, 725, 395))     # seca, falsa-cor NIR (painel superior direito)
hr = Image.open(CHIPS / "esri_basemap/d3.png")
c = hr.crop((481, 100, 821, 440))     # zoom 18

LARG_MM, ALT_MM = 178.0, 96.0
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5})
fig = plt.figure(figsize=(LARG_MM / 25.4, ALT_MM / 25.4), dpi=300)
# linha de cima: três painéis quadrados
lado = 0.285
y0 = 0.41
gap = (1 - 3 * lado) / 4
for i, (im, rot) in enumerate([(a, "(a) Sentinel-2, estação seca, cor verdadeira"),
                               (b, "(b) Sentinel-2, estação seca, falsa-cor NIR"),
                               (c, "(c) Alta resolução, zoom 18 (~0,56 m/px)")]):
    ax = fig.add_axes([gap + i * (lado + gap), y0, lado, lado * (LARG_MM / ALT_MM)])
    ax.imshow(im)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_linewidth(0.6)
        s.set_color("#444444")
    ax.set_title(rot, fontsize=7.5, pad=3)
# escala: 295 px do chip S2 = 295/371 × 310 m ≈ 246 m; 340 px do HR a 0,56 m/px ≈ 190 m
def barra(ax, px, texto):
    ax.plot([0.06 * px, 0.06 * px + px * 100 / escala[texto]], [0.93 * px] * 2, color="#000000", lw=1.6)
    ax.text(0.06 * px, 0.90 * px, "100 m", fontsize=7, color="#000000", va="bottom")
escala = {"a": 295 / (295 / 371 * 310), "c": 340 / 190.4}   # px por metro
for ax, k, px in zip(fig.axes[:3], ("a", "a", "c"), (295, 295, 340), strict=True):
    ppm = escala[k]
    ax.plot([0.06 * px, 0.06 * px + 100 * ppm], [0.94 * px] * 2, color="#ffffff", lw=4.0, solid_capstyle="butt", zorder=4)
    ax.plot([0.06 * px, 0.06 * px + 100 * ppm], [0.94 * px] * 2, color="#000000", lw=2.0, solid_capstyle="butt", zorder=5)
    ax.text(0.06 * px, 0.90 * px, "100 m", fontsize=7, color="#ffffff", va="bottom",
            bbox=dict(facecolor="#000000", edgecolor="none", pad=1.2, alpha=0.75))

# linha de baixo: série NDVI
d = json.load(open(DADOS))
obs = sorted((date.fromisoformat(t), v) for t, v in d["obs"])
por_dia = {}
for t, v in obs:
    por_dia.setdefault(t, []).append(v)
obs = sorted((t, median(vs)) for t, vs in por_dia.items())
datas = [t for t, _ in obs]
vals = [v for _, v in obs]
j = d["janela_mediana"]
meio = j // 2
suave = [median(vals[max(0, i - meio):min(len(vals), i + meio + 1)]) for i in range(len(vals))]
ax = fig.add_axes([0.06, 0.085, 0.925, 0.25])
ax.axvspan(date(d["ano_referencia"], 1, 1), date(d["ano_referencia"] + 1, 1, 1), color="#bbbbbb", alpha=0.35, lw=0)
ax.scatter(datas, vals, s=5, color="#555555", alpha=0.7, linewidths=0, zorder=3)
ax.plot(datas, suave, color="#000000", lw=0.9, zorder=2)
ax.set_xlim(date(d["ano_inicio"], 1, 1), date(d["ano_fim"] + 1, 1, 1))
ax.set_ylim(-0.2, 1.0)
ax.set_yticks([0, 0.5, 1.0])
ax.set_ylabel("NDVI", fontsize=7.5, labelpad=2)
ax.text(date(d["ano_referencia"], 7, 1), -0.17, f"ano de referência {d['ano_referencia']}", ha="center", va="bottom", fontsize=7)
ax.set_title(f"(d) Série NDVI do pixel de 10 m, {len(obs)} datas sem nuvem; pontos = cenas, linha = mediana móvel de {j}",
             fontsize=7.5, pad=3, loc="left")
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.tick_params(labelsize=7)
ax.yaxis.grid(True, color="#dddddd", lw=0.5)
ax.set_axisbelow(True)
fig.savefig(OUT, dpi=300)
print("OK →", OUT, Image.open(OUT).size)
