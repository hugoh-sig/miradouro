"""CLI de ponta a ponta com um provedor falso registrado."""

import io
from pathlib import Path

import pytest
import yaml
from PIL import Image

from miradouro import __version__
from miradouro.chips import ProvedorChip, registrar
from miradouro.cli import CODIGO_ERRO, CODIGO_FALHAS_PARCIAIS, CODIGO_OK, main


@registrar
class ProvedorCli(ProvedorChip):
    nome = "cli_falso"
    descricao = "provedor de teste da CLI"

    def gerar(self, pedido):
        if pedido.plotid in self.config.get("falhar", []):
            raise ValueError("falhou de propósito")
        buf = io.BytesIO()
        Image.new("RGB", (2, 2)).save(buf, format="PNG")
        return buf.getvalue()


@pytest.fixture
def yaml_cli(pasta_projeto, dados_projeto) -> Path:
    dados_projeto["chips"]["provedores"] = {"cli_falso": {"falhar": ["p2"]}}
    y = pasta_projeto / "projeto.yaml"
    y.write_text(yaml.safe_dump(dados_projeto, allow_unicode=True), encoding="utf-8")
    return y


def test_versao(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--versao"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_projeto_validar(yaml_cli, capsys):
    assert main(["projeto", "validar", str(yaml_cli)]) == CODIGO_OK
    saida = capsys.readouterr().out
    assert "3 em" in saida and "classe_ref" in saida and "OK" in saida


def test_projeto_validar_avisa_coluna_oculta_ausente(pasta_projeto, dados_projeto, capsys):
    dados_projeto["pontos"]["colunas_ocultas"] = ["nao_existe"]
    y = pasta_projeto / "projeto.yaml"
    y.write_text(yaml.safe_dump(dados_projeto), encoding="utf-8")
    assert main(["projeto", "validar", str(y)]) == CODIGO_OK
    assert "AVISO" in capsys.readouterr().out


def test_projeto_invalido_retorna_erro(tmp_path, capsys):
    (tmp_path / "p.yaml").write_text("nome: x\n")
    assert main(["projeto", "validar", str(tmp_path / "p.yaml")]) == CODIGO_ERRO
    assert "erro:" in capsys.readouterr().err


def test_chips_listar(capsys):
    assert main(["chips", "listar"]) == CODIGO_OK
    out = capsys.readouterr().out
    assert "s2_sazonal" in out and "esri_basemap" in out and "ndvi_serie" in out


def test_chips_gerar_status_e_cache(yaml_cli, pasta_projeto, capsys):
    codigo = main(["chips", "gerar", str(yaml_cli), "--sem-barra"])
    assert codigo == CODIGO_FALHAS_PARCIAIS
    err = capsys.readouterr().err
    assert "2 gerados" in err and "1 falhas" in err and "cli_falso/p2" in err
    assert (pasta_projeto / "chips" / "cli_falso" / "p1.png").exists()
    assert (pasta_projeto / "chips" / "erros.log").exists()

    assert main(["chips", "status", str(yaml_cli)]) == CODIGO_OK
    assert "cli_falso      2/3  v1" in capsys.readouterr().out

    # Chip de versão antiga aparece como "será regerado" no status.
    from miradouro.chips import CacheChips

    CacheChips(pasta_projeto / "chips").gravar("cli_falso", "p3", (pasta_projeto / "chips" / "cli_falso" / "p3.png").read_bytes(), versao="0")
    assert main(["chips", "status", str(yaml_cli)]) == CODIGO_OK
    assert "1/3  v1  (1 de versão antiga, serão regerados)" in capsys.readouterr().out

    # Segunda rodada com barra de progresso: p1 vem do cache, p3 é regerado (versão antiga); p2 falha de novo.
    assert main(["chips", "gerar", str(yaml_cli)]) == CODIGO_FALHAS_PARCIAIS
    err = capsys.readouterr().err
    assert "1 gerados (1 regerados por versão nova), 1 já em cache" in err


def test_chips_gerar_filtros(yaml_cli, capsys):
    assert main(["chips", "gerar", str(yaml_cli), "--sem-barra", "--plotid", "p1", "--provedor", "cli_falso"]) == CODIGO_OK
    assert "1 gerados" in capsys.readouterr().err
    assert main(["chips", "gerar", str(yaml_cli), "--sem-barra", "--limite", "1", "--forcar", "--paralelo", "2"]) == CODIGO_OK
    assert main(["chips", "gerar", str(yaml_cli), "--sem-barra", "--plotid", "zzz"]) == CODIGO_ERRO
    assert "não encontrado" in capsys.readouterr().err
    assert main(["chips", "gerar", str(yaml_cli), "--sem-barra", "--provedor", "outro"]) == CODIGO_ERRO


def test_chips_gerar_sem_provedores(pasta_projeto, capsys):
    assert main(["chips", "gerar", str(pasta_projeto / "projeto.yaml"), "--sem-barra"]) == CODIGO_ERRO
    assert "nenhum provedor" in capsys.readouterr().err


def test_modulo_executavel():
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "miradouro", "--versao"], capture_output=True, text=True)
    assert r.returncode == 0 and __version__ in r.stdout


def test_app_comando_monta_streamlit(yaml_cli, monkeypatch, capsys):
    pytest.importorskip("streamlit")
    import subprocess

    chamadas = []
    monkeypatch.setattr(subprocess, "call", lambda cmd: chamadas.append(cmd) or 0)
    assert main(["app", str(yaml_cli), "--interprete", "ana", "--porta", "8600", "--sem-navegador"]) == CODIGO_OK
    cmd = chamadas[0]
    assert cmd[1:4] == ["-m", "streamlit", "run"] and cmd[4].endswith("interface/app.py")
    assert "--server.port" in cmd and "8600" in cmd and cmd[cmd.index("--server.headless") + 1] == "true"
    assert cmd[cmd.index("--projeto") + 1] == str(yaml_cli.resolve()) and cmd[cmd.index("--interprete") + 1] == "ana"
    assert "Abrindo a interface" in capsys.readouterr().err


def test_app_comando_projeto_invalido(tmp_path):
    (tmp_path / "p.yaml").write_text("nome: x\n")
    assert main(["app", str(tmp_path / "p.yaml")]) == CODIGO_ERRO


def test_app_comando_segunda_passada_e_consenso(yaml_cli, monkeypatch):
    pytest.importorskip("streamlit")
    import subprocess

    chamadas = []
    monkeypatch.setattr(subprocess, "call", lambda cmd: chamadas.append(cmd) or 0)
    assert main(["app", str(yaml_cli), "--segunda-passada", "--fracao-controle", "0.05", "--sem-navegador"]) == CODIGO_OK
    assert chamadas[-1][-4:] == ["--passada", "segunda", "--fracao-controle", "0.05"]
    assert main(["app", str(yaml_cli), "--segunda-passada", "--fracao-controle", "2"]) == CODIGO_ERRO
    assert main(["app", str(yaml_cli), "--consenso"]) == CODIGO_ERRO  # sem segunda passada
    (yaml_cli.parent / "respostas" / "segunda").mkdir(parents=True)
    (yaml_cli.parent / "respostas" / "segunda" / "respostas.json").write_text("{}")
    assert main(["app", str(yaml_cli), "--consenso", "--sem-navegador"]) == CODIGO_OK
    assert chamadas[-1][-2:] == ["--passada", "consenso"]


def test_app_comando_lista_dirigida(yaml_cli, monkeypatch, capsys):
    pytest.importorskip("streamlit")
    import subprocess

    chamadas = []
    monkeypatch.setattr(subprocess, "call", lambda cmd: chamadas.append(cmd) or 0)
    lista = yaml_cli.parent / "lista.txt"
    lista.write_text("p3\np1\np3\n", encoding="utf-8")
    assert main(["app", str(yaml_cli), "--interprete", "ana", "--lista", str(lista), "--sem-navegador"]) == CODIGO_OK
    assert chamadas[-1][-4:] == ["--passada", "dirigida", "--lista", str(lista.resolve())]
    err = capsys.readouterr().err
    assert "Revisão dirigida: 2 pontos de lista.txt" in err and "1 repetidos ignorados" in err
    lista.write_text("p1\nzzz\n", encoding="utf-8")
    assert main(["app", str(yaml_cli), "--lista", str(lista)]) == CODIGO_ERRO
    assert "zzz" in capsys.readouterr().err
    assert main(["app", str(yaml_cli), "--lista", str(yaml_cli.parent / "nao_existe.txt")]) == CODIGO_ERRO
    with pytest.raises(SystemExit):  # argparse: --lista, --segunda-passada e --consenso são exclusivos
        main(["app", str(yaml_cli), "--lista", str(lista), "--consenso"])


def test_sortear_persiste_amostra(yaml_cli, capsys):
    import json

    from miradouro.core import Armazenamento, carregar_projeto

    y = str(yaml_cli)
    assert main(["sortear", y, "--fracao-controle", "0.5"]) == CODIGO_ERRO  # sem primeira passada
    assert "não há respostas" in capsys.readouterr().err
    projeto = carregar_projeto(yaml_cli)
    arm = Armazenamento(projeto, interprete="ana")
    arm.gravar("p1", {"classe_ref": "1", "confianca": "baixa", "classe_alt": "2"})
    arm.gravar("p2", {"classe_ref": "2", "confianca": "alta"})
    arm.gravar("p3", {"classe_ref": "6", "confianca": "alta"})
    assert main(["sortear", y, "--fracao-controle", "1.5"]) == CODIGO_ERRO
    assert main(["sortear", y, "--fracao-controle", "0.5", "--interprete", "hugo2p"]) == CODIGO_OK
    out = capsys.readouterr().out
    assert "1 de confiança baixa + 1 de controle" in out and "= 2 pontos" in out and "--interprete hugo2p --segunda-passada" in out
    arquivo = yaml_cli.parent / "respostas" / "segunda" / "amostra.json"
    d = json.loads(arquivo.read_text(encoding="utf-8"))
    assert d["baixa"] == ["p1"] and len(d["controle"]) == 1 and d["interprete_previsto"] == "hugo2p"
    assert d["fracao_controle"] == 0.5 and len(d["respostas_sha256"]) == 64 and d["projeto"]["yaml_sha256"] == projeto.hash_yaml
    # Não refaz sem --forcar; refaz com --forcar; nunca depois que a segunda passada começou.
    assert main(["sortear", y, "--fracao-controle", "0.5"]) == CODIGO_ERRO
    assert "--forcar" in capsys.readouterr().err
    assert main(["sortear", y, "--fracao-controle", "0.5", "--forcar"]) == CODIGO_OK
    (arquivo.parent / "respostas.json").write_text("{}")
    assert main(["sortear", y, "--fracao-controle", "0.5", "--forcar"]) == CODIGO_ERRO
    assert "já começou" in capsys.readouterr().err
