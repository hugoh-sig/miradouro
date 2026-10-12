"""Série temporal NDVI multianual do pixel de 10 m (Sentinel-2, GEE + matplotlib).

Útil para separar pasto de lavoura (ciclo abrupto solo nu → verde → colheita),
cultivo de pousio e para confirmar que a cobertura vista numa imagem de outro
ano ainda valia no ano de referência.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timezone
from statistics import median
from typing import Any

from miradouro.chips.base import ErroProvedor, PedidoChip, ProvedorChip, registrar
from miradouro.chips.gee import colecao_s2, inicializar_ee, projeto_gee_de

PADRAO: dict[str, Any] = {
    "colecao": "COPERNICUS/S2_SR_HARMONIZED",
    "ano_inicio": None,  # padrão: ano_referencia - 3
    "ano_fim": None,  # padrão: ano_referencia + 1
    "nuvens_max": 60,
    "janela_mediana": 3,  # observações na mediana móvel
    "largura_px": 1100,
    "altura_px": 360,
}

# Paleta (ver skill dataviz): uma série → um matiz; texto em tinta, nunca na cor da série.
_SUPERFICIE = "#fcfcfb"
_TINTA = "#0b0b0b"
_TINTA_SEC = "#52514e"
_GRADE = "#e4e4e1"
_SERIE = "#2a78d6"

Observacao = tuple[date, float]


def agregar_por_dia(obs: list[Observacao]) -> list[Observacao]:
    """Mediana por dia (tiles S2 sobrepostos produzem 2 cenas na mesma data)."""
    por_dia: dict[date, list[float]] = {}
    for d, v in obs:
        por_dia.setdefault(d, []).append(v)
    return sorted((d, median(vs)) for d, vs in por_dia.items())


def mediana_movel(valores: list[float], janela: int) -> list[float]:
    if janela <= 1 or len(valores) < janela:
        return list(valores)
    meio = janela // 2
    saida = []
    for i in range(len(valores)):
        a, b = max(0, i - meio), min(len(valores), i + meio + 1)
        saida.append(median(valores[a:b]))
    return saida


def desenhar_serie(
    obs: list[Observacao],
    *,
    plotid: str,
    lon: float,
    lat: float,
    ano_referencia: int,
    ano_inicio: int,
    ano_fim: int,
    janela_mediana: int = 3,
    largura_px: int = 1100,
    altura_px: int = 360,
    colecao: str = "Sentinel-2 SR",
) -> bytes:
    """Desenha o gráfico NDVI e devolve PNG. Função pura (sem rede)."""
    import matplotlib

    matplotlib.use("Agg", force=False)
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import FixedLocator

    dpi = 100
    fig = Figure(figsize=(largura_px / dpi, altura_px / dpi), dpi=dpi, facecolor=_SUPERFICIE)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.set_facecolor(_SUPERFICIE)

    x0, x1 = date(ano_inicio, 1, 1), date(ano_fim + 1, 1, 1)
    ax.set_xlim(x0, x1)
    ax.set_ylim(-0.2, 1.0)

    # Ano de referência: lavagem do matiz da série a ~10 %.
    ax.axvspan(date(ano_referencia, 1, 1), date(ano_referencia + 1, 1, 1), color=_SERIE, alpha=0.10, lw=0)
    ax.text(
        date(ano_referencia, 7, 1), 0.96, f"ano de referência {ano_referencia}",
        ha="center", va="top", fontsize=9, color=_TINTA_SEC,
    )

    obs = agregar_por_dia(obs)
    if obs:
        datas = [d for d, _ in obs]
        valores = [v for _, v in obs]
        suave = mediana_movel(valores, janela_mediana)
        ax.plot(datas, suave, color=_SERIE, lw=1.5, solid_joinstyle="round", solid_capstyle="round", zorder=2)
        ax.scatter(
            datas, valores, s=22, color=_SERIE, alpha=0.75,
            edgecolors=_SUPERFICIE, linewidths=0.8, zorder=3,
        )
    else:
        ax.text(0.5, 0.5, "sem observações sem nuvem no período", transform=ax.transAxes,
                ha="center", va="center", fontsize=12, color=_TINTA_SEC)

    # Eixos recessivos: linhas de grade finas e sólidas, só no y.
    anos = list(range(ano_inicio, ano_fim + 2))
    ax.xaxis.set_major_locator(FixedLocator([matplotlib.dates.date2num(date(a, 1, 1)) for a in anos]))
    ax.set_xticklabels([str(a) for a in anos], fontsize=9, color=_TINTA_SEC)
    ax.set_yticks([-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.tick_params(axis="y", labelsize=9, colors=_TINTA_SEC, length=0)
    ax.tick_params(axis="x", colors=_TINTA_SEC, length=3)
    ax.yaxis.grid(True, color=_GRADE, lw=1, ls="-")
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(_GRADE)
    ax.set_ylabel("NDVI", fontsize=9, color=_TINTA_SEC)

    fig.suptitle(f"PLOTID {plotid} — NDVI Sentinel-2 do pixel de 10 m", x=0.01, ha="left",
                 fontsize=12, fontweight="bold", color=_TINTA)
    fig.text(
        0.01, 0.905,
        f"lon {lon:.5f}, lat {lat:.5f} · {len(obs)} observações sem nuvem · "
        f"pontos = cenas individuais, linha = mediana móvel de {janela_mediana} · {colecao}",
        fontsize=8.5, color=_TINTA_SEC,
    )
    fig.subplots_adjust(left=0.05, right=0.99, top=0.84, bottom=0.12)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=_SUPERFICIE)
    return buf.getvalue()


@registrar
class ProvedorNdviSerie(ProvedorChip):
    nome = "ndvi_serie"
    versao = "1.0"
    descricao = "Série temporal NDVI multianual do pixel de 10 m (Sentinel-2 SR via GEE, gráfico matplotlib)."

    def validar_config(self) -> None:
        cfg = {**PADRAO, **self.config}
        for k in ("ano_inicio", "ano_fim"):
            if cfg[k] is not None and not isinstance(cfg[k], int):
                raise ErroProvedor(f"ndvi_serie.{k} deve ser inteiro (ano)")
        if cfg["ano_inicio"] is not None and cfg["ano_fim"] is not None and cfg["ano_inicio"] > cfg["ano_fim"]:
            raise ErroProvedor("ndvi_serie.ano_inicio não pode ser maior que ano_fim")
        if not isinstance(cfg["janela_mediana"], int) or cfg["janela_mediana"] < 1:
            raise ErroProvedor("ndvi_serie.janela_mediana deve ser inteiro ≥ 1")
        self.config = cfg

    def preparar(self) -> None:
        inicializar_ee(projeto_gee_de(self.config))

    def periodo(self, ano_referencia: int) -> tuple[int, int]:
        a0 = self.config["ano_inicio"] if self.config["ano_inicio"] is not None else ano_referencia - 3
        a1 = self.config["ano_fim"] if self.config["ano_fim"] is not None else ano_referencia + 1
        return a0, a1

    # ---- ponto de injeção ----------------------------------------------------

    def _obter_serie(self, pedido: PedidoChip, ano_inicio: int, ano_fim: int) -> list[Observacao]:
        import ee

        ponto = ee.Geometry.Point(pedido.lon, pedido.lat)
        col = colecao_s2(
            self.config["colecao"], ponto, f"{ano_inicio}-01-01", f"{ano_fim + 1}-01-01", self.config["nuvens_max"]
        ).map(lambda i: i.normalizedDifference(["B8", "B4"]).rename("ndvi").copyProperties(i, ["system:time_start"]))
        tabela = col.select("ndvi").getRegion(ponto, 10).getInfo()
        cab = tabela[0]
        i_t, i_v = cab.index("time"), cab.index("ndvi")
        obs: list[Observacao] = []
        for linha in tabela[1:]:
            v = linha[i_v]
            if v is None:
                continue
            d = datetime.fromtimestamp(linha[i_t] / 1000, tz=timezone.utc).date()
            obs.append((d, float(v)))
        return obs

    def gerar(self, pedido: PedidoChip) -> bytes:
        a0, a1 = self.periodo(pedido.ano_referencia)
        obs = self._obter_serie(pedido, a0, a1)
        return desenhar_serie(
            obs,
            plotid=pedido.plotid,
            lon=pedido.lon,
            lat=pedido.lat,
            ano_referencia=pedido.ano_referencia,
            ano_inicio=a0,
            ano_fim=a1,
            janela_mediana=self.config["janela_mediana"],
            largura_px=self.config["largura_px"],
            altura_px=self.config["altura_px"],
            colecao=self.config["colecao"],
        )
