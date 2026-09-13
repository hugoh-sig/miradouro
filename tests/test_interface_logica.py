"""Lógica pura da interface: teclas, filtros, navegação, cegueira, cronômetro."""

from pathlib import Path

import pytest

from miradouro.chips import CacheChips
from miradouro.core import carregar_projeto
from miradouro.core.pontos import Ponto
from miradouro.core.projeto import CondicaoCampo, ErroProjeto, projeto_de_dict
from miradouro.interface import logica as lg

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def paraopeba():
    return carregar_projeto(RAIZ / "exemplos" / "paraopeba" / "projeto.yaml")


# ---- teclas ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "evento, esperado",
    [
        ({"key": "1", "code": "Digit1"}, "1"),
        ({"key": "!", "code": "Digit1", "shift": True}, "shift+1"),  # ABNT2/US: mesmo resultado
        ({"key": "a", "code": "KeyA"}, "a"),
        ({"key": "A", "code": "KeyA", "shift": True}, "shift+a"),
        ({"key": "1", "code": "Numpad1"}, "1"),
        ({"key": "Enter", "code": "Enter"}, "enter"),
        ({"key": "Enter", "code": "NumpadEnter"}, "enter"),
        ({"key": "Enter", "code": "Enter", "shift": True}, "enter"),  # shift não altera ações
        ({"key": "ArrowRight", "code": "ArrowRight"}, "right"),
        ({"key": "ArrowLeft", "code": "ArrowLeft"}, "left"),
        ({"key": "Backspace", "code": "Backspace"}, "backspace"),
        ({"key": "Escape", "code": "Escape"}, "escape"),
        ({"key": "ç", "code": "Semicolon"}, "ç"),
        ({"key": "a", "code": "KeyA", "ctrl": True}, None),  # não sequestra Ctrl/Cmd
        ({"key": "a", "code": "KeyA", "meta": True}, None),
        ({"key": "F5", "code": "F5"}, None),
    ],
)
def test_normalizar_tecla(evento, esperado):
    assert lg.normalizar_tecla(lg.Tecla.de_dict(evento)) == esperado


def test_mapa_de_atalhos_paraopeba(paraopeba):
    mapa, avisos = lg.mapa_de_atalhos(paraopeba)
    assert avisos == []
    for i in range(1, 9):
        assert mapa[str(i)] == lg.Atalho("classe_ref", str(i), paraopeba.classe(i).rotulo)
        assert mapa[f"shift+{i}"].campo == "classe_alternativa" and mapa[f"shift+{i}"].valor == str(i)
    assert mapa["a"] == lg.Atalho("confianca", "alta", "Alta")
    assert mapa["m"].valor == "media" and mapa["b"].valor == "baixa"
    assert mapa["h"] == lg.Atalho("fonte_principal", "hr", "Alta resolução", alternar=True)
    assert mapa["n"].valor == "serie" and mapa["s"].valor == "sazonal" and mapa["s"].alternar
    assert mapa["c"] == lg.Atalho("ano_confirmado_ndvi", "sim", "Sim, confirmada") and mapa["x"].valor == "nao"
    assert not mapa["a"].alternar
    assert lg.tecla_do_valor(mapa, "classe_alternativa", "3") == "shift+3"
    assert lg.rotulo_com_tecla(mapa, "classe_alternativa", "3", "X") == "[⇧3] X"
    assert lg.rotulo_com_tecla(mapa, "confianca", "alta", "Alta") == "[A] Alta"
    assert lg.rotulo_com_tecla(mapa, "observacao", "x", "Obs") == "Obs"


def test_mapa_avisa_conflitos_e_reservadas(dados_projeto):
    dados_projeto["campos"][1]["opcoes"][0]["tecla"] = "1"  # confianca alta = '1' colide com classe 1
    dados_projeto["campos"][1]["opcoes"][1]["tecla"] = "U"  # reservada (desfazer)
    dados_projeto["campos"].append({"nome": "classe_3", "tipo": "classe"})
    mapa, avisos = lg.mapa_de_atalhos(projeto_de_dict(dados_projeto))
    assert mapa["1"].campo == "classe_ref"  # o primeiro vence
    assert "u" not in mapa
    assert any("'1'" in a and "confianca" in a for a in avisos)
    assert any("'U'" in a and "reservada" in a for a in avisos)
    assert any("classe_3" in a and "só mouse" in a for a in avisos)


def test_aplicar_atalho_alterna_multiopcao(paraopeba):
    mapa, _ = lg.mapa_de_atalhos(paraopeba)
    r: dict = {}
    lg.aplicar_atalho(r, mapa["h"])
    assert r == {"fonte_principal": ["hr"]}
    lg.aplicar_atalho(r, mapa["n"])
    assert r["fonte_principal"] == ["hr", "serie"]
    lg.aplicar_atalho(r, mapa["h"])  # desliga
    assert r["fonte_principal"] == ["serie"]
    lg.aplicar_atalho(r, mapa["n"])
    assert r["fonte_principal"] == []
    r["fonte_principal"] = "sazonal"  # rascunho vindo de resposta antiga (string)
    lg.aplicar_atalho(r, mapa["h"])
    assert r["fonte_principal"] == ["sazonal", "hr"]
    lg.aplicar_atalho(r, mapa["2"])  # seleção simples continua substituindo
    lg.aplicar_atalho(r, mapa["3"])
    assert r["classe_ref"] == "3"


def test_interpretar_tecla(paraopeba):
    mapa, _ = lg.mapa_de_atalhos(paraopeba)
    assert lg.interpretar_tecla("enter", mapa) == ("acao", "confirmar")
    assert lg.interpretar_tecla("right", mapa) == ("acao", "proximo")
    assert lg.interpretar_tecla("u", mapa) == ("acao", "desfazer")
    assert lg.interpretar_tecla("2", mapa) == ("atalho", mapa["2"])
    assert lg.interpretar_tecla("z", mapa) is None
    assert lg.interpretar_tecla(None, mapa) is None


# ---- campos condicionais ----------------------------------------------------------


def test_campos_condicionais_aparecem_so_quando_exigidos(paraopeba):
    nomes = lambda r: [c.nome for c in lg.campos_visiveis(paraopeba, r)]  # noqa: E731
    assert nomes({}) == ["classe_ref", "confianca", "fonte_principal", "data_imagem_hr", "observacao"]
    assert "ano_confirmado_ndvi" in nomes({"fonte_principal": ["hr", "serie"]})
    assert "ano_confirmado_ndvi" in nomes({"fonte_principal": "hr"})
    assert "ano_confirmado_ndvi" not in nomes({"fonte_principal": ["serie", "sazonal"]})
    assert "classe_alternativa" in nomes({"confianca": "baixa"})
    assert "classe_alternativa" not in nomes({"confianca": "alta"})


def test_condicionais_ficam_logo_abaixo_do_gatilho(paraopeba, dados_projeto):
    ordem = [c.nome for c in lg.ordem_dos_campos(paraopeba)]
    assert ordem == ["classe_ref", "confianca", "classe_alternativa", "fonte_principal", "ano_confirmado_ndvi", "data_imagem_hr", "observacao"]
    assert [c.nome for c in lg.campos_visiveis(paraopeba, {"confianca": "media", "fonte_principal": ["hr"]})] == ordem
    # Gatilho declarado depois do condicional: o condicional vai para logo após o gatilho mesmo assim.
    dados_projeto["campos"].insert(0, dados_projeto["campos"].pop(3))  # classe_alt (gatilho confianca) vai para o início
    p = projeto_de_dict(dados_projeto)
    ordem2 = [c.nome for c in lg.ordem_dos_campos(p)]
    assert ordem2.index("classe_alt") == ordem2.index("confianca") + 1 and len(ordem2) == len(p.campos)


def test_limpar_valores_ocultos(paraopeba):
    rascunho = {"classe_ref": "1", "confianca": "alta", "fonte_principal": ["serie"], "ano_confirmado_ndvi": "sim", "classe_alternativa": "2", "observacao": "  ", "data_imagem_hr": "", "campo_x": None}
    assert lg.limpar_valores_ocultos(paraopeba, rascunho) == {"classe_ref": "1", "confianca": "alta", "fonte_principal": ["serie"]}
    rascunho.update({"fonte_principal": ("hr", "serie"), "confianca": "baixa", "observacao": " ok ", "data_imagem_hr": "2023-01"})
    assert lg.limpar_valores_ocultos(paraopeba, rascunho) == {
        "classe_ref": "1", "confianca": "baixa", "fonte_principal": ["hr", "serie"], "ano_confirmado_ndvi": "sim",
        "data_imagem_hr": "2023-01", "classe_alternativa": "2", "observacao": "ok",
    }
    assert lg.limpar_valores_ocultos(paraopeba, {"fonte_principal": []}) == {}


def test_formatar_valor_e_campo_do_erro():
    assert lg.formatar_valor(["hr", "serie"]) == "hr+serie" and lg.formatar_valor([]) == "—" and lg.formatar_valor("x") == "x"
    assert lg.campo_do_erro("data_hr: obrigatório quando fonte = hr") == "data_hr"
    assert lg.campo_do_erro("campo desconhecido: 'x'") is None


# ---- filtros e navegação ---------------------------------------------------------------


IDS = ["a", "b", "c", "d", "e"]
RESP = {"b": {"classe_ref": "1", "confianca": "baixa"}, "d": {"classe_ref": "2", "confianca": "alta"}}
COND = CondicaoCampo(campo="confianca", igual_a="baixa")


def test_ordem_visivel():
    assert lg.ordem_visivel(IDS, RESP, "todos") == IDS
    assert lg.ordem_visivel(IDS, RESP, "pendentes") == ["a", "c", "e"]
    assert lg.ordem_visivel(IDS, RESP, "revisao", COND) == ["b"]
    assert lg.ordem_visivel(IDS, RESP, "revisao", None) == []
    with pytest.raises(ValueError):
        lg.ordem_visivel(IDS, RESP, "outro")


def test_lista_de_revisao_esvaziada_apos_gravacao():
    """Item 3 do teste de aceitação: o último ponto em revisão deixa de ter confiança baixa."""
    respostas = {"b": {"classe_ref": "1", "confianca": "baixa"}, "d": {"classe_ref": "2", "confianca": "alta"}}
    ordem = lg.ordem_visivel(IDS, respostas, "revisao", COND)
    assert ordem == ["b"] and lg.posicao(ordem, "b") == (1, 1)
    respostas["b"] = {"classe_ref": "1", "confianca": "alta"}  # gravação na revisão
    ordem = lg.ordem_visivel(IDS, respostas, "revisao", COND)
    assert ordem == []
    assert lg.vizinho(ordem, IDS, "b", +1) is None and "b" not in ordem  # → a interface descarrega o ponto
    assert lg.posicao(ordem, None) == (0, 0)
    # Cronômetro: descarregar pausa a contagem; nada é atribuído a um ponto descarregado.
    t = [0.0]
    cron = lg.Cronometro(relogio=lambda: t[0])
    cron.ir_para("b")
    t[0] = 20.0
    cron.zerar("b")
    cron.ir_para(None)
    t[0] = 60.0
    assert cron.decorrido("b") == 0.0 and cron.decorrido() == 0.0


def test_primeiro_pendente():
    assert lg.primeiro_pendente(IDS, RESP) == "a"
    assert lg.primeiro_pendente(IDS, {"a", "b", "c"}) == "d"
    assert lg.primeiro_pendente(IDS, IDS) is None


def test_vizinho():
    ordem = ["a", "c", "e"]
    assert lg.vizinho(ordem, IDS, "a", +1) == "c" and lg.vizinho(ordem, IDS, "c", -1) == "a"
    assert lg.vizinho(ordem, IDS, "e", +1) is None and lg.vizinho(ordem, IDS, "a", -1) is None
    # 'b' acabou de sair da lista de pendentes: o vizinho é achado pela posição no CSV.
    assert lg.vizinho(ordem, IDS, "b", +1) == "c" and lg.vizinho(ordem, IDS, "b", -1) == "a"
    assert lg.vizinho(ordem, IDS, "d", +1) == "e" and lg.vizinho(ordem, IDS, "d", -1) == "c"
    assert lg.vizinho(ordem, IDS, None, +1) == "a" and lg.vizinho(ordem, IDS, None, -1) == "e"
    assert lg.vizinho([], IDS, "a", +1) is None
    assert lg.vizinho(ordem, IDS, "zz", +1) == "a"
    assert lg.posicao(ordem, "c") == (2, 3) and lg.posicao(ordem, "b") == (0, 3) and lg.posicao(ordem, None) == (0, 3)


def test_condicao_revisao(paraopeba, dados_projeto):
    assert paraopeba.condicao_revisao() == CondicaoCampo(campo="confianca", igual_a="baixa")
    p = projeto_de_dict(dados_projeto)  # sem seção interface: padrão confianca = baixa
    assert p.condicao_revisao().satisfeita("baixa") and not p.condicao_revisao().satisfeita("alta")
    dados_projeto["interface"] = {"revisao": {"campo": "confianca", "diferente_de": "alta"}}
    assert projeto_de_dict(dados_projeto).condicao_revisao().satisfeita("media")
    dados_projeto["interface"] = {"revisao": {"campo": "nao_existe", "igual_a": "x"}}
    with pytest.raises(ErroProjeto, match="interface.revisao"):
        projeto_de_dict(dados_projeto)
    dados_projeto["interface"] = {"revisao": {"campo": "confianca", "igual_a": "zzz"}}
    with pytest.raises(ErroProjeto, match="não existem"):
        projeto_de_dict(dados_projeto)
    dados_projeto.pop("interface")
    dados_projeto["campos"][1]["nome"] = "certeza"
    dados_projeto["campos"][3]["obrigatorio_se"]["campo"] = "certeza"
    assert projeto_de_dict(dados_projeto).condicao_revisao() is None


# ---- cegueira ---------------------------------------------------------------------------


def test_dados_visiveis_nunca_incluem_colunas_ocultas(projeto):
    p = Ponto("p1", -44.1, -19.9, {"classe_mapa": "SEGREDO", "regiao": "norte"})
    dados = lg.dados_visiveis_do_ponto(p, projeto)
    assert dados == {"PLOTID": "p1", "LON": "-44.100000", "LAT": "-19.900000", "regiao": "norte"}
    texto = " ".join(f"{k}={v}" for k, v in dados.items())
    assert lg.contem_dado_oculto(texto, [p], projeto) == []
    assert lg.contem_dado_oculto("… classe_mapa …", [p], projeto) == ["classe_mapa"]
    assert lg.contem_dado_oculto("valor SEGREDO aqui", [p], projeto) == ["classe_mapa=SEGREDO"]


# ---- chips ---------------------------------------------------------------------------------


def test_chips_do_ponto(tmp_path):
    cache = CacheChips(tmp_path)
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    cache.gravar("s2", "7", buf.getvalue())
    chips = lg.chips_do_ponto(cache, ["s2", "esri"], "7")
    assert chips["s2"] == cache.caminho("s2", "7") and chips["esri"] is None
    assert lg.provedores_faltantes(chips) == ["esri"]


# ---- cronômetro e histórico ------------------------------------------------------------------


def test_cronometro_soma_visitas():
    t = [100.0]
    cron = lg.Cronometro(relogio=lambda: t[0])
    assert cron.decorrido() == 0.0
    cron.ir_para("a")
    t[0] = 110.0
    assert cron.decorrido("a") == 10.0
    cron.ir_para("b")
    t[0] = 115.0
    assert cron.decorrido("b") == 5.0 and cron.decorrido("a") == 10.0
    cron.ir_para("a")
    t[0] = 118.0
    assert cron.decorrido("a") == 13.0  # soma as duas visitas
    cron.zerar("a")
    assert cron.decorrido("a") == 0.0
    t[0] = 120.0
    assert cron.decorrido("a") == 2.0
    cron.ir_para(None)
    assert cron.decorrido() == 0.0


def test_formatar_duracao():
    assert lg.formatar_duracao(7.4) == "7s"
    assert lg.formatar_duracao(65) == "1m05s"
    assert lg.formatar_duracao(3700) == "1h01m"


def test_historico():
    h = lg.Historico(limite=2)
    assert h.desempilhar() is None
    h.empurrar("a", None, {"x": 1})
    h.empurrar("b", {"x": 0}, {"x": 2})
    h.empurrar("c", None, {"x": 3})
    assert len(h) == 2
    assert h.desempilhar() == ("c", None, {"x": 3})
    assert h.desempilhar() == ("b", {"x": 0}, {"x": 2})
    assert h.desempilhar() is None
