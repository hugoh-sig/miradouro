"""Exportador para o AcATaMa (plugin QGIS de avaliação de acurácia).

O AcATaMa não importa rótulos de CSV: o caminho é o arquivo de configuração
``.yml`` que o próprio plugin salva e restaura (*Restore configuration*). Ele
casa cada rótulo com a camada de amostras pelo campo ``id`` (inteiro, minúsculo)
e lê a classe do mapa no pixel do raster — nunca de uma coluna. Por isso saem:

* ``<nome>.yml``: configuração restaurável (botões = legenda, ``samples`` = respostas);
* ``<nome>_pontos.geojson``: camada de amostras com ``id`` inteiro (+ PLOTID e extras);
* ``<nome>_referencia.csv``: tabela plana completa para versionar.

FORMATO DO YML — versão-alvo: AcATaMa 26.7. O formato foi derivado do código-fonte do
plugin (``AcATaMa/core/config.py``, funções ``save`` e ``restore``; repositório
https://github.com/SMByC/AcATaMa, release 26.7). O ``save`` é a especificação; o
``restore`` define o que é obrigatório. Chaves que o ``restore`` lê SEM checar existência
(um ``KeyError`` aborta o restore depois de carregar raster e pontos e ANTES de
restaurar os rótulos — sintoma: "0 / N samples labeled"):
``general.config_file_version``, ``thematic_map.path``, ``thematic_map.nodata``,
``sampling_layer``, ``grid_view_widgets.{columns,rows}``, ``dialog_size``,
``current_sample_idx``, ``fit_to_sample``, ``is_completed``, ``labeling_buttons``,
``view_widgets_config``, ``samples`` e ``samples_order``. O golden file
``tests/golden/acatama_26.7.yml`` documenta chave a chave a origem no fonte.
Versões futuras do plugin podem mudar o formato: reconferir ``save``/``restore``.

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

# Raio padrão "fit to sample" do plugin por unidade do CRS da camada de amostras
# (AcATaMa/core/response_design.py, ResponseDesign.__init__, dict fit_to_sample_list).
FIT_TO_SAMPLE_GRAUS = 0.0011
FIT_TO_SAMPLE_METROS = 120


@dataclass
class ResultadoExportacao:
    yml: Path
    geojson: Path
    csv: Path
    n_pontos: int
    n_rotulados: int
    nodata: int
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


def fit_to_sample(crs: str | None) -> float:
    """Raio ``fit_to_sample`` que o plugin usaria por padrão para o CRS da camada:
    graus → 0.0011, unidades lineares → 120 (assume metros; mesma tabela do plugin)."""
    if crs is None or crs.upper() == "EPSG:4326":
        return FIT_TO_SAMPLE_GRAUS
    try:
        from pyproj import CRS

        unidade = (CRS.from_user_input(crs).axis_info[0].unit_name or "").lower()
    except Exception:  # noqa: BLE001 — sem pyproj ou CRS exótico: assume projetado em metros
        return FIT_TO_SAMPLE_METROS
    return FIT_TO_SAMPLE_GRAUS if "degree" in unidade else FIT_TO_SAMPLE_METROS


def resolver_nodata(mapa: str, nodata_cli: int | None) -> tuple[int, list[str]]:
    """NODATA a gravar no yml. Lê a tag do raster (rasterio); ``--nodata`` explícito
    prevalece (com aviso se divergir). Nunca devolve None: o ``restore`` do 26.7 faz
    ``float(nodata)`` (utils/others_utils.py, set_nodata_format) e quebra com null."""
    avisos: list[str] = []
    caminho = Path(mapa)
    if not caminho.exists():
        if nodata_cli is None:
            raise ErroExportacao(f"raster {mapa!r} não encontrado: passe --nodata explicitamente (o AcATaMa 26.7 não aceita nodata nulo)")
        return int(nodata_cli), avisos
    try:
        import rasterio
    except ImportError:
        if nodata_cli is None:
            raise ErroExportacao("ler a tag nodata do raster exige rasterio (pip install 'miradouro[acatama]'); ou passe --nodata") from None
        avisos.append("rasterio não instalado: tag nodata do raster não conferida; usando --nodata.")
        return int(nodata_cli), avisos
    try:
        with rasterio.open(caminho) as src:
            tag = src.nodata
    except Exception as e:  # noqa: BLE001
        if nodata_cli is None:
            raise ErroExportacao(f"não foi possível ler o raster {mapa!r} ({e}); passe --nodata") from None
        avisos.append(f"não foi possível ler o raster ({e}); usando --nodata.")
        return int(nodata_cli), avisos
    if tag is None:
        if nodata_cli is None:
            raise ErroExportacao(f"raster {mapa!r} não tem tag nodata: passe --nodata explicitamente (valor fora dos códigos da legenda)")
        avisos.append("raster sem tag nodata; usando --nodata.")
        return int(nodata_cli), avisos
    if tag != int(tag):
        raise ErroExportacao(f"tag nodata do raster não é inteira ({tag}); o AcATaMa compara classes inteiras")
    tag = int(tag)
    if nodata_cli is not None and int(nodata_cli) != tag:
        avisos.append(f"--nodata {nodata_cli} difere da tag do raster ({tag}); gravado --nodata.")
        return int(nodata_cli), avisos
    return tag, avisos


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
    nodata: int,
    camada: str,
    versao_acatama: str,
    crs: str | None = None,
) -> dict[str, Any]:
    """Dicionário no formato que ``AcATaMa.core.config.restore`` (26.7) espera.

    Ordem e nomes das chaves seguem ``AcATaMa.core.config.save``; ver
    ``tests/golden/acatama_26.7.yml`` para a referência linha a linha. ``mapa`` e
    ``camada`` devem ser caminhos absolutos.
    """
    campo = _campo_classe(projeto)
    por_codigo = label_id_por_codigo(projeto)
    samples: dict[int, dict[str, int]] = {}
    ordem: list[int] = []
    for idx, linha in enumerate(linhas):
        sid = ids[linha["PLOTID"]]
        ordem.append(sid)
        codigo = linha.get(campo.nome)
        if codigo is not None and str(codigo) in por_codigo:
            # save(): points_config[pnt_idx] = {"label_id": ..., "sample_id": ...}
            samples[idx] = {"label_id": por_codigo[str(codigo)], "sample_id": sid}
    return {
        "general": {
            "config_file_version": versao_acatama,
            # chaves extras: o restore só lê config_file_version
            "generated_by": f"miradouro {__version__}",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "project": projeto.nome,
        },
        # save(): nodata é o texto do campo da interface (string); restore aceita str ou número
        "thematic_map": {"path": mapa, "band": int(banda), "nodata": str(int(nodata))},
        "sampling_layer": camada,
        "dialog_size": None,                              # obrigatório; None = tamanho padrão da janela
        "response_design_grid_settings_first_open": False,
        "grid_view_widgets": {"columns": 2, "rows": 1},
        "current_sample_idx": 0,
        "sampling_unit_pixel_buffer": 0,
        "sampling_unit_color": "#FF0000",
        "fit_to_sample": fit_to_sample(crs),              # obrigatório
        "is_completed": bool(linhas) and len(samples) == len(linhas),  # obrigatório; recalculado no restore
        "view_widgets_config": {},
        "labeling_buttons": botoes_acatama(projeto),
        "auto_next_sample": True,
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
    nodata_final, avisos = resolver_nodata(mapa, nodata)
    ids, gerados = ids_inteiros([linha["PLOTID"] for linha in linhas])
    saida.mkdir(parents=True, exist_ok=True)
    caminho_yml = saida / f"{nome}.yml"
    caminho_geojson = saida / f"{nome}_pontos.geojson"
    caminho_csv = saida / f"{nome}_referencia.csv"

    fc = geojson_pontos(linhas, ids, pontos.colunas_extras, crs=crs)
    escrever_atomico(caminho_geojson, json.dumps(fc, ensure_ascii=False, indent=1))

    # Caminhos ABSOLUTOS para raster e camada: o AcATaMa 26.7 não carregou a camada de
    # amostras dada como caminho relativo ao yml (smoke test de 2026-09-13).
    caminho_mapa = str(Path(mapa).resolve()) if Path(mapa).exists() else mapa
    cfg = configuracao_acatama(
        projeto, linhas, ids, mapa=caminho_mapa, banda=banda, nodata=nodata_final,
        camada=str(caminho_geojson.resolve()), versao_acatama=versao_acatama, crs=crs,
    )
    escrever_atomico(caminho_yml, yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))

    colunas = colunas_referencia(projeto, pontos)
    if gerados:
        for linha in linhas:
            linha["acatama_id"] = ids[linha["PLOTID"]]
        colunas = ["acatama_id", *colunas]
    escrever_csv(linhas, colunas, caminho_csv)

    if gerados:
        avisos.append("PLOTIDs não são inteiros: gerado `id` sequencial (coluna acatama_id no CSV).")
    if not Path(mapa).exists():
        avisos.append(f"raster {mapa!r} não encontrado agora; o AcATaMa tentará o caminho relativo ao yml.")
    if crs is None:
        avisos.append("camada em WGS84 (EPSG:4326); se o plugin exigir o CRS do raster, reexporte com --crs.")
    return ResultadoExportacao(
        caminho_yml, caminho_geojson, caminho_csv, n_pontos=len(linhas), n_rotulados=len(cfg["samples"]),
        nodata=nodata_final, ids_gerados=gerados, avisos=avisos,
    )
