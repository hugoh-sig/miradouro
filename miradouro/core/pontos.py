"""Leitura e validação do ``pontos.csv``.

Colunas obrigatórias: ``PLOTID``, ``LON``, ``LAT`` (aceitas em qualquer caixa).
Qualquer outra coluna é guardada em ``Ponto.extras`` como texto; as listadas em
``colunas_ocultas`` no projeto nunca chegam ao intérprete.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from miradouro.core.erros import ErroPontos

COLUNAS_OBRIGATORIAS = ("PLOTID", "LON", "LAT")


@dataclass(frozen=True)
class Ponto:
    """Um ponto de validação."""

    plotid: str
    lon: float
    lat: float
    extras: dict[str, str] = field(default_factory=dict)

    def extras_visiveis(self, colunas_ocultas: Iterable[str] = ()) -> dict[str, str]:
        """Colunas extras que o intérprete pode ver."""
        ocultas = set(colunas_ocultas)
        return {k: v for k, v in self.extras.items() if k not in ocultas}


@dataclass
class ConjuntoPontos:
    """Todos os pontos de um projeto, na ordem do CSV."""

    pontos: list[Ponto]
    colunas: list[str]
    caminho: Path | None = None

    def __post_init__(self) -> None:
        self._por_id = {p.plotid: p for p in self.pontos}

    def __len__(self) -> int:
        return len(self.pontos)

    def __iter__(self) -> Iterator[Ponto]:
        return iter(self.pontos)

    def __contains__(self, plotid: object) -> bool:
        return str(plotid) in self._por_id

    def obter(self, plotid: str) -> Ponto | None:
        return self._por_id.get(str(plotid))

    @property
    def ids(self) -> list[str]:
        return [p.plotid for p in self.pontos]

    @property
    def colunas_extras(self) -> list[str]:
        return [c for c in self.colunas if c.upper() not in COLUNAS_OBRIGATORIAS]


def _detectar_delimitador(amostra: str) -> str:
    try:
        return csv.Sniffer().sniff(amostra, delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def _float(valor: str, coluna: str, linha: int, minimo: float, maximo: float) -> float:
    try:
        v = float(str(valor).strip().replace(",", "."))
    except ValueError:
        raise ErroPontos(f"linha {linha}: {coluna}={valor!r} não é numérico") from None
    if not (minimo <= v <= maximo):
        raise ErroPontos(f"linha {linha}: {coluna}={v} fora do intervalo [{minimo}, {maximo}]")
    return v


def pontos_de_texto(texto: str, caminho: Path | None = None) -> ConjuntoPontos:
    """Constrói um :class:`ConjuntoPontos` a partir do conteúdo de um CSV."""
    if not texto.strip():
        raise ErroPontos(f"CSV de pontos vazio: {caminho or '(texto)'}")
    delim = _detectar_delimitador(texto.splitlines()[0])
    leitor = csv.DictReader(io.StringIO(texto), delimiter=delim)
    cabecalho = [c.strip() for c in (leitor.fieldnames or [])]
    if any(not c for c in cabecalho):
        raise ErroPontos("CSV de pontos tem coluna sem nome no cabeçalho")

    mapa = {c.upper(): c for c in cabecalho}
    faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in mapa]
    if faltando:
        raise ErroPontos(
            f"CSV de pontos sem coluna(s) obrigatória(s) {faltando}; cabeçalho: {cabecalho}"
        )
    col_id, col_lon, col_lat = (mapa[c] for c in COLUNAS_OBRIGATORIAS)
    extras_cols = [c for c in cabecalho if c not in (col_id, col_lon, col_lat)]

    pontos: list[Ponto] = []
    vistos: set[str] = set()
    for n, linha in enumerate(leitor, start=2):
        linha = {(k or "").strip(): (v if v is not None else "") for k, v in linha.items()}
        if all(str(v).strip() == "" for v in linha.values()):
            continue  # linha em branco
        plotid = str(linha.get(col_id, "")).strip()
        if not plotid:
            raise ErroPontos(f"linha {n}: PLOTID vazio")
        if plotid in vistos:
            raise ErroPontos(f"linha {n}: PLOTID repetido {plotid!r}")
        vistos.add(plotid)
        lon = _float(linha.get(col_lon, ""), "LON", n, -180.0, 180.0)
        lat = _float(linha.get(col_lat, ""), "LAT", n, -90.0, 90.0)
        extras = {c: str(linha.get(c, "")).strip() for c in extras_cols}
        pontos.append(Ponto(plotid=plotid, lon=lon, lat=lat, extras=extras))

    if not pontos:
        raise ErroPontos(f"CSV de pontos sem linhas de dados: {caminho or '(texto)'}")
    return ConjuntoPontos(pontos=pontos, colunas=cabecalho, caminho=caminho)


def carregar_pontos(caminho: str | Path) -> ConjuntoPontos:
    """Lê e valida um CSV de pontos.

    Raises:
        ErroPontos: arquivo ausente, colunas faltando, PLOTID repetido, coordenada inválida.
    """
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroPontos(f"CSV de pontos não encontrado: {caminho}")
    try:
        texto = caminho.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        texto = caminho.read_text(encoding="latin-1")
    return pontos_de_texto(texto, caminho=caminho.resolve())
