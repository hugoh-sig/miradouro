"""Interface comum dos provedores de chips e registro por nome."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from miradouro.core.erros import ErroMiradouro


class ErroProvedor(ErroMiradouro):
    """Configuração de provedor inválida ou provedor desconhecido."""


@dataclass(frozen=True)
class PedidoChip:
    """O que um provedor recebe para gerar um chip: (lon, lat, config) + identificação."""

    plotid: str
    lon: float
    lat: float
    ano_referencia: int
    config: dict[str, Any]


class ProvedorChip(ABC):
    """Contrato de um provedor de chips.

    Subclasses definem ``nome`` (chave usada no yaml e no cache) e implementam
    :meth:`gerar`, que devolve os bytes de um PNG. :meth:`preparar` roda uma
    vez por lote (ex.: inicializar o Earth Engine) e :meth:`validar_config`
    roda na construção.
    """

    nome: ClassVar[str]
    descricao: ClassVar[str] = ""
    #: Versão do painel gerado. Mude ao alterar layout/conteúdo: chips em cache com
    #: outra versão são considerados desatualizados e regerados.
    versao: ClassVar[str] = "1"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = dict(config or {})
        self.validar_config()

    def validar_config(self) -> None:  # noqa: B027 — gancho opcional
        """Levanta :class:`ErroProvedor` se a configuração for inválida."""

    def preparar(self) -> None:  # noqa: B027 — gancho opcional
        """Chamado uma vez antes do lote (autenticação, sessões HTTP...)."""

    @abstractmethod
    def gerar(self, pedido: PedidoChip) -> bytes:
        """Gera o painel PNG de um ponto. Qualquer exceção é tratada como falha do ponto."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} nome={self.nome!r}>"


_REGISTRO: dict[str, type[ProvedorChip]] = {}


def registrar(cls: type[ProvedorChip]) -> type[ProvedorChip]:
    """Decorador: registra um provedor pelo seu atributo ``nome``."""
    nome = getattr(cls, "nome", None)
    if not nome or not isinstance(nome, str):
        raise ErroProvedor(f"{cls.__name__} precisa definir o atributo de classe `nome`")
    _REGISTRO[nome] = cls
    return cls


def _carregar_embutidos() -> None:
    # Importa os provedores do pacote para que se registrem (import tardio para
    # não puxar Earth Engine/matplotlib ao importar o core).
    import miradouro.chips.provedores  # noqa: F401


def provedores_disponiveis() -> dict[str, type[ProvedorChip]]:
    _carregar_embutidos()
    return dict(_REGISTRO)


def obter_provedor(nome: str) -> type[ProvedorChip]:
    _carregar_embutidos()
    try:
        return _REGISTRO[nome]
    except KeyError:
        raise ErroProvedor(
            f"provedor de chips desconhecido: {nome!r}; disponíveis: {sorted(_REGISTRO)}"
        ) from None
