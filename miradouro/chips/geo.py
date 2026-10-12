"""Geometria pura (sem rede): UTM, grade de pixel Sentinel-2 e Web Mercator."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

TAMANHO_TILE = 256
RAIO_TERRA = 6378137.0


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG da zona UTM (WGS84) que contém o ponto."""
    zona = int((lon + 180.0) // 6) + 1
    zona = max(1, min(60, zona))
    return (32600 if lat >= 0 else 32700) + zona


@lru_cache(maxsize=64)
def _transformadores(epsg: int):
    from pyproj import Transformer

    ida = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    volta = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    return ida, volta


def para_utm(lon: float, lat: float, epsg: int | None = None) -> tuple[float, float, int]:
    epsg = epsg or utm_epsg(lon, lat)
    ida, _ = _transformadores(epsg)
    x, y = ida.transform(lon, lat)
    return x, y, epsg


def de_utm(x: float, y: float, epsg: int) -> tuple[float, float]:
    _, volta = _transformadores(epsg)
    lon, lat = volta.transform(x, y)
    return lon, lat


@dataclass(frozen=True)
class JanelaPixels:
    """Janela quadrada de ``n`` pixels alinhada à grade de ``tamanho`` m na UTM.

    ``crs_transform`` segue a convenção GDAL/EE ``[a, b, c, d, e, f]``.
    O pixel que contém o ponto fica no índice ``(centro, centro)``.
    """

    epsg: int
    n: int
    tamanho: float
    x0: float  # borda esquerda
    y_topo: float  # borda superior

    @property
    def crs(self) -> str:
        return f"EPSG:{self.epsg}"

    @property
    def crs_transform(self) -> list[float]:
        return [self.tamanho, 0.0, self.x0, 0.0, -self.tamanho, self.y_topo]

    @property
    def centro(self) -> int:
        return self.n // 2

    @property
    def largura_m(self) -> float:
        return self.n * self.tamanho

    def pixel_bbox_utm(self, col: int, lin: int) -> tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) do pixel ``(col, lin)`` em metros UTM."""
        xmin = self.x0 + col * self.tamanho
        ymax = self.y_topo - lin * self.tamanho
        return xmin, ymax - self.tamanho, xmin + self.tamanho, ymax

    def pixel_alvo_bbox_utm(self, meia_janela: int = 0) -> tuple[float, float, float, float]:
        """BBox do pixel alvo (meia_janela=0) ou da janela (2*meia_janela+1)² ao redor."""
        c = self.centro
        xmin, ymin, _, _ = self.pixel_bbox_utm(c - meia_janela, c + meia_janela)
        _, _, xmax, ymax = self.pixel_bbox_utm(c + meia_janela, c - meia_janela)
        return xmin, ymin, xmax, ymax


def janela_pixels(lon: float, lat: float, n: int = 31, tamanho: float = 10.0) -> JanelaPixels:
    """Janela de ``n``×``n`` pixels alinhada à grade de ``tamanho`` m, centrada no pixel do ponto.

    A grade Sentinel-2 em UTM tem origem em múltiplos de 10 m, portanto
    ``floor(x/10)`` identifica a coluna do pixel que contém o ponto.
    """
    if n < 1 or n % 2 == 0:
        raise ValueError(f"n deve ser ímpar e positivo, recebido {n}")
    x, y, epsg = para_utm(lon, lat)
    col = math.floor(x / tamanho)
    lin = math.floor(y / tamanho)
    meio = n // 2
    x0 = (col - meio) * tamanho
    y_topo = (lin + meio + 1) * tamanho
    return JanelaPixels(epsg=epsg, n=n, tamanho=tamanho, x0=x0, y_topo=y_topo)


# ---- Web Mercator (tiles XYZ) ------------------------------------------------


def lonlat_para_pixel_global(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Coordenada de pixel global (Web Mercator, tiles de 256 px) no zoom dado."""
    lat = max(-85.05112878, min(85.05112878, lat))
    escala = TAMANHO_TILE * (2**zoom)
    x = (lon + 180.0) / 360.0 * escala
    rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * escala
    return x, min(max(y, 0.0), escala)


def pixel_global_para_tile(px: float, py: float) -> tuple[int, int]:
    return int(px // TAMANHO_TILE), int(py // TAMANHO_TILE)


def metros_por_pixel(lat: float, zoom: int) -> float:
    """Resolução nominal do Web Mercator na latitude dada."""
    return 2 * math.pi * RAIO_TERRA * math.cos(math.radians(lat)) / (TAMANHO_TILE * (2**zoom))
