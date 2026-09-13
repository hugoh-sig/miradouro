"""Lógica da interface sem Streamlit: atalhos, navegação, filtros, cronômetro, cegueira.

Tudo aqui é determinístico e testável. A casca Streamlit só chama estas funções.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from miradouro.chips.cache import CacheChips
from miradouro.core.pontos import Ponto
from miradouro.core.projeto import Campo, CondicaoCampo, Projeto

FILTROS: dict[str, str] = {
    "pendentes": "Pendentes",
    "todos": "Todos os pontos",
    "revisao": "Revisão (confiança baixa)",
}
FILTROS_SEGUNDA: dict[str, str] = {"pendentes": "Pendentes", "todos": "Todos da segunda passada"}
FILTROS_CONSENSO: dict[str, str] = {"divergentes": "Divergentes sem consenso", "todos_segunda": "Todos da segunda passada"}
PASTA_SEGUNDA = "segunda"  # subpasta da saída onde a segunda passada grava

# Ações reservadas do teclado; têm precedência sobre atalhos de campos.
ACOES_RESERVADAS: dict[str, str] = {
    "enter": "confirmar",
    "right": "proximo",
    "left": "anterior",
    "down": "proximo",
    "up": "anterior",
    "u": "desfazer",
    "backspace": "limpar",
}
TEXTO_ACOES = "Enter confirma e avança · ← → navegam · U desfaz · Backspace limpa · T foca o texto · Esc sai do texto"


# ---- teclas --------------------------------------------------------------------


@dataclass(frozen=True)
class Tecla:
    """Evento de teclado vindo do navegador."""

    key: str
    code: str = ""
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    meta: bool = False

    @classmethod
    def de_dict(cls, d: Mapping[str, Any]) -> Tecla:
        return cls(
            key=str(d.get("key", "")),
            code=str(d.get("code", "")),
            shift=bool(d.get("shift", False)),
            ctrl=bool(d.get("ctrl", False)),
            alt=bool(d.get("alt", False)),
            meta=bool(d.get("meta", False)),
        )


_ESPECIAIS = {
    "enter": "enter",
    "numpadenter": "enter",
    "arrowleft": "left",
    "arrowright": "right",
    "arrowup": "up",
    "arrowdown": "down",
    "backspace": "backspace",
    "escape": "escape",
}


def normalizar_tecla(t: Tecla) -> str | None:
    """Identificador independente de layout: ``'1'``, ``'a'``, ``'shift+1'``, ``'enter'``...

    Usa ``code`` (posição física) para dígitos e letras, de modo que Shift+1 seja
    ``shift+1`` tanto em ABNT2 quanto em US. Combinações com Ctrl/Alt/Meta são
    ignoradas (retorna None) para não sequestrar atalhos do navegador.
    """
    if t.ctrl or t.alt or t.meta:
        return None
    code = t.code or ""
    base: str | None = None
    if code.startswith("Digit") and len(code) == 6:
        base = code[5]
    elif code.startswith("Numpad") and len(code) == 7 and code[6].isdigit():
        base = code[6]
    elif code.startswith("Key") and len(code) == 4:
        base = code[3].lower()
    elif code.lower() in _ESPECIAIS:
        base = _ESPECIAIS[code.lower()]
    elif t.key.lower() in _ESPECIAIS:
        base = _ESPECIAIS[t.key.lower()]
    elif len(t.key) == 1:
        base = t.key.lower()
    if base is None:
        return None
    if t.shift and base not in _ESPECIAIS.values():
        return f"shift+{base}"
    return base


@dataclass(frozen=True)
class Atalho:
    campo: str
    valor: str
    rotulo: str
    alternar: bool = False  # multiopcao: a tecla liga/desliga o valor em vez de selecionar


def mapa_de_atalhos(projeto: Projeto) -> tuple[dict[str, Atalho], list[str]]:
    """Tecla normalizada → (campo, valor). Devolve também avisos de conflito.

    Regras: as teclas da legenda vão para o primeiro campo do tipo ``classe``;
    o segundo campo ``classe`` usa ``Shift+tecla``; campos ``opcao`` usam as
    teclas das suas opções. Teclas reservadas (Enter, setas, U, Backspace)
    vencem; conflitos entre campos mantêm o primeiro e geram aviso.
    """
    mapa: dict[str, Atalho] = {}
    avisos: list[str] = []

    def registrar(chave: str, atalho: Atalho) -> None:
        if chave in ACOES_RESERVADAS:
            avisos.append(f"tecla {chave.upper()!r} de {atalho.campo} é reservada ({ACOES_RESERVADAS[chave]}); use o mouse")
            return
        if chave in mapa:
            outro = mapa[chave]
            avisos.append(f"tecla {chave.upper()!r} usada por {outro.campo} e {atalho.campo}; vale {outro.campo}")
            return
        mapa[chave] = atalho

    campos_classe = [c for c in projeto.campos if c.tipo == "classe"]
    for i, campo in enumerate(campos_classe):
        if i >= 2:
            avisos.append(f"campo {campo.nome} sem atalho de teclado (só mouse)")
            continue
        prefixo = "" if i == 0 else "shift+"
        for classe in projeto.legenda:
            registrar(prefixo + classe.tecla.lower(), Atalho(campo.nome, classe.codigo, classe.rotulo or classe.nome))
    for campo in projeto.campos:
        if campo.tipo not in ("opcao", "multiopcao"):
            continue
        for op in campo.opcoes:
            if op.tecla:
                registrar(op.tecla.lower(), Atalho(campo.nome, op.valor, op.rotulo or op.valor, alternar=campo.tipo == "multiopcao"))
    return mapa, avisos


def aplicar_atalho(rascunho: dict[str, Any], atalho: Atalho) -> dict[str, Any]:
    """Aplica um atalho ao rascunho (in place e devolve): seleciona, ou alterna se ``alternar``."""
    if atalho.alternar:
        atual = [str(v) for v in (rascunho.get(atalho.campo) or [])] if isinstance(rascunho.get(atalho.campo), (list, tuple)) else ([str(rascunho[atalho.campo])] if rascunho.get(atalho.campo) else [])
        if atalho.valor in atual:
            atual = [v for v in atual if v != atalho.valor]
        else:
            atual = atual + [atalho.valor]
        rascunho[atalho.campo] = atual
    else:
        rascunho[atalho.campo] = atalho.valor
    return rascunho


def tecla_do_valor(mapa: Mapping[str, Atalho], campo: str, valor: Any) -> str | None:
    """Tecla que produz ``valor`` em ``campo`` (para exibir nos rótulos)."""
    for chave, a in mapa.items():
        if a.campo == campo and a.valor == str(valor):
            return chave
    return None


def rotulo_com_tecla(mapa: Mapping[str, Atalho], campo: str, valor: Any, rotulo: str) -> str:
    tecla = tecla_do_valor(mapa, campo, valor)
    if tecla is None:
        return rotulo
    return f"[{tecla.replace('shift+', '⇧').upper()}] {rotulo}"


def interpretar_tecla(chave: str | None, mapa: Mapping[str, Atalho]) -> tuple[str, Any] | None:
    """Devolve ``('acao', nome)`` ou ``('atalho', Atalho)`` ou None."""
    if chave is None:
        return None
    if chave in ACOES_RESERVADAS:
        return ("acao", ACOES_RESERVADAS[chave])
    if chave in mapa:
        return ("atalho", mapa[chave])
    return None


# ---- campos condicionais -----------------------------------------------------------


def campo_visivel(campo: Campo, rascunho: Mapping[str, Any]) -> bool:
    """Campos com ``obrigatorio_se`` só aparecem quando a condição vale."""
    if campo.obrigatorio_se is None:
        return True
    return campo.obrigatorio_se.satisfeita(rascunho.get(campo.obrigatorio_se.campo))


def ordem_dos_campos(projeto: Projeto) -> list[Campo]:
    """Campos na ordem de exibição: cada condicional vai logo abaixo do campo que o dispara.

    Condicionais cujo gatilho vem depois deles no yaml (ou é outro condicional)
    ficam onde estavam.
    """
    dependentes: dict[str, list[Campo]] = {}
    for c in projeto.campos:
        if c.obrigatorio_se is not None:
            dependentes.setdefault(c.obrigatorio_se.campo, []).append(c)
    movidos = {c.nome for lista in dependentes.values() for c in lista}
    saida: list[Campo] = []
    for c in projeto.campos:
        if c.nome in movidos and c.obrigatorio_se.campo not in {x.nome for x in saida}:
            continue  # será inserido logo após o gatilho
        if c.nome in movidos:
            continue
        saida.append(c)
        saida.extend(dependentes.get(c.nome, []))
    for c in projeto.campos:  # gatilho inexistente na saída (ordem estranha): mantém no fim
        if c not in saida:
            saida.append(c)
    return saida


def campos_visiveis(projeto: Projeto, rascunho: Mapping[str, Any]) -> list[Campo]:
    return [c for c in ordem_dos_campos(projeto) if campo_visivel(c, rascunho)]


def limpar_valores_ocultos(projeto: Projeto, rascunho: Mapping[str, Any]) -> dict[str, Any]:
    """Remove valores de campos condicionais que não estão visíveis e valores vazios."""
    visiveis = {c.nome for c in campos_visiveis(projeto, rascunho)}
    saida: dict[str, Any] = {}
    for k, v in rascunho.items():
        if k not in visiveis:
            continue
        if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, tuple)) and not v):
            continue
        saida[k] = v.strip() if isinstance(v, str) else (list(v) if isinstance(v, tuple) else v)
    return saida


def formatar_valor(valor: Any) -> str:
    """Valor legível: listas viram ``a+b``."""
    if isinstance(valor, (list, tuple)):
        return "+".join(str(v) for v in valor) or "—"
    return str(valor)


def campo_do_erro(erro: str) -> str | None:
    """Nome do campo a partir de uma mensagem de ``validar_resposta`` (``"campo: ..."``)."""
    nome, sep, _ = erro.partition(":")
    return nome.strip() if sep and " " not in nome.strip() else None


# ---- filtros e navegação -----------------------------------------------------------


def ordem_visivel(
    ids: list[str],
    valores_por_id: Mapping[str, Mapping[str, Any]],
    filtro: str,
    cond_revisao: CondicaoCampo | None = None,
) -> list[str]:
    """IDs (na ordem do CSV) que o filtro mostra."""
    if filtro == "todos":
        return list(ids)
    if filtro == "pendentes":
        return [i for i in ids if i not in valores_por_id]
    if filtro == "revisao":
        if cond_revisao is None:
            return []
        return [i for i in ids if i in valores_por_id and cond_revisao.satisfeita(valores_por_id[i].get(cond_revisao.campo))]
    raise ValueError(f"filtro desconhecido: {filtro!r}")


def primeiro_pendente(ids: Iterable[str], respondidos: Iterable[str]) -> str | None:
    feitos = set(respondidos)
    return next((i for i in ids if i not in feitos), None)


def vizinho(ordem: list[str], ids: list[str], atual: str | None, passo: int) -> str | None:
    """Próximo (``passo=+1``) ou anterior (``-1``) na ``ordem`` a partir de ``atual``.

    Se ``atual`` não está mais na ordem (ex.: acabou de ser respondido no modo
    pendentes), usa a posição dele no CSV para achar o vizinho.
    """
    if not ordem:
        return None
    if atual is None:
        return ordem[0] if passo > 0 else ordem[-1]
    if atual in ordem:
        i = ordem.index(atual) + passo
        return ordem[i] if 0 <= i < len(ordem) else None
    pos = {pid: n for n, pid in enumerate(ids)}
    p = pos.get(atual)
    if p is None:
        return ordem[0]
    if passo > 0:
        return next((i for i in ordem if pos[i] > p), None)
    return next((i for i in reversed(ordem) if pos[i] < p), None)


def posicao(ordem: list[str], atual: str | None) -> tuple[int, int]:
    """(índice 1-based ou 0, total) para exibir 'ponto 12 de 458'."""
    if atual is None or atual not in ordem:
        return 0, len(ordem)
    return ordem.index(atual) + 1, len(ordem)


# ---- cegueira -----------------------------------------------------------------------


def dados_visiveis_do_ponto(ponto: Ponto, projeto: Projeto) -> dict[str, str]:
    """Tudo o que a interface pode mostrar sobre um ponto: PLOTID, lon, lat e extras não ocultos."""
    dados = {"PLOTID": ponto.plotid, "LON": f"{ponto.lon:.6f}", "LAT": f"{ponto.lat:.6f}"}
    dados.update(ponto.extras_visiveis(projeto.colunas_ocultas))
    return dados


def contem_dado_oculto(texto: str, pontos: Iterable[Ponto], projeto: Projeto) -> list[str]:
    """Nomes/valores de colunas ocultas que aparecem em ``texto`` (para testes e verificação)."""
    ocultas = projeto.colunas_ocultas
    achados: list[str] = []
    for nome in ocultas:
        if nome in texto:
            achados.append(nome)
    for p in pontos:
        for nome in ocultas:
            v = p.extras.get(nome, "")
            if v and len(v) >= 3 and v in texto:
                achados.append(f"{nome}={v}")
    return sorted(set(achados))


# ---- chips ----------------------------------------------------------------------------


def chips_do_ponto(cache: CacheChips, provedores: Iterable[str], plotid: str) -> dict[str, Path | None]:
    """Caminho do chip de cada provedor (None quando falta)."""
    return {nome: (cache.caminho(nome, plotid) if cache.existe(nome, plotid) else None) for nome in provedores}


def provedores_faltantes(chips: Mapping[str, Path | None]) -> list[str]:
    return [nome for nome, caminho in chips.items() if caminho is None]


# ---- cronômetro e histórico -----------------------------------------------------------


@dataclass
class Cronometro:
    """Tempo gasto por ponto, somando visitas. ``relogio`` é injetável nos testes."""

    relogio: Any = time.monotonic
    acumulado: dict[str, float] = field(default_factory=dict)
    atual: str | None = None
    inicio: float | None = None

    def ir_para(self, plotid: str | None) -> None:
        agora = self.relogio()
        if self.atual is not None and self.inicio is not None:
            self.acumulado[self.atual] = self.acumulado.get(self.atual, 0.0) + (agora - self.inicio)
        self.atual = plotid
        self.inicio = agora if plotid is not None else None

    def decorrido(self, plotid: str | None = None) -> float:
        plotid = plotid or self.atual
        if plotid is None:
            return 0.0
        total = self.acumulado.get(plotid, 0.0)
        if plotid == self.atual and self.inicio is not None:
            total += self.relogio() - self.inicio
        return total

    def zerar(self, plotid: str) -> None:
        self.acumulado.pop(plotid, None)
        if plotid == self.atual:
            self.inicio = self.relogio()


def formatar_duracao(segundos: float) -> str:
    s = int(round(segundos))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


@dataclass
class Historico:
    """Pilha de desfazer: (plotid, valores anteriores ou None se era novo)."""

    itens: list[tuple[str, dict[str, Any] | None, dict[str, Any]]] = field(default_factory=list)
    limite: int = 50

    def empurrar(self, plotid: str, anterior: dict[str, Any] | None, gravado: dict[str, Any]) -> None:
        self.itens.append((plotid, anterior, gravado))
        del self.itens[: -self.limite]

    def desempilhar(self) -> tuple[str, dict[str, Any] | None, dict[str, Any]] | None:
        return self.itens.pop() if self.itens else None

    def __len__(self) -> int:
        return len(self.itens)


# ---- segunda passada e consenso ---------------------------------------------------------


def selecionar_segunda_passada(
    ids: list[str],
    valores_por_id: Mapping[str, Mapping[str, Any]],
    cond: CondicaoCampo | None,
    fracao_controle: float = 0.0,
    semente: str = "",
) -> tuple[list[str], list[str]]:
    """IDs da segunda passada cega: os que satisfazem ``cond`` (confiança baixa) e uma
    fração aleatória de controle dos demais respondidos.

    A amostra de controle é determinística para a mesma ``semente`` e o mesmo
    conjunto de respondidos: rode a segunda passada depois de concluir a primeira.
    """
    import random

    if not 0.0 <= fracao_controle <= 1.0:
        raise ValueError("fracao_controle deve estar entre 0 e 1")
    baixa = [i for i in ids if i in valores_por_id and cond is not None and cond.satisfeita(valores_por_id[i].get(cond.campo))]
    elegiveis = [i for i in ids if i in valores_por_id and i not in baixa]
    n = round(len(elegiveis) * fracao_controle)
    if fracao_controle > 0 and elegiveis and n == 0:
        n = 1
    rnd = random.Random(f"{semente}|controle|{len(elegiveis)}")
    controle = rnd.sample(elegiveis, n) if n else []
    posicao_csv = {pid: k for k, pid in enumerate(ids)}
    return baixa, sorted(controle, key=posicao_csv.__getitem__)


def divergencias(
    primeira: Mapping[str, Mapping[str, Any]],
    segunda: Mapping[str, Mapping[str, Any]],
    campo: str,
) -> list[str]:
    """IDs presentes nas duas passadas cujo ``campo`` difere (comparação como texto)."""
    return [pid for pid in segunda if pid in primeira and str(primeira[pid].get(campo)) != str(segunda[pid].get(campo))]


def ordem_consenso(
    ids: list[str],
    primeira: Mapping[str, Mapping[str, Any]],
    segunda: Mapping[str, Mapping[str, Any]],
    consenso_feito: Iterable[str],
    filtro: str,
    campo: str,
) -> list[str]:
    """Ordem (do CSV) no modo consenso: divergentes sem consenso, ou todos da segunda passada."""
    feitos = set(consenso_feito)
    if filtro == "todos_segunda":
        return [i for i in ids if i in segunda]
    if filtro == "divergentes":
        div = set(divergencias(primeira, segunda, campo))
        return [i for i in ids if i in div and i not in feitos]
    raise ValueError(f"filtro de consenso desconhecido: {filtro!r}")
