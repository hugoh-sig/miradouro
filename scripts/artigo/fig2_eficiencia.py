"""Fig. 2 do artigo do MIRADOURO: eficiência por sessão na primeira passada do caso Paraopeba.

Dados: relatório de sessão gerado ao fim da primeira passada
(exemplos/paraopeba/respostas/relatorios/relatorio_20260916T003324.md): quatro sessões
produtivas de 13 a 15/09/2026 (uma quinta sessão, aberta às 22:56 de 13/09, não gravou
resposta e não entra). Mediana de segundos por ponto e pontos por hora, por sessão.
Figura para coluna simples (≈ 70 mm), fontes ≥ 7,5 pt no tamanho final, preto e branco.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parents[2] / "docs/artigo/fig2_eficiencia.png"
SESSOES = ["13/09\n17h30", "13/09\n22h57", "14/09\n23h20", "15/09\n23h48"]
RESPOSTAS = [15, 155, 107, 181]
MEDIANA_S = [25.8, 16.0, 11.1, 8.8]
PONTOS_H = [141.6, 158.3, 175.8, 246.8]

LARG_MM = 70.0
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 7.5})
fig, ax = plt.subplots(figsize=(LARG_MM / 25.4, 38 / 25.4), dpi=300)
x = list(range(len(SESSOES)))
ax.bar(x, MEDIANA_S, width=0.62, color="#9a9a9a", edgecolor="#222222", linewidth=0.6, zorder=2)
for xi, m in zip(x, MEDIANA_S, strict=True):
    ax.text(xi, m + 0.6, f"{m:.1f} s".replace(".", ","), ha="center", va="bottom", fontsize=7.5)
rotulos = [f"{s}\nn = {n}\n{p:.0f} pt/h" for s, n, p in zip(SESSOES, RESPOSTAS, PONTOS_H, strict=True)]
ax.set_ylabel("mediana por ponto (s)", fontsize=7.5)
ax.set_xticks(x)
ax.set_xticklabels(rotulos, fontsize=7)
ax.set_ylim(0, 30)
ax.set_yticks([0, 10, 20, 30])
ax.yaxis.grid(True, color="#dddddd", linewidth=0.5, zorder=0)
ax.set_axisbelow(True)
for lado in ("top", "right"):
    ax.spines[lado].set_visible(False)
ax.tick_params(labelsize=7)
fig.subplots_adjust(left=0.16, right=0.98, bottom=0.42, top=0.96)
fig.savefig(OUT, dpi=300)
print("OK →", OUT)
