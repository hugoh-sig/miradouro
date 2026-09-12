import pytest

from miradouro.core import ErroPontos, carregar_pontos
from miradouro.core.pontos import pontos_de_texto


def test_carrega_csv_valido(pasta_projeto):
    c = carregar_pontos(pasta_projeto / "pontos.csv")
    assert len(c) == 3
    assert c.ids == ["p1", "p2", "p3"]
    assert c.colunas_extras == ["classe_mapa", "regiao"]
    p = c.obter("p2")
    assert (p.lon, p.lat) == (-44.2, -20.0)
    assert p.extras == {"classe_mapa": "2", "regiao": "sul"}
    assert p.extras_visiveis(["classe_mapa"]) == {"regiao": "sul"}
    assert "p3" in c and "p9" not in c and 1 not in c
    assert [x.plotid for x in c] == c.ids
    assert c.caminho == (pasta_projeto / "pontos.csv").resolve()


def test_cabecalho_em_qualquer_caixa_e_ponto_e_virgula():
    c = pontos_de_texto("plotid;Lon;LAT\n7;-44,5;-19,5\n")
    assert c.obter("7").lon == -44.5 and c.obter("7").lat == -19.5
    assert c.colunas_extras == []


def test_plotid_numerico_vira_texto_e_ignora_linhas_em_branco():
    c = pontos_de_texto("PLOTID,LON,LAT\n1,-44,-19\n\n2,-45,-20\n")
    assert c.ids == ["1", "2"]


def test_bom_utf8(tmp_path):
    f = tmp_path / "p.csv"
    f.write_bytes("﻿PLOTID,LON,LAT\na,-44,-19\n".encode())
    assert carregar_pontos(f).ids == ["a"]


@pytest.mark.parametrize(
    "texto, trecho",
    [
        ("", "vazio"),
        ("PLOTID,LON\n1,-44\n", "obrigatória"),
        ("PLOTID,LON,LAT\n", "sem linhas de dados"),
        ("PLOTID,LON,LAT\n1,-44,-19\n1,-45,-20\n", "PLOTID repetido"),
        ("PLOTID,LON,LAT\n,-44,-19\n", "PLOTID vazio"),
        ("PLOTID,LON,LAT\n1,abc,-19\n", "não é numérico"),
        ("PLOTID,LON,LAT\n1,-200,-19\n", "fora do intervalo"),
        ("PLOTID,LON,LAT\n1,-44,95\n", "fora do intervalo"),
        ("PLOTID,LON,LAT,\n1,-44,-19,x\n", "sem nome"),
    ],
)
def test_csv_invalidos(texto, trecho):
    with pytest.raises(ErroPontos, match=trecho):
        pontos_de_texto(texto)


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(ErroPontos, match="não encontrado"):
        carregar_pontos(tmp_path / "x.csv")
