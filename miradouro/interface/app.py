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
VAR_PASSADA = "MIRADOURO_PASSADA"  # primeira (padrão) | segunda | consenso | dirigida
VAR_FRACAO = "MIRADOURO_FRACAO_CONTROLE"
VAR_LISTA = "MIRADOURO_LISTA"  # arquivo da lista de PLOTIDs (modo dirigida)
ROTULO_SALTO = "Ir para o ponto"


# ---- configuração e carga -------------------------------------------------------


def configuracao() -> tuple[str | None, str | None, str, float, str | None]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--projeto")
    parser.add_argument("--interprete")
    parser.add_argument("--passada", choices=["primeira", "segunda", "consenso", "dirigida"])
    parser.add_argument("--fracao-controle", type=float)
    parser.add_argument("--lista")
    args, _ = parser.parse_known_args(sys.argv[1:])
    passada = args.passada or os.environ.get(VAR_PASSADA) or "primeira"
    fracao = args.fracao_controle if args.fracao_controle is not None else float(os.environ.get(VAR_FRACAO) or 0.0)
    return (
        args.projeto or os.environ.get(VAR_PROJETO) or None,
        args.interprete or os.environ.get(VAR_INTERPRETE) or None,
        passada,
        fracao,
        args.lista or os.environ.get(VAR_LISTA) or None,
    )


@st.cache_resource(show_spinner=False)
def _carregar(caminho: str, _mtime: float):
    projeto = carregar_projeto(caminho)
    pontos = carregar_pontos(projeto.caminho_pontos)
    return projeto, pontos


# ---- estado -----------------------------------------------------------------------


def _campo_classe(projeto) -> str | None:
    return next((c.nome for c in projeto.campos if c.tipo == "classe"), None)


def _iniciar(projeto, pontos, interprete: str, passada: str = "primeira", fracao: float = 0.0, lista=None) -> None:
    ss = st.session_state
    if "arm" in ss:
        return
    ss.passada = passada
    ss.controle = set()
    ss.arm_segunda = None
    ss.lista = None
    ss.amostra = None
    extra_sessao = None
    if passada == "segunda":
        # Cega: lê a primeira passada só para escolher os pontos; grava em outra pasta.
        # A amostra sorteada fica persistida em segunda/amostra.json (`miradouro sortear`
        # ou o primeiro início deste modo) e é reutilizada tal qual nas sessões seguintes.
        pasta_segunda = projeto.pasta_saida / lg.PASTA_SEGUNDA
        amostra = lg.carregar_amostra_segunda(pasta_segunda)
        if amostra is None:
            primeira = Armazenamento(projeto, interprete=interprete)
            vals = {pid: r.valores for pid, r in primeira.todas().items()}
            amostra = lg.sortear_amostra_segunda(projeto, pontos.ids, vals, fracao, interprete_previsto=interprete)
            lg.gravar_amostra_segunda(pasta_segunda, amostra)
        ss.amostra = amostra
        ss.controle = set(amostra["controle"])
        selecionados = set(amostra["baixa"]) | ss.controle
        ss.ids = [i for i in pontos.ids if i in selecionados]
        ss.arm = Armazenamento(projeto, interprete=interprete, pasta=pasta_segunda)
        ss.filtros = lg.FILTROS_SEGUNDA
    elif passada == "dirigida":
        # Revisão dirigida: só a lista externa; a interface conhece apenas os PLOTIDs.
        ss.lista = lista
        ss.ids = list(lista.ids)
        ss.arm = Armazenamento(projeto, interprete=interprete)
        ss.filtros = lg.FILTROS_DIRIGIDA
        extra_sessao = {"modo": lg.MODO_DIRIGIDA, "lista": lista.carimbo()}
    elif passada == "consenso":
        ss.arm = Armazenamento(projeto, interprete=interprete)
        ss.arm_segunda = Armazenamento(projeto, interprete=interprete, pasta=projeto.pasta_saida / lg.PASTA_SEGUNDA)
        ss.ids = pontos.ids
        ss.filtros = lg.FILTROS_CONSENSO
    else:
        ss.arm = Armazenamento(projeto, interprete=interprete)
        ss.ids = pontos.ids
        ss.filtros = lg.FILTROS
    ss.arm.abrir_sessao(extra_sessao)
    ss.cache = CacheChips(projeto.pasta_chips)
    ss.mapa, ss.avisos_teclas = lg.mapa_de_atalhos(projeto)
    ss.filtro = next(iter(ss.filtros))
    ss.rascunhos = {}
    ss.cron = lg.Cronometro()
    ss.hist = lg.Historico()
    ss.ultimo_evento = None
    ss.erros = []
    ss.focar = None  # {"id", "rotulo"}: o componente de teclado rola até o campo e o foca
    ss.n_focar = 0
    ss.aviso = None
    if passada in ("consenso", "dirigida"):
        ordem = _ordem(projeto, pontos)
        ss.atual = ordem[0] if ordem else None
    else:
        ss.atual = lg.primeiro_pendente(ss.ids, ss.arm.respondidos())
    ss.cron.ir_para(ss.atual)


def _valores_por_id(arm=None) -> dict[str, dict]:
    arm = arm or st.session_state.arm
    return {pid: r.valores for pid, r in arm.todas().items()}


def _ordem(projeto, pontos) -> list[str]:
    ss = st.session_state
    if ss.passada == "consenso":
        feitos = [pid for pid, r in ss.arm.todas().items() if r.meta.get("consenso") is not None]
        return lg.ordem_consenso(ss.ids, _valores_por_id(ss.arm), _valores_por_id(ss.arm_segunda), feitos, ss.filtro, _campo_classe(projeto) or "")
    if ss.passada == "dirigida":
        metas = {pid: r.meta for pid, r in ss.arm.todas().items()}
        return lg.ordem_dirigida(ss.ids, metas, ss.filtro, ss.lista.sha256)
    return lg.ordem_visivel(ss.ids, _valores_por_id(), ss.filtro, projeto.condicao_revisao())


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
    prox = lg.vizinho(_ordem(projeto, pontos), ss.ids, ss.atual, passo)
    if prox is None:
        ss.aviso = "Fim da lista neste modo." if passo > 0 else "Início da lista."
    else:
        _ir_para(prox)


def _saltar(projeto, pontos) -> None:
    """Campo "Ir para o ponto": abre o PLOTID digitado, em qualquer modo."""
    ss = st.session_state
    entrada = ss.get("salto_widget", "")
    pid, aviso = lg.saltar_para(entrada, ss.ids, _ordem(projeto, pontos))
    if aviso:
        ss.aviso = aviso
    if pid is not None:
        _ir_para(pid)
    ss.salto_widget = ""


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
        nome = lg.campo_do_erro(erros[0])
        campo = projeto.campo(nome) if nome else None
        if campo is not None:
            ss.n_focar += 1
            ss.focar = {"id": ss.n_focar, "rotulo": _rotulo_widget(campo)}
        return
    anterior = ss.arm.obter(pid)
    faltantes = lg.provedores_faltantes(lg.chips_do_ponto(ss.cache, projeto.provedores_habilitados(), pid))
    meta = {"duracao_s": round(ss.cron.decorrido(pid), 1), "modo": ss.filtro, "interface": f"streamlit/{__version__}"}
    if faltantes:
        meta["sem_subsidio"] = faltantes
    if ss.passada == "segunda":
        meta["passada"] = 2
        if pid in ss.controle:
            meta["controle"] = True
    elif ss.passada == "dirigida":
        # Edições e confirmações sem mudança contam como revisão (revisoes+1 no núcleo).
        meta["modo"] = lg.MODO_DIRIGIDA
        meta["filtro"] = ss.filtro
        meta["lista"] = ss.lista.carimbo()
    elif ss.passada == "consenso":
        r1, r2 = ss.arm.obter(pid), ss.arm_segunda.obter(pid)
        meta["consenso"] = {
            "primeira": {"interprete": r1.interprete, "valores": r1.valores} if r1 else None,
            "segunda": {"interprete": r2.interprete, "valores": r2.valores} if r2 else None,
        }
    ss.arm.gravar(pid, valores, meta=meta)
    ss.hist.empurrar(pid, dict(anterior.valores) if anterior else None, valores)
    ss.rascunhos[pid] = dict(valores)
    ss.cron.zerar(pid)
    ss.erros = []
    ordem = _ordem(projeto, pontos)
    prox = lg.vizinho(ordem, ss.ids, pid, +1)
    if prox is not None:
        _ir_para(prox)
    elif pid in ordem:
        ss.aviso = "Resposta gravada. Era o último ponto da lista neste modo."
        _ir_para(pid)  # continua na lista (modo todos): fica visível, cronômetro reinicia
    else:
        # O ponto saiu da lista (pendentes/revisão) e não há próximo: descarrega e pausa o cronômetro.
        ss.aviso = "Resposta gravada. Não há mais pontos neste modo."
        _ir_para(None)


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
            lg.aplicar_atalho(_rascunho(ss.atual), x)
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


def _rotulo_widget(campo) -> str:
    obrig = campo.obrigatorio or (campo.obrigatorio_se is not None)
    return f"{campo.rotulo}{' *' if obrig else ''}"


def _widget_campo(projeto, campo, pid: str) -> None:
    ss = st.session_state
    mapa = ss.mapa
    rascunho = _rascunho(pid)
    chave = f"f_{campo.nome}"
    rotulo = _rotulo_widget(campo)
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
    elif campo.tipo == "multiopcao":
        opcoes = [o.valor for o in campo.opcoes]
        atuais = valor if isinstance(valor, list) else ([valor] if valor else [])
        ss[chave] = [v for v in atuais if v in opcoes]
        st.pills(
            rotulo, opcoes, selection_mode="multi", key=chave, help=ajuda,
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
        if ss.passada == "segunda":
            sorteio = f" Amostra sorteada em {str(ss.amostra.get('gerado_em', ''))[:10]}." if ss.amostra else ""
            st.warning(f"**Segunda passada (cega)** · {len(ss.ids)} pontos, {len(ss.controle)} de controle. As respostas da primeira passada não são mostradas.{sorteio}")
        elif ss.passada == "dirigida":
            st.warning(f"**Revisão dirigida** · {len(ss.ids)} pontos da lista `{ss.lista.nome}` (sha256 {ss.lista.sha256[:12]}). Cada confirmação conta como revisão.")
        elif ss.passada == "consenso":
            st.warning("**Consenso** · a decisão final vai para o arquivo principal, guardando as duas passadas na auditoria.")

        ss.filtro_widget = ss.filtro
        st.radio("Modo", list(ss.filtros), key="filtro_widget", format_func=ss.filtros.get, horizontal=True, on_change=_mudar_filtro, args=(projeto, pontos))
        st.text_input(ROTULO_SALTO, key="salto_widget", placeholder="PLOTID + Enter", on_change=_saltar, args=(projeto, pontos))

        ids = set(ss.ids)
        feitos = len(ss.arm.respondidos() & ids)
        nesta_sessao = sum(1 for r in ss.arm.todas().values() if r.sessao_id == ss.arm.sessao_id)
        st.progress(feitos / max(1, len(ids)), text=f"{feitos}/{len(ids)} respondidos · {nesta_sessao} nesta sessão")

        st.divider()
        pid = ss.atual
        if pid is None:
            st.success("Nenhum ponto neste modo. Troque o modo ou encerre a sessão.")
        else:
            if ss.erros:
                st.error("\n".join(f"- {e}" for e in ss.erros))
            for campo in lg.campos_visiveis(projeto, _rascunho(pid)):
                _widget_campo(projeto, campo, pid)
            classe_sel = next((_rascunho(pid).get(c.nome) for c in projeto.campos if c.tipo == "classe"), None)
            cls = projeto.classe(classe_sel) if classe_sel is not None else None
            if cls is not None and cls.descricao:
                with st.expander(f"Como reconhecer: {cls.rotulo}", expanded=False):
                    st.write(cls.descricao)

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
    cab1.subheader(f"PLOTID {pid} · ponto {n} de {total} ({ss.filtros[ss.filtro].lower()})")
    extras = " · ".join(f"{k}: {v}" for k, v in dados.items() if k not in ("PLOTID",))
    cab1.caption(extras)

    def _cronometro() -> None:
        st.caption(f"⏱ {lg.formatar_duracao(ss.cron.decorrido(pid))} neste ponto")

    # Fragmento que se atualiza sozinho a cada 2 s (não reexecuta o resto da página).
    fragmento = st.fragment(run_every="2s")(_cronometro)
    fragmento()

    resposta = ss.arm.obter(pid)
    if ss.passada == "consenso":
        r2 = ss.arm_segunda.obter(pid) if ss.arm_segunda else None
        col1, col2 = st.columns(2)
        for col, titulo, r in ((col1, "Primeira passada", resposta), (col2, "Segunda passada", r2)):
            if r is None:
                col.info(f"{titulo}: sem resposta")
                continue
            resumo = "\n".join(f"- {k} = {lg.formatar_valor(v)}" for k, v in r.valores.items())
            estado = " · **consenso registrado**" if r.meta.get("consenso") is not None else ""
            col.markdown(f"**{titulo}** ({r.interprete}, {r.atualizado_em[:16].replace('T', ' ')}){estado}\n{resumo}")
    elif resposta is not None:
        resumo = " · ".join(f"{k} = {lg.formatar_valor(v)}" for k, v in resposta.valores.items())
        revisto = " · **já revisto nesta lista**" if ss.passada == "dirigida" and lg.revisto_na_lista(resposta.meta, ss.lista.sha256) else ""
        st.success(f"Já respondido ({resposta.interprete}, {resposta.atualizado_em[:16].replace('T', ' ')}): {resumo}{revisto}")

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
    caminho, interprete_cli, passada, fracao, caminho_lista = configuracao()
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
    if passada == "consenso" and not (projeto.pasta_saida / lg.PASTA_SEGUNDA / "respostas.json").exists():
        st.error(f"Modo consenso exige a segunda passada em {projeto.pasta_saida / lg.PASTA_SEGUNDA}.")
        st.stop()
        return
    lista = None
    if passada == "dirigida":
        try:
            lista = lg.carregar_lista_plotids(caminho_lista or "", pontos.ids)
        except ErroMiradouro as e:
            st.error(str(e))
            st.stop()
            return
        if lista.desconhecidos:
            st.error(f"Lista {lista.nome}: PLOTID(s) que não existem no projeto: {', '.join(lista.desconhecidos)}. Corrija o arquivo.")
            st.stop()
            return
    _iniciar(projeto, pontos, interprete, passada, fracao, lista)

    rotulos_texto = [_rotulo_widget(c) for c in projeto.campos if c.tipo in ("texto", "numero")]
    focar_antes = st.session_state.focar
    evento = capturar_tecla(rotulos_texto=rotulos_texto, focar=focar_antes, rotulos_sem_confirmar=[ROTULO_SALTO])
    _processar_evento(projeto, pontos, evento)
    if st.session_state.focar != focar_antes:
        # O componente já foi renderizado com o foco antigo: reexecuta uma vez para
        # entregar o novo pedido de foco (o evento de teclado é deduplicado pelo id).
        st.rerun()

    _render_sidebar(projeto, pontos, interprete)
    _render_principal(projeto, pontos)


if __name__ == "__main__":  # o Streamlit (e o AppTest) executam este arquivo como script
    main()
