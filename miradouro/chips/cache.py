"""Cache local de chips: ``<pasta>/<provedor>/<PLOTID>.png``.

A versão do provedor que gerou o chip fica gravada num chunk de texto do PNG
(``miradouro:provedor_versao``). Um chip cuja versão difere da versão atual do
provedor conta como inexistente e é regerado.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from miradouro import __version__
from miradouro.core.respostas import escrever_atomico

CHAVE_VERSAO = "miradouro:provedor_versao"
CHAVE_PACOTE = "miradouro:versao"

_RE_INSEGURO = re.compile(r"[^A-Za-z0-9._-]+")


def nome_seguro(plotid: str) -> str:
    """Converte um PLOTID em nome de arquivo seguro e reversível na prática."""
    s = _RE_INSEGURO.sub("_", str(plotid).strip())
    return s or "_"


class CacheChips:
    def __init__(self, pasta: str | Path) -> None:
        self.pasta = Path(pasta)

    def caminho(self, provedor: str, plotid: str) -> Path:
        return self.pasta / provedor / f"{nome_seguro(plotid)}.png"

    def versao_de(self, provedor: str, plotid: str) -> str | None:
        """Versão do provedor gravada no chip, ou None se ausente/ilegível."""
        p = self.caminho(provedor, plotid)
        if not p.is_file():
            return None
        try:
            from PIL import Image

            with Image.open(p) as im:
                v = im.info.get(CHAVE_VERSAO)
        except Exception:  # noqa: BLE001 — arquivo truncado/corrompido conta como ausente
            return None
        return str(v) if v is not None else None

    def existe(self, provedor: str, plotid: str, versao: str | None = None) -> bool:
        """True se o chip existe e, quando ``versao`` é dada, foi gerado por essa versão."""
        p = self.caminho(provedor, plotid)
        if not (p.is_file() and p.stat().st_size > 0):
            return False
        if versao is None:
            return True
        return self.versao_de(provedor, plotid) == str(versao)

    def gravar(self, provedor: str, plotid: str, png: bytes, versao: str | None = None) -> Path:
        if not png or png[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"provedor {provedor!r} devolveu algo que não é PNG para {plotid!r}")
        if versao is not None:
            png = _embutir_versao(png, str(versao))
        destino = self.caminho(provedor, plotid)
        escrever_atomico(destino, png)
        return destino

    def listar(self, provedor: str) -> list[Path]:
        pasta = self.pasta / provedor
        return sorted(pasta.glob("*.png")) if pasta.is_dir() else []

    def contar(self, provedor: str) -> int:
        return len(self.listar(provedor))


def _embutir_versao(png: bytes, versao: str) -> bytes:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    with Image.open(io.BytesIO(png)) as im:
        im.load()
        meta = PngInfo()
        for k, v in im.info.items():
            if isinstance(v, str) and not k.startswith("miradouro:"):
                meta.add_text(k, v)
        meta.add_text(CHAVE_VERSAO, versao)
        meta.add_text(CHAVE_PACOTE, __version__)
        saida = io.BytesIO()
        im.save(saida, format="PNG", pnginfo=meta, optimize=True)
    return saida.getvalue()
