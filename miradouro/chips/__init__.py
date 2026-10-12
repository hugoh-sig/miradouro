"""Motor de pré-computação de chips com provedores plugáveis.

Um *chip* é um painel PNG por ponto e por provedor, gravado em
``<pasta_chips>/<provedor>/<PLOTID>.png``. Provedores implementam
:class:`ProvedorChip` e são registrados por nome; o ``projeto.yaml`` diz quais
estão habilitados e com que configuração.
"""

from miradouro.chips.base import (
    PedidoChip,
    ProvedorChip,
    obter_provedor,
    provedores_disponiveis,
    registrar,
)
from miradouro.chips.cache import CacheChips
from miradouro.chips.motor import Falha, ResultadoLote, gerar_chips, instanciar_provedores

__all__ = [
    "CacheChips",
    "Falha",
    "PedidoChip",
    "ProvedorChip",
    "ResultadoLote",
    "gerar_chips",
    "instanciar_provedores",
    "obter_provedor",
    "provedores_disponiveis",
    "registrar",
]
