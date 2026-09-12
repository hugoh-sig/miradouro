"""Provedores reais com os acessos de rede substituídos (sem GEE, sem HTTP)."""

import io
import json
from datetime import date

import pytest
from PIL import Image

from miradouro.chips import PedidoChip
from miradouro.chips.base import ErroProvedor
from miradouro.chips.provedores import esri_basemap, ndvi_serie, s2_sazonal
from miradouro.chips.provedores.ndvi_serie import agregar_por_dia, desenhar_serie, mediana_movel
from miradouro.chips.provedores.s2_sazonal import resolver_data

PEDIDO = PedidoChip(plotid="42", lon=-44.2, lat=-19.9, ano_referencia=2023, config={})


def _png(tam, cor=(90, 120, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", tam, cor).save(buf, format="PNG")
    return buf.getvalue()


def _abrir(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def _png_textura(tam=(256, 256), semente=1) -> bytes:
    """Tile 'de imagem real': ruído determinístico, nenhuma cor dominante."""
    import random

    rnd = random.Random(semente)
    im = Image.new("RGB", tam)
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(tam[0] * tam[1])])
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _png_placeholder(tam=(256, 256)) -> bytes:
    """Imita o tile 'Map data not yet available': cinza com um pouco de texto."""
    from PIL import ImageDraw

    im = Image.new("RGB", tam, (204, 204, 204))
    d = ImageDraw.Draw(im)
    d.text((40, 120), "Map data not yet available", fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ---- s2_sazonal -------------------------------------------------------------------


def test_resolver_data():
    assert resolver_data("2022-11-01", 2023) == date(2022, 11, 1)
    assert resolver_data("05-01", 2023) == date(2023, 5, 1)
    assert resolver_data(date(2020, 1, 2), 2023) == date(2020, 1, 2)
    with pytest.raises(ErroProvedor):
        resolver_data("maio", 2023)


@pytest.mark.parametrize(
    "cfg, trecho",
    [
        ({"janela_pixels": 30}, "ímpar"),
        ({"ampliacao": 0}, "ampliacao"),
        ({"estacoes": []}, "estacoes"),
        ({"estacoes": [{"nome": "x"}]}, "inicio"),
        ({"estacoes": [{"nome": "x", "inicio": "hoje", "fim": "01-01"}]}, "data inválida"),
        ({"composicoes": [{"bandas": ["B4"]}]}, "3 bandas"),
    ],
)
def test_s2_config_invalida(cfg, trecho):
    with pytest.raises(ErroProvedor, match=trecho):
        s2_sazonal.ProvedorS2Sazonal(cfg)


def test_s2_config_padrao_completada():
    p = s2_sazonal.ProvedorS2Sazonal({"composicoes": [{"bandas": ["B8", "B4", "B3"]}]})
    assert p.config["janela_pixels"] == 31 and p.config["composicoes"][0]["nome"] == "B8-B4-B3"


def test_s2_gera_painel(monkeypatch):
    p = s2_sazonal.ProvedorS2Sazonal({"janela_pixels": 11, "ampliacao": 4})
    pedidos = []

    def composicao(pedido, inicio, fim):
        pedidos.append((inicio, fim))
        return (None, 0) if inicio.month == 1 else ("IMG", 7)

    monkeypatch.setattr(p, "_composicao_estacao", composicao)
    monkeypatch.setattr(p, "_baixar_tile", lambda img, comp, janela: _png((janela.n, janela.n)))
    png = p.gerar(PEDIDO)
    im = _abrir(png)
    assert im.format == "PNG" and im.width > 2 * 44 and im.height > 2 * 44
    # Estações padrão relativas ao ano de referência (seca e chuvosa).
    assert pedidos == [(date(2023, 5, 1), date(2023, 9, 30)), (date(2023, 1, 1), date(2023, 3, 31))]


def test_s2_tamanho_inesperado_falha(monkeypatch):
    p = s2_sazonal.ProvedorS2Sazonal({"janela_pixels": 11})
    monkeypatch.setattr(p, "_composicao_estacao", lambda *a: ("IMG", 1))
    monkeypatch.setattr(p, "_baixar_tile", lambda *a: _png((5, 5)))
    with pytest.raises(RuntimeError, match="tamanho inesperado"):
        p.gerar(PEDIDO)


def test_s2_baixar_tile_usa_thumb_url(monkeypatch):
    from miradouro.chips.geo import janela_pixels

    p = s2_sazonal.ProvedorS2Sazonal({})
    params = {}

    class ImagemFalsa:
        def getThumbURL(self, kw):
            params.update(kw)
            return "http://x"

    monkeypatch.setattr(s2_sazonal, "baixar_bytes", lambda url: b"bytes")
    j = janela_pixels(-44.2, -19.9, n=31)
    assert p._baixar_tile(ImagemFalsa(), p.config["composicoes"][1], j) == b"bytes"
    assert params["bands"] == ["B8", "B4", "B3"] and params["crs"] == "EPSG:32723"
    assert params["dimensions"] == [31, 31] and params["crs_transform"] == j.crs_transform


# ---- ndvi_serie -------------------------------------------------------------------


def test_agregar_e_mediana():
    obs = [(date(2023, 1, 2), 0.2), (date(2023, 1, 2), 0.4), (date(2023, 1, 1), 0.9)]
    agregado = agregar_por_dia(obs)
    assert [d for d, _ in agregado] == [date(2023, 1, 1), date(2023, 1, 2)]
    assert [v for _, v in agregado] == pytest.approx([0.9, 0.3])
    assert mediana_movel([1, 9, 2, 8, 3], 3) == [5, 2, 8, 3, 5.5]
    assert mediana_movel([1, 2], 3) == [1, 2] and mediana_movel([4, 5], 1) == [4, 5]


def test_desenhar_serie_com_e_sem_dados():
    obs = [(date(2019 + i // 30, 1 + (i % 12), 1 + (i % 27)), 0.1 + 0.6 * ((i % 7) / 7)) for i in range(120)]
    png = desenhar_serie(obs, plotid="x", lon=-44.2, lat=-19.9, ano_referencia=2023, ano_inicio=2019, ano_fim=2025, largura_px=600, altura_px=200)
    im = _abrir(png)
    assert im.size == (600, 200)
    png2 = desenhar_serie([], plotid="x", lon=0, lat=0, ano_referencia=2023, ano_inicio=2020, ano_fim=2024)
    assert _abrir(png2).size == (1100, 360)


@pytest.mark.parametrize("cfg, trecho", [({"ano_inicio": "2019"}, "inteiro"), ({"ano_inicio": 2025, "ano_fim": 2019}, "maior"), ({"janela_mediana": 0}, "janela_mediana")])
def test_ndvi_config_invalida(cfg, trecho):
    with pytest.raises(ErroProvedor, match=trecho):
        ndvi_serie.ProvedorNdviSerie(cfg)


def test_ndvi_periodo_padrao_e_gerar(monkeypatch):
    p = ndvi_serie.ProvedorNdviSerie({})
    assert p.periodo(2023) == (2020, 2024)
    p2 = ndvi_serie.ProvedorNdviSerie({"ano_inicio": 2019, "ano_fim": 2025})
    assert p2.periodo(2023) == (2019, 2025)
    monkeypatch.setattr(p2, "_obter_serie", lambda pedido, a0, a1: [(date(a0, 6, 1), 0.5), (date(a1, 6, 1), 0.7)])
    assert _abrir(p2.gerar(PEDIDO)).size == (1100, 360)


def test_ndvi_obter_serie_converte_tabela(monkeypatch):
    """Simula o `ee` só o suficiente para exercer a conversão da tabela do getRegion."""
    import sys
    import types

    tabela = [
        ["id", "longitude", "latitude", "time", "ndvi"],
        ["a", -44.2, -19.9, 1672531200000, 0.5],  # 2023-01-01
        ["b", -44.2, -19.9, 1672617600000, None],  # mascarado
    ]

    class Cadeia:
        def __getattr__(self, nome):
            return lambda *a, **k: self

        def getInfo(self):
            return tabela

    ee_falso = types.SimpleNamespace(
        Geometry=types.SimpleNamespace(Point=lambda *a: "pt"),
        ImageCollection=lambda nome: Cadeia(),
        Filter=types.SimpleNamespace(lte=lambda *a: None),
    )
    monkeypatch.setitem(sys.modules, "ee", ee_falso)
    p = ndvi_serie.ProvedorNdviSerie({})
    assert p._obter_serie(PEDIDO, 2023, 2023) == [(date(2023, 1, 1), 0.5)]


# ---- esri_basemap ------------------------------------------------------------------


@pytest.mark.parametrize("cfg, trecho", [({"zooms": []}, "zooms"), ({"zooms": [30]}, "zooms"), ({"tamanho_px": 10}, "tamanho_px"), ({"atribuicao": " "}, "atribuicao"), ({"zoom_minimo": -1}, "zoom_minimo")])
def test_esri_config_invalida(cfg, trecho):
    with pytest.raises(ErroProvedor, match=trecho):
        esri_basemap.ProvedorEsriBasemap(cfg)


def test_esri_gera_painel_com_recuo_de_zoom(monkeypatch):
    p = esri_basemap.ProvedorEsriBasemap({"zooms": [16, 19], "tamanho_px": 300, "zoom_minimo": 15})
    baixados = []

    def tile(z, x, y):
        baixados.append((z, x, y))
        return _png_textura(semente=z)

    monkeypatch.setattr(p, "_baixar_tile", tile)
    monkeypatch.setattr(p, "_tile_existe", lambda z, x, y: z <= 17)
    png = p.gerar(PEDIDO)
    im = _abrir(png)
    assert im.format == "PNG" and im.width > 600
    zooms = {z for z, _, _ in baixados}
    assert zooms == {16, 17}  # 19 recuou até 17
    assert all(1 <= len([t for t in baixados if t[0] == z]) <= 9 for z in zooms)


def test_esri_zoom_disponivel_para_no_minimo(monkeypatch):
    p = esri_basemap.ProvedorEsriBasemap({"zoom_minimo": 12})
    monkeypatch.setattr(p, "_tile_existe", lambda z, x, y: False)
    assert p.zoom_disponivel(-44.2, -19.9, 19) == 12
    p2 = esri_basemap.ProvedorEsriBasemap({"tilemap_url": None})
    assert p2.zoom_disponivel(-44.2, -19.9, 19) == 19  # sem tilemap, confia no pedido


def test_esri_tile_existe_interpreta_json(monkeypatch):
    p = esri_basemap.ProvedorEsriBasemap({})
    p.preparar()

    class Resp:
        def __init__(self, dados):
            self._d = dados

        def raise_for_status(self):
            pass

        def json(self):
            return json.loads(self._d)

    respostas = iter(['{"data":[1]}', '{"data":[0]}', "não json"])
    monkeypatch.setattr(p._sessao, "get", lambda url, timeout: Resp(next(respostas)))
    assert p._tile_existe(17, 1, 1) is True
    assert p._tile_existe(17, 1, 1) is False
    assert p._tile_existe(17, 1, 1) is True  # erro → assume que existe


def test_esri_baixar_tile_tenta_de_novo(monkeypatch):
    p = esri_basemap.ProvedorEsriBasemap({"tentativas": 2, "timeout": 1})
    p.preparar()
    monkeypatch.setattr(esri_basemap.time, "sleep", lambda s: None)
    chamadas = []

    def get(url, timeout):
        chamadas.append(url)
        raise OSError("rede")

    monkeypatch.setattr(p._sessao, "get", get)
    with pytest.raises(RuntimeError, match="indisponível"):
        p._baixar_tile(17, 5, 6)
    assert len(chamadas) == 2 and chamadas[0].endswith("/17/6/5")


def test_tile_e_placeholder():
    from miradouro.chips.provedores.esri_basemap import HASHES_PLACEHOLDER, tile_e_placeholder

    assert tile_e_placeholder(_png_placeholder()) is True
    assert tile_e_placeholder(_png((256, 256), (128, 128, 128))) is True  # totalmente uniforme
    assert tile_e_placeholder(_png_textura()) is False
    # Água lisa: metade dos pixels numa cor, o resto em tons próximos — NÃO é placeholder.
    im = Image.new("RGB", (256, 256), (20, 40, 60))
    px = im.load()
    for y in range(128):
        for x in range(256):
            px[x, y] = (20 + (x % 3), 40, 60 + (y % 2))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    assert tile_e_placeholder(buf.getvalue()) is False
    # Caminho por hash: o tile padrão conhecido é reconhecido pelos bytes.
    import hashlib

    real = _png_textura(semente=99)
    assert tile_e_placeholder(real) is False
    HASHES_PLACEHOLDER_NOVO = HASHES_PLACEHOLDER | {hashlib.md5(real).hexdigest()}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(esri_basemap, "HASHES_PLACEHOLDER", HASHES_PLACEHOLDER_NOVO)
        assert tile_e_placeholder(real) is True


def test_esri_recua_quando_servico_serve_placeholder(monkeypatch):
    """O tilemap diz que o tile existe, mas o servidor entrega o placeholder cinza."""
    p = esri_basemap.ProvedorEsriBasemap({"zooms": [19], "tamanho_px": 300, "zoom_minimo": 15})
    monkeypatch.setattr(p, "_tile_existe", lambda z, x, y: True)
    baixados = []

    def tile(z, x, y):
        baixados.append(z)
        return _png_placeholder() if z >= 18 else _png_textura(semente=z)

    monkeypatch.setattr(p, "_baixar_tile", tile)
    png = p.gerar(PEDIDO)
    assert _abrir(png).format == "PNG"
    assert 19 in baixados and 18 in baixados and 17 in baixados and min(baixados) == 17


def test_esri_no_zoom_minimo_aceita_placeholder(monkeypatch):
    p = esri_basemap.ProvedorEsriBasemap({"zooms": [17], "tamanho_px": 300, "zoom_minimo": 16})
    monkeypatch.setattr(p, "_tile_existe", lambda z, x, y: True)
    monkeypatch.setattr(p, "_baixar_tile", lambda z, x, y: _png_placeholder())
    assert _abrir(p.gerar(PEDIDO)).format == "PNG"  # não entra em loop nem levanta


def test_versoes_dos_provedores_definidas():
    assert s2_sazonal.ProvedorS2Sazonal.versao == "1.1"
    assert esri_basemap.ProvedorEsriBasemap.versao == "1.1"
    assert ndvi_serie.ProvedorNdviSerie.versao == "1.0"
