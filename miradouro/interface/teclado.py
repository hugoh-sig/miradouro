"""Componente Streamlit que captura teclas na página (sem dependências externas)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_PASTA = Path(__file__).parent / "teclado_html"
_componente = None


def _obter():
    global _componente
    if _componente is None:
        import streamlit.components.v1 as components

        _componente = components.declare_component("miradouro_teclado", path=str(_PASTA))
    return _componente


def capturar_tecla(
    rotulos_texto: list[str] | None = None,
    focar: dict[str, Any] | None = None,
    key: str = "miradouro_teclado",
) -> dict[str, Any] | None:
    """Renderiza o capturador (invisível) e devolve o último evento ``{id, key, code, shift}``.

    O mesmo evento é devolvido em todas as reexecuções até chegar outro; o
    chamador deve deduplicar pelo ``id``. ``focar={"id", "rotulo"}`` faz a página
    rolar até o widget com esse rótulo e focá-lo (uma vez por ``id``).
    """
    valor = _obter()(rotulos_texto=list(rotulos_texto or []), focar=focar, key=key, default=None)
    return valor if isinstance(valor, dict) else None
