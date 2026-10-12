"""Tabela de referência e exportador AcATaMa (sem QGIS: valida a estrutura do yml/GeoJSON)."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from miradouro.cli import CODIGO_ERRO, CODIGO_OK, main
from miradouro.core import Armazenamento, carregar_pontos
from miradouro.exportacao import aplicar_filtro, linhas_referencia, parse_filtro
from miradouro.exportacao.acatama import (
    botoes_acatama,
    configuracao_acatama,
    exportar_acatama,
    geojson_pontos,
    ids_inteiros,
)

# Sem rasterio, resolver_nodata não tenta abrir o raster e avisa que a tag não foi conferida; com rasterio
# (extra `acatama`, instalado na CI), um arquivo ilegível produz "não foi possível ler". Os dois ramos
# são comportamento esperado do mesmo resolvedor; o teste verifica o ramo do ambiente em que roda.
TEM_RASTERIO = importlib.util.find_spec("rasterio") is not None
AVISO_RASTER_ILEGIVEL = "não foi possível ler" if TEM_RASTERIO else "rasterio não instalado"
from miradouro.exportacao.tabela import ErroExportacao, colunas_referencia, escrever_csv


@pytest.fixture
def respondido(projeto):
    """p1 completa, p2 incompleta (rascunho), p3 sem resposta."""
    pontos = carregar_pontos(projeto.caminho_pontos)
    arm = Armazenamento(projeto, interprete="ana")
    arm.abrir_sessao()
    arm.gravar("p1", {"classe_ref": "1", "confianca": "media", "classe_alt": "2", "fonte": ["hr", "serie"], "observacao": "ok"}, meta={"duracao_s": 12.5, "modo": "pendentes"})
    arm.gravar("p2", {"confianca": "alta"}, validar=False)
    return projeto, pontos, arm


def test_parse_e_aplicar_filtro(respondido):
    projeto, pontos, _ = respondido
    assert parse_filtro(["classe_mapa=2", "regiao = sul "]) == {"classe_mapa": "2", "regiao": "sul"}
    with pytest.raises(ErroExportacao, match="coluna=valor"):
        parse_filtro(["semigual"])
    assert [p.plotid for p in aplicar_filtro(pontos, {"regiao": "sul"}, pontos.colunas_extras)] == ["p2", "p3"]
    assert [p.plotid for p in aplicar_filtro(pontos, {"regiao": "sul", "classe_mapa": "6"}, pontos.colunas_extras)] == ["p3"]
    with pytest.raises(ErroExportacao, match="inexistente"):
        aplicar_filtro(pontos, {"nao_existe": "x"}, pontos.colunas_extras)


def test_linhas_referencia(respondido):
    projeto, pontos, arm = respondido
    linhas = linhas_referencia(projeto, pontos, arm)
    assert [linha["PLOTID"] for linha in linhas] == ["p1"]  # só completas
    l1 = linhas[0]
    assert l1["classe_mapa"] == "1" and l1["regiao"] == "norte"  # ocultas voltam para o analista
    assert l1["fonte"] == ["hr", "serie"] and l1["classe_alt"] == "2" and l1["interprete"] == "ana"
    assert l1["duracao_s"] == 12.5 and l1["modo"] == "pendentes" and l1["resposta_completa"] is True
    linhas = linhas_referencia(projeto, pontos, arm, apenas_completas=False)
    assert [linha["PLOTID"] for linha in linhas] == ["p1", "p2"] and linhas[1]["resposta_completa"] is False
    linhas = linhas_referencia(projeto, pontos, arm, apenas_respondidos=False, apenas_completas=False)
    assert [linha["PLOTID"] for linha in linhas] == ["p1", "p2", "p3"] and linhas[2]["classe_ref"] is None
    assert [linha["PLOTID"] for linha in linhas_referencia(projeto, pontos, arm, filtro={"regiao": "sul"}, apenas_completas=False)] == ["p2"]


def test_escrever_csv_formata_listas_e_booleanos(respondido, tmp_path):
    projeto, pontos, arm = respondido
    linhas = linhas_referencia(projeto, pontos, arm)
    destino = escrever_csv(linhas, colunas_referencia(projeto, pontos), tmp_path / "ref.csv")
    with destino.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["fonte"] == "hr|serie" and rows[0]["resposta_completa"] == "true" and rows[0]["sem_subsidio"] == ""
    assert list(rows[0])[:5] == ["PLOTID", "LON", "LAT", "classe_mapa", "regiao"]


def test_ids_inteiros():
    assert ids_inteiros(["10", "2", "7"]) == ({"10": 10, "2": 2, "7": 7}, False)
    assert ids_inteiros(["a", "b"]) == ({"a": 1, "b": 2}, True)
    assert ids_inteiros(["1", "01"]) == ({"1": 1, "01": 2}, True)  # colidiriam como inteiros


def test_botoes_acatama(projeto, dados_projeto):
    botoes = botoes_acatama(projeto)
    assert botoes == {
        1: {"name": "floresta", "color": "#1A9850", "thematic_class": "1", "shortcut": ""},
        2: {"name": "pasto", "color": "#FEE08B", "thematic_class": "2", "shortcut": ""},
        3: {"name": "agua", "color": "#4575B4", "thematic_class": "6", "shortcut": ""},
    }
    from miradouro.core.projeto import projeto_de_dict

    dados_projeto["legenda"][0]["codigo"] = "FLO"
    with pytest.raises(ErroExportacao, match="inteiros"):
        botoes_acatama(projeto_de_dict(dados_projeto))


def test_geojson_pontos_wgs84_e_reprojetado(respondido):
    projeto, pontos, arm = respondido
    linhas = linhas_referencia(projeto, pontos, arm, apenas_respondidos=False, apenas_completas=False)
    ids, _ = ids_inteiros([linha["PLOTID"] for linha in linhas])
    fc = geojson_pontos(linhas, ids, pontos.colunas_extras)
    assert fc["type"] == "FeatureCollection" and "crs" not in fc and len(fc["features"]) == 3
    f0 = fc["features"][0]
    assert f0["geometry"]["coordinates"] == [-44.1, -19.9]
    assert f0["properties"] == {"id": 1, "PLOTID": "p1", "classe_mapa": "1", "regiao": "norte"}
    fc2 = geojson_pontos(linhas, ids, [], crs="EPSG:31983")
    x, y = fc2["features"][0]["geometry"]["coordinates"]
    assert 500_000 < x < 700_000 and 7_700_000 < y < 7_900_000
    assert fc2["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::31983"
    with pytest.raises(ErroExportacao, match="CRS inválido"):
        geojson_pontos(linhas, ids, [], crs="EPSG:abc")


def test_configuracao_acatama_estrutura(respondido):
    projeto, pontos, arm = respondido
    linhas = linhas_referencia(projeto, pontos, arm, apenas_respondidos=False, apenas_completas=False)
    ids = {"p1": 1, "p2": 2, "p3": 3}
    cfg = configuracao_acatama(projeto, linhas, ids, mapa="/x/mapa.tif", banda=1, nodata=0, camada="/x/a_pontos.geojson", versao_acatama="26.7")
    assert cfg["general"]["config_file_version"] == "26.7"
    assert cfg["thematic_map"] == {"path": "/x/mapa.tif", "band": 1, "nodata": "0"}
    assert cfg["sampling_layer"] == "/x/a_pontos.geojson"
    assert cfg["samples_order"] == [1, 2, 3]
    assert cfg["samples"] == {0: {"label_id": 1, "sample_id": 1}}  # só p1 tem classe
    for chave in ("grid_view_widgets", "current_sample_idx", "sampling_unit_pixel_buffer", "sampling_unit_color", "view_widgets_config", "labeling_buttons", "dialog_size", "fit_to_sample", "is_completed"):
        assert chave in cfg


def test_exportar_acatama_arquivos(respondido, tmp_path):
    projeto, pontos, arm = respondido
    mapa = tmp_path / "mapa.tif"
    mapa.write_bytes(b"nao e um tif de verdade")
    with pytest.raises(ErroExportacao, match="--nodata"):  # arquivo ilegível e sem --nodata
        exportar_acatama(projeto, pontos, arm, mapa=str(mapa), saida=tmp_path / "exp", nome="teste", crs=None)
    r = exportar_acatama(projeto, pontos, arm, mapa=str(mapa), saida=tmp_path / "exp", nome="teste", crs=None, nodata=0)
    assert r.n_pontos == 1 and r.n_rotulados == 1 and r.ids_gerados  # 'p1' não é inteiro → id gerado
    cfg = yaml.safe_load(r.yml.read_text(encoding="utf-8"))
    assert cfg["thematic_map"]["path"] == str(mapa.resolve()) and cfg["sampling_layer"] == str(r.geojson.resolve())
    assert cfg["thematic_map"]["nodata"] == "0" and any(AVISO_RASTER_ILEGIVEL in a for a in r.avisos)
    assert cfg["labeling_buttons"][1]["thematic_class"] == "1" and cfg["samples"] == {0: {"label_id": 1, "sample_id": 1}}
    fc = json.loads(r.geojson.read_text(encoding="utf-8"))
    assert fc["features"][0]["properties"]["id"] == 1 and fc["features"][0]["properties"]["PLOTID"] == "p1"
    with r.csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["acatama_id"] == "1" and rows[0]["PLOTID"] == "p1"
    assert any("WGS84" in a for a in r.avisos) and any("sequencial" in a for a in r.avisos)
    with pytest.raises(ErroExportacao, match="nada a exportar"):
        exportar_acatama(projeto, pontos, arm, mapa=str(mapa), saida=tmp_path / "exp2", filtro={"regiao": "sul"}, nodata=0)


def test_cli_exportar(respondido, capsys):
    projeto, pontos, arm = respondido
    y = str(projeto.caminho_yaml)
    assert main(["exportar", "acatama", y, "--mapa", "mapa_inexistente.tif", "--versao-acatama", "26.7"]) == CODIGO_ERRO  # sem --nodata
    assert "--nodata" in capsys.readouterr().err
    assert main(["exportar", "acatama", y, "--mapa", "mapa_inexistente.tif", "--nodata", "0", "--versao-acatama", "26.7"]) == CODIGO_OK
    out = capsys.readouterr().out
    assert "1 rotulados de 1 pontos" in out and "não encontrado agora" in out
    exp = projeto.pasta_saida / "exportacao" / "acatama"
    assert (exp / "acatama.yml").exists() and (exp / "acatama_pontos.geojson").exists() and (exp / "acatama_referencia.csv").exists()
    assert yaml.safe_load((exp / "acatama.yml").read_text())["general"]["config_file_version"] == "26.7"

    assert main(["exportar", "csv", y, "--incluir-pendentes", "--nome", "tudo"]) == CODIGO_OK
    assert "3 linhas" in capsys.readouterr().out and (projeto.pasta_saida / "exportacao" / "tudo.csv").exists()
    assert main(["exportar", "csv", y, "--filtro", "coluna_x=1"]) == CODIGO_ERRO
    assert main(["exportar", "acatama", y, "--mapa", "m.tif", "--nodata", "0", "--respostas", str(Path(y).parent / "vazio")]) == CODIGO_ERRO
    assert "não há respostas" in capsys.readouterr().err


# ── formato AcATaMa 26.7 (derivado do fonte do plugin; ver tests/golden/acatama_26.7.yml) ──

GOLDEN = Path(__file__).parent / "golden" / "acatama_26.7.yml"

# Chaves que AcATaMa.core.config.restore (26.7) lê SEM checar existência. Um KeyError
# aborta o restore depois de carregar raster e pontos e ANTES dos rótulos.
OBRIGATORIAS_RESTORE_26_7 = {
    ("general", "config_file_version"): "restore L344-346",
    ("thematic_map", "path"): "restore L393",
    ("thematic_map", "nodata"): "restore L407 (set_nodata_format → float)",
    ("sampling_layer",): "restore L604",
    ("grid_view_widgets", "columns"): "restore L620",
    ("grid_view_widgets", "rows"): "restore L621",
    ("dialog_size",): "restore L622",
    ("current_sample_idx",): "restore L625",
    ("fit_to_sample",): "restore L630",
    ("is_completed",): "restore L631",
    ("labeling_buttons",): "restore L633",
    ("view_widgets_config",): "restore L635",
    ("samples",): "restore L651",
    ("samples_order",): "restore L664",
}


def _estrutura(obj, chave_dinamica=False):
    """Esqueleto de tipos: dicts viram {chave: esqueleto}; dicts com chaves dinâmicas
    (samples, labeling_buttons) comparam só o primeiro valor."""
    if isinstance(obj, dict):
        if chave_dinamica:
            return {"<id>": _estrutura(next(iter(obj.values())))} if obj else {}
        return {k: _estrutura(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [type(obj[0]).__name__] if obj else []
    return type(obj).__name__


def _cfg_exemplo(respondido):
    projeto, pontos, arm = respondido
    linhas = linhas_referencia(projeto, pontos, arm, apenas_respondidos=False, apenas_completas=False)
    return configuracao_acatama(projeto, linhas, {"p1": 1, "p2": 2, "p3": 3}, mapa="/abs/mapa.tif", banda=1, nodata=255, camada="/abs/a_pontos.geojson", versao_acatama="26.7")


def test_yml_segue_golden_26_7(respondido):
    golden = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    cfg = _cfg_exemplo(respondido)
    assert list(cfg) == list(golden), "ordem/nomes das chaves de topo diferem do save() do 26.7"
    for chave in cfg:
        dinamica = chave in ("samples", "labeling_buttons")
        assert _estrutura(cfg[chave], dinamica) == _estrutura(golden[chave], dinamica), f"estrutura de {chave!r} difere do golden"
    # tipos que o restore exige
    assert isinstance(cfg["thematic_map"]["nodata"], str) and float(cfg["thematic_map"]["nodata"]) == 255
    assert cfg["dialog_size"] is None and isinstance(cfg["fit_to_sample"], float) and isinstance(cfg["is_completed"], bool)
    assert all(isinstance(k, int) for k in cfg["samples"]) and all(isinstance(k, int) for k in cfg["labeling_buttons"])
    for s in cfg["samples"].values():
        assert list(s) == ["label_id", "sample_id"] and isinstance(s["label_id"], int) and isinstance(s["sample_id"], int)


def test_yml_tem_todas_as_chaves_obrigatorias_do_restore(respondido):
    cfg = _cfg_exemplo(respondido)
    faltam = []
    for caminho, ref in OBRIGATORIAS_RESTORE_26_7.items():
        d = cfg
        try:
            for k in caminho:
                d = d[k]
        except KeyError:
            faltam.append((".".join(caminho), ref))
        else:
            assert d is not None or caminho == ("dialog_size",), f"{'.'.join(caminho)} nula ({ref})"
    assert not faltam, f"chaves obrigatórias ausentes: {faltam}"
    # o yml gravado (safe_dump) precisa reler com as mesmas chaves inteiras
    relido = yaml.safe_load(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    assert relido["samples"] == cfg["samples"] and relido["samples_order"] == cfg["samples_order"]


def test_fit_to_sample_por_crs():
    from miradouro.exportacao.acatama import (
        FIT_TO_SAMPLE_GRAUS,
        FIT_TO_SAMPLE_METROS,
        fit_to_sample,
    )

    assert fit_to_sample(None) == FIT_TO_SAMPLE_GRAUS == 0.0011
    assert fit_to_sample("EPSG:4326") == FIT_TO_SAMPLE_GRAUS
    assert fit_to_sample("EPSG:31983") == FIT_TO_SAMPLE_METROS == 120


def test_is_completed_reflete_rotulos(respondido):
    projeto, pontos, arm = respondido
    todas = linhas_referencia(projeto, pontos, arm, apenas_respondidos=False, apenas_completas=False)
    so_completas = linhas_referencia(projeto, pontos, arm)
    ids = {"p1": 1, "p2": 2, "p3": 3}
    kw = dict(mapa="/abs/m.tif", banda=1, nodata=255, camada="/abs/p.geojson", versao_acatama="26.7")
    assert configuracao_acatama(projeto, todas, ids, **kw)["is_completed"] is False
    assert configuracao_acatama(projeto, so_completas, ids, **kw)["is_completed"] is True


def _tif(caminho: Path, nodata):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_origin

    with rasterio.open(caminho, "w", driver="GTiff", width=4, height=4, count=1, dtype="uint8", crs="EPSG:4326", transform=from_origin(-44.5, -19.5, 0.0001, 0.0001), nodata=nodata) as dst:
        dst.write(np.ones((4, 4), dtype="uint8"), 1)
    return caminho


def test_resolver_nodata(tmp_path):
    from miradouro.exportacao.acatama import resolver_nodata

    # raster inexistente: só com --nodata
    with pytest.raises(ErroExportacao, match="--nodata"):
        resolver_nodata(str(tmp_path / "nao_existe.tif"), None)
    assert resolver_nodata(str(tmp_path / "nao_existe.tif"), 0) == (0, [])
    # arquivo que não é raster
    falso = tmp_path / "falso.tif"
    falso.write_bytes(b"nao e um tif")
    with pytest.raises(ErroExportacao, match="--nodata"):
        resolver_nodata(str(falso), None)
    v, avisos = resolver_nodata(str(falso), 0)
    assert v == 0 and any(AVISO_RASTER_ILEGIVEL in a for a in avisos)
    # tag presente: lida do raster; --nodata divergente prevalece com aviso
    com_tag = _tif(tmp_path / "com_tag.tif", 255)
    assert resolver_nodata(str(com_tag), None) == (255, [])
    assert resolver_nodata(str(com_tag), 255) == (255, [])
    v, avisos = resolver_nodata(str(com_tag), 0)
    assert v == 0 and any("difere da tag" in a for a in avisos)
    # sem tag: exige --nodata
    sem_tag = _tif(tmp_path / "sem_tag.tif", None)
    with pytest.raises(ErroExportacao, match="não tem tag nodata"):
        resolver_nodata(str(sem_tag), None)
    v, avisos = resolver_nodata(str(sem_tag), 0)
    assert v == 0 and any("sem tag" in a for a in avisos)


def test_exportar_acatama_caminhos_absolutos_e_nodata_da_tag(respondido, tmp_path):
    projeto, pontos, arm = respondido
    mapa = _tif(tmp_path / "mapa.tif", 255)
    r = exportar_acatama(projeto, pontos, arm, mapa=str(mapa), saida=tmp_path / "exp", nome="t")
    cfg = yaml.safe_load(r.yml.read_text(encoding="utf-8"))
    assert r.nodata == 255 and cfg["thematic_map"]["nodata"] == "255"
    assert cfg["thematic_map"]["path"] == str(mapa.resolve())
    assert cfg["sampling_layer"] == str((tmp_path / "exp" / "t_pontos.geojson").resolve()) and Path(cfg["sampling_layer"]).is_absolute()
    assert Path(cfg["sampling_layer"]).exists()
    for chave in ("dialog_size", "fit_to_sample", "is_completed"):
        assert chave in cfg
