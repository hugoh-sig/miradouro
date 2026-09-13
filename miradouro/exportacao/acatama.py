"""Exportador para o AcATaMa (plugin QGIS de avaliação de acurácia).

O AcATaMa não importa rótulos de CSV: o caminho é o arquivo de configuração
``.yml`` que o próprio plugin salva e restaura (*Restore configuration*). Ele
casa cada rótulo com a camada de amostras pelo campo ``id`` (inteiro, minúsculo)
e lê a classe do mapa no pixel do raster — nunca de uma coluna. Por isso saem:

* ``<nome>.yml``: configuração restaurável (botões = legenda, ``samples`` = respostas);
* ``<nome>_pontos.geojson``: camada de amostras com ``id`` inteiro (+ PLOTID e extras);
* ``<nome>_referencia.csv``: tabela plana completa para versionar.

``thematic_class`` de cada botão é o ``codigo`` da legenda; o AcATaMa o compara
ao valor do pixel com ``int()``, portanto os códigos precisam ser inteiros.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from miradouro import __version__
from miradouro.core.pontos import ConjuntoPontos
from miradouro.core.projeto import Projeto
from miradouro.core.respostas import Armazenamento, escrever_atomico
from miradouro.exportacao.tabela import (
    ErroExportacao,
    colunas_referencia,
    escrever_csv,
    linhas_referencia,
)

VERSAO_ACATAMA_PADRAO = "26.7"  # versão do plugin alvo; ajuste com --versao-acatama


@dataclass
class ResultadoExportacao:
    yml: Path
    geojson: Path
    csv: Path
    n_pontos: int
    n_rotulados: int
    ids_gerados: bool = False
    avisos: list[str] = field(default_factory=list)

    def resumo(self) -> str:
        return f"{self.n_rotulados} rotulados de {self.n_pontos} pontos → {self.yml.parent}"


def _campo_classe(projeto: Projeto):
    campo = next((c for c in projeto.campos if c.tipo == "classe"), None)
    if campo is None:
        raise ErroExportacao("o projeto não tem campo do tipo 'classe' para exportar")
    return campo


def botoes_acatama(projeto: Projeto) -> dict[int, dict[str, Any]]:
    """``labeling_buttons`` do AcATaMa: label_id sequencial → {name, color, thematic_class, shortcut}."""
    botoes: dict[int, dict[str, Any]] = {}
    for i, classe in enumerate(projeto.legenda, start=1):
        try:
            codigo = int(classe.codigo)
        except ValueError:
            raise ErroExportacao(
                f"classe {classe.nome!r} tem código {classe.codigo!r}; o AcATaMa exige códigos inteiros iguais ao valor do pixel"
            ) from None
        botoes[i] = {"name": classe.nome, "color": classe.cor.upper(), "thematic_class": str(codigo), "shortcut": ""}
    return botoes


def label_id_por_codigo(projeto: Projeto) -> dict[str, int]:
    return {classe.codigo: i for i, classe in enumerate(projeto.legenda, start=1)}


def ids_inteiros(plotids: list[str]) -> tuple[dict[str, int], bool]:
    """``sample_id`` inteiro por PLOTID. Se algum PLOTID não for inteiro, gera 1..n (``ids_gerados``)."""
    try:
        mapa = {p: int(p) for p in plotids}
        if len(set(mapa.values())) == len(mapa):
            return mapa, False
    except ValueError:
        pass
    return {p: i for i, p in enumerate(plotids, start=1)}, True


def _transformador(crs: str | None):
    if crs is None or crs.upper() == "EPSG:4326":
        return None
    try:
        from pyproj import CRS, Transformer
    except ImportError:
        raise ErroExportacao("--crs exige pyproj: pip install 'miradouro[chips]'") from None
    try:
        return Transformer.from_crs("EPSG:4326", CRS.from_user_input(crs), always_xy=True)
    except Exception as e:  # noqa: BLE001
        raise ErroExportacao(f"CRS inválido {crs!r}: {e}") from None


def geojson_pontos(linhas: list[dict[str, Any]], ids: Mapping[str, int], extras: list[str], crs: str | None = None) -> dict[str, Any]:
    tr = _transformador(crs)
    feats = []
    for linha in linhas:
        x, y = (tr.transform(linha["LON"], linha["LAT"]) if tr else (linha["LON"], linha["LAT"]))
        props = {"id": ids[linha["PLOTID"]], "PLOTID": linha["PLOTID"], **{c: linha.get(c, "") for c in extras}}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]}, "properties": props})
    fc: dict[str, Any] = {"type": "FeatureCollection", "features": feats}
    if tr is not None:
        # GeoJSON "puro" é WGS84; o membro crs (legado) é lido pelo QGIS/GDAL.
        fc["crs"] = {"type": "name", "properties": {"name": f"urn:ogc:def:crs:{crs.upper().replace(':', '::')}"}}
    return fc


def configuracao_acatama(
    projeto: Projeto,
    linhas: list[dict[str, Any]],
    ids: Mapping[str, int],
    *,
    mapa: str,
    banda: int,
    nodata: int | None,
    camada: str,
    versao_acatama: str,
) -> dict[str, Any]:
    """Dicionário no formato que ``AcATaMa.core.config.restore`` espera."""
    campo = _campo_classe(projeto)
    por_codigo = label_id_por_codigo(projeto)
    samples: dict[int, dict[str, int]] = {}
    ordem: list[int] = []
    for idx, linha in enumerate(linhas):
        sid = ids[linha["PLOTID"]]
        ordem.append(sid)
        codigo = linha.get(campo.nome)
        if codigo is not None and str(codigo) in por_codigo:
            samples[idx] = {"sample_id": sid, "label_id": por_codigo[str(codigo)]}
    return {
        "general": {"config_file_version": versao_acatama, "generated_by": f"miradouro {__version__}", "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "project": projeto.nome},
        "thematic_map": {"path": mapa, "band": int(banda), "nodata": nodata},
        "sampling_layer": camada,
        "grid_view_widgets": {"columns": 2, "rows": 1},
        "current_sample_idx": 0,
        "sampling_unit_pixel_buffer": 0,
        "sampling_unit_color": "#FF0000",
        "view_widgets_config": {},
        "labeling_buttons": botoes_acatama(projeto),
        "samples": samples,
        "samples_order": ordem,
    }


def exportar_acatama(
    projeto: Projeto,
    pontos: ConjuntoPontos,
    arm: Armazenamento,
    *,
    mapa: str,
    saida: Path,
    nome: str = "acatama",
    banda: int = 1,
    nodata: int | None = None,
    filtro: Mapping[str, str] | None = None,
    crs: str | None = None,
    incluir_pendentes: bool = False,
    versao_acatama: str = VERSAO_ACATAMA_PADRAO,
) -> ResultadoExportacao:
    linhas = linhas_referencia(projeto, pontos, arm, filtro=filtro, apenas_respondidos=not incluir_pendentes, apenas_completas=True)
    if not linhas:
        raise ErroExportacao("nada a exportar: nenhum ponto com resposta completa dentro do filtro")
    ids, gerados = ids_inteiros([linha["PLOTID"] for linha in linhas])
    saida.mkdir(parents=True, exist_ok=True)
    caminho_yml = saida / f"{nome}.yml"
    caminho_geojson = saida / f"{nome}_pontos.geojson"
    caminho_csv = saida / f"{nome}_referencia.csv"

    fc = geojson_pontos(linhas, ids, pontos.colunas_extras, crs=crs)
    escrever_atomico(caminho_geojson, json.dumps(fc, ensure_ascii=False, indent=1))

    # Caminho do raster: absoluto se existir; senão como veio (o AcATaMa tenta relativo ao yml).
    caminho_mapa = str(Path(mapa).resolve()) if Path(mapa).exists() else mapa
    cfg = configuracao_acatama(projeto, linhas, ids, mapa=caminho_mapa, banda=banda, nodata=nodata, camada=caminho_geojson.name, versao_acatama=versao_acatama)
    escrever_atomico(caminho_yml, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))

    colunas = colunas_referencia(projeto, pontos)
    if gerados:
        for linha in linhas:
            linha["acatama_id"] = ids[linha["PLOTID"]]
        colunas = ["acatama_id", *colunas]
    escrever_csv(linhas, colunas, caminho_csv)

    avisos = []
    if gerados:
        avisos.append("PLOTIDs não são inteiros: gerado `id` sequencial (coluna acatama_id no CSV).")
    if not Path(mapa).exists():
        avisos.append(f"raster {mapa!r} não encontrado agora; o AcATaMa tentará o caminho relativo ao yml.")
    if crs is None:
        avisos.append("camada em WGS84 (EPSG:4326); se o plugin exigir o CRS do raster, reexporte com --crs.")
    return ResultadoExportacao(caminho_yml, caminho_geojson, caminho_csv, n_pontos=len(linhas), n_rotulados=len(cfg["samples"]), ids_gerados=gerados, avisos=avisos)
