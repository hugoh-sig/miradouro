"""Relatório de sessão e lógica da segunda passada / consenso."""

import json

import pytest

from miradouro.cli import CODIGO_ERRO, CODIGO_OK, main
from miradouro.core import Armazenamento, carregar_pontos
from miradouro.core.projeto import CondicaoCampo
from miradouro.exportacao.relatorio import (
    concordancia,
    dados_relatorio,
    gerar_relatorio,
    markdown_relatorio,
)
from miradouro.interface import logica as lg


@pytest.fixture
def cenario(projeto):
    pontos = carregar_pontos(projeto.caminho_pontos)
    arm = Armazenamento(projeto, interprete="ana")
    arm.abrir_sessao()
    arm.gravar("p1", {"classe_ref": "1", "confianca": "baixa", "classe_alt": "2", "fonte": ["hr"], "observacao": "dúvida"}, meta={"duracao_s": 30, "modo": "pendentes", "sem_subsidio": ["esri_basemap"]})
    arm.gravar("p2", {"classe_ref": "2", "confianca": "alta"}, meta={"duracao_s": 10, "modo": "pendentes"})
    arm.gravar("p2", {"classe_ref": "6", "confianca": "alta"}, meta={"duracao_s": 5, "modo": "todos"})  # revisão
    arm.gravar("p3", {"confianca": "media"}, validar=False)  # incompleta
    return projeto, pontos, arm


def test_dados_relatorio(cenario):
    projeto, pontos, arm = cenario
    d = dados_relatorio(projeto, pontos, arm)
    pr = d["progresso"]
    assert (pr["total"], pr["respondidos"], pr["completas"], pr["pendentes"]) == (3, 3, 2, 0)
    assert pr["percentual"] == 100.0 and sum(pr["por_dia"].values()) == 3
    s = d["sessoes"][0]
    assert s["interprete"] == "ana" and s["respostas"] == 3 and s["tempo_interpretando_s"] == 35.0
    assert s["mediana_s_por_ponto"] == 17.5 and s["pontos_por_hora"] == round(2 / (35 / 3600), 1)
    assert d["interpretes"] == {"ana": {"respostas": 3, "tempo_interpretando_s": 35.0}}
    assert d["distribuicoes"]["classe_ref"] == {"1 floresta": 1, "6 Água": 1}
    assert d["distribuicoes"]["confianca"] == {"alta": 1, "baixa": 1}
    assert d["distribuicoes"]["fonte"] == {"(vazio)": 1, "hr": 1}
    si = d["sinais"]
    assert si["confianca_baixa"] == ["p1"] and si["sem_subsidio"] == ["p1"] and si["com_revisoes"] == ["p2"]
    assert si["incompletas"] == ["p3"] and si["com_observacao"] == ["p1"] and si["desfeitos"] == [] and si["yaml_divergente"] == []
    assert "cruzamento_mapa" not in d and "segunda_passada" not in d


def test_relatorio_com_mapa_e_markdown(cenario, tmp_path):
    projeto, pontos, arm = cenario
    d = dados_relatorio(projeto, pontos, arm, com_mapa=True)
    cm = d["cruzamento_mapa"]
    assert cm["coluna_mapa"] == "classe_mapa" and cm["tabela"] == {"1": {"1": 1}, "2": {"6": 1}} and cm["concordancia"] == 50.0
    md = markdown_relatorio(d)
    assert "# Relatório de sessão — Teste" in md and "| ana |" in md and "Confiança baixa (1): p1" in md
    assert "Não abra durante a interpretação" in md and "| mapa \\ referência | 1 | 6 |" in md
    md_path, js_path = gerar_relatorio(projeto, pontos, arm, tmp_path / "rel", nome="r1")
    assert md_path.name == "r1.md" and json.loads(js_path.read_text())["progresso"]["total"] == 3
    assert "classe_mapa" not in md_path.read_text()  # sem --com-mapa nada da coluna oculta aparece


def test_relatorio_sem_sessoes_nem_respostas(projeto, tmp_path):
    pontos = carregar_pontos(projeto.caminho_pontos)
    arm = Armazenamento(projeto, interprete="x")
    d = dados_relatorio(projeto, pontos, arm)
    assert d["progresso"]["percentual"] == 0.0 and d["sessoes"] == [] and d["sinais"]["confianca_baixa"] == []
    assert "nenhum" in markdown_relatorio(d)


def test_cli_relatorio(cenario, capsys):
    projeto, _, arm = cenario
    y = str(projeto.caminho_yaml)
    assert main(["relatorio", y, "--nome", "r"]) == CODIGO_OK
    assert (arm.pasta / "relatorios" / "r.md").exists()
    assert main(["relatorio", y, "--com-mapa", "--nome", "r2"]) == CODIGO_OK
    assert "AVISO" in capsys.readouterr().out
    assert main(["relatorio", y, "--segunda", str(arm.pasta / "nao_existe")]) == CODIGO_ERRO


# ---- segunda passada e consenso ---------------------------------------------------------

IDS = [str(i) for i in range(1, 21)]
COND = CondicaoCampo(campo="confianca", igual_a="baixa")


def _valores(baixa: set[str], respondidos: set[str]) -> dict:
    return {i: {"classe_ref": "1", "confianca": "baixa" if i in baixa else "alta"} for i in respondidos}


def test_selecionar_segunda_passada_determinista():
    valores = _valores({"3", "7", "15"}, set(IDS[:18]))
    baixa, controle = lg.selecionar_segunda_passada(IDS, valores, COND, fracao_controle=0.2, semente="abc")
    assert baixa == ["3", "7", "15"]
    assert len(controle) == 3 and set(controle) <= set(IDS[:18]) - {"3", "7", "15"}  # 20 % de 15 elegíveis
    assert controle == sorted(controle, key=IDS.index)
    assert lg.selecionar_segunda_passada(IDS, valores, COND, 0.2, "abc")[1] == controle  # mesma semente → mesma amostra
    assert lg.selecionar_segunda_passada(IDS, valores, COND, 0.2, "outra")[1] != controle
    assert lg.selecionar_segunda_passada(IDS, valores, COND, 0.0, "abc") == (["3", "7", "15"], [])
    assert len(lg.selecionar_segunda_passada(IDS, valores, COND, 0.01, "abc")[1]) == 1  # fração pequena: ao menos 1
    assert lg.selecionar_segunda_passada(IDS, valores, None, 0.5, "abc")[0] == []
    with pytest.raises(ValueError):
        lg.selecionar_segunda_passada(IDS, valores, COND, 1.5)


def test_divergencias_e_ordem_consenso():
    primeira = {"1": {"classe_ref": "1"}, "2": {"classe_ref": "2"}, "3": {"classe_ref": "6"}, "4": {"classe_ref": "1"}}
    segunda = {"1": {"classe_ref": "1"}, "2": {"classe_ref": "6"}, "3": {"classe_ref": 6}, "9": {"classe_ref": "1"}}
    assert lg.divergencias(primeira, segunda, "classe_ref") == ["2"]
    assert lg.ordem_consenso(IDS, primeira, segunda, [], "divergentes", "classe_ref") == ["2"]
    assert lg.ordem_consenso(IDS, primeira, segunda, ["2"], "divergentes", "classe_ref") == []
    assert lg.ordem_consenso(IDS, primeira, segunda, [], "todos_segunda", "classe_ref") == ["1", "2", "3", "9"]
    with pytest.raises(ValueError):
        lg.ordem_consenso(IDS, primeira, segunda, [], "x", "classe_ref")


def test_concordancia_no_relatorio(cenario):
    projeto, pontos, arm = cenario
    seg = Armazenamento(projeto, interprete="bia", pasta=arm.pasta / "segunda")
    seg.gravar("p1", {"classe_ref": "2", "confianca": "alta"}, meta={"passada": 2})
    seg.gravar("p2", {"classe_ref": "6", "confianca": "alta"}, meta={"passada": 2, "controle": True})
    d = dados_relatorio(projeto, pontos, arm, segunda=seg)
    sp = d["segunda_passada"]
    assert (sp["pontos_segunda_passada"], sp["comparados"], sp["concordantes"], sp["concordancia_pct"]) == (2, 2, 1, 50.0)
    assert sp["divergentes"] == [{"PLOTID": "p1", "primeira": "1", "segunda": "2", "consenso": False}]
    assert sp["consenso_pendente"] == ["p1"] and sp["controle"] == ["p2"]
    arm.gravar("p1", {"classe_ref": "2", "confianca": "alta"}, meta={"consenso": {"primeira": {}, "segunda": {}}})
    assert concordancia(projeto, {p: r for p, r in arm.todas().items()}, seg.todas())["consenso_pendente"] == []
    md = markdown_relatorio(dados_relatorio(projeto, pontos, arm, segunda=seg))
    assert "## Segunda passada e consenso" in md and "(1 de controle)" in md
    assert main(["relatorio", str(projeto.caminho_yaml), "--nome", "r3"]) == CODIGO_OK  # detecta <respostas>/segunda sozinho
    assert "Segunda passada" in (arm.pasta / "relatorios" / "r3.md").read_text()
