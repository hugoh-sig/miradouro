from pathlib import Path

import pytest
import yaml

from miradouro.core import ErroProjeto, carregar_projeto, normalizar_valores, validar_resposta
from miradouro.core.projeto import CondicaoCampo, projeto_de_dict


def test_carrega_projeto_valido(projeto, pasta_projeto):
    assert projeto.nome == "Teste"
    assert projeto.ano_referencia == 2023
    assert [c.codigo for c in projeto.legenda] == ["1", "2", "6"]
    assert projeto.classe(6).rotulo == "Água"
    assert projeto.classe(1).rotulo == "floresta"  # rótulo assume o nome
    assert projeto.classe(6).cor == "#4575b4"  # cor normalizada em minúsculas
    assert projeto.classe_por_tecla("A") is None
    assert projeto.classe_por_tecla("2").nome == "pasto"
    assert projeto.campo("fonte").opcoes[1].valor == "serie"
    assert projeto.campo("fonte").opcoes[1].rotulo == "serie"
    assert projeto.caminho_yaml == (pasta_projeto / "projeto.yaml").resolve()
    assert projeto.caminho_pontos == (pasta_projeto / "pontos.csv").resolve()
    assert projeto.pasta_chips == (pasta_projeto / "chips").resolve()
    assert projeto.pasta_saida == (pasta_projeto / "respostas").resolve()
    assert projeto.colunas_ocultas == {"classe_mapa"}
    assert len(projeto.hash_yaml) == 64
    assert [c.nome for c in projeto.campos_obrigatorios] == ["classe_ref", "confianca"]
    assert projeto.campo("classe_alt").condicional


def test_hash_muda_com_conteudo(pasta_projeto):
    h1 = carregar_projeto(pasta_projeto / "projeto.yaml").hash_yaml
    (pasta_projeto / "projeto.yaml").write_text(
        (pasta_projeto / "projeto.yaml").read_text() + "\n# comentário\n"
    )
    h2 = carregar_projeto(pasta_projeto / "projeto.yaml").hash_yaml
    assert h1 != h2


def test_caminho_absoluto_respeitado(dados_projeto, tmp_path):
    dados_projeto["pontos"]["arquivo"] = str(tmp_path / "x.csv")
    p = projeto_de_dict(dados_projeto)
    assert p.caminho_pontos == tmp_path / "x.csv"


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(ErroProjeto, match="não encontrado"):
        carregar_projeto(tmp_path / "nao_existe.yaml")


def test_yaml_malformado(tmp_path):
    (tmp_path / "p.yaml").write_text("nome: [abc\n")
    with pytest.raises(ErroProjeto, match="malformado"):
        carregar_projeto(tmp_path / "p.yaml")


def test_yaml_vazio(tmp_path):
    (tmp_path / "p.yaml").write_text("")
    with pytest.raises(ErroProjeto, match="vazio"):
        carregar_projeto(tmp_path / "p.yaml")


def test_yaml_nao_mapeamento(tmp_path):
    (tmp_path / "p.yaml").write_text("- a\n- b\n")
    with pytest.raises(ErroProjeto, match="mapeamento"):
        carregar_projeto(tmp_path / "p.yaml")


@pytest.mark.parametrize(
    "alteracao, trecho",
    [
        (lambda d: d.pop("legenda"), "legenda"),
        (lambda d: d.__setitem__("legenda", []), "legenda"),
        (lambda d: d.pop("campos"), "campos"),
        (lambda d: d.__setitem__("ano_referencia", "dois mil"), "ano_referencia"),
        (lambda d: d.__setitem__("chave_inexistente", 1), "chave_inexistente"),
        (lambda d: d["legenda"][1].__setitem__("codigo", 1), "códigos da legenda repetidos"),
        (lambda d: d["legenda"][1].__setitem__("nome", "floresta"), "nomes da legenda repetidos"),
        (lambda d: d["legenda"][1].__setitem__("tecla", "1"), "teclas da legenda repetidos"),
        (lambda d: d["legenda"][0].__setitem__("tecla", "12"), "exatamente um caractere"),
        (lambda d: d["legenda"][0].__setitem__("cor", "verde"), "#rrggbb"),
        (lambda d: d["legenda"][0].pop("tecla"), "tecla"),
        (lambda d: d["campos"][0].__setitem__("tipo", "lista"), "tipo"),
        (lambda d: d["campos"][0].__setitem__("nome", "Classe Ref"), "nome de campo inválido"),
        (lambda d: d["campos"][0].__setitem__("nome", "plotid"), "reservado"),
        (lambda d: d["campos"][4].__setitem__("nome", "classe_ref"), "nomes dos campos repetidos"),
        (lambda d: d["campos"][1].__setitem__("opcoes", []), "precisa de `opcoes`"),
        (lambda d: d["campos"][0].__setitem__("opcoes", ["a"]), "não aceita `opcoes`"),
        (lambda d: d["campos"][1]["opcoes"].append({"valor": "alta"}), "valores do campo 'confianca' repetidos"),
        (lambda d: d["campos"][1]["opcoes"].append({"valor": "x", "tecla": "a"}), "teclas do campo 'confianca' repetidos"),
        (lambda d: d["campos"][3].__setitem__("obrigatorio_se", {"campo": "nao_existe", "igual_a": "x"}), "inexistente"),
        (lambda d: d["campos"][3].__setitem__("obrigatorio_se", {"campo": "confianca", "igual_a": "altissima"}), "não existem"),
        (lambda d: d["campos"][3].__setitem__("obrigatorio_se", {"campo": "classe_alt", "igual_a": "1"}), "a si mesmo"),
        (lambda d: d["campos"][3].__setitem__("obrigatorio_se", {"campo": "confianca"}), "exatamente um"),
        (lambda d: d["campos"][3].update({"obrigatorio": True}), "excludentes"),
        (lambda d: d["saida"].__setitem__("backups", -1), "backups"),
    ],
)
def test_projetos_invalidos(dados_projeto, alteracao, trecho):
    alteracao(dados_projeto)
    with pytest.raises(ErroProjeto) as exc:
        projeto_de_dict(dados_projeto)
    assert trecho in str(exc.value)


def test_multiopcao_validacao_e_normalizacao(projeto):
    base = {"classe_ref": "1", "confianca": "alta"}
    assert validar_resposta(projeto, {**base, "fonte": ["hr", "serie"]}) == []
    assert validar_resposta(projeto, {**base, "fonte": "hr"}) == []  # string antiga é aceita
    assert validar_resposta(projeto, {**base, "fonte": []}) == []  # opcional
    assert validar_resposta(projeto, {**base, "fonte": ["hr", "hr"]}) == ["fonte: valores repetidos"]
    assert validar_resposta(projeto, {**base, "fonte": ["hr", "x", "y"]}) == ["fonte: opção inválida ['x', 'y']"]
    assert normalizar_valores(projeto, {"fonte": "hr", "classe_ref": "1"}) == {"fonte": ["hr"], "classe_ref": "1"}
    assert normalizar_valores(projeto, {"fonte": "", "outro": 3}) == {"fonte": [], "outro": 3}
    assert normalizar_valores(projeto, {"fonte": ("hr", "serie")}) == {"fonte": ["hr", "serie"]}


def test_multiopcao_obrigatorio_e_condicao_de_conjunto(dados_projeto):
    dados_projeto["campos"][2]["obrigatorio"] = True
    dados_projeto["campos"].append({"nome": "conf_ndvi", "tipo": "opcao", "opcoes": ["sim", "nao"], "obrigatorio_se": {"campo": "fonte", "igual_a": "hr"}})
    p = projeto_de_dict(dados_projeto)
    base = {"classe_ref": "1", "confianca": "alta"}
    assert validar_resposta(p, {**base, "fonte": []}) == ["fonte: obrigatório"]
    assert validar_resposta(p, {**base, "fonte": ["serie"]}) == []
    assert validar_resposta(p, {**base, "fonte": ["serie", "hr"]}) == ["conf_ndvi: obrigatório quando fonte = hr"]
    assert validar_resposta(p, {**base, "fonte": ["hr"], "conf_ndvi": "sim"}) == []
    cond = CondicaoCampo(campo="fonte", diferente_de="hr")
    assert cond.satisfeita(["serie"]) and not cond.satisfeita(["serie", "hr"]) and not cond.satisfeita([])
    cond2 = CondicaoCampo(campo="fonte", igual_a=["hr", "sazonal"])
    assert cond2.satisfeita(["sazonal"]) and not cond2.satisfeita(["serie"])


def test_multiopcao_precisa_de_opcoes(dados_projeto):
    dados_projeto["campos"][2]["opcoes"] = []
    with pytest.raises(ErroProjeto, match="precisa de `opcoes`"):
        projeto_de_dict(dados_projeto)


def test_padrao_de_texto(dados_projeto):
    dados_projeto["campos"].append({"nome": "data_hr", "tipo": "texto", "padrao": r"[0-9]{4}-(0[1-9]|1[0-2])"})
    p = projeto_de_dict(dados_projeto)
    base = {"classe_ref": "1", "confianca": "alta"}
    assert validar_resposta(p, {**base, "data_hr": "2023-07"}) == []
    assert validar_resposta(p, {**base, "data_hr": " 2023-12 "}) == []
    assert validar_resposta(p, {**base}) == []  # opcional e vazio
    erros = validar_resposta(p, {**base, "data_hr": "07/2023"})
    assert erros == ["data_hr: '07/2023' não segue o formato esperado ([0-9]{4}-(0[1-9]|1[0-2]))"]
    assert validar_resposta(p, {**base, "data_hr": "2023-13"}) != []
    assert validar_resposta(p, {**base, "data_hr": "x2023-07"}) != []


@pytest.mark.parametrize(
    "campo, trecho",
    [
        ({"nome": "n", "tipo": "numero", "padrao": "x"}, "só se aplica"),
        ({"nome": "t", "tipo": "texto", "padrao": "("}, "regex válida"),
    ],
)
def test_padrao_invalido(dados_projeto, campo, trecho):
    dados_projeto["campos"].append(campo)
    with pytest.raises(ErroProjeto, match=trecho):
        projeto_de_dict(dados_projeto)


def test_condicao_igual_a_lista(dados_projeto):
    dados_projeto["campos"][3]["obrigatorio_se"] = {"campo": "confianca", "igual_a": ["media", "baixa"]}
    p = projeto_de_dict(dados_projeto)
    cond = p.campo("classe_alt").obrigatorio_se
    assert cond.satisfeita("media") and cond.satisfeita("baixa") and not cond.satisfeita("alta")
    assert not cond.satisfeita(None)


def test_provedores_config_nula_vira_dict(dados_projeto):
    dados_projeto["chips"]["provedores"] = {"a": None, "b": {"x": 1}}
    p = projeto_de_dict(dados_projeto)
    assert p.chips.provedores == {"a": {}, "b": {"x": 1}}
    assert p.provedores_habilitados() == ["a", "b"]


def test_padroes_chips_e_saida(dados_projeto):
    dados_projeto.pop("chips")
    dados_projeto.pop("saida")
    p = projeto_de_dict(dados_projeto)
    assert p.chips.pasta == Path("chips") and p.saida.backups == 10


# ---- validar_resposta ---------------------------------------------------------


def test_resposta_valida(projeto):
    assert validar_resposta(projeto, {"classe_ref": "1", "confianca": "alta"}) == []
    assert validar_resposta(projeto, {"classe_ref": 6, "confianca": "media", "classe_alt": 2}) == []


def test_resposta_obrigatorios_ausentes(projeto):
    erros = validar_resposta(projeto, {})
    assert "classe_ref: obrigatório" in erros
    assert "confianca: obrigatório" in erros
    assert len(erros) == 2


def test_resposta_vazio_conta_como_ausente(projeto):
    erros = validar_resposta(projeto, {"classe_ref": "  ", "confianca": None})
    assert len(erros) == 2


def test_resposta_condicional(projeto):
    erros = validar_resposta(projeto, {"classe_ref": "1", "confianca": "baixa"})
    assert erros == ["classe_alt: obrigatório quando confianca ≠ alta"]
    assert validar_resposta(projeto, {"classe_ref": "1", "confianca": "baixa", "classe_alt": "2"}) == []


def test_resposta_valores_invalidos(projeto):
    erros = validar_resposta(
        projeto,
        {
            "classe_ref": "9",
            "confianca": "altíssima",
            "fonte": "gps",
            "cobertura_pct": "muito",
            "revisar": "talvez",
            "observacao": 42,
            "campo_x": 1,
        },
    )
    assert "classe_ref: código de classe inválido '9'" in erros
    assert "confianca: opção inválida 'altíssima'" in erros
    assert "fonte: opção inválida ['gps']" in erros
    assert "cobertura_pct: valor numérico inválido 'muito'" in erros
    assert "revisar: valor booleano inválido 'talvez'" in erros
    assert "observacao: deve ser texto" in erros
    assert "campo desconhecido: 'campo_x'" in erros


def test_resposta_tipos_aceitos(projeto):
    ok = {"classe_ref": "1", "confianca": "alta", "cobertura_pct": 12.5, "revisar": True, "observacao": "x"}
    assert validar_resposta(projeto, ok) == []
    ok["revisar"] = "sim"
    ok["cobertura_pct"] = "3"
    assert validar_resposta(projeto, ok) == []


def test_exemplos_do_repositorio_validam():
    raiz = Path(__file__).resolve().parent.parent / "exemplos"
    for nome in ("demo", "paraopeba"):
        p = carregar_projeto(raiz / nome / "projeto.yaml")
        assert p.legenda and p.campos
    para = carregar_projeto(raiz / "paraopeba" / "projeto.yaml")
    assert len(para.legenda) == 8
    assert [c.tecla for c in para.legenda] == [str(i) for i in range(1, 9)]
    assert {"estrato_classe", "faixa_rio", "conjunto"} <= para.colunas_ocultas
    assert para.campo("classe_alternativa").obrigatorio_se.campo == "confianca"
    fonte = para.campo("fonte_principal")
    assert fonte.tipo == "multiopcao" and fonte.obrigatorio
    assert [o.valor for o in fonte.opcoes] == ["hr", "serie", "sazonal"] and [o.tecla for o in fonte.opcoes] == ["H", "N", "S"]
    conf = para.campo("ano_confirmado_ndvi")
    assert conf.tipo == "opcao" and conf.obrigatorio_se.campo == "fonte_principal" and conf.obrigatorio_se.igual_a == "hr"
    assert [o.tecla for o in conf.opcoes] == ["C", "X"]
    data_hr = para.campo("data_imagem_hr")
    assert data_hr.tipo == "texto" and not data_hr.obrigatorio and data_hr.obrigatorio_se is None and data_hr.padrao
    base = {"classe_ref": "1", "confianca": "alta"}
    assert validar_resposta(para, base) == ["fonte_principal: obrigatório"]
    assert validar_resposta(para, {**base, "fonte_principal": ["serie", "sazonal"]}) == []
    assert validar_resposta(para, {**base, "fonte_principal": ["hr", "serie"]}) == ["ano_confirmado_ndvi: obrigatório quando fonte_principal = hr"]
    assert validar_resposta(para, {**base, "fonte_principal": ["hr"], "ano_confirmado_ndvi": "sim"}) == []
    assert validar_resposta(para, {**base, "fonte_principal": "hr", "ano_confirmado_ndvi": "nao", "data_imagem_hr": "2023-08"}) == []
    assert validar_resposta(para, {**base, "fonte_principal": ["serie"], "data_imagem_hr": "ago/2023"}) != []
    assert set(para.provedores_habilitados()) == {"s2_sazonal", "ndvi_serie", "esri_basemap"}


def test_yaml_de_exemplo_e_yaml_valido():
    raiz = Path(__file__).resolve().parent.parent / "exemplos"
    for nome in ("demo", "paraopeba"):
        assert isinstance(yaml.safe_load((raiz / nome / "projeto.yaml").read_text(encoding="utf-8")), dict)
