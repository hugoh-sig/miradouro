"""Cache, registro de provedores, geometria e composição de painéis."""

import io

import pytest
from PIL import Image

from miradouro.chips import (
    CacheChips,
    PedidoChip,
    ProvedorChip,
    geo,
    obter_provedor,
    painel,
    provedores_disponiveis,
    registrar,
)
from miradouro.chips.base import ErroProvedor
from miradouro.chips.cache import nome_seguro


def _png(cor=(10, 20, 30), tam=(4, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", tam, cor).save(buf, format="PNG")
    return buf.getvalue()


# ---- cache -------------------------------------------------------------------


def test_cache_caminho_existe_gravar_listar(tmp_path):
    c = CacheChips(tmp_path / "chips")
    assert c.caminho("prov", "12") == tmp_path / "chips" / "prov" / "12.png"
    assert not c.existe("prov", "12")
    destino = c.gravar("prov", "12", _png())
    assert destino.exists() and c.existe("prov", "12")
    assert c.listar("prov") == [destino] and c.contar("prov") == 1
    assert c.listar("outro") == []
    destino.write_bytes(b"")  # arquivo vazio não conta como cache válido
    assert not c.existe("prov", "12")


def test_cache_versao_embutida_e_invalidacao(tmp_path):
    c = CacheChips(tmp_path)
    c.gravar("prov", "1", _png(), versao="1.0")
    assert c.versao_de("prov", "1") == "1.0"
    assert c.existe("prov", "1") and c.existe("prov", "1", "1.0")
    assert not c.existe("prov", "1", "1.1")  # versão nova → desatualizado
    # O PNG continua sendo uma imagem válida e a versão do pacote também está lá.
    from miradouro import __version__
    from miradouro.chips.cache import CHAVE_PACOTE

    with Image.open(c.caminho("prov", "1")) as im:
        assert im.size == (4, 4) and im.info[CHAVE_PACOTE] == __version__
    # Chip antigo, gravado sem versão, conta como desatualizado para qualquer versão.
    c.gravar("prov", "2", _png())
    assert c.versao_de("prov", "2") is None
    assert c.existe("prov", "2") and not c.existe("prov", "2", "1.0")
    # Regravar troca a versão em vez de acumular.
    c.gravar("prov", "1", c.caminho("prov", "1").read_bytes(), versao="2.0")
    assert c.versao_de("prov", "1") == "2.0"
    # Arquivo ilegível não derruba a consulta.
    c.caminho("prov", "1").write_bytes(b"\x89PNG\r\n\x1a\nlixo")
    assert c.versao_de("prov", "1") is None and c.versao_de("prov", "9") is None


def test_cache_recusa_nao_png(tmp_path):
    c = CacheChips(tmp_path)
    with pytest.raises(ValueError, match="não é PNG"):
        c.gravar("prov", "1", b"<html>erro</html>")
    with pytest.raises(ValueError):
        c.gravar("prov", "1", b"")


@pytest.mark.parametrize("plotid, esperado", [("a b/c", "a_b_c"), ("  12 ", "12"), ("x..y", "x..y"), ("", "_"), ("ç", "_")])
def test_nome_seguro(plotid, esperado):
    assert nome_seguro(plotid) == esperado


# ---- registro ------------------------------------------------------------------


def test_provedores_embutidos_registrados():
    assert {"s2_sazonal", "ndvi_serie", "esri_basemap"} <= set(provedores_disponiveis())
    assert obter_provedor("s2_sazonal").nome == "s2_sazonal"
    with pytest.raises(ErroProvedor, match="desconhecido"):
        obter_provedor("nao_existe")


def test_registrar_exige_nome():
    class SemNome(ProvedorChip):
        def gerar(self, pedido):
            return b""

    with pytest.raises(ErroProvedor, match="nome"):
        registrar(SemNome)


def test_provedor_valida_config_na_construcao():
    @registrar
    class Exigente(ProvedorChip):
        nome = "teste_exigente"

        def validar_config(self):
            if "x" not in self.config:
                raise ErroProvedor("falta x")

        def gerar(self, pedido):
            return _png()

    with pytest.raises(ErroProvedor, match="falta x"):
        Exigente({})
    p = Exigente({"x": 1})
    assert p.config == {"x": 1} and "teste_exigente" in repr(p)
    p.preparar()  # gancho padrão não faz nada
    assert p.gerar(PedidoChip("1", 0.0, 0.0, 2023, p.config))[:4] == b"\x89PNG"


# ---- geometria -------------------------------------------------------------------


def test_utm_epsg():
    assert geo.utm_epsg(-44.2, -19.9) == 32723
    assert geo.utm_epsg(-44.2, 10.0) == 32623
    assert geo.utm_epsg(-48.1, -20.0) == 32722
    assert geo.utm_epsg(179.9, 0.0) == 32660
    assert geo.utm_epsg(-179.9, 0.0) == 32601


def test_para_utm_e_volta():
    x, y, epsg = geo.para_utm(-44.2, -19.9)
    assert epsg == 32723 and 500_000 < x < 700_000 and 7_700_000 < y < 7_900_000
    lon, lat = geo.de_utm(x, y, epsg)
    assert abs(lon + 44.2) < 1e-7 and abs(lat + 19.9) < 1e-7


def test_janela_alinhada_a_grade_de_10m():
    j = geo.janela_pixels(-44.2, -19.9, n=31)
    assert j.n == 31 and j.centro == 15 and j.largura_m == 310
    assert j.x0 % 10 == 0 and j.y_topo % 10 == 0
    assert j.crs == "EPSG:32723"
    assert j.crs_transform == [10.0, 0.0, j.x0, 0.0, -10.0, j.y_topo]
    # O ponto cai dentro do pixel central.
    x, y, _ = geo.para_utm(-44.2, -19.9)
    xmin, ymin, xmax, ymax = j.pixel_alvo_bbox_utm(0)
    assert xmin <= x < xmax and ymin <= y < ymax
    assert (xmax - xmin, ymax - ymin) == (10, 10)
    # Janela 3×3 = 30 m centrada no pixel alvo.
    xmin3, ymin3, xmax3, ymax3 = j.pixel_alvo_bbox_utm(1)
    assert (xmax3 - xmin3, ymax3 - ymin3) == (30, 30)
    assert xmin3 == xmin - 10 and ymax3 == ymax + 10


def test_janela_exige_impar():
    with pytest.raises(ValueError):
        geo.janela_pixels(-44, -19, n=30)
    with pytest.raises(ValueError):
        geo.janela_pixels(-44, -19, n=0)


def test_mercator():
    x, y = geo.lonlat_para_pixel_global(0.0, 0.0, 1)
    assert (x, y) == (256.0, 256.0)
    assert geo.pixel_global_para_tile(300.0, 100.0) == (1, 0)
    assert abs(geo.metros_por_pixel(0.0, 0) - 156543.03) < 0.1
    assert geo.metros_por_pixel(-19.9, 17) < geo.metros_por_pixel(-19.9, 16)
    # Latitudes além do limite do Mercator são grampeadas em vez de explodir.
    _, y = geo.lonlat_para_pixel_global(0.0, 89.9, 1)
    assert 0 <= y <= 512


# ---- painel --------------------------------------------------------------------


def test_marcar_pixel_alvo_desenha_contornos():
    img = Image.new("RGB", (60, 60), (0, 0, 0))
    painel.marcar_pixel_alvo(img, (30, 30), 10, janela=3)
    assert img.getpixel((30, 25)) == painel.COR_ALVO  # borda superior do pixel alvo
    assert img.getpixel((30, 15)) == painel.COR_JANELA  # borda superior da janela
    assert img.getpixel((30, 30)) == (0, 0, 0)  # centro NÃO é preenchido


def test_compor_grade_e_rotulos():
    tiles = [painel.rotular(Image.new("RGB", (50, 40), (i * 40, 0, 0)), ["linha 1", "linha 2"]) for i in range(3)]
    g = painel.compor_grade(tiles, colunas=2, titulo="T", subtitulo="S", rodape=["a", "b"])
    assert g.width == painel.MARGEM * 2 + 2 * 50 + 8
    assert g.height > 2 * 40 + 8
    assert painel.para_png(g)[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(ValueError):
        painel.compor_grade([], colunas=1, titulo="x")


def test_ampliar_barra_escala_tile_de_erro():
    im = painel.ampliar(Image.new("RGB", (3, 3)), 4)
    assert im.size == (12, 12)
    assert painel.ampliar(im, 1) is im
    painel.barra_escala(im, 1.0)
    painel.barra_escala(Image.new("RGB", (400, 400)), 0.3, metros=50)
    painel.barra_escala(Image.new("RGB", (400, 400)), 1000.0)
    assert painel.tile_de_erro(100, 50, "x").size == (100, 50)
