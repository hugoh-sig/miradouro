"""Motor de lote: cache, tolerância a falha, paralelismo, log de erros."""

import io

import pytest
from PIL import Image

from miradouro.chips import CacheChips, ProvedorChip, gerar_chips, instanciar_provedores, registrar
from miradouro.chips.base import ErroProvedor
from miradouro.chips.motor import NOME_LOG_ERROS
from miradouro.core import carregar_pontos


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


@registrar
class ProvedorFalso(ProvedorChip):
    nome = "falso"
    descricao = "provedor de teste"

    chamadas: list[str] = []
    preparado = 0

    def preparar(self):
        type(self).preparado += 1

    def gerar(self, pedido):
        type(self).chamadas.append(pedido.plotid)
        if pedido.plotid in self.config.get("falhar", []):
            raise RuntimeError("boom")
        if pedido.plotid in self.config.get("lixo", []):
            return b"nao e png"
        return _png()


@registrar
class ProvedorFalso2(ProvedorFalso):
    nome = "falso2"


@pytest.fixture(autouse=True)
def _limpar():
    ProvedorFalso.chamadas = []
    ProvedorFalso.preparado = 0
    ProvedorFalso2.chamadas = []
    ProvedorFalso2.preparado = 0


def test_instanciar_provedores(dados_projeto, projeto_sem_arquivo):
    projeto_sem_arquivo.chips.provedores = {"falso": {"a": 1}, "falso2": {}}
    provs = instanciar_provedores(projeto_sem_arquivo)
    assert [p.nome for p in provs] == ["falso", "falso2"] and provs[0].config == {"a": 1}
    assert [p.nome for p in instanciar_provedores(projeto_sem_arquivo, apenas=["falso2"])] == ["falso2"]
    with pytest.raises(ErroProvedor, match="não habilitado"):
        instanciar_provedores(projeto_sem_arquivo, apenas=["esri_basemap"])
    projeto_sem_arquivo.chips.provedores = {"inexistente": {}}
    with pytest.raises(ErroProvedor, match="desconhecido"):
        instanciar_provedores(projeto_sem_arquivo)


def test_lote_gera_usa_cache_e_forca(projeto, tmp_path):
    pontos = carregar_pontos(projeto.caminho_pontos)
    cache = CacheChips(tmp_path / "chips")
    prov = ProvedorFalso({})
    progresso = []
    r = gerar_chips(projeto, pontos, [prov], cache, progresso=lambda f, t: progresso.append((f, t)))
    assert (r.gerados, r.em_cache, r.falhas) == (3, 0, [])
    assert r.total == 3 and "3 gerados" in r.resumo()
    assert ProvedorFalso.preparado == 1
    assert sorted(ProvedorFalso.chamadas) == ["p1", "p2", "p3"]
    assert progresso[0] == (0, 3) and progresso[-1] == (3, 3)
    assert cache.contar("falso") == 3

    r2 = gerar_chips(projeto, pontos, [prov], cache)
    assert (r2.gerados, r2.em_cache) == (0, 3) and len(ProvedorFalso.chamadas) == 3

    r3 = gerar_chips(projeto, pontos, [prov], cache, forcar=True)
    assert (r3.gerados, r3.em_cache) == (3, 0)


def test_lote_regera_chips_de_versao_antiga(projeto, tmp_path):
    pontos = carregar_pontos(projeto.caminho_pontos)
    cache = CacheChips(tmp_path / "chips")
    gerar_chips(projeto, pontos, [ProvedorFalso({})], cache)
    assert all(cache.versao_de("falso", i) == ProvedorFalso.versao for i in pontos.ids)

    class FalsoV2(ProvedorFalso):
        versao = "2"

    ProvedorFalso.chamadas = []
    r = gerar_chips(projeto, pontos, [FalsoV2({})], cache)
    assert (r.gerados, r.desatualizados, r.em_cache) == (3, 3, 0)
    assert "3 regerados por versão nova" in r.resumo()
    assert sorted(ProvedorFalso.chamadas) == ["p1", "p2", "p3"]
    assert all(cache.versao_de("falso", i) == "2" for i in pontos.ids)
    r2 = gerar_chips(projeto, pontos, [FalsoV2({})], cache)
    assert (r2.gerados, r2.desatualizados, r2.em_cache) == (0, 0, 3)


def test_lote_tolera_falhas_e_registra(projeto, tmp_path):
    pontos = carregar_pontos(projeto.caminho_pontos)
    cache = CacheChips(tmp_path / "chips")
    prov = ProvedorFalso({"falhar": ["p2"], "lixo": ["p3"]})
    r = gerar_chips(projeto, pontos, [prov], cache)
    assert r.gerados == 1 and len(r.falhas) == 2
    por_id = {f.plotid: f for f in r.falhas}
    assert por_id["p2"].erro.startswith("RuntimeError: boom") and por_id["p2"].provedor == "falso"
    assert "não é PNG" in por_id["p3"].erro
    log = (cache.pasta / NOME_LOG_ERROS).read_text(encoding="utf-8").splitlines()
    assert len(log) == 2 and all("\tfalso\t" in linha for linha in log)
    assert cache.existe("falso", "p1") and not cache.existe("falso", "p2") and not cache.existe("falso", "p3")

    # Segunda rodada: só os que falharam são tentados de novo.
    ProvedorFalso.chamadas = []
    r2 = gerar_chips(projeto, pontos, [ProvedorFalso({})], cache)
    assert sorted(ProvedorFalso.chamadas) == ["p2", "p3"] and r2.em_cache == 1 and r2.gerados == 2


def test_lote_paralelo_e_varios_provedores(projeto, tmp_path):
    pontos = carregar_pontos(projeto.caminho_pontos)
    cache = CacheChips(tmp_path / "chips")
    r = gerar_chips(projeto, pontos, [ProvedorFalso({"falhar": ["p1"]}), ProvedorFalso2({})], cache, paralelo=3)
    assert r.gerados == 5 and len(r.falhas) == 1 and r.total == 6
    assert cache.contar("falso") == 2 and cache.contar("falso2") == 3


def test_falha_em_preparar_propaga(projeto, tmp_path):
    class Quebrado(ProvedorFalso):
        nome = "quebrado"

        def preparar(self):
            raise ErroProvedor("sem credencial")

    with pytest.raises(ErroProvedor, match="sem credencial"):
        gerar_chips(projeto, carregar_pontos(projeto.caminho_pontos), [Quebrado({})], CacheChips(tmp_path))


def test_cache_padrao_na_pasta_do_projeto(projeto):
    pontos = carregar_pontos(projeto.caminho_pontos)
    gerar_chips(projeto, pontos, [ProvedorFalso({})])
    assert (projeto.pasta_chips / "falso" / "p1.png").exists()
