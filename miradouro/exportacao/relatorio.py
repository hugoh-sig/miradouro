"""Relatório de sessão: progresso, sessões, distribuições e sinais para a segunda passada.

Sai em Markdown (leitura) e JSON (máquina) com os mesmos números. É material do
analista: as colunas ocultas só entram com ``com_mapa=True``, e o Markdown avisa.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from miradouro import __version__
from miradouro.core.pontos import ConjuntoPontos
from miradouro.core.projeto import Projeto
from miradouro.core.respostas import Armazenamento, Resposta, escrever_atomico
from miradouro.exportacao.tabela import resposta_completa


def _fmt_valor(v: Any) -> str:
    if isinstance(v, (list, tuple)):
        return "+".join(str(x) for x in v) or "(vazio)"
    if v is None or v == "":
        return "(vazio)"
    return str(v)


def _contagem(respostas: Iterable[Resposta], campo: str) -> dict[str, int]:
    c: Counter[str] = Counter(_fmt_valor(r.valores.get(campo)) for r in respostas)
    return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))


def _mediana(valores: list[float]) -> float | None:
    return round(statistics.median(valores), 1) if valores else None


def _duracoes(respostas: Iterable[Resposta]) -> list[float]:
    out = []
    for r in respostas:
        d = r.meta.get("duracao_s")
        if isinstance(d, (int, float)):
            out.append(float(d))
    return out


def dados_relatorio(
    projeto: Projeto,
    pontos: ConjuntoPontos,
    arm: Armazenamento,
    *,
    com_mapa: bool = False,
    segunda: Armazenamento | None = None,
) -> dict[str, Any]:
    """Todos os números do relatório, serializáveis em JSON."""
    ids = pontos.ids
    respostas = {pid: r for pid, r in arm.todas().items() if pid in pontos}
    completas = {pid: r for pid, r in respostas.items() if resposta_completa(projeto, r)}
    cond = projeto.condicao_revisao()

    por_dia: Counter[str] = Counter(r.atualizado_em[:10] for r in respostas.values())
    sessoes = []
    for s in arm.sessoes:
        rs = [r for r in respostas.values() if r.sessao_id == s["id"]]
        durs = _duracoes(rs)
        total = sum(durs)
        sessoes.append(
            {
                "id": s["id"],
                "interprete": s.get("interprete"),
                "inicio": s.get("inicio"),
                "respostas": len(rs),
                "tempo_interpretando_s": round(total, 1),
                "mediana_s_por_ponto": _mediana(durs),
                "pontos_por_hora": round(len(durs) / (total / 3600), 1) if total > 0 else None,
            }
        )
    interpretes: dict[str, dict[str, Any]] = {}
    for r in respostas.values():
        d = interpretes.setdefault(r.interprete, {"respostas": 0, "tempo_interpretando_s": 0.0})
        d["respostas"] += 1
        d["tempo_interpretando_s"] += float(r.meta.get("duracao_s") or 0)
    for d in interpretes.values():
        d["tempo_interpretando_s"] = round(d["tempo_interpretando_s"], 1)

    distribuicoes = {c.nome: _contagem(completas.values(), c.nome) for c in projeto.campos if c.tipo in ("classe", "opcao", "multiopcao", "booleano")}
    campo_classe = next((c.nome for c in projeto.campos if c.tipo == "classe"), None)
    if campo_classe:
        distribuicoes[campo_classe] = {
            f"{k} {projeto.classe(k).rotulo}" if projeto.classe(k) else k: v for k, v in distribuicoes[campo_classe].items()
        }

    sinais = {
        "confianca_baixa": sorted(pid for pid, r in completas.items() if cond and cond.satisfeita(r.valores.get(cond.campo))),
        "sem_subsidio": sorted(pid for pid, r in respostas.items() if r.meta.get("sem_subsidio")),
        "com_revisoes": sorted(pid for pid, r in respostas.items() if r.revisoes > 0),
        "desfeitos": sorted(pid for pid, r in respostas.items() if r.meta.get("desfeito")),
        "incompletas": sorted(pid for pid in respostas if pid not in completas),
        "com_observacao": sorted(pid for pid, r in respostas.items() if any(isinstance(v, str) and v.strip() for k, v in r.valores.items() if (projeto.campo(k) and projeto.campo(k).tipo == "texto"))),
        "yaml_divergente": sorted(pid for pid, r in respostas.items() if r.yaml_sha256 and projeto.hash_yaml and r.yaml_sha256 != projeto.hash_yaml),
    }

    revisao_dirigida = []
    for s in arm.sessoes:
        if s.get("modo") != "dirigida":
            continue
        lista = s.get("lista") or {}
        gravadas = sorted(pid for pid, r in respostas.items() if r.sessao_id == s["id"] and r.meta.get("modo") == "dirigida")
        revisao_dirigida.append(
            {
                "sessao": s["id"],
                "interprete": s.get("interprete"),
                "inicio": s.get("inicio"),
                "lista": {"arquivo": lista.get("arquivo"), "sha256": lista.get("sha256"), "n": lista.get("n")},
                "gravadas": len(gravadas),
                "plotids": gravadas,
            }
        )

    dados: dict[str, Any] = {
        "projeto": {"nome": projeto.nome, "ano_referencia": projeto.ano_referencia, "yaml": str(projeto.caminho_yaml), "yaml_sha256": projeto.hash_yaml},
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "miradouro_versao": __version__,
        "arquivo_respostas": str(arm.arquivo),
        "progresso": {
            "total": len(ids),
            "respondidos": len(respostas),
            "completas": len(completas),
            "pendentes": len(ids) - len(respostas),
            "percentual": round(100 * len(respostas) / len(ids), 1) if ids else 0.0,
            "por_dia": dict(sorted(por_dia.items())),
        },
        "sessoes": sessoes,
        "interpretes": interpretes,
        "distribuicoes": distribuicoes,
        "sinais": sinais,
        "revisao_dirigida": revisao_dirigida,
    }
    if com_mapa:
        dados["cruzamento_mapa"] = cruzamento_com_mapa(projeto, pontos, completas)
    if segunda is not None:
        dados["segunda_passada"] = concordancia(projeto, completas, {pid: r for pid, r in segunda.todas().items() if pid in pontos})
    return dados


def cruzamento_com_mapa(projeto: Projeto, pontos: ConjuntoPontos, completas: dict[str, Resposta]) -> dict[str, Any]:
    """Tabela referência × classe do mapa a partir da primeira coluna oculta que pareça a classe do mapa."""
    campo_classe = next((c.nome for c in projeto.campos if c.tipo == "classe"), None)
    coluna = next((c for c in projeto.pontos.colunas_ocultas if c in pontos.colunas_extras), None)
    if campo_classe is None or coluna is None:
        return {"coluna_mapa": None, "tabela": {}, "concordancia": None}
    tabela: dict[str, dict[str, int]] = {}
    iguais = 0
    for pid, r in completas.items():
        p = pontos.obter(pid)
        mapa = str(p.extras.get(coluna, "")).strip()
        ref = str(r.valores.get(campo_classe))
        tabela.setdefault(mapa, {}).setdefault(ref, 0)
        tabela[mapa][ref] += 1
        iguais += mapa == ref
    return {
        "coluna_mapa": coluna,
        "tabela": {k: dict(sorted(v.items())) for k, v in sorted(tabela.items())},
        "concordancia": round(100 * iguais / len(completas), 1) if completas else None,
        "aviso": "cruzamento preliminar, sem estimador de área; a matriz oficial é do AcATaMa",
    }


def concordancia(projeto: Projeto, primeira: dict[str, Resposta], segunda: dict[str, Resposta]) -> dict[str, Any]:
    """Concordância entre passadas no campo de classe, entre os pontos presentes nas duas."""
    campo = next((c.nome for c in projeto.campos if c.tipo == "classe"), None)
    comuns = sorted(set(primeira) & set(segunda))
    divergentes = []
    for pid in comuns:
        a, b = primeira[pid].valores.get(campo), segunda[pid].valores.get(campo)
        if str(a) != str(b):
            divergentes.append({"PLOTID": pid, "primeira": a, "segunda": b, "consenso": primeira[pid].meta.get("consenso") is not None})
    controle = sorted(pid for pid, r in segunda.items() if r.meta.get("controle"))
    return {
        "campo": campo,
        "pontos_segunda_passada": len(segunda),
        "comparados": len(comuns),
        "concordantes": len(comuns) - len(divergentes),
        "concordancia_pct": round(100 * (len(comuns) - len(divergentes)) / len(comuns), 1) if comuns else None,
        "divergentes": divergentes,
        "consenso_pendente": [d["PLOTID"] for d in divergentes if not d["consenso"]],
        "controle": controle,
    }


# ---- Markdown ----------------------------------------------------------------------------


def _tabela_md(cabecalho: list[str], linhas: list[list[Any]]) -> str:
    def cel(v: Any) -> str:
        return "" if v is None else str(v)

    out = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    out += ["| " + " | ".join(cel(v) for v in linha) + " |" for linha in linhas]
    return "\n".join(out)


def _lista(ids: list[str], maximo: int = 60) -> str:
    if not ids:
        return "nenhum"
    texto = ", ".join(ids[:maximo])
    return texto + (f" … (+{len(ids) - maximo})" if len(ids) > maximo else "")


def markdown_relatorio(d: dict[str, Any]) -> str:
    p, pr = d["projeto"], d["progresso"]
    md = [
        f"# Relatório de sessão — {p['nome']}",
        "",
        f"Gerado em {d['gerado_em']} pelo miradouro {d['miradouro_versao']} · yaml `{(p['yaml_sha256'] or '')[:12]}` · respostas em `{d['arquivo_respostas']}`",
        "",
        "## Progresso",
        "",
        f"- **{pr['respondidos']}/{pr['total']}** respondidos ({pr['percentual']} %), {pr['completas']} completos, {pr['pendentes']} pendentes",
        "- Por dia: " + (", ".join(f"{k}: {v}" for k, v in pr["por_dia"].items()) or "—"),
        "",
        "## Sessões",
        "",
        _tabela_md(
            ["sessão", "intérprete", "início", "respostas", "tempo (s)", "mediana s/ponto", "pontos/h"],
            [[s["id"], s["interprete"], (s["inicio"] or "")[:16].replace("T", " "), s["respostas"], s["tempo_interpretando_s"], s["mediana_s_por_ponto"], s["pontos_por_hora"]] for s in d["sessoes"]],
        ),
        "",
        "Por intérprete: " + (", ".join(f"{k}: {v['respostas']} respostas, {v['tempo_interpretando_s']} s" for k, v in d["interpretes"].items()) or "—"),
        "",
        "## Distribuições (respostas completas)",
        "",
    ]
    for campo, cont in d["distribuicoes"].items():
        md.append(f"**{campo}**: " + (", ".join(f"{k} = {v}" for k, v in cont.items()) or "—"))
        md.append("")
    s = d["sinais"]
    md += [
        "## Sinais para a segunda passada",
        "",
        f"- Confiança baixa ({len(s['confianca_baixa'])}): {_lista(s['confianca_baixa'])}",
        f"- Sem subsídio pré-computado ({len(s['sem_subsidio'])}): {_lista(s['sem_subsidio'])}",
        f"- Com revisões ({len(s['com_revisoes'])}): {_lista(s['com_revisoes'])}",
        f"- Desfeitos ({len(s['desfeitos'])}): {_lista(s['desfeitos'])}",
        f"- Incompletos ({len(s['incompletas'])}): {_lista(s['incompletas'])}",
        f"- Com observação ({len(s['com_observacao'])}): {_lista(s['com_observacao'])}",
        f"- Gravados com outro yaml ({len(s['yaml_divergente'])}): {_lista(s['yaml_divergente'])}",
        "",
    ]
    if d.get("revisao_dirigida"):
        md += ["## Revisão dirigida (listas externas)", ""]
        md.append(
            _tabela_md(
                ["sessão", "intérprete", "início", "lista", "sha256", "n na lista", "gravadas"],
                [[x["sessao"], x["interprete"], (x["inicio"] or "")[:16].replace("T", " "), x["lista"]["arquivo"], (x["lista"]["sha256"] or "")[:12], x["lista"]["n"], x["gravadas"]] for x in d["revisao_dirigida"]],
            )
        )
        md.append("")
        md.append("O critério que gerou cada lista não é conhecido pela ferramenta; só o arquivo e o hash ficam registrados.")
        md.append("")
    if "segunda_passada" in d:
        sp = d["segunda_passada"]
        md += [
            "## Segunda passada e consenso",
            "",
            f"- {sp['pontos_segunda_passada']} pontos na segunda passada ({len(sp['controle'])} de controle), {sp['comparados']} comparados em `{sp['campo']}`",
            f"- Concordância: {sp['concordantes']}/{sp['comparados']}" + (f" ({sp['concordancia_pct']} %)" if sp["concordancia_pct"] is not None else ""),
            f"- Divergentes sem consenso ({len(sp['consenso_pendente'])}): {_lista(sp['consenso_pendente'])}",
            "",
        ]
        if sp["divergentes"]:
            md.append(_tabela_md(["PLOTID", "primeira", "segunda", "consenso"], [[x["PLOTID"], x["primeira"], x["segunda"], "sim" if x["consenso"] else "não"] for x in sp["divergentes"]]))
            md.append("")
    if "cruzamento_mapa" in d:
        cm = d["cruzamento_mapa"]
        md += ["## Cruzamento preliminar com a classe do mapa", "", f"> ⚠ Contém a classe do mapa (`{cm['coluna_mapa']}`). Não abra durante a interpretação. {cm.get('aviso', '')}", ""]
        if cm["tabela"]:
            refs = sorted({r for linha in cm["tabela"].values() for r in linha})
            md.append(_tabela_md(["mapa \\ referência", *refs], [[m, *[linha.get(r, 0) for r in refs]] for m, linha in cm["tabela"].items()]))
            md.append(f"\nConcordância bruta: {cm['concordancia']} %")
            md.append("")
    return "\n".join(md)


def gerar_relatorio(
    projeto: Projeto,
    pontos: ConjuntoPontos,
    arm: Armazenamento,
    saida: Path,
    *,
    com_mapa: bool = False,
    segunda: Armazenamento | None = None,
    nome: str | None = None,
) -> tuple[Path, Path]:
    d = dados_relatorio(projeto, pontos, arm, com_mapa=com_mapa, segunda=segunda)
    saida.mkdir(parents=True, exist_ok=True)
    nome = nome or f"relatorio_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    md, js = saida / f"{nome}.md", saida / f"{nome}.json"
    escrever_atomico(md, markdown_relatorio(d))
    escrever_atomico(js, json.dumps(d, ensure_ascii=False, indent=2))
    return md, js
