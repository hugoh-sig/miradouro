"""Linha de comando: ``python -m miradouro <comando> ...``.

Comandos do Sprint 1:

* ``projeto validar <projeto.yaml>`` — valida yaml e CSV, resume o projeto.
* ``chips listar`` — provedores registrados.
* ``chips gerar <projeto.yaml>`` — pré-computa os chips em lote (com cache).
* ``chips status <projeto.yaml>`` — quantos chips já existem por provedor.
* ``app <projeto.yaml> [--interprete id]`` — interface de interpretação (Streamlit).
* ``exportar acatama <projeto.yaml> --mapa raster.tif`` — yml + GeoJSON + CSV para o AcATaMa.
* ``exportar csv <projeto.yaml>`` — tabela plana de referência (versionável).
* ``relatorio <projeto.yaml>`` — relatório de sessão em Markdown + JSON.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from miradouro import __version__
from miradouro.core.erros import ErroMiradouro
from miradouro.core.pontos import carregar_pontos
from miradouro.core.projeto import carregar_projeto

log = logging.getLogger("miradouro")

CODIGO_OK = 0
CODIGO_ERRO = 1
CODIGO_FALHAS_PARCIAIS = 3


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="miradouro",
        description="MIRADOURO — fotointerpretação de pontos de validação.",
    )
    p.add_argument("--versao", action="version", version=f"miradouro {__version__}")
    p.add_argument("-v", "--verboso", action="store_true", help="log detalhado")
    sub = p.add_subparsers(dest="comando", required=True)

    # projeto
    proj = sub.add_parser("projeto", help="operações sobre o projeto.yaml")
    proj_sub = proj.add_subparsers(dest="subcomando", required=True)
    val = proj_sub.add_parser("validar", help="valida projeto.yaml e pontos.csv")
    val.add_argument("projeto", help="caminho do projeto.yaml")

    # chips
    chips = sub.add_parser("chips", help="pré-computação de chips")
    chips_sub = chips.add_subparsers(dest="subcomando", required=True)
    chips_sub.add_parser("listar", help="lista os provedores registrados")

    ger = chips_sub.add_parser("gerar", help="gera os chips de todos os pontos (com cache)")
    ger.add_argument("projeto", help="caminho do projeto.yaml")
    ger.add_argument("--forcar", action="store_true", help="regera chips já existentes")
    ger.add_argument("--paralelo", type=int, default=1, metavar="N", help="tarefas simultâneas (padrão 1)")
    ger.add_argument("--limite", type=int, default=None, metavar="N", help="só os N primeiros pontos")
    ger.add_argument("--plotid", nargs="+", default=None, metavar="ID", help="só estes PLOTIDs")
    ger.add_argument("--provedor", nargs="+", default=None, metavar="NOME", help="só estes provedores")
    ger.add_argument("--sem-barra", action="store_true", help="sem barra de progresso (logs/CI)")

    st = chips_sub.add_parser("status", help="chips existentes por provedor")
    st.add_argument("projeto", help="caminho do projeto.yaml")

    # exportar
    exp = sub.add_parser("exportar", help="exporta respostas")
    exp_sub = exp.add_subparsers(dest="subcomando", required=True)
    for nome_sub, ajuda in (("acatama", "configuração restaurável do AcATaMa + camada de pontos + CSV"), ("csv", "tabela plana de referência")):
        e = exp_sub.add_parser(nome_sub, help=ajuda)
        e.add_argument("projeto", help="caminho do projeto.yaml")
        e.add_argument("--respostas", default=None, metavar="PASTA", help="pasta de saída com respostas.json (padrão: saida.pasta do yaml)")
        e.add_argument("--filtro", action="append", default=[], metavar="COLUNA=VALOR", help="só pontos com esse valor na coluna do CSV (repetível)")
        e.add_argument("--saida", default=None, metavar="PASTA", help="pasta de destino (padrão: <saida>/exportacao/<nome>)")
        e.add_argument("--nome", default=None, metavar="NOME", help="prefixo dos arquivos (padrão: acatama ou referencia)")
        e.add_argument("--incluir-pendentes", action="store_true", help="inclui pontos sem resposta")
        if nome_sub == "acatama":
            e.add_argument("--mapa", required=True, metavar="RASTER", help="raster do mapa temático (classes = códigos da legenda)")
            e.add_argument("--banda", type=int, default=1)
            e.add_argument("--nodata", type=int, default=None, metavar="N", help="nodata do raster (padrão: tag do GeoTIFF; obrigatório se o raster não tiver tag)")
            e.add_argument("--crs", default=None, metavar="EPSG:XXXX", help="CRS da camada de pontos (padrão WGS84)")
            e.add_argument("--versao-acatama", default=None, metavar="V", help="config_file_version gravada no yml")

    # relatorio
    rel = sub.add_parser("relatorio", help="relatório de sessão (Markdown + JSON)")
    rel.add_argument("projeto", help="caminho do projeto.yaml")
    rel.add_argument("--respostas", default=None, metavar="PASTA", help="pasta com respostas.json (padrão: saida.pasta do yaml)")
    rel.add_argument("--segunda", default=None, metavar="PASTA", help="pasta da segunda passada (padrão: <respostas>/segunda, se existir)")
    rel.add_argument("--com-mapa", action="store_true", help="inclui cruzamento com a classe do mapa (coluna oculta) — só após a interpretação")
    rel.add_argument("--saida", default=None, metavar="PASTA", help="pasta de destino (padrão: <respostas>/relatorios)")
    rel.add_argument("--nome", default=None, metavar="NOME", help="nome dos arquivos (padrão: relatorio_<timestamp>)")

    # app
    app = sub.add_parser("app", help="abre a interface de interpretação (Streamlit)")
    app.add_argument("projeto", help="caminho do projeto.yaml")
    app.add_argument("--interprete", default=None, metavar="ID", help="id do intérprete (senão a interface pergunta)")
    app.add_argument("--porta", type=int, default=8501, metavar="N", help="porta do servidor (padrão 8501)")
    app.add_argument("--sem-navegador", action="store_true", help="não abre o navegador automaticamente")
    grupo = app.add_mutually_exclusive_group()
    grupo.add_argument("--segunda-passada", action="store_true", help="segunda interpretação cega dos pontos de confiança baixa (grava em <saida>/segunda)")
    grupo.add_argument("--consenso", action="store_true", help="resolve divergências entre as duas passadas no arquivo principal")
    app.add_argument("--fracao-controle", type=float, default=0.0, metavar="F", help="na segunda passada, fração aleatória de controle dos demais pontos (ex.: 0.05)")
    return p


def _configurar_log(verboso: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if not verboso:
        # Bibliotecas de rede são ruidosas em INFO.
        for nome in ("urllib3", "googleapiclient", "requests"):
            logging.getLogger(nome).setLevel(logging.WARNING)


# ---- comandos ----------------------------------------------------------------


def cmd_projeto_validar(args: argparse.Namespace) -> int:
    projeto = carregar_projeto(args.projeto)
    pontos = carregar_pontos(projeto.caminho_pontos)
    ocultas_ausentes = [c for c in projeto.pontos.colunas_ocultas if c not in pontos.colunas]
    print(f"Projeto: {projeto.nome} (ano de referência {projeto.ano_referencia})")
    print(f"  yaml:     {projeto.caminho_yaml}  sha256 {projeto.hash_yaml[:12] if projeto.hash_yaml else '-'}")
    print(f"  pontos:   {len(pontos)} em {pontos.caminho}")
    print(f"  colunas extras: {pontos.colunas_extras or '-'}")
    print(f"  ocultas ao intérprete: {projeto.pontos.colunas_ocultas or '-'}")
    if ocultas_ausentes:
        print(f"  AVISO: colunas ocultas que não existem no CSV: {ocultas_ausentes}")
    print(f"  legenda:  {len(projeto.legenda)} classes")
    for c in projeto.legenda:
        print(f"    [{c.tecla}] {c.codigo:>4}  {c.rotulo}")
    print(f"  campos:   {len(projeto.campos)}")
    for c in projeto.campos:
        obrig = "obrigatório" if c.obrigatorio else ("condicional" if c.condicional else "opcional")
        print(f"    {c.nome:<20} {c.tipo:<9} {obrig}")
    print(f"  provedores de chips: {projeto.provedores_habilitados() or '-'}")
    print(f"  pasta de chips: {projeto.pasta_chips}")
    print(f"  pasta de saída: {projeto.pasta_saida}")
    print("OK")
    return CODIGO_OK


def cmd_chips_listar(_: argparse.Namespace) -> int:
    from miradouro.chips import provedores_disponiveis

    for nome, cls in sorted(provedores_disponiveis().items()):
        print(f"{nome:<14} {cls.descricao}")
    return CODIGO_OK


def cmd_chips_status(args: argparse.Namespace) -> int:
    from miradouro.chips import CacheChips, obter_provedor

    projeto = carregar_projeto(args.projeto)
    pontos = carregar_pontos(projeto.caminho_pontos)
    cache = CacheChips(projeto.pasta_chips)
    print(f"Chips em {cache.pasta} ({len(pontos)} pontos):")
    for nome in projeto.provedores_habilitados():
        versao = obter_provedor(nome).versao
        atuais = sum(1 for p in pontos if cache.existe(nome, p.plotid, versao))
        antigos = sum(1 for p in pontos if cache.existe(nome, p.plotid)) - atuais
        aviso = f"  ({antigos} de versão antiga, serão regerados)" if antigos else ""
        print(f"  {nome:<14} {atuais}/{len(pontos)}  v{versao}{aviso}")
    return CODIGO_OK


def cmd_chips_gerar(args: argparse.Namespace) -> int:
    from miradouro.chips import CacheChips, gerar_chips, instanciar_provedores

    projeto = carregar_projeto(args.projeto)
    conjunto = carregar_pontos(projeto.caminho_pontos)
    pontos = list(conjunto)
    if args.plotid:
        pedidos = [str(i) for i in args.plotid]
        desconhecidos = [i for i in pedidos if i not in conjunto]
        if desconhecidos:
            raise ErroMiradouro(f"PLOTID(s) não encontrado(s) no CSV: {desconhecidos}")
        pontos = [conjunto.obter(i) for i in pedidos]
    if args.limite is not None:
        pontos = pontos[: args.limite]

    provedores = instanciar_provedores(projeto, apenas=args.provedor)
    if not provedores:
        raise ErroMiradouro("nenhum provedor de chips habilitado em `chips.provedores` do projeto")
    cache = CacheChips(projeto.pasta_chips)

    print(
        f"Gerando chips: {len(pontos)} pontos × {len(provedores)} provedores "
        f"({', '.join(p.nome for p in provedores)}) → {cache.pasta}",
        file=sys.stderr,
    )

    barra = None
    if not args.sem_barra:
        from tqdm import tqdm

        barra = tqdm(total=0, unit="chip", dynamic_ncols=True, file=sys.stderr)

    def progresso(feitos: int, total: int) -> None:
        if barra is not None:
            barra.total = total
            barra.n = feitos
            barra.refresh()

    try:
        resultado = gerar_chips(
            projeto, pontos, provedores, cache, forcar=args.forcar, paralelo=args.paralelo, progresso=progresso
        )
    finally:
        if barra is not None:
            barra.close()

    print(f"Concluído: {resultado.resumo()}", file=sys.stderr)
    if resultado.falhas:
        print(f"Falhas registradas em {cache.pasta / 'erros.log'}:", file=sys.stderr)
        for f in resultado.falhas[:20]:
            print(f"  {f.provedor}/{f.plotid}: {f.erro}", file=sys.stderr)
        if len(resultado.falhas) > 20:
            print(f"  ... e mais {len(resultado.falhas) - 20}", file=sys.stderr)
        return CODIGO_FALHAS_PARCIAIS
    return CODIGO_OK


def _abrir_respostas(args: argparse.Namespace):
    from miradouro.core.respostas import Armazenamento

    projeto = carregar_projeto(args.projeto)
    pontos = carregar_pontos(projeto.caminho_pontos)
    arm = Armazenamento(projeto, interprete="exportacao", pasta=args.respostas)
    if not arm.arquivo.exists():
        raise ErroMiradouro(f"não há respostas em {arm.arquivo}")
    return projeto, pontos, arm


def cmd_exportar_acatama(args: argparse.Namespace) -> int:
    from miradouro.exportacao.acatama import VERSAO_ACATAMA_PADRAO, exportar_acatama
    from miradouro.exportacao.tabela import parse_filtro

    projeto, pontos, arm = _abrir_respostas(args)
    nome = args.nome or "acatama"
    saida = Path(args.saida) if args.saida else arm.pasta / "exportacao" / nome
    r = exportar_acatama(
        projeto, pontos, arm, mapa=args.mapa, saida=saida, nome=nome, banda=args.banda, nodata=args.nodata,
        filtro=parse_filtro(args.filtro), crs=args.crs, incluir_pendentes=args.incluir_pendentes,
        versao_acatama=args.versao_acatama or VERSAO_ACATAMA_PADRAO,
    )
    print(f"AcATaMa: {r.resumo()}")
    for f in (r.yml, r.geojson, r.csv):
        print(f"  {f}")
    for a in r.avisos:
        print(f"  AVISO: {a}")
    print("No QGIS: AcATaMa → Restore configuration → escolha o .yml (o raster e a camada são carregados por ele).")
    return CODIGO_OK


def cmd_exportar_csv(args: argparse.Namespace) -> int:
    from miradouro.exportacao.tabela import (
        colunas_referencia,
        escrever_csv,
        linhas_referencia,
        parse_filtro,
    )

    projeto, pontos, arm = _abrir_respostas(args)
    nome = args.nome or "referencia"
    saida = Path(args.saida) if args.saida else arm.pasta / "exportacao"
    saida.mkdir(parents=True, exist_ok=True)
    linhas = linhas_referencia(projeto, pontos, arm, filtro=parse_filtro(args.filtro), apenas_respondidos=not args.incluir_pendentes, apenas_completas=False)
    destino = escrever_csv(linhas, colunas_referencia(projeto, pontos), saida / f"{nome}.csv")
    print(f"CSV: {len(linhas)} linhas → {destino}")
    return CODIGO_OK


def cmd_relatorio(args: argparse.Namespace) -> int:
    from miradouro.core.respostas import Armazenamento
    from miradouro.exportacao.relatorio import gerar_relatorio
    from miradouro.interface.logica import PASTA_SEGUNDA

    projeto, pontos, arm = _abrir_respostas(args)
    pasta_segunda = Path(args.segunda) if args.segunda else arm.pasta / PASTA_SEGUNDA
    segunda = None
    if (pasta_segunda / "respostas.json").exists():
        segunda = Armazenamento(projeto, interprete="relatorio", pasta=pasta_segunda)
    elif args.segunda:
        raise ErroMiradouro(f"não há respostas da segunda passada em {pasta_segunda}")
    saida = Path(args.saida) if args.saida else arm.pasta / "relatorios"
    md, js = gerar_relatorio(projeto, pontos, arm, saida, com_mapa=args.com_mapa, segunda=segunda, nome=args.nome)
    print(f"Relatório: {md}\n          {js}")
    if args.com_mapa:
        print("AVISO: o relatório contém a classe do mapa; não abra durante a interpretação.")
    return CODIGO_OK


def cmd_app(args: argparse.Namespace) -> int:
    import subprocess

    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise ErroMiradouro("streamlit não instalado: pip install 'miradouro[app]'") from None
    projeto = carregar_projeto(args.projeto)
    carregar_pontos(projeto.caminho_pontos)  # falha cedo se o CSV estiver quebrado
    import miradouro.interface

    caminho_app = Path(miradouro.interface.__file__).parent / "app.py"
    comando = [
        sys.executable, "-m", "streamlit", "run", str(caminho_app),
        "--server.port", str(args.porta),
        "--browser.gatherUsageStats", "false",
        "--server.headless", "true" if args.sem_navegador else "false",
        "--", "--projeto", str(projeto.caminho_yaml),
    ]
    if args.interprete:
        comando += ["--interprete", args.interprete]
    if args.segunda_passada:
        if not (0.0 <= args.fracao_controle <= 1.0):
            raise ErroMiradouro("--fracao-controle deve estar entre 0 e 1")
        comando += ["--passada", "segunda", "--fracao-controle", str(args.fracao_controle)]
    elif args.consenso:
        from miradouro.interface.logica import PASTA_SEGUNDA

        if not (projeto.pasta_saida / PASTA_SEGUNDA / "respostas.json").exists():
            raise ErroMiradouro(f"--consenso exige a segunda passada em {projeto.pasta_saida / PASTA_SEGUNDA}")
        comando += ["--passada", "consenso"]
    print(f"Abrindo a interface para {projeto.nome} em http://localhost:{args.porta}", file=sys.stderr)
    return subprocess.call(comando)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _configurar_log(args.verboso)
    comandos = {
        ("projeto", "validar"): cmd_projeto_validar,
        ("chips", "listar"): cmd_chips_listar,
        ("chips", "gerar"): cmd_chips_gerar,
        ("chips", "status"): cmd_chips_status,
        ("app", None): cmd_app,
        ("exportar", "acatama"): cmd_exportar_acatama,
        ("exportar", "csv"): cmd_exportar_csv,
        ("relatorio", None): cmd_relatorio,
    }
    funcao = comandos[(args.comando, getattr(args, "subcomando", None))]
    try:
        return funcao(args)
    except ErroMiradouro as e:
        print(f"erro: {e}", file=sys.stderr)
        return CODIGO_ERRO
    except KeyboardInterrupt:
        print("interrompido", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
