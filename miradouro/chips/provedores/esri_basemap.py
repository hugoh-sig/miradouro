"""Basemap Esri World Imagery (tiles XYZ), com atribuição obrigatória no chip.

O serviço não informa a data da imagem por tile; o rodapé do painel avisa
isso e remete o intérprete à série NDVI para confirmar o ano.
"""

from __future__ import annotations

import hashlib
import io
import time
from typing import Any

from miradouro import __version__
from miradouro.chips import painel
from miradouro.chips.base import ErroProvedor, PedidoChip, ProvedorChip, registrar
from miradouro.chips.geo import (
    TAMANHO_TILE,
    de_utm,
    janela_pixels,
    lonlat_para_pixel_global,
    metros_por_pixel,
    pixel_global_para_tile,
)

URL_PADRAO = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
# Endpoint que diz se um tile existe (evita o placeholder "Map data not yet available").
TILEMAP_PADRAO = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tilemap/{z}/{y}/{x}/1/1"
ATRIBUICAO_PADRAO = "Esri, Maxar, Earthstar Geographics, and the GIS User Community"

# O serviço às vezes devolve HTTP 200 com um tile cinza "Map data not yet available"
# em vez de negar. Detectamos pelo hash dos bytes (tile padrão conhecido) ou pela
# uniformidade: ≥ 85 % dos pixels na mesma cor. Água lisa fica bem abaixo disso.
HASHES_PLACEHOLDER = frozenset({"f27d9de7f80c13501f470595e327aa6d"})
FRACAO_DOMINANTE_PLACEHOLDER = 0.85


class TilePlaceholder(RuntimeError):
    """O tile baixado é o placeholder de 'sem cobertura'."""


def tile_e_placeholder(dados: bytes) -> bool:
    if hashlib.md5(dados).hexdigest() in HASHES_PLACEHOLDER:  # noqa: S324 — não é criptografia
        return True
    from PIL import Image

    with Image.open(io.BytesIO(dados)) as im:
        im = im.convert("RGB")
        cores = im.getcolors(maxcolors=im.width * im.height)
    if not cores:
        return False
    dominante = max(cores)[0] / (im.width * im.height)
    return dominante >= FRACAO_DOMINANTE_PLACEHOLDER

PADRAO: dict[str, Any] = {
    "url": URL_PADRAO,
    "tilemap_url": TILEMAP_PADRAO,  # None desliga a verificação
    "zooms": [17, 19],
    "zoom_minimo": 15,  # até onde recuar quando o zoom pedido não tem cobertura
    "tamanho_px": 420,
    "atribuicao": ATRIBUICAO_PADRAO,
    "timeout": 30,
    "tentativas": 3,
}


@registrar
class ProvedorEsriBasemap(ProvedorChip):
    nome = "esri_basemap"
    versao = "1.1"
    descricao = "Esri World Imagery (alta resolução) em um ou mais zooms, com pixel de 10 m e janela 3×3 projetados."

    def validar_config(self) -> None:
        cfg = {**PADRAO, **self.config}
        zooms = cfg["zooms"]
        if not isinstance(zooms, list) or not zooms or not all(isinstance(z, int) and 0 <= z <= 23 for z in zooms):
            raise ErroProvedor("esri_basemap.zooms deve ser lista de inteiros entre 0 e 23")
        if not isinstance(cfg["tamanho_px"], int) or cfg["tamanho_px"] < 64:
            raise ErroProvedor("esri_basemap.tamanho_px deve ser inteiro ≥ 64")
        if not isinstance(cfg["zoom_minimo"], int) or cfg["zoom_minimo"] < 0:
            raise ErroProvedor("esri_basemap.zoom_minimo deve ser inteiro ≥ 0")
        if not str(cfg["atribuicao"]).strip():
            raise ErroProvedor("esri_basemap.atribuicao não pode ser vazia (termos de uso do serviço)")
        self.config = cfg
        self._sessao = None

    def preparar(self) -> None:
        import requests

        self._sessao = requests.Session()
        self._sessao.headers["User-Agent"] = f"miradouro/{__version__} (+https://github.com/hugosalis/miradouro)"

    # ---- ponto de injeção ----------------------------------------------------

    def _baixar_tile(self, z: int, x: int, y: int) -> bytes:
        import requests

        sessao = self._sessao or requests.Session()
        url = self.config["url"].format(z=z, x=x, y=y)
        ultimo: Exception | None = None
        for i in range(int(self.config["tentativas"])):
            try:
                r = sessao.get(url, timeout=self.config["timeout"])
                r.raise_for_status()
                return r.content
            except Exception as e:  # noqa: BLE001
                ultimo = e
                time.sleep(1.0 * (i + 1))
        raise RuntimeError(f"tile {z}/{y}/{x} indisponível: {ultimo}")

    def _tile_existe(self, z: int, x: int, y: int) -> bool:
        """Consulta o tilemap; em caso de erro de rede assume que existe."""
        import requests

        url_modelo = self.config.get("tilemap_url")
        if not url_modelo:
            return True
        sessao = self._sessao or requests.Session()
        try:
            r = sessao.get(url_modelo.format(z=z, x=x, y=y), timeout=self.config["timeout"])
            r.raise_for_status()
            dados = r.json().get("data", [])
            return bool(dados) and all(int(v) == 1 for v in dados)
        except Exception:  # noqa: BLE001 — sem tilemap, tenta baixar mesmo assim
            return True

    def zoom_disponivel(self, lon: float, lat: float, zoom: int) -> int:
        """Maior zoom ≤ ``zoom`` com cobertura no tile central (recua até ``zoom_minimo``)."""
        z = zoom
        while z > self.config["zoom_minimo"]:
            px, py = lonlat_para_pixel_global(lon, lat, z)
            tx, ty = pixel_global_para_tile(px, py)
            if self._tile_existe(z, tx % (2**z), ty):
                return z
            z -= 1
        return z

    # ---- geração -------------------------------------------------------------

    def _mosaico(self, lon: float, lat: float, zoom: int, tamanho: int, aceitar_placeholder: bool = False):
        """Recorte ``tamanho``×``tamanho`` centrado no ponto; devolve (imagem, px0, py0).

        Raises:
            TilePlaceholder: algum tile é o placeholder de "sem cobertura".
        """
        from PIL import Image

        cx, cy = lonlat_para_pixel_global(lon, lat, zoom)
        px0, py0 = cx - tamanho / 2, cy - tamanho / 2
        tx0, ty0 = pixel_global_para_tile(px0, py0)
        tx1, ty1 = pixel_global_para_tile(px0 + tamanho - 1, py0 + tamanho - 1)
        n_tiles = 2**zoom
        mosaico = Image.new("RGB", ((tx1 - tx0 + 1) * TAMANHO_TILE, (ty1 - ty0 + 1) * TAMANHO_TILE), (60, 60, 60))
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                dados = self._baixar_tile(zoom, tx % n_tiles, ty)
                if not aceitar_placeholder and tile_e_placeholder(dados):
                    raise TilePlaceholder(f"zoom {zoom}: tile {tx}/{ty} sem cobertura")
                tile = Image.open(io.BytesIO(dados)).convert("RGB")
                mosaico.paste(tile, ((tx - tx0) * TAMANHO_TILE, (ty - ty0) * TAMANHO_TILE))
        ox, oy = px0 - tx0 * TAMANHO_TILE, py0 - ty0 * TAMANHO_TILE
        recorte = mosaico.crop((int(round(ox)), int(round(oy)), int(round(ox)) + tamanho, int(round(oy)) + tamanho))
        return recorte, px0, py0

    def gerar(self, pedido: PedidoChip) -> bytes:
        cfg = self.config
        tamanho = cfg["tamanho_px"]
        # Footprint real do pixel S2 de 10 m (grade UTM) e da janela 3×3, em lon/lat.
        janela = janela_pixels(pedido.lon, pedido.lat, n=3, tamanho=10.0)
        poligonos = []
        for meia in (1, 0):
            xmin, ymin, xmax, ymax = janela.pixel_alvo_bbox_utm(meia)
            cantos = [de_utm(x, y, janela.epsg) for x, y in ((xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin))]
            poligonos.append((meia, cantos))

        tiles = []
        for zoom_pedido in cfg["zooms"]:
            zoom = self.zoom_disponivel(pedido.lon, pedido.lat, zoom_pedido)
            while True:
                try:
                    im, px0, py0 = self._mosaico(pedido.lon, pedido.lat, zoom, tamanho, aceitar_placeholder=zoom <= cfg["zoom_minimo"])
                    break
                except TilePlaceholder:
                    zoom -= 1  # o tilemap disse que existia, mas veio placeholder: recua
            for meia, cantos in poligonos:
                pts = []
                for lo, la in cantos:
                    gx, gy = lonlat_para_pixel_global(lo, la, zoom)
                    pts.append((gx - px0, gy - py0))
                painel.marcar_poligono(im, pts, cor=painel.COR_JANELA if meia else painel.COR_ALVO, largura=2)
            mpp = metros_por_pixel(pedido.lat, zoom)
            painel.barra_escala(im, mpp)
            aviso = "" if zoom == zoom_pedido else f" (pedido {zoom_pedido}, sem cobertura)"
            tiles.append(
                painel.rotular(
                    im,
                    [f"Esri World Imagery · zoom {zoom}{aviso}", f"~{mpp:.2f} m/px · {tamanho * mpp:.0f} m de lado"],
                )
            )

        grade = painel.compor_grade(
            tiles,
            colunas=len(cfg["zooms"]),
            titulo=f"PLOTID {pedido.plotid} — imagem de alta resolução",
            subtitulo=f"lon {pedido.lon:.5f}, lat {pedido.lat:.5f} · Web Mercator (EPSG:3857)",
            rodape=[
                f"Fonte: Esri World Imagery — {cfg['atribuicao']}.",
                "Data da imagem não informada pelo serviço: confirme o ano de referência com a série NDVI.",
                "Amarelo: pixel Sentinel-2 de 10 m que contém o ponto (grade UTM). Branco: janela 3×3 (30 m).",
            ],
        )
        return painel.para_png(grade)
