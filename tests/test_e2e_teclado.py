"""Teste ponta a ponta do teclado num Chrome real (Playwright).

Pulado por padrão. Para rodar localmente::

    pip install playwright            # usa o Google Chrome já instalado (channel="chrome")
    MIRADOURO_E2E=1 pytest tests/test_e2e_teclado.py -q

Verifica o que o AppTest não alcança: o componente JS captura teclas na página,
o Enter dentro de um campo de texto grava o texto antes de confirmar, e letras
digitadas num campo de texto não disparam atalhos.
"""

from __future__ import annotations

import copy
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from tests.conftest import PROJETO_MINIMO

pytestmark = pytest.mark.skipif(not os.environ.get("MIRADOURO_E2E"), reason="defina MIRADOURO_E2E=1 para rodar")
playwright = pytest.importorskip("playwright.sync_api")

CSV = "PLOTID,LON,LAT,oculta\np1,-44.1,-19.9,X1\np2,-44.2,-20.0,X2\np3,-44.3,-20.1,X3\n"


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def servidor(tmp_path: Path):
    dados = copy.deepcopy(PROJETO_MINIMO)
    dados["pontos"]["colunas_ocultas"] = ["oculta"]
    dados["campos"][2]["opcoes"] = [{"valor": "hr", "tecla": "H"}, {"valor": "serie", "tecla": "N"}, {"valor": "s2", "tecla": "S"}]
    y = tmp_path / "projeto.yaml"
    y.write_text(yaml.safe_dump(dados, allow_unicode=True), encoding="utf-8")
    (tmp_path / "pontos.csv").write_text(CSV, encoding="utf-8")
    porta = _porta_livre()
    proc = subprocess.Popen(
        [sys.executable, "-m", "miradouro", "app", str(y), "--interprete", "e2e", "--porta", str(porta), "--sem-navegador"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=1):
                    break
            except OSError:
                time.sleep(0.5)
        yield f"http://127.0.0.1:{porta}", tmp_path / "respostas" / "respostas.json"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _respostas(arquivo: Path, esperado: int, timeout: float = 10.0) -> dict:
    fim = time.time() + timeout
    while time.time() < fim:
        if arquivo.exists():
            d = json.loads(arquivo.read_text(encoding="utf-8"))["respostas"]
            if len(d) >= esperado:
                return d
        time.sleep(0.2)
    raise AssertionError(f"esperava {esperado} respostas em {arquivo}")


def test_teclado_real(servidor):
    url, arquivo = servidor
    with playwright.sync_playwright() as p:
        navegador = p.chromium.launch(channel="chrome", headless=True)
        pagina = navegador.new_page(viewport={"width": 1400, "height": 900})
        pagina.goto(url)
        pagina.get_by_text("PLOTID p1").wait_for(timeout=30000)
        pagina.wait_for_timeout(1500)  # componente de teclado monta
        pagina.mouse.click(700, 450)  # foco na página, fora de qualquer input

        # Atalhos: classe 2, confiança alta, fonte série; Enter confirma e avança.
        for tecla in ("2", "a", "n"):
            pagina.keyboard.press(tecla)
            pagina.wait_for_timeout(700)
        assert pagina.get_by_text("[2] pasto").first.is_visible()
        pagina.keyboard.press("Enter")
        r = _respostas(arquivo, 1)
        assert r["p1"]["valores"] == {"classe_ref": "2", "confianca": "alta", "fonte": "serie"}
        pagina.get_by_text("PLOTID p2").wait_for(timeout=15000)

        # Texto: T foca a observação; letras digitadas lá NÃO viram atalhos; Enter grava o texto e confirma.
        pagina.keyboard.press("6")
        pagina.wait_for_timeout(700)
        pagina.keyboard.press("m")
        pagina.wait_for_timeout(700)
        pagina.keyboard.press("t")
        pagina.wait_for_timeout(500)
        pagina.keyboard.type("banhado 2 ha")  # contém 'b', 'a', 'h', '2' — nada deve mudar
        pagina.wait_for_timeout(300)
        pagina.keyboard.press("Enter")
        pagina.wait_for_timeout(1500)
        r = _respostas(arquivo, 1)
        # Confiança média exige classe_alt → não confirmou; classe/confiança intactas.
        assert "p2" not in r
        pagina.get_by_text("classe_alt: obrigatório").wait_for(timeout=10000)
        pagina.keyboard.press("Escape")
        pagina.mouse.click(700, 450)
        pagina.keyboard.press("Shift+Digit1")
        pagina.wait_for_timeout(700)
        pagina.keyboard.press("Enter")
        r = _respostas(arquivo, 2)
        assert r["p2"]["valores"] == {"classe_ref": "6", "confianca": "media", "classe_alt": "1", "observacao": "banhado 2 ha"}

        # U desfaz a última (p2) e volta para ela.
        pagina.get_by_text("PLOTID p3").wait_for(timeout=15000)
        pagina.keyboard.press("u")
        pagina.get_by_text("PLOTID p2").wait_for(timeout=15000)
        pagina.wait_for_timeout(500)
        assert "p2" not in json.loads(arquivo.read_text(encoding="utf-8"))["respostas"]

        # Cegueira no DOM real.
        html = pagina.content()
        assert "oculta" not in html.replace("colunas_ocultas", "") and "X2" not in html
        navegador.close()
