"""Interface Streamlit sem navegador (streamlit.testing.v1.AppTest).

Cobre cegueira, fluxo de resposta, autosave/retomada, campos condicionais,
ponto sem chip, modo revisão e desfazer. O teclado real e o layout ficam para
o teste manual.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from miradouro.interface import app as modulo_app  # noqa: E402
from tests.conftest import PROJETO_MINIMO  # noqa: E402

SENTINELA_COLUNA = "coluna_secreta"
SENTINELA_VALOR = "SEGREDO_XYZ_"
CSV = f"""PLOTID,LON,LAT,{SENTINELA_COLUNA},regiao
p1,-44.1,-19.9,{SENTINELA_VALOR}1,norte
p2,-44.2,-20.0,{SENTINELA_VALOR}2,sul
p3,-44.3,-20.1,{SENTINELA_VALOR}3,sul
"""


@pytest.fixture
def projeto_app(tmp_path: Path, monkeypatch) -> Path:
    dados = copy.deepcopy(PROJETO_MINIMO)
    dados["pontos"]["colunas_ocultas"] = [SENTINELA_COLUNA]
    dados["chips"]["provedores"] = {"s2_sazonal": {}, "esri_basemap": {}}
    # data_hr aparece e é exigido só quando fonte = hr (como no Paraopeba).
    dados["campos"].insert(3, {"nome": "data_hr", "tipo": "texto", "padrao": "[0-9]{4}-[0-9]{2}", "obrigatorio_se": {"campo": "fonte", "igual_a": "hr"}})
    y = tmp_path / "projeto.yaml"
    y.write_text(yaml.safe_dump(dados, allow_unicode=True), encoding="utf-8")
    (tmp_path / "pontos.csv").write_text(CSV, encoding="utf-8")
    monkeypatch.setenv(modulo_app.VAR_PROJETO, str(y))
    monkeypatch.setenv(modulo_app.VAR_INTERPRETE, "tester")
    monkeypatch.setattr(sys, "argv", ["app.py"])
    # Chip só para p1/s2_sazonal; p2 e p3 ficam sem subsídio.
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buf, format="PNG")
    from miradouro.chips import CacheChips

    CacheChips(tmp_path / "chips").gravar("s2_sazonal", "p1", buf.getvalue())
    return y


def _app() -> AppTest:
    at = AppTest.from_file(modulo_app.__file__, default_timeout=60)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def _todo_texto(at: AppTest) -> str:
    """Tudo o que o front-end receberia (protobuf de cada elemento), em texto."""
    partes: list[str] = []

    def andar(bloco):
        for filho in getattr(bloco, "children", {}).values():
            proto = getattr(filho, "proto", None)
            if proto is not None:
                partes.append(str(proto))
            andar(filho)

    andar(at._tree)
    return "\n".join(partes)


def _radio(at: AppTest, rotulo: str):
    return next(r for r in at.radio if r.label.startswith(rotulo))


def _pills(at: AppTest, rotulo: str):
    return next(w for w in at.get("button_group") if w.label.startswith(rotulo))


def _botao(at: AppTest, rotulo: str):
    return next(b for b in at.button if rotulo in b.label)


def _respostas(projeto_app: Path) -> dict:
    return json.loads((projeto_app.parent / "respostas" / "respostas.json").read_text(encoding="utf-8"))["respostas"]


# ---- cegueira ------------------------------------------------------------------------


def test_colunas_ocultas_nunca_chegam_ao_frontend(projeto_app):
    at = _app()
    texto = _todo_texto(at)
    assert SENTINELA_COLUNA not in texto
    assert SENTINELA_VALOR not in texto
    assert "regiao: norte" in texto  # a coluna não oculta aparece
    assert dict(at.query_params) == {}
    # Também depois de navegar e nos modos todos/revisão.
    _botao(at, "Próximo").click().run()
    _radio(at, "Modo").set_value("todos").run()
    texto = _todo_texto(at)
    assert SENTINELA_COLUNA not in texto and SENTINELA_VALOR not in texto


# ---- fluxo -----------------------------------------------------------------------------


def test_abre_no_primeiro_pendente_e_responde(projeto_app):
    at = _app()
    assert at.subheader[0].value.startswith("PLOTID p1 · ponto 1 de 3")
    assert "0/3 respondidos" in _todo_texto(at)
    # Campos condicionais escondidos até serem exigidos.
    assert not any(t.label.startswith("data_hr") for t in at.text_input)
    assert not any(r.label.startswith("classe_alt") for r in at.radio)

    _botao(at, "Confirmar").click().run()
    assert at.error and "classe_ref: obrigatório" in at.error[0].value
    assert _respostas.__name__ and not (projeto_app.parent / "respostas" / "respostas.json").exists() or "p1" not in _respostas(projeto_app)

    _radio(at, "classe_ref").set_value("1").run()
    _radio(at, "confianca").set_value("alta").run()
    _pills(at, "fonte").set_value(["serie", "hr"]).run()
    assert any(t.label.startswith("data_hr") for t in at.text_input)  # apareceu
    # O condicional vem logo abaixo do gatilho (fonte), antes da observação.
    rotulos = [w.label for w in list(at.get("button_group")) + list(at.text_input)]
    assert rotulos.index("fonte") < rotulos.index("data_hr *") < rotulos.index("observacao")
    _botao(at, "Confirmar").click().run()
    assert "data_hr: obrigatório quando fonte = hr" in at.error[0].value

    next(t for t in at.text_input if t.label.startswith("data_hr")).set_value("2023-07").run()
    _botao(at, "Confirmar").click().run()
    assert not at.error
    r = _respostas(projeto_app)["p1"]
    assert r["valores"] == {"classe_ref": "1", "confianca": "alta", "fonte": ["serie", "hr"], "data_hr": "2023-07"}
    assert r["interprete"] == "tester" and r["meta"]["modo"] == "pendentes"
    assert "duracao_s" in r["meta"] and r["meta"]["sem_subsidio"] == ["esri_basemap"]  # p1 tem só o chip S2
    # Avançou para o próximo pendente e o progresso subiu.
    assert at.subheader[0].value.startswith("PLOTID p2")
    texto = _todo_texto(at)
    assert "1/3 respondidos" in texto and "1 nesta sessão" in texto


def test_ponto_sem_chip_avisa_e_marca_auditoria(projeto_app):
    at = _app()
    # p1 tem o chip S2 mas não o Esri: aviso parcial, e a imagem existente aparece.
    assert len(at.warning) == 1 and "esri_basemap" in at.warning[0].value and "s2_sazonal" not in at.warning[0].value
    assert len(at.get("image")) == 1  # só o chip existente é mostrado
    _botao(at, "Próximo").click().run()
    assert at.subheader[0].value.startswith("PLOTID p2")
    assert any("Sem subsídio" in w.value and "s2_sazonal" in w.value for w in at.warning)
    _radio(at, "classe_ref").set_value("2").run()
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    assert set(_respostas(projeto_app)["p2"]["meta"]["sem_subsidio"]) == {"s2_sazonal", "esri_basemap"}


def test_retoma_no_primeiro_pendente_ao_reabrir(projeto_app):
    at = _app()
    _radio(at, "classe_ref").set_value("1").run()
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    assert at.subheader[0].value.startswith("PLOTID p2")
    # Nova sessão (outro navegador/reload): retoma em p2, não em p1.
    at2 = _app()
    assert at2.subheader[0].value.startswith("PLOTID p2 · ponto 1 de 2")
    dados = json.loads((projeto_app.parent / "respostas" / "respostas.json").read_text())
    assert len(dados["sessoes"]) == 2
    assert len(list((projeto_app.parent / "respostas" / "backups").glob("*.json"))) == 1


def test_modo_revisao_filtra_confianca_baixa_e_mostra_resposta(projeto_app):
    at = _app()
    for classe, conf in (("1", "baixa"), ("2", "alta")):
        _radio(at, "classe_ref").set_value(classe).run()
        _radio(at, "confianca").set_value(conf).run()
        if conf == "baixa":
            assert any(r.label.startswith("classe_alt") for r in at.radio)
            _radio(at, "classe_alt").set_value("2").run()
        _botao(at, "Confirmar").click().run()
    assert at.subheader[0].value.startswith("PLOTID p3")
    _radio(at, "Modo").set_value("revisao").run()
    assert at.subheader[0].value.startswith("PLOTID p1 · ponto 1 de 1 (revisão")
    assert any("Já respondido" in s.value and "classe_ref = 1" in s.value for s in at.success)
    assert _radio(at, "classe_ref").value == "1"  # rascunho vem da resposta gravada
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    r = _respostas(projeto_app)["p1"]
    assert r["valores"]["confianca"] == "alta" and "classe_alt" not in r["valores"] and r["revisoes"] == 1
    assert r["meta"]["modo"] == "revisao"


def test_desfazer_remove_ou_restaura(projeto_app):
    at = _app()
    _botao(at, "Desfazer").click().run()
    assert any("Nada a desfazer" in i.value for i in at.info)
    _radio(at, "classe_ref").set_value("1").run()
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    assert "p1" in _respostas(projeto_app)
    _botao(at, "Desfazer").click().run()
    assert "p1" not in _respostas(projeto_app)
    assert at.subheader[0].value.startswith("PLOTID p1")
    assert _radio(at, "classe_ref").value == "1"  # rascunho preservado para revisar
    _botao(at, "Confirmar").click().run()
    _radio(at, "Modo").set_value("todos").run()
    _botao(at, "Anterior").click().run()
    _radio(at, "confianca").set_value("media").run()
    _radio(at, "classe_alt").set_value("6").run()
    _botao(at, "Confirmar").click().run()
    assert _respostas(projeto_app)["p1"]["valores"]["confianca"] == "media"
    _botao(at, "Desfazer").click().run()
    r = _respostas(projeto_app)["p1"]
    assert r["valores"]["confianca"] == "alta" and r["meta"] == {"desfeito": True}


def test_revisao_esvaziada_descarrega_ponto(projeto_app):
    at = _app()
    _radio(at, "classe_ref").set_value("1").run()
    _radio(at, "confianca").set_value("baixa").run()
    _radio(at, "classe_alt").set_value("2").run()
    _botao(at, "Confirmar").click().run()
    _radio(at, "Modo").set_value("revisao").run()
    assert at.subheader[0].value.startswith("PLOTID p1 · ponto 1 de 1")
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    # Lista vazia: nenhum ponto carregado, nenhum cronômetro, mensagem clara.
    assert not at.subheader and not any("⏱" in c.value for c in at.caption)
    assert any("Não há mais pontos neste modo" in i.value for i in at.info)
    assert any("Nenhum ponto neste modo" in s.value for s in at.success)
    assert not at.radio[1:]  # só o rádio de modo; nenhum formulário
    # Voltar ao modo todos recarrega um ponto normalmente.
    _radio(at, "Modo").set_value("todos").run()
    assert at.subheader[0].value.startswith("PLOTID p1")


def test_resposta_antiga_com_string_pre_preenche_lista(projeto_app):
    import json as _json

    at = _app()
    _radio(at, "classe_ref").set_value("1").run()
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    arquivo = projeto_app.parent / "respostas" / "respostas.json"
    d = _json.loads(arquivo.read_text())
    d["respostas"]["p1"]["valores"]["fonte"] = "serie"  # formato antigo (escolha única)
    arquivo.write_text(_json.dumps(d))
    at2 = _app()  # abre em p2 (pendente); volta a p1 no modo todos
    _radio(at2, "Modo").set_value("todos").run()
    _botao(at2, "Anterior").click().run()
    assert at2.subheader[0].value.startswith("PLOTID p1")
    assert _pills(at2, "fonte").value == ["serie"]
    assert any("fonte = serie" in s.value for s in at2.success)


def test_limpar_e_navegacao_nos_limites(projeto_app):
    at = _app()
    _radio(at, "classe_ref").set_value("6").run()
    _botao(at, "Limpar").click().run()
    assert _radio(at, "classe_ref").value is None
    _botao(at, "Anterior").click().run()
    assert any("Início da lista" in i.value for i in at.info)
    _botao(at, "Próximo").click().run()
    _botao(at, "Próximo").click().run()
    _botao(at, "Próximo").click().run()
    assert any("Fim da lista" in i.value for i in at.info)
    assert at.subheader[0].value.startswith("PLOTID p3")


def test_teclado_simulado_via_evento(projeto_app, monkeypatch):
    """Simula o componente de teclado devolvendo eventos ao Python."""
    eventos: list[dict | None] = [None]
    focos: list[dict | None] = []
    from miradouro.interface import teclado

    def falso(rotulos_texto=None, focar=None):
        focos.append(focar)
        return eventos[-1]

    monkeypatch.setattr(teclado, "capturar_tecla", falso)
    at = _app()

    def tecla(key, code, shift=False):
        eventos.append({"id": f"ev{len(eventos)}", "key": key, "code": code, "shift": shift})
        at.run()

    tecla("2", "Digit2")
    assert _radio(at, "classe_ref").value == "2"
    tecla("@", "Digit2", shift=True)  # classe_alt só aparece com confiança ≠ alta, mas o rascunho guarda
    tecla("b", "KeyB")
    assert _radio(at, "confianca").value == "baixa"
    assert _radio(at, "classe_alt").value == "2"
    # Multiopção: H/N/S alternam.
    tecla("h", "KeyH")
    tecla("n", "KeyN")
    assert _pills(at, "fonte").value == ["hr", "serie"]
    tecla("h", "KeyH")
    assert _pills(at, "fonte").value == ["serie"]
    # Recusa por campo vazio pede foco no campo faltante.
    tecla("h", "KeyH")
    tecla("Enter", "Enter")
    assert "data_hr: obrigatório" in at.error[0].value and focos[-1] == {"id": 1, "rotulo": "data_hr *"}
    tecla("h", "KeyH")  # desliga hr de novo → data_hr some e não é exigido
    tecla("Enter", "Enter")
    r = _respostas(projeto_app)["p1"]
    assert r["valores"] == {"classe_ref": "2", "confianca": "baixa", "classe_alt": "2", "fonte": ["serie"]}
    assert at.subheader[0].value.startswith("PLOTID p2")
    tecla("ArrowLeft", "ArrowLeft")  # no modo pendentes p1 já não está na lista: fica em p2
    assert at.subheader[0].value.startswith("PLOTID p2") and any("Início da lista" in i.value for i in at.info)
    _radio(at, "Modo").set_value("todos").run()
    tecla("ArrowLeft", "ArrowLeft")
    assert at.subheader[0].value.startswith("PLOTID p1")
    tecla("u", "KeyU")
    assert "p1" not in _respostas(projeto_app)
    # O mesmo evento repetido (mesmo id) não é reprocessado.
    at.run()
    assert "p1" not in _respostas(projeto_app)


def test_sem_projeto_mostra_erro(monkeypatch):
    monkeypatch.delenv(modulo_app.VAR_PROJETO, raising=False)
    monkeypatch.setattr(sys, "argv", ["app.py"])
    at = AppTest.from_file(modulo_app.__file__, default_timeout=30)
    at.run()
    assert at.error and "Informe o projeto" in at.error[0].value


def test_pede_interprete_quando_nao_informado(projeto_app, monkeypatch):
    monkeypatch.delenv(modulo_app.VAR_INTERPRETE)
    at = AppTest.from_file(modulo_app.__file__, default_timeout=30)
    at.run()
    assert at.text_input[0].label == "Id do intérprete" and not at.radio
    at.text_input[0].set_value("maria").run()
    _botao(at, "Começar").click().run()
    assert at.radio and "Intérprete **maria**" in _todo_texto(at)


# ---- segunda passada e consenso ---------------------------------------------------------


def _primeira_passada(projeto_app: Path):
    from miradouro.core import Armazenamento, carregar_projeto

    projeto = carregar_projeto(projeto_app)
    arm = Armazenamento(projeto, interprete="ana")
    arm.gravar("p1", {"classe_ref": "1", "confianca": "baixa", "classe_alt": "2"})
    arm.gravar("p2", {"classe_ref": "2", "confianca": "alta"})
    arm.gravar("p3", {"classe_ref": "6", "confianca": "alta"})
    return projeto, arm


def test_segunda_passada_cega(projeto_app, monkeypatch):
    projeto, arm = _primeira_passada(projeto_app)
    monkeypatch.setenv(modulo_app.VAR_PASSADA, "segunda")
    monkeypatch.setenv(modulo_app.VAR_FRACAO, "0.5")
    monkeypatch.setenv(modulo_app.VAR_INTERPRETE, "bia")
    at = _app()
    texto = _todo_texto(at)
    assert "Segunda passada (cega)" in texto and "2 pontos, 1 de controle" in texto
    assert "Já respondido" not in texto and "classe_ref = " not in texto  # nada da primeira passada
    assert SENTINELA_VALOR not in texto
    assert [r.label for r in at.radio][0] == "Modo" and list(at.radio[0].options) == ["Pendentes", "Todos da segunda passada"]
    assert at.subheader[0].value.startswith("PLOTID p1 · ponto 1 de 2")
    assert _radio(at, "classe_ref").value is None  # formulário vazio, não pré-preenchido
    _radio(at, "classe_ref").set_value("2").run()
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    seg = json.loads((projeto_app.parent / "respostas" / "segunda" / "respostas.json").read_text(encoding="utf-8"))
    assert seg["respostas"]["p1"]["valores"]["classe_ref"] == "2" and seg["respostas"]["p1"]["meta"]["passada"] == 2
    assert "controle" not in seg["respostas"]["p1"]["meta"] and seg["respostas"]["p1"]["interprete"] == "bia"
    # Arquivo principal intacto.
    assert arm.obter("p1").valores["classe_ref"] == "1" and _respostas(projeto_app)["p1"]["interprete"] == "ana"
    # Segundo ponto é o de controle (p2 ou p3), marcado na auditoria.
    pid = at.subheader[0].value.split()[1]
    assert pid in ("p2", "p3")
    _radio(at, "classe_ref").set_value("6").run()
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    seg = json.loads((projeto_app.parent / "respostas" / "segunda" / "respostas.json").read_text(encoding="utf-8"))
    assert seg["respostas"][pid]["meta"]["controle"] is True
    assert not at.subheader  # lista esvaziada


def test_consenso(projeto_app, monkeypatch):
    from miradouro.core import Armazenamento

    projeto, arm = _primeira_passada(projeto_app)
    monkeypatch.setenv(modulo_app.VAR_PASSADA, "consenso")
    at = AppTest.from_file(modulo_app.__file__, default_timeout=60)
    at.run()
    assert at.error and "exige a segunda passada" in at.error[0].value
    seg = Armazenamento(projeto, interprete="bia", pasta=projeto.pasta_saida / "segunda")
    seg.gravar("p1", {"classe_ref": "2", "confianca": "alta"}, meta={"passada": 2})
    seg.gravar("p2", {"classe_ref": "2", "confianca": "alta"}, meta={"passada": 2, "controle": True})
    at = _app()
    texto = _todo_texto(at)
    assert "Consenso" in texto and list(at.radio[0].options) == ["Divergentes sem consenso", "Todos da segunda passada"]
    assert at.subheader[0].value.startswith("PLOTID p1 · ponto 1 de 1")
    assert "Primeira passada" in texto and "Segunda passada" in texto and "classe_ref = 1" in texto and "classe_ref = 2" in texto
    assert _radio(at, "classe_ref").value == "1"  # pré-preenchido com a primeira passada
    _radio(at, "classe_ref").set_value("2").run()
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    r = _respostas(projeto_app)["p1"]
    assert r["valores"]["classe_ref"] == "2" and r["revisoes"] == 1 and r["meta"]["modo"] == "divergentes"
    assert r["meta"]["consenso"]["primeira"]["valores"]["classe_ref"] == "1" and r["meta"]["consenso"]["segunda"]["interprete"] == "bia"
    assert not at.subheader  # não há mais divergências
    _radio(at, "Modo").set_value("todos_segunda").run()
    assert at.subheader[0].value.startswith("PLOTID p1 · ponto 1 de 2")
    assert "consenso registrado" in _todo_texto(at)
