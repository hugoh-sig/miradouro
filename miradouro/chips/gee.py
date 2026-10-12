"""Utilidades comuns aos provedores baseados no Google Earth Engine."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from miradouro.chips.base import ErroProvedor

log = logging.getLogger(__name__)
_lock = threading.Lock()
_inicializado: str | None = None

VARIAVEL_PROJETO = "EARTHENGINE_PROJECT"


def projeto_gee_de(config: dict[str, Any]) -> str | None:
    """Projeto GEE: ``projeto_gee`` no yaml, senão a variável ``EARTHENGINE_PROJECT``."""
    return config.get("projeto_gee") or os.environ.get(VARIAVEL_PROJETO) or None


def inicializar_ee(projeto_gee: str | None) -> None:
    """Inicializa o Earth Engine uma vez por processo (thread-safe)."""
    global _inicializado
    with _lock:
        if _inicializado is not None:
            return
        try:
            import ee
        except ImportError:
            raise ErroProvedor(
                "earthengine-api não instalado: pip install 'miradouro[chips]'"
            ) from None
        try:
            ee.Initialize(project=projeto_gee)
        except Exception as e:  # ee.EEException ou erro de credencial
            raise ErroProvedor(
                f"falha ao inicializar o Earth Engine (projeto={projeto_gee!r}): {e}\n"
                "Rode `earthengine authenticate` e defina `projeto_gee` no yaml "
                f"ou a variável {VARIAVEL_PROJETO}."
            ) from None
        _inicializado = projeto_gee or "(padrão)"
        log.info("Earth Engine inicializado (projeto=%s)", _inicializado)


def mascarar_nuvens_s2(img):
    """Máscara com a banda SCL do S2 SR: remove nuvem, sombra, cirrus, neve e saturado."""
    import ee

    scl = img.select("SCL")
    ruim = (
        scl.eq(1).Or(scl.eq(3)).Or(scl.eq(8)).Or(scl.eq(9)).Or(scl.eq(10)).Or(scl.eq(11))
    )
    return img.updateMask(ruim.Not()).copyProperties(img, ["system:time_start"])


def colecao_s2(colecao: str, geometria, inicio: str, fim: str, nuvens_max: float):
    import ee

    return (
        ee.ImageCollection(colecao)
        .filterBounds(geometria)
        .filterDate(inicio, fim)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", nuvens_max))
        .map(mascarar_nuvens_s2)
    )


def baixar_bytes(url: str, tentativas: int = 3, timeout: float = 120.0) -> bytes:
    """GET com novas tentativas; devolve o corpo da resposta."""
    import requests

    ultimo: Exception | None = None
    for i in range(tentativas):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.content
        except Exception as e:  # noqa: BLE001 — qualquer falha de rede conta
            ultimo = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"falha ao baixar {url[:80]}...: {ultimo}")
