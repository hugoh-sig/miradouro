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
