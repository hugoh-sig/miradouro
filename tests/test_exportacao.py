"""Tabela de referência e exportador AcATaMa (sem QGIS: valida a estrutura do yml/GeoJSON)."""

import csv
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
    cfg = configuracao_acatama(projeto, linhas, ids, mapa="/x/mapa.tif", banda=1, nodata=0, camada="a_pontos.geojson", versao_acatama="26.7")
    assert cfg["general"]["config_file_version"] == "26.7"
    assert cfg["thematic_map"] == {"path": "/x/mapa.tif", "band": 1, "nodata": 0}
    assert cfg["sampling_layer"] == "a_pontos.geojson"
    assert cfg["samples_order"] == [1, 2, 3]
    assert cfg["samples"] == {0: {"sample_id": 1, "label_id": 1}}  # só p1 tem classe
    for chave in ("grid_view_widgets", "current_sample_idx", "sampling_unit_pixel_buffer", "sampling_unit_color", "view_widgets_config", "labeling_buttons"):
        assert chave in cfg


def test_exportar_acatama_arquivos(respondido, tmp_path):
    projeto, pontos, arm = respondido
    mapa = tmp_path / "mapa.tif"
    mapa.write_bytes(b"nao e um tif de verdade")
    r = exportar_acatama(projeto, pontos, arm, mapa=str(mapa), saida=tmp_path / "exp", nome="teste", crs=None)
    assert r.n_pontos == 1 and r.n_rotulados == 1 and r.ids_gerados  # 'p1' não é inteiro → id gerado
    cfg = yaml.safe_load(r.yml.read_text(encoding="utf-8"))
    assert cfg["thematic_map"]["path"] == str(mapa.resolve()) and cfg["sampling_layer"] == "teste_pontos.geojson"
    assert cfg["labeling_buttons"][1]["thematic_class"] == "1" and cfg["samples"] == {0: {"sample_id": 1, "label_id": 1}}
    fc = json.loads(r.geojson.read_text(encoding="utf-8"))
    assert fc["features"][0]["properties"]["id"] == 1 and fc["features"][0]["properties"]["PLOTID"] == "p1"
    with r.csv.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["acatama_id"] == "1" and rows[0]["PLOTID"] == "p1"
    assert any("WGS84" in a for a in r.avisos) and any("sequencial" in a for a in r.avisos)
    with pytest.raises(ErroExportacao, match="nada a exportar"):
        exportar_acatama(projeto, pontos, arm, mapa=str(mapa), saida=tmp_path / "exp2", filtro={"regiao": "sul"})


def test_cli_exportar(respondido, capsys):
    projeto, pontos, arm = respondido
    y = str(projeto.caminho_yaml)
    assert main(["exportar", "acatama", y, "--mapa", "mapa_inexistente.tif", "--versao-acatama", "26.7"]) == CODIGO_OK
    out = capsys.readouterr().out
    assert "1 rotulados de 1 pontos" in out and "não encontrado agora" in out
    exp = projeto.pasta_saida / "exportacao" / "acatama"
    assert (exp / "acatama.yml").exists() and (exp / "acatama_pontos.geojson").exists() and (exp / "acatama_referencia.csv").exists()
    assert yaml.safe_load((exp / "acatama.yml").read_text())["general"]["config_file_version"] == "26.7"

    assert main(["exportar", "csv", y, "--incluir-pendentes", "--nome", "tudo"]) == CODIGO_OK
    assert "3 linhas" in capsys.readouterr().out and (projeto.pasta_saida / "exportacao" / "tudo.csv").exists()
    assert main(["exportar", "csv", y, "--filtro", "coluna_x=1"]) == CODIGO_ERRO
    assert main(["exportar", "acatama", y, "--mapa", "m.tif", "--respostas", str(Path(y).parent / "vazio")]) == CODIGO_ERRO
    assert "não há respostas" in capsys.readouterr().err
