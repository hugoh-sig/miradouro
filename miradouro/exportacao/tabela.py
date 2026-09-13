"""Tabela plana de referência: um ponto por linha, com resposta, auditoria e colunas do CSV.

É a base do CSV versionável (protocolo de rastreabilidade), do exportador
AcATaMa e do relatório. Aqui as colunas ocultas ao intérprete VOLTAM a aparecer:
esta camada é do analista, não da interpretação.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from miradouro.core.erros import ErroMiradouro
from miradouro.core.pontos import ConjuntoPontos, Ponto
from miradouro.core.projeto import Projeto, validar_resposta
from miradouro.core.respostas import Armazenamento, Resposta, escrever_atomico

SEPARADOR_LISTA = "|"
COLUNAS_AUDITORIA = ("interprete", "sessao_id", "criado_em", "atualizado_em", "revisoes", "miradouro_versao", "yaml_sha256")
COLUNAS_META = ("duracao_s", "modo", "sem_subsidio", "desfeito", "passada", "controle")


class ErroExportacao(ErroMiradouro):
    """Filtro inválido, dados incompatíveis com o formato de destino etc."""


def parse_filtro(expressoes: Iterable[str]) -> dict[str, str]:
    """``["conjunto=classe", "faixa_rio=0-1 km"]`` → ``{"conjunto": "classe", ...}``."""
    filtro: dict[str, str] = {}
    for e in expressoes:
        coluna, sep, valor = e.partition("=")
        if not sep or not coluna.strip():
            raise ErroExportacao(f"filtro inválido {e!r}: use coluna=valor")
        filtro[coluna.strip()] = valor.strip()
    return filtro


def aplicar_filtro(pontos: Iterable[Ponto], filtro: Mapping[str, str], colunas: Iterable[str] = ()) -> list[Ponto]:
    """Mantém os pontos cujas colunas extras batem com o filtro (comparação exata, como texto)."""
    colunas = set(colunas)
    if colunas:
        desconhecidas = [c for c in filtro if c not in colunas]
        if desconhecidas:
            raise ErroExportacao(f"filtro usa coluna(s) inexistente(s) no CSV: {desconhecidas}; disponíveis: {sorted(colunas)}")
    return [p for p in pontos if all(str(p.extras.get(c, "")).strip() == v for c, v in filtro.items())]


def _valor_csv(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return SEPARADOR_LISTA.join(str(x) for x in v)
    return str(v)


def resposta_completa(projeto: Projeto, resposta: Resposta | None) -> bool:
    return resposta is not None and not validar_resposta(projeto, resposta.valores)


def linhas_referencia(
    projeto: Projeto,
    pontos: ConjuntoPontos,
    arm: Armazenamento,
    *,
    filtro: Mapping[str, str] | None = None,
    apenas_respondidos: bool = True,
    apenas_completas: bool = True,
) -> list[dict[str, Any]]:
    """Uma linha por ponto: PLOTID, LON, LAT, extras do CSV (inclusive ocultas), campos, auditoria, meta.

    Valores brutos (listas continuam listas); :func:`escrever_csv` formata.
    """
    selecionados = aplicar_filtro(pontos, filtro or {}, pontos.colunas_extras)
    respostas = arm.todas()
    linhas: list[dict[str, Any]] = []
    for p in selecionados:
        r = respostas.get(p.plotid)
        if r is None and apenas_respondidos:
            continue
        completa = resposta_completa(projeto, r)
        if r is not None and apenas_completas and not completa:
            continue
        linha: dict[str, Any] = {"PLOTID": p.plotid, "LON": p.lon, "LAT": p.lat}
        linha.update({c: p.extras.get(c, "") for c in pontos.colunas_extras})
        for campo in projeto.campos:
            linha[campo.nome] = r.valores.get(campo.nome) if r else None
        linha["resposta_completa"] = completa if r else False
        for c in COLUNAS_AUDITORIA:
            linha[c] = getattr(r, c) if r else None
        for c in COLUNAS_META:
            linha[c] = r.meta.get(c) if r else None
        linhas.append(linha)
    return linhas


def colunas_referencia(projeto: Projeto, pontos: ConjuntoPontos) -> list[str]:
    return (
        ["PLOTID", "LON", "LAT", *pontos.colunas_extras, *[c.nome for c in projeto.campos], "resposta_completa"]
        + list(COLUNAS_AUDITORIA)
        + list(COLUNAS_META)
    )


def escrever_csv(linhas: list[dict[str, Any]], colunas: list[str], destino: Path) -> Path:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=colunas, lineterminator="\n")
    w.writeheader()
    for linha in linhas:
        w.writerow({c: _valor_csv(linha.get(c)) for c in colunas})
    escrever_atomico(destino, buf.getvalue())
    return destino
