"""Motor de lote: percorre pontos × provedores, respeita o cache e tolera falhas."""

from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from miradouro.chips.base import ErroProvedor, PedidoChip, ProvedorChip, obter_provedor
from miradouro.chips.cache import CacheChips
from miradouro.core.pontos import Ponto
from miradouro.core.projeto import Projeto

log = logging.getLogger(__name__)

NOME_LOG_ERROS = "erros.log"


@dataclass(frozen=True)
class Falha:
    plotid: str
    provedor: str
    erro: str


@dataclass
class ResultadoLote:
    gerados: int = 0
    em_cache: int = 0
    desatualizados: int = 0  # existiam em cache com versão antiga e foram regerados
    falhas: list[Falha] = field(default_factory=list)
    duracao_s: float = 0.0

    @property
    def total(self) -> int:
        return self.gerados + self.em_cache + len(self.falhas)

    def resumo(self) -> str:
        extra = f" ({self.desatualizados} regerados por versão nova)" if self.desatualizados else ""
        return (
            f"{self.gerados} gerados{extra}, {self.em_cache} já em cache, "
            f"{len(self.falhas)} falhas em {self.duracao_s:.0f}s"
        )


def instanciar_provedores(projeto: Projeto, apenas: Iterable[str] | None = None) -> list[ProvedorChip]:
    """Cria os provedores habilitados no yaml (opcionalmente só os nomes em ``apenas``)."""
    nomes = list(projeto.chips.provedores)
    if apenas is not None:
        apenas = list(apenas)
        desconhecidos = [n for n in apenas if n not in nomes]
        if desconhecidos:
            raise ErroProvedor(
                f"provedor(es) {desconhecidos} não habilitado(s) no projeto; habilitados: {nomes}"
            )
        nomes = [n for n in nomes if n in apenas]
    return [obter_provedor(n)(projeto.chips.provedores[n]) for n in nomes]


def _registrar_falha(pasta: Path, falha: Falha) -> None:
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        with (pasta / NOME_LOG_ERROS).open("a", encoding="utf-8") as f:
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            f.write(f"{ts}\t{falha.provedor}\t{falha.plotid}\t{falha.erro}\n")
    except OSError:  # pragma: no cover
        log.exception("não foi possível escrever o log de erros")


def gerar_chips(
    projeto: Projeto,
    pontos: Iterable[Ponto],
    provedores: list[ProvedorChip],
    cache: CacheChips | None = None,
    *,
    forcar: bool = False,
    paralelo: int = 1,
    progresso: Callable[[int, int], None] | None = None,
) -> ResultadoLote:
    """Gera os chips de ``pontos`` para cada provedor.

    Um ponto que falha num provedor é registrado em ``erros.log`` (na pasta de
    chips), incluído em ``ResultadoLote.falhas`` e pulado; o lote continua.
    Falhas em ``preparar()`` (ex.: Earth Engine sem credencial) propagam, pois
    invalidariam o lote inteiro.

    Args:
        progresso: chamado com ``(feitos, total)`` a cada tarefa concluída.
    """
    cache = cache or CacheChips(projeto.pasta_chips)
    pontos = list(pontos)
    inicio = time.monotonic()
    resultado = ResultadoLote()

    for p in provedores:
        p.preparar()

    tarefas: list[tuple[Ponto, ProvedorChip]] = []
    for ponto in pontos:
        for prov in provedores:
            if not forcar and cache.existe(prov.nome, ponto.plotid, prov.versao):
                resultado.em_cache += 1
            else:
                if not forcar and cache.existe(prov.nome, ponto.plotid):
                    resultado.desatualizados += 1
                tarefas.append((ponto, prov))

    total = len(tarefas) + resultado.em_cache
    feitos = resultado.em_cache
    if progresso:
        progresso(feitos, total)

    def executar(ponto: Ponto, prov: ProvedorChip) -> Falha | None:
        pedido = PedidoChip(
            plotid=ponto.plotid,
            lon=ponto.lon,
            lat=ponto.lat,
            ano_referencia=projeto.ano_referencia,
            config=prov.config,
        )
        try:
            png = prov.gerar(pedido)
            cache.gravar(prov.nome, ponto.plotid, png, versao=prov.versao)
            return None
        except Exception as e:  # noqa: BLE001 — tolerância a falha é o contrato
            log.debug("falha em %s/%s:\n%s", prov.nome, ponto.plotid, traceback.format_exc())
            return Falha(plotid=ponto.plotid, provedor=prov.nome, erro=f"{type(e).__name__}: {e}")

    def contabilizar(falha: Falha | None) -> None:
        nonlocal feitos
        if falha is None:
            resultado.gerados += 1
        else:
            resultado.falhas.append(falha)
            _registrar_falha(cache.pasta, falha)
            log.warning("chip %s/%s falhou: %s", falha.provedor, falha.plotid, falha.erro)
        feitos += 1
        if progresso:
            progresso(feitos, total)

    if paralelo <= 1 or len(tarefas) <= 1:
        for ponto, prov in tarefas:
            contabilizar(executar(ponto, prov))
    else:
        with ThreadPoolExecutor(max_workers=paralelo) as pool:
            futuros = [pool.submit(executar, ponto, prov) for ponto, prov in tarefas]
            for fut in as_completed(futuros):
                contabilizar(fut.result())

    resultado.duracao_s = time.monotonic() - inicio
    return resultado
