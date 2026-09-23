"""Embrião do fluxo guiado: diagnóstico das etapas do protocolo e os comandos de cada uma.

Só lê o estado do projeto (respostas, amostra da segunda passada, listas) e devolve
etapas com situação e comando pronto. **Nada é executado aqui**; a única escrita é a
lista de PLOTIDs de confiança a revisar em ``listas/`` (só identificadores), e só
quando o conteúdo muda. A sequência completa e configurável fica para o orquestrador
de protocolo (ROADMAP, fase 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from miradouro.core.pontos import ConjuntoPontos
from miradouro.core.projeto import Projeto
from miradouro.core.respostas import Armazenamento, escrever_atomico
from miradouro.interface import logica as lg

PASTA_LISTAS = "listas"
ARQUIVO_LISTA_CONFIANCA = "revisao_confianca.csv"
SITUACOES = ("pendente", "em_andamento", "concluida", "nao_aplicavel", "disponivel")


@dataclass(frozen=True)
class Etapa:
    chave: str
    titulo: str
    situacao: str  # um de SITUACOES
    detalhe: str
    comando: str | None = None

    @property
    def pendente(self) -> bool:
        return self.situacao in ("pendente", "em_andamento")


def valores_confianca_a_revisar(projeto: Projeto) -> tuple[str | None, list[str]]:
    """Campo de confiança (o de ``interface.revisao``) e os valores que pedem revisão:
    todas as opções do campo exceto a primeira (a mais alta, por convenção do yaml)."""
    cond = projeto.condicao_revisao()
    if cond is None:
        return None, []
    campo = projeto.campo(cond.campo)
    if campo is None or campo.tipo not in ("opcao", "multiopcao") or len(campo.opcoes) < 2:
        return cond.campo, []
    return cond.campo, [o.valor for o in campo.opcoes[1:]]


def ids_confianca_a_revisar(projeto: Projeto, pontos: ConjuntoPontos, arm: Armazenamento) -> tuple[str | None, list[str], list[str]]:
    """(campo, valores, PLOTIDs na ordem do CSV) cujas respostas têm confiança a revisar."""
    campo, valores = valores_confianca_a_revisar(projeto)
    if not valores:
        return campo, valores, []
    respostas = arm.todas()
    ids = [i for i in pontos.ids if i in respostas and str(respostas[i].valores.get(campo)) in valores]
    return campo, valores, ids


def escrever_lista(caminho: Path, ids: list[str]) -> bool:
    """Grava ``caminho`` com só a coluna PLOTID; devolve True se escreveu (conteúdo mudou)."""
    conteudo = "PLOTID\n" + "".join(f"{i}\n" for i in ids)
    if caminho.is_file() and caminho.read_text(encoding="utf-8") == conteudo:
        return False
    escrever_atomico(caminho, conteudo)
    return True


def _cmd(python: str, *partes: str) -> str:
    return " ".join([python, *partes])


def diagnosticar(
    projeto: Projeto,
    pontos: ConjuntoPontos,
    arm: Armazenamento,
    *,
    interprete: str = "<id>",
    pasta_listas: Path | None = None,
    python: str = "python -m miradouro",
) -> list[Etapa]:
    """Etapas do protocolo na ordem em que se executam, cada uma com situação e comando.

    ``arm`` é o arquivo principal (primeira passada), lido sem abrir sessão.
    """
    yaml = str(projeto.caminho_yaml)
    ids = pontos.ids
    respostas = {pid: r for pid, r in arm.todas().items() if pid in pontos}
    etapas: list[Etapa] = []

    # 1. Interpretação
    pendentes = [i for i in ids if i not in respostas]
    if pendentes:
        etapas.append(Etapa("interpretacao", "Interpretação", "pendente", f"{len(respostas)}/{len(ids)} respondidos; faltam {len(pendentes)}.",
                            _cmd(python, "app", yaml, "--interprete", interprete)))
    else:
        etapas.append(Etapa("interpretacao", "Interpretação", "concluida", f"{len(respostas)}/{len(ids)} respondidos."))

    # 2. Revisão dirigida dos pontos de confiança a revisar (lista gerada em listas/, só PLOTIDs)
    campo, valores, ids_rev = ids_confianca_a_revisar(projeto, pontos, arm)
    if campo is None:
        etapas.append(Etapa("revisao_confianca", "Revisão por confiança", "nao_aplicavel", "O projeto não define `interface.revisao`."))
    elif not ids_rev:
        etapas.append(Etapa("revisao_confianca", "Revisão por confiança", "concluida", f"Nenhum ponto com {campo} em {valores}."))
    else:
        pasta = pasta_listas or (projeto.caminho_yaml.parent / PASTA_LISTAS)
        arquivo = pasta / ARQUIVO_LISTA_CONFIANCA
        escrever_lista(arquivo, ids_rev)
        lista = lg.carregar_lista_plotids(arquivo)
        nao_revistos = [i for i in ids_rev if not lg.revisto_na_lista(respostas[i].meta, lista.sha256)]
        det = f"{len(ids_rev)} ponto(s) com {campo} em {valores} (lista `{arquivo}`); {len(nao_revistos)} ainda não revisto(s) com ela."
        if nao_revistos:
            etapas.append(Etapa("revisao_confianca", "Revisão por confiança", "pendente" if len(nao_revistos) == len(ids_rev) else "em_andamento", det,
                                _cmd(python, "app", yaml, "--interprete", interprete, "--lista", str(arquivo))))
        else:
            etapas.append(Etapa("revisao_confianca", "Revisão por confiança", "concluida", det))

    # 3. Segunda passada cega
    pasta_segunda = projeto.pasta_saida / lg.PASTA_SEGUNDA
    amostra = lg.carregar_amostra_segunda(pasta_segunda)
    seg_arquivo = pasta_segunda / "respostas.json"
    segunda = Armazenamento(projeto, interprete="diagnostico", pasta=pasta_segunda) if seg_arquivo.exists() else None
    if amostra is None:
        aviso = " Sorteie só depois de concluir a interpretação." if pendentes else ""
        etapas.append(Etapa("segunda_passada", "Segunda passada cega", "pendente", f"Amostra ainda não sorteada.{aviso}",
                            _cmd(python, "sortear", yaml, "--fracao-controle", "0.10", "--interprete", "<id-da-segunda-passada>")))
    else:
        sorteados = [i for i in ids if i in set(amostra.get("baixa", [])) | set(amostra.get("controle", []))]
        feitos = [i for i in sorteados if segunda is not None and segunda.obter(i) is not None]
        quem = amostra.get("interprete_previsto") or "<id-da-segunda-passada>"
        cmd = _cmd(python, "app", yaml, "--interprete", str(quem), "--segunda-passada")
        if not feitos:
            etapas.append(Etapa("segunda_passada", "Segunda passada cega", "pendente", f"Sorteada ({len(sorteados)} pontos, {len(amostra.get('controle', []))} de controle) e não iniciada.", cmd))
        elif len(feitos) < len(sorteados):
            etapas.append(Etapa("segunda_passada", "Segunda passada cega", "em_andamento", f"{len(feitos)}/{len(sorteados)} pontos sorteados respondidos.", cmd))
        else:
            etapas.append(Etapa("segunda_passada", "Segunda passada cega", "concluida", f"{len(feitos)}/{len(sorteados)} pontos sorteados respondidos."))

    # 4. Consenso
    campo_classe = next((c.nome for c in projeto.campos if c.tipo == "classe"), None)
    if segunda is None or not segunda.respondidos():
        etapas.append(Etapa("consenso", "Consenso", "nao_aplicavel", "Só depois da segunda passada."))
    else:
        div = lg.divergencias({p: r.valores for p, r in respostas.items()}, {p: r.valores for p, r in segunda.todas().items()}, campo_classe or "")
        pend = [d for d in div if respostas[d].meta.get("consenso") is None]
        det = f"{len(div)} divergências em {campo_classe}; {len(pend)} sem consenso."
        if pend:
            etapas.append(Etapa("consenso", "Consenso", "pendente", det, _cmd(python, "app", yaml, "--interprete", interprete, "--consenso")))
        else:
            etapas.append(Etapa("consenso", "Consenso", "concluida", det))

    # 5. Relatório e exportação (sempre disponíveis)
    etapas.append(Etapa("relatorio_exportacao", "Relatório e exportação", "disponivel", "Relatório de sessão (Markdown + JSON) e tabela plana de referência.",
                        _cmd(python, "relatorio", yaml) + "\n" + _cmd(python, "exportar", "csv", yaml)))
    return etapas


def para_dict(etapas: list[Etapa]) -> list[dict[str, Any]]:
    return [{"chave": e.chave, "titulo": e.titulo, "situacao": e.situacao, "detalhe": e.detalhe, "comando": e.comando} for e in etapas]
