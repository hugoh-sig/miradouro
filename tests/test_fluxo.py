"""Diagnóstico das etapas do protocolo (embrião do fluxo guiado): só lê e sugere comandos."""

import json
from pathlib import Path

from miradouro import fluxo
from miradouro.core import Armazenamento, carregar_pontos, carregar_projeto
from miradouro.interface import logica as lg

RAIZ = Path(__file__).resolve().parent.parent


def _por_chave(etapas):
    return {e.chave: e for e in etapas}


def test_valores_confianca_a_revisar(projeto):
    assert fluxo.valores_confianca_a_revisar(projeto) == ("confianca", ["media", "baixa"])
    paraopeba = carregar_projeto(RAIZ / "exemplos" / "paraopeba" / "projeto.yaml")
    assert fluxo.valores_confianca_a_revisar(paraopeba) == ("confianca", ["media", "baixa"])


def test_diagnostico_sem_respostas(projeto):
    pontos = carregar_pontos(projeto.caminho_pontos)
    arm = Armazenamento(projeto, interprete="x")
    e = _por_chave(fluxo.diagnosticar(projeto, pontos, arm, interprete="ana"))
    assert [x.chave for x in fluxo.diagnosticar(projeto, pontos, arm)] == ["interpretacao", "revisao_confianca", "segunda_passada", "consenso", "relatorio_exportacao"]
    assert e["interpretacao"].situacao == "pendente" and e["interpretacao"].comando == f"python -m miradouro app {projeto.caminho_yaml} --interprete ana"
    assert e["revisao_confianca"].situacao == "concluida" and not (projeto.caminho_yaml.parent / "listas").exists()
    assert e["segunda_passada"].situacao == "pendente" and "Sorteie só depois" in e["segunda_passada"].detalhe and "sortear" in e["segunda_passada"].comando
    assert e["consenso"].situacao == "nao_aplicavel" and e["consenso"].comando is None
    assert e["relatorio_exportacao"].situacao == "disponivel" and "relatorio" in e["relatorio_exportacao"].comando and "exportar csv" in e["relatorio_exportacao"].comando
    assert not arm.arquivo.exists()  # diagnóstico não grava respostas nem abre sessão


def test_diagnostico_fluxo_completo(projeto, tmp_path):
    pontos = carregar_pontos(projeto.caminho_pontos)
    arm = Armazenamento(projeto, interprete="ana")
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    arm.gravar("p2", {"classe_ref": "2", "confianca": "media", "classe_alt": "1"})
    arm.gravar("p3", {"classe_ref": "6", "confianca": "baixa", "classe_alt": "1"})
    py = "/venv/bin/python -m miradouro"
    e = _por_chave(fluxo.diagnosticar(projeto, pontos, arm, interprete="ana", python=py))
    assert e["interpretacao"].situacao == "concluida" and e["interpretacao"].comando is None
    # Lista gerada com só PLOTIDs, na ordem do CSV; comando pronto com --lista.
    lista = projeto.caminho_yaml.parent / "listas" / "revisao_confianca.csv"
    assert lista.read_text(encoding="utf-8") == "PLOTID\np2\np3\n"
    assert e["revisao_confianca"].situacao == "pendente" and e["revisao_confianca"].comando == f"{py} app {projeto.caminho_yaml} --interprete ana --lista {lista}"
    # Não reescreve se o conteúdo não mudou.
    mtime = lista.stat().st_mtime_ns
    assert fluxo.escrever_lista(lista, ["p2", "p3"]) is False and lista.stat().st_mtime_ns == mtime
    # Um revisto com esta lista → em andamento; os dois → concluída.
    sha = lg.carregar_lista_plotids(lista).sha256
    carimbo = {"modo": "dirigida", "lista": {"arquivo": lista.name, "sha256": sha, "n": 2}}
    arm.gravar("p2", {"classe_ref": "2", "confianca": "media", "classe_alt": "1"}, meta=carimbo)
    assert _por_chave(fluxo.diagnosticar(projeto, pontos, arm))["revisao_confianca"].situacao == "em_andamento"
    arm.gravar("p3", {"classe_ref": "6", "confianca": "alta"}, meta=carimbo)  # confiança mudou: sai da lista
    assert _por_chave(fluxo.diagnosticar(projeto, pontos, arm))["revisao_confianca"].situacao == "pendente"
    assert lista.read_text(encoding="utf-8") == "PLOTID\np2\n"  # lista regravada
    sha2 = lg.carregar_lista_plotids(lista).sha256
    assert sha2 != sha  # lista mudou → hash mudou → p2 conta como não revisto com a lista nova
    arm.gravar("p2", {"classe_ref": "2", "confianca": "media", "classe_alt": "1"}, meta={"modo": "dirigida", "lista": {"sha256": sha2}})
    assert _por_chave(fluxo.diagnosticar(projeto, pontos, arm))["revisao_confianca"].situacao == "concluida"

    # Segunda passada: sorteada e não iniciada → comando com o intérprete previsto.
    pasta_segunda = projeto.pasta_saida / lg.PASTA_SEGUNDA
    amostra = lg.sortear_amostra_segunda(projeto, pontos.ids, {p: r.valores for p, r in arm.todas().items()}, 0.5, interprete_previsto="hugo2p")
    lg.gravar_amostra_segunda(pasta_segunda, amostra)
    e = _por_chave(fluxo.diagnosticar(projeto, pontos, arm, python=py))
    assert e["segunda_passada"].situacao == "pendente" and "não iniciada" in e["segunda_passada"].detalhe
    assert e["segunda_passada"].comando == f"{py} app {projeto.caminho_yaml} --interprete hugo2p --segunda-passada"
    assert e["consenso"].situacao == "nao_aplicavel"
    # Em andamento → concluída; consenso pendente quando há divergência → concluído após meta.consenso.
    seg = Armazenamento(projeto, interprete="hugo2p", pasta=pasta_segunda)
    sorteados = amostra["baixa"] + amostra["controle"]
    seg.gravar(sorteados[0], {"classe_ref": "2", "confianca": "alta"}, meta={"passada": 2})
    e = _por_chave(fluxo.diagnosticar(projeto, pontos, arm))
    assert e["segunda_passada"].situacao == "em_andamento" and f"1/{len(sorteados)}" in e["segunda_passada"].detalhe
    for pid in sorteados[1:]:
        seg.gravar(pid, {"classe_ref": "2", "confianca": "alta"}, meta={"passada": 2})
    e = _por_chave(fluxo.diagnosticar(projeto, pontos, arm, interprete="ana"))
    assert e["segunda_passada"].situacao == "concluida"
    divergentes = [p for p in sorteados if arm.obter(p).valores["classe_ref"] != "2"]
    assert e["consenso"].situacao == "pendente" and f"{len(divergentes)} divergências" in e["consenso"].detalhe and e["consenso"].comando.endswith("--interprete ana --consenso")
    for p in divergentes:
        arm.gravar(p, {"classe_ref": "2", "confianca": "alta"}, meta={"consenso": {}})
    assert _por_chave(fluxo.diagnosticar(projeto, pontos, arm))["consenso"].situacao == "concluida"
    assert json.dumps(fluxo.para_dict(fluxo.diagnosticar(projeto, pontos, arm)))  # serializável
