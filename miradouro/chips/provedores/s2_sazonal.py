"""Sentinel-2 sazonal via Google Earth Engine.

Para cada estação configurada, uma composição mediana (sem nuvens) da coleção
S2 SR harmonizada, mostrada em cor verdadeira e em falsa-cor NIR, com o pixel
alvo de 10 m e a janela 3×3 marcados. A janela é alinhada à grade UTM de 10 m
do Sentinel-2, portanto o quadrado amarelo é *o* pixel que contém o ponto.
"""

from __future__ import annotations

import io
import re
from datetime import date, timedelta
from typing import Any

from miradouro.chips import painel
from miradouro.chips.base import ErroProvedor, PedidoChip, ProvedorChip, registrar
from miradouro.chips.gee import baixar_bytes, colecao_s2, inicializar_ee, projeto_gee_de
from miradouro.chips.geo import JanelaPixels, janela_pixels

_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_MES_DIA = re.compile(r"^\d{2}-\d{2}$")


def resolver_data(valor: Any, ano_referencia: int) -> date:
    """``AAAA-MM-DD`` literal, ou ``MM-DD`` relativo ao ano de referência."""
    if isinstance(valor, date):
        return valor
    s = str(valor).strip()
    if _RE_DATA.match(s):
        return date.fromisoformat(s)
    if _RE_MES_DIA.match(s):
        return date.fromisoformat(f"{ano_referencia}-{s}")
    raise ErroProvedor(f"data inválida {valor!r}: use AAAA-MM-DD ou MM-DD")


PADRAO: dict[str, Any] = {
    "colecao": "COPERNICUS/S2_SR_HARMONIZED",
    "janela_pixels": 31,
    "ampliacao": 12,
    "nuvens_max": 60,
    "estacoes": [
        {"nome": "seca", "inicio": "05-01", "fim": "09-30"},
        {"nome": "chuvosa", "inicio": "01-01", "fim": "03-31"},
    ],
    "composicoes": [
        {"nome": "cor verdadeira (B4-B3-B2)", "bandas": ["B4", "B3", "B2"], "min": 0, "max": 3000},
        {"nome": "falsa-cor NIR (B8-B4-B3)", "bandas": ["B8", "B4", "B3"], "min": 0, "max": [5000, 3000, 3000]},
    ],
}


@registrar
class ProvedorS2Sazonal(ProvedorChip):
    nome = "s2_sazonal"
    versao = "1.1"
    descricao = (
        "Sentinel-2 SR (GEE): mediana por estação em cor verdadeira e falsa-cor NIR, "
        "pixel alvo de 10 m e janela 3×3 marcados."
    )

    def validar_config(self) -> None:
        cfg = {**PADRAO, **self.config}
        n = cfg["janela_pixels"]
        if not isinstance(n, int) or n < 3 or n % 2 == 0:
            raise ErroProvedor(f"s2_sazonal.janela_pixels deve ser inteiro ímpar ≥ 3, recebido {n!r}")
        if not isinstance(cfg["ampliacao"], int) or cfg["ampliacao"] < 1:
            raise ErroProvedor("s2_sazonal.ampliacao deve ser inteiro ≥ 1")
        if not isinstance(cfg["estacoes"], list) or not cfg["estacoes"]:
            raise ErroProvedor("s2_sazonal.estacoes deve ser uma lista com ao menos uma estação")
        for e in cfg["estacoes"]:
            if not isinstance(e, dict) or not {"nome", "inicio", "fim"} <= set(e):
                raise ErroProvedor(f"estação inválida {e!r}: precisa de nome, inicio e fim")
            resolver_data(e["inicio"], 2000)
            resolver_data(e["fim"], 2000)
        if not isinstance(cfg["composicoes"], list) or not cfg["composicoes"]:
            raise ErroProvedor("s2_sazonal.composicoes deve ser uma lista com ao menos uma composição")
        for c in cfg["composicoes"]:
            if not isinstance(c, dict) or "bandas" not in c or len(c["bandas"]) != 3:
                raise ErroProvedor(f"composição inválida {c!r}: precisa de nome e 3 bandas")
            c.setdefault("nome", "-".join(c["bandas"]))
            c.setdefault("min", 0)
            c.setdefault("max", 3000)
        self.config = cfg

    def preparar(self) -> None:
        inicializar_ee(projeto_gee_de(self.config))

    # ---- pontos de injeção (substituíveis em testes) -----------------------

    def _composicao_estacao(self, pedido: PedidoChip, inicio: date, fim: date):
        """Devolve ``(imagem_ee_ou_None, n_cenas)`` para a estação."""
        import ee

        ponto = ee.Geometry.Point(pedido.lon, pedido.lat)
        col = colecao_s2(
            self.config["colecao"],
            ponto,
            inicio.isoformat(),
            (fim + timedelta(days=1)).isoformat(),  # filterDate é exclusivo no fim
            self.config["nuvens_max"],
        )
        n = int(col.size().getInfo())
        if n == 0:
            return None, 0
        return col.median(), n

    def _baixar_tile(self, imagem, comp: dict[str, Any], janela: JanelaPixels) -> bytes:
        url = imagem.getThumbURL(
            {
                "bands": list(comp["bandas"]),
                "min": comp["min"],
                "max": comp["max"],
                "crs": janela.crs,
                "crs_transform": janela.crs_transform,
                "dimensions": [janela.n, janela.n],
                "format": "png",
            }
        )
        return baixar_bytes(url)

    # ---- geração -------------------------------------------------------------

    def gerar(self, pedido: PedidoChip) -> bytes:
        from PIL import Image

        cfg = self.config
        n, amp = cfg["janela_pixels"], cfg["ampliacao"]
        janela = janela_pixels(pedido.lon, pedido.lat, n=n, tamanho=10.0)
        lado = n * amp
        composicoes = cfg["composicoes"]
        tiles: list[Image.Image] = []

        for est in cfg["estacoes"]:
            inicio = resolver_data(est["inicio"], pedido.ano_referencia)
            fim = resolver_data(est["fim"], pedido.ano_referencia)
            periodo = f"{inicio.isoformat()} a {fim.isoformat()}"
            imagem, n_cenas = self._composicao_estacao(pedido, inicio, fim)
            for comp in composicoes:
                if imagem is None:
                    rotulo = [f"{est['nome']} · {periodo} · 0 cenas", comp["nome"]]
                    tiles.append(painel.rotular(painel.tile_de_erro(lado, lado, "sem cenas sem nuvem"), rotulo))
                    continue
                png = self._baixar_tile(imagem, comp, janela)
                im = Image.open(io.BytesIO(png)).convert("RGB")
                if im.size != (n, n):
                    raise RuntimeError(f"thumbnail com tamanho inesperado {im.size}, esperado {(n, n)}")
                im = painel.ampliar(im, amp)
                centro = ((janela.centro + 0.5) * amp, (janela.centro + 0.5) * amp)
                painel.marcar_pixel_alvo(im, centro, amp, janela=3)
                painel.barra_escala(im, 10.0 / amp)
                tiles.append(painel.rotular(im, [f"{est['nome']} · {periodo} · {n_cenas} cenas", comp["nome"]]))

        grade = painel.compor_grade(
            tiles,
            colunas=len(composicoes),
            titulo=f"PLOTID {pedido.plotid} — Sentinel-2, ano {pedido.ano_referencia}",
            subtitulo=(
                f"lon {pedido.lon:.5f}, lat {pedido.lat:.5f} · {janela.crs} · "
                f"janela {n}×{n} px de 10 m ({janela.largura_m:.0f} m)"
            ),
            rodape=[
                "Amarelo: pixel de 10 m que contém o ponto (grade UTM do Sentinel-2). Branco: janela 3×3 (30 m).",
                f"Mediana das cenas sem nuvem (SCL) da coleção {cfg['colecao']}, nuvens ≤ {cfg['nuvens_max']}% por cena.",
                "Fonte: Copernicus Sentinel-2 (ESA), processado no Google Earth Engine.",
            ],
        )
        return painel.para_png(grade)
