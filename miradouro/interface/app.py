"""Casca Streamlit da interface de interpretação.

Rode via ``python -m miradouro app projeto.yaml [--interprete id]``. O script lê
``--projeto``/``--interprete`` de ``sys.argv`` (depois de ``--``) ou das
variáveis de ambiente ``MIRADOURO_PROJETO``/``MIRADOURO_INTERPRETE``.

Toda a lógica está em :mod:`miradouro.interface.logica`; aqui só há
renderização e estado de sessão.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

import streamlit as st

from miradouro import __version__
from miradouro.chips.cache import CacheChips
from miradouro.core import (
    Armazenamento,
    ErroMiradouro,
    carregar_pontos,
    carregar_projeto,
    validar_resposta,
)
from miradouro.interface import logica as lg
from miradouro.interface.teclado import capturar_tecla

VAR_PROJETO = "MIRADOURO_PROJETO"
VAR_INTERPRETE = "MIRADOURO_INTERPRETE"


# ---- configuração e carga -------------------------------------------------------


def configuracao() -> tuple[str | None, str | None]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--projeto")
    parser.add_argument("--interprete")
    args, _ = parser.parse_known_args(sys.argv[1:])
    return (args.projeto or os.environ.get(VAR_PROJETO) or None, args.interprete or os.environ.get(VAR_INTERPRETE) or None)


@st.cache_resource(show_spinner=False)
def _carregar(caminho: str, _mtime: float):
    projeto = carregar_projeto(caminho)
    pontos = carregar_pontos(projeto.caminho_pontos)
    return projeto, pontos


# ---- estado -----------------------------------------------------------------------


def _iniciar(projeto, pontos, interprete: str) -> None:
    ss = st.session_state
    if "arm" in ss:
        return
    ss.arm = Armazenamento(projeto, interprete=interprete)
    ss.arm.abrir_sessao()
    ss.cache = CacheChips(projeto.pasta_chips)
    ss.mapa, ss.avisos_teclas = lg.mapa_de_atalhos(projeto)
    ss.filtro = "pendentes"
    ss.rascunhos = {}
    ss.cron = lg.Cronometro()
    ss.hist = lg.Historico()
    ss.ultimo_evento = None
    ss.erros = []
    ss.aviso = None
    ss.atual = lg.primeiro_pendente(pontos.ids, ss.arm.respondidos())
    ss.cron.ir_para(ss.atual)


def _valores_por_id() -> dict[str, dict]:
    return {pid: r.valores for pid, r in st.session_state.arm.todas().items()}


def _ordem(projeto, pontos) -> list[str]:
    return lg.ordem_visivel(pontos.ids, _valores_por_id(), st.session_state.filtro, projeto.condicao_revisao())


def _rascunho(pid: str) -> dict:
    ss = st.session_state
    if pid not in ss.rascunhos:
        r = ss.arm.obter(pid)
        ss.rascunhos[pid] = dict(r.valores) if r else {}
    return ss.rascunhos[pid]


def _ir_para(pid: str | None) -> None:
    ss = st.session_state
    ss.atual = pid
    ss.cron.ir_para(pid)
    ss.erros = []


def _navegar(projeto, pontos, passo: int) -> None:
    ss = st.session_state
    prox = lg.vizinho(_ordem(projeto, pontos), pontos.ids, ss.atual, passo)
    if prox is None:
        ss.aviso = "Fim da lista neste modo." if passo > 0 else "Início da lista."
    else:
        _ir_para(prox)


def _mudar_filtro(projeto, pontos) -> None:
    ss = st.session_state
    ss.filtro = ss.filtro_widget
    ordem = _ordem(projeto, pontos)
    if ss.atual not in ordem:
        _ir_para(ordem[0] if ordem else None)


def _confirmar(projeto, pontos) -> None:
    ss = st.session_state
    pid = ss.atual
    if pid is None:
        return
    valores = lg.limpar_valores_ocultos(projeto, _rascunho(pid))
    erros = validar_resposta(projeto, valores)
    if erros:
        ss.erros = erros
        return
    anterior = ss.arm.obter(pid)
    faltantes = lg.provedores_faltantes(lg.chips_do_ponto(ss.cache, projeto.provedores_habilitados(), pid))
    meta = {"duracao_s": round(ss.cron.decorrido(pid), 1), "modo": ss.filtro, "interface": f"streamlit/{__version__}"}
    if faltantes:
        meta["sem_subsidio"] = faltantes
    ss.arm.gravar(pid, valores, meta=meta)
    ss.hist.empurrar(pid, dict(anterior.valores) if anterior else None, valores)
    ss.rascunhos[pid] = dict(valores)
    ss.cron.zerar(pid)
    ss.erros = []
    prox = lg.vizinho(_ordem(projeto, pontos), pontos.ids, pid, +1)
    if prox is None:
        ss.aviso = "Resposta gravada. Fim da lista neste modo."
        if ss.filtro == "pendentes":
            _ir_para(None)
    else:
        _ir_para(prox)


def _desfazer() -> None:
    ss = st.session_state
    item = ss.hist.desempilhar()
    if item is None:
        ss.aviso = "Nada a desfazer."
        return
    pid, anterior, gravado = item
    if anterior is None:
        ss.arm.remover(pid)
    else:
        ss.arm.gravar(pid, anterior, validar=False, meta={"desfeito": True})
    ss.rascunhos[pid] = dict(gravado)
    ss.aviso = f"Resposta de {pid} desfeita; revise e confirme de novo."
    _ir_para(pid)


def _limpar() -> None:
    ss = st.session_state
    if ss.atual is not None:
        ss.rascunhos[ss.atual] = {}
        ss.erros = []


def _processar_evento(projeto, pontos, evento: dict | None) -> None:
    ss = st.session_state
    if not evento or evento.get("id") == ss.ultimo_evento:
        return
    ss.ultimo_evento = evento.get("id")
    resultado = lg.interpretar_tecla(lg.normalizar_tecla(lg.Tecla.de_dict(evento)), ss.mapa)
    if resultado is None:
        return
    tipo, x = resultado
    if tipo == "atalho":
        if ss.atual is not None:
            _rascunho(ss.atual)[x.campo] = x.valor
            ss.erros = []
        return
    acoes = {
        "confirmar": lambda: _confirmar(projeto, pontos),
        "proximo": lambda: _navegar(projeto, pontos, +1),
        "anterior": lambda: _navegar(projeto, pontos, -1),
        "desfazer": _desfazer,
        "limpar": _limpar,
    }
    acoes[x]()


# ---- formulário --------------------------------------------------------------------


def _ao_mudar(pid: str, campo: str) -> None:
    ss = st.session_state
    _rascunho(pid)[campo] = ss[f"f_{campo}"]
    ss.erros = []


def _widget_campo(projeto, campo, pid: str) -> None:
    ss = st.session_state
    mapa = ss.mapa
    rascunho = _rascunho(pid)
    chave = f"f_{campo.nome}"
    obrig = campo.obrigatorio or (campo.obrigatorio_se is not None)
    rotulo = f"{campo.rotulo}{' *' if obrig else ''}"
    ajuda = campo.ajuda or None
    valor = rascunho.get(campo.nome)

    if campo.tipo == "classe":
        opcoes = [c.codigo for c in projeto.legenda]
        ss[chave] = valor if valor in opcoes else None
        st.radio(
            rotulo, opcoes, key=chave, help=ajuda,
            format_func=lambda v: lg.rotulo_com_tecla(mapa, campo.nome, v, projeto.classe(v).rotulo),
            on_change=_ao_mudar, args=(pid, campo.nome),
        )
    elif campo.tipo == "opcao":
        opcoes = [o.valor for o in campo.opcoes]
        ss[chave] = valor if valor in opcoes else None
        st.radio(
            rotulo, opcoes, key=chave, help=ajuda, horizontal=len(opcoes) <= 4,
            format_func=lambda v: lg.rotulo_com_tecla(mapa, campo.nome, v, next(o.rotulo for o in campo.opcoes if o.valor == v)),
            on_change=_ao_mudar, args=(pid, campo.nome),
        )
    elif campo.tipo == "booleano":
        ss[chave] = bool(valor) if valor is not None else False
        st.checkbox(rotulo, key=chave, help=ajuda, on_change=_ao_mudar, args=(pid, campo.nome))
    else:  # texto, numero
        ss[chave] = "" if valor is None else str(valor)
        st.text_input(rotulo, key=chave, help=ajuda, placeholder=campo.padrao or None, on_change=_ao_mudar, args=(pid, campo.nome))


def _render_sidebar(projeto, pontos, interprete: str) -> None:
    ss = st.session_state
    with st.sidebar:
        st.markdown(f"**MIRADOURO** · {projeto.nome}")
        st.caption(f"Intérprete **{interprete}** · sessão {ss.arm.sessao_id} · ano de referência {projeto.ano_referencia}")

        ss.filtro_widget = ss.filtro
        st.radio("Modo", list(lg.FILTROS), key="filtro_widget", format_func=lg.FILTROS.get, horizontal=True, on_change=_mudar_filtro, args=(projeto, pontos))

        ids = set(pontos.ids)
        feitos = len(ss.arm.respondidos() & ids)
        nesta_sessao = sum(1 for r in ss.arm.todas().values() if r.sessao_id == ss.arm.sessao_id)
        st.progress(feitos / max(1, len(ids)), text=f"{feitos}/{len(ids)} respondidos · {nesta_sessao} nesta sessão")

        st.divider()
        pid = ss.atual
        if pid is None:
            st.success("Nenhum ponto neste modo. Troque o modo ou encerre a sessão.")
        else:
            for campo in lg.campos_visiveis(projeto, _rascunho(pid)):
                _widget_campo(projeto, campo, pid)
            classe_sel = next((_rascunho(pid).get(c.nome) for c in projeto.campos if c.tipo == "classe"), None)
            cls = projeto.classe(classe_sel) if classe_sel is not None else None
            if cls is not None and cls.descricao:
                with st.expander(f"Como reconhecer: {cls.rotulo}", expanded=False):
                    st.write(cls.descricao)

            if ss.erros:
                st.error("\n".join(f"- {e}" for e in ss.erros))
            c1, c2 = st.columns(2)
            c1.button("Confirmar ⏎", type="primary", width="stretch", on_click=_confirmar, args=(projeto, pontos))
            c2.button("Desfazer (U)", width="stretch", on_click=_desfazer)
            c3, c4, c5 = st.columns(3)
            c3.button("◀ Anterior", width="stretch", on_click=_navegar, args=(projeto, pontos, -1))
            c4.button("Próximo ▶", width="stretch", on_click=_navegar, args=(projeto, pontos, +1))
            c5.button("Limpar", width="stretch", on_click=_limpar)

        st.divider()
        st.caption(lg.TEXTO_ACOES)
        st.caption("Classe alternativa: ⇧ + tecla da classe.")
        for aviso in ss.avisos_teclas:
            st.warning(aviso)
        st.caption(f"miradouro {__version__}")


# ---- área principal ----------------------------------------------------------------


def _render_principal(projeto, pontos) -> None:
    ss = st.session_state
    if ss.aviso:
        st.info(ss.aviso)
        ss.aviso = None
    pid = ss.atual
    if pid is None:
        st.title("MIRADOURO")
        st.write("Nenhum ponto selecionado neste modo.")
        return
    ponto = pontos.obter(pid)
    ordem = _ordem(projeto, pontos)
    n, total = lg.posicao(ordem, pid)
    dados = lg.dados_visiveis_do_ponto(ponto, projeto)

    cab1, cab2 = st.columns([5, 1])
    cab1.subheader(f"PLOTID {pid} · ponto {n} de {total} ({lg.FILTROS[ss.filtro].lower()})")
    extras = " · ".join(f"{k}: {v}" for k, v in dados.items() if k not in ("PLOTID",))
    cab1.caption(extras)

    def _cronometro() -> None:
        st.caption(f"⏱ {lg.formatar_duracao(ss.cron.decorrido(pid))} neste ponto")

    # Fragmento que se atualiza sozinho a cada 2 s (não reexecuta o resto da página).
    fragmento = st.fragment(run_every="2s")(_cronometro)
    fragmento()

    resposta = ss.arm.obter(pid)
    if resposta is not None:
        resumo = " · ".join(f"{k} = {v}" for k, v in resposta.valores.items())
        st.success(f"Já respondido ({resposta.interprete}, {resposta.atualizado_em[:16].replace('T', ' ')}): {resumo}")

    provedores = projeto.provedores_habilitados()
    chips = lg.chips_do_ponto(ss.cache, provedores, pid)
    faltantes = lg.provedores_faltantes(chips)
    if faltantes:
        st.warning(
            f"**Sem subsídio pré-computado** para: {', '.join(faltantes)}. "
            "Rode `python -m miradouro chips gerar` ou consulte `chips/erros.log`. "
            "Você pode pular (→) ou responder mesmo assim; a falta fica registrada na auditoria."
        )
    existentes = [(nome, caminho) for nome, caminho in chips.items() if caminho is not None]
    if not existentes:
        return
    if len(existentes) == 1:
        st.image(str(existentes[0][1]), width="stretch")
        return
    col_a, col_b = st.columns(2)
    col_a.image(str(existentes[0][1]), width="stretch")
    col_b.image(str(existentes[1][1]), width="stretch")
    for _, caminho in existentes[2:]:
        st.image(str(caminho), width="stretch")


# ---- entrada -------------------------------------------------------------------------


def _pedir_interprete(sugestao: str) -> None:
    st.title("MIRADOURO")
    st.write("Identifique-se para começar. O id fica gravado em cada resposta.")
    valor = st.text_input("Id do intérprete", value=sugestao, key="interprete_input")
    if st.button("Começar", type="primary") and valor.strip():
        st.session_state.interprete = valor.strip()
        st.rerun()
    st.stop()


def main() -> None:
    caminho, interprete_cli = configuracao()
    if not caminho:
        st.set_page_config(page_title="MIRADOURO")
        st.error(f"Informe o projeto: `python -m miradouro app projeto.yaml` (ou variável {VAR_PROJETO}).")
        st.stop()
    try:
        projeto, pontos = _carregar(str(Path(caminho).resolve()), Path(caminho).stat().st_mtime)
    except (ErroMiradouro, OSError) as e:
        st.set_page_config(page_title="MIRADOURO")
        st.error(str(e))
        st.stop()
        return
    st.set_page_config(page_title=f"MIRADOURO · {projeto.nome}", page_icon="🔭", layout="wide", initial_sidebar_state="expanded")

    interprete = interprete_cli or st.session_state.get("interprete")
    if not interprete:
        _pedir_interprete(getpass.getuser())
        return
    _iniciar(projeto, pontos, interprete)

    rotulos_texto = [c.rotulo + " *" if (c.obrigatorio or c.obrigatorio_se) else c.rotulo for c in projeto.campos if c.tipo in ("texto", "numero")]
    evento = capturar_tecla(rotulos_texto=rotulos_texto)
    _processar_evento(projeto, pontos, evento)

    _render_sidebar(projeto, pontos, interprete)
    _render_principal(projeto, pontos)


if __name__ == "__main__":  # o Streamlit (e o AppTest) executam este arquivo como script
    main()
