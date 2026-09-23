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

    def falso(rotulos_texto=None, focar=None, **kw):
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


# ---- salto direto por PLOTID -----------------------------------------------------------


def _saltar(at: AppTest, pid: str) -> AppTest:
    next(t for t in at.text_input if t.label == "Ir para o ponto").set_value(pid).run()
    return at


def test_ir_para_o_ponto_em_qualquer_modo(projeto_app):
    at = _app()
    _saltar(at, "p3")
    assert at.subheader[0].value.startswith("PLOTID p3 · ponto 3 de 3")
    assert next(t for t in at.text_input if t.label == "Ir para o ponto").value == ""  # campo limpo após o salto
    _saltar(at, "zzz")
    assert any("não existe neste conjunto" in i.value for i in at.info) and at.subheader[0].value.startswith("PLOTID p3")
    # Responde p1 e volta a ele no modo pendentes: está fora do filtro, mas abre com aviso.
    _saltar(at, "p1")
    _radio(at, "classe_ref").set_value("1").run()
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    assert at.subheader[0].value.startswith("PLOTID p2")
    _saltar(at, "p1")
    assert at.subheader[0].value.startswith("PLOTID p1") and any("fora da lista do modo atual" in i.value for i in at.info)
    assert any("Já respondido" in s.value for s in at.success)
    _radio(at, "Modo").set_value("revisao").run()
    _saltar(at, "p2")
    assert at.subheader[0].value.startswith("PLOTID p2")
    assert SENTINELA_VALOR not in _todo_texto(at)


def test_ir_para_o_ponto_na_segunda_passada_respeita_o_sorteio(projeto_app, monkeypatch):
    _primeira_passada(projeto_app)
    monkeypatch.setenv(modulo_app.VAR_PASSADA, "segunda")
    monkeypatch.setenv(modulo_app.VAR_FRACAO, "0.5")
    monkeypatch.setenv(modulo_app.VAR_INTERPRETE, "bia")
    at = _app()
    sorteados = json.loads((projeto_app.parent / "respostas" / "segunda" / "amostra.json").read_text(encoding="utf-8"))
    fora = next(p for p in ("p2", "p3") if p not in sorteados["controle"])
    _saltar(at, fora)
    assert any("não existe neste conjunto" in i.value for i in at.info)
    assert at.subheader[0].value.startswith("PLOTID p1")
    assert "Já respondido" not in _todo_texto(at)


# ---- segunda passada: amostra persistida ----------------------------------------------------


def test_segunda_passada_persiste_e_reusa_a_amostra(projeto_app, monkeypatch):
    projeto, arm = _primeira_passada(projeto_app)
    monkeypatch.setenv(modulo_app.VAR_PASSADA, "segunda")
    monkeypatch.setenv(modulo_app.VAR_FRACAO, "0.5")
    monkeypatch.setenv(modulo_app.VAR_INTERPRETE, "bia")
    at = _app()
    arquivo = projeto_app.parent / "respostas" / "segunda" / "amostra.json"
    amostra = json.loads(arquivo.read_text(encoding="utf-8"))
    assert amostra["baixa"] == ["p1"] and len(amostra["controle"]) == 1 and amostra["interprete_previsto"] == "bia"
    assert "Amostra sorteada em" in _todo_texto(at)
    # A amostra gravada manda, mesmo que as respostas da primeira passada mudem depois.
    arm.gravar("p3", {"classe_ref": "6", "confianca": "baixa", "classe_alt": "1"})
    amostra["controle"] = ["p2"]
    arquivo.write_text(json.dumps(amostra), encoding="utf-8")
    at2 = _app()
    assert "2 pontos, 1 de controle" in _todo_texto(at2)
    _saltar(at2, "p3")
    assert any("não existe neste conjunto" in i.value for i in at2.info)
    _saltar(at2, "p2")
    assert at2.subheader[0].value.startswith("PLOTID p2")


# ---- revisão dirigida por lista externa ---------------------------------------------------


def _lista(projeto_app: Path, conteudo: str, nome: str = "lista.csv") -> Path:
    arq = projeto_app.parent / nome
    arq.write_text(conteudo, encoding="utf-8")
    return arq


def test_revisao_dirigida(projeto_app, monkeypatch):
    projeto, arm = _primeira_passada(projeto_app)
    # CSV com o critério numa coluna extra: a interface só pode conhecer os PLOTIDs.
    arq = _lista(projeto_app, "criterio,PLOTID\nMOTIVO_SECRETO_A,p3\nMOTIVO_SECRETO_B,p1\n")
    monkeypatch.setenv(modulo_app.VAR_PASSADA, "dirigida")
    monkeypatch.setenv(modulo_app.VAR_LISTA, str(arq))
    monkeypatch.setenv(modulo_app.VAR_INTERPRETE, "ana")
    at = _app()
    texto = _todo_texto(at)
    assert "Revisão dirigida" in texto and "2 pontos da lista `lista.csv`" in texto
    assert "MOTIVO_SECRETO" not in texto and "criterio" not in texto and SENTINELA_VALOR not in texto
    assert list(at.radio[0].options) == ["Da lista, ainda não revistos", "Toda a lista"]
    # Ordem do arquivo (p3 antes de p1), resposta anterior visível e rascunho preenchido.
    assert at.subheader[0].value.startswith("PLOTID p3 · ponto 1 de 2")
    assert any("Já respondido" in s.value and "classe_ref = 6" in s.value for s in at.success)
    assert _radio(at, "classe_ref").value == "6"
    # Confirmar sem mudar nada conta como revisão e carimba a lista.
    _botao(at, "Confirmar").click().run()
    r = _respostas(projeto_app)["p3"]
    assert r["valores"]["classe_ref"] == "6" and r["revisoes"] == 1 and r["interprete"] == "ana"
    assert r["meta"]["modo"] == "dirigida" and r["meta"]["filtro"] == "pendentes"
    assert r["meta"]["lista"]["arquivo"] == "lista.csv" and len(r["meta"]["lista"]["sha256"]) == 64 and r["meta"]["lista"]["n"] == 2
    assert "MOTIVO_SECRETO" not in json.dumps(r)
    # Avançou para p1 (ponto 1 de 1 entre os não revistos); mudança de valor também é revisão.
    assert at.subheader[0].value.startswith("PLOTID p1 · ponto 1 de 1")
    _radio(at, "confianca").set_value("alta").run()
    _botao(at, "Confirmar").click().run()
    r = _respostas(projeto_app)["p1"]
    assert r["valores"]["confianca"] == "alta" and r["revisoes"] == 1 and r["meta"]["modo"] == "dirigida"
    assert not at.subheader and any("Sessão concluída" in i.value for i in at.info)
    assert "Universo desta sessão (revisão dirigida (lista.csv)): 2/2" in _todo_texto(at)
    _radio(at, "Modo").set_value("todos").run()
    assert at.subheader[0].value.startswith("PLOTID p3 · ponto 1 de 2") and "já revisto nesta lista" in _todo_texto(at)
    # p2 não está na lista: o salto recusa.
    _saltar(at, "p2")
    assert any("não existe neste conjunto" in i.value for i in at.info)
    # A sessão ficou registrada com a lista e o hash; nada do critério no arquivo.
    dados = json.loads((projeto_app.parent / "respostas" / "respostas.json").read_text(encoding="utf-8"))
    sessao = dados["sessoes"][-1]
    assert sessao["modo"] == "dirigida" and sessao["lista"]["arquivo"] == "lista.csv" and sessao["lista"]["n"] == 2
    assert "MOTIVO_SECRETO" not in json.dumps(dados)
    # Reabrir com a mesma lista: nada pendente (já revistos com este hash).
    at2 = _app()
    assert not at2.subheader and any("Sessão concluída" in s.value for s in at2.success)
    assert "MOTIVO_SECRETO" not in _todo_texto(at2)


def test_revisao_dirigida_recusa_plotid_desconhecido(projeto_app, monkeypatch):
    _primeira_passada(projeto_app)
    arq = _lista(projeto_app, "p1\np9\n", nome="lista.txt")
    monkeypatch.setenv(modulo_app.VAR_PASSADA, "dirigida")
    monkeypatch.setenv(modulo_app.VAR_LISTA, str(arq))
    at = AppTest.from_file(modulo_app.__file__, default_timeout=60)
    at.run()
    assert at.error and "p9" in at.error[0].value and not at.radio


# ---- conclusão, fluxo guiado (embrião) e encerramento --------------------------------------


def _responder_tudo(at: AppTest) -> None:
    for classe in ("1", "2", "6"):
        _radio(at, "classe_ref").set_value(classe).run()
        _radio(at, "confianca").set_value("media" if classe == "2" else "alta").run()
        if classe == "2":
            _radio(at, "classe_alt").set_value("1").run()
        _botao(at, "Confirmar").click().run()


def test_tela_de_conclusao_e_proximas_etapas(projeto_app, monkeypatch):
    from miradouro.interface import servidor

    chamadas: list[str] = []
    monkeypatch.setattr(servidor, "desligar_servidor", lambda: chamadas.append("stop") or True)
    at = _app()
    _responder_tudo(at)
    texto = _todo_texto(at)
    assert not at.subheader and any("Sessão concluída" in i.value for i in at.info)
    assert "Universo desta sessão (interpretação): 3/3 pontos revisados" in texto
    assert "**3** respondidos de 3" in texto and "**3** gravados nesta sessão (0 revisões)" in texto
    assert "1 floresta = 1" in texto and "6 Água = 1" in texto
    assert SENTINELA_VALOR not in texto and SENTINELA_COLUNA not in texto
    # Etapas do protocolo com comandos copiáveis (st.code), sem executar nada.
    assert "Interpretação** — 3/3 respondidos" in texto
    assert "Revisão por confiança** — 1 ponto(s) com confianca em" in texto and "1 ainda não revisto(s) com ela" in texto
    codigos = [c.value for c in at.code]
    assert any("--lista" in c and c.endswith("revisao_confianca.csv") for c in codigos)
    assert any("sortear" in c and "--fracao-controle 0.10" in c for c in codigos)
    assert any("relatorio" in c and "exportar csv" in c for c in codigos)
    assert not any("--consenso" in c for c in codigos)  # consenso não aplicável ainda
    lista = projeto_app.parent / "listas" / "revisao_confianca.csv"
    assert lista.read_text(encoding="utf-8") == "PLOTID\np2\n"
    # Da conclusão dá para reabrir um ponto; reabrir o app cai direto na conclusão.
    _saltar(at, "p2")
    assert at.subheader[0].value.startswith("PLOTID p2") and any("fora da lista" in i.value for i in at.info)
    at2 = _app()
    assert not at2.subheader and "Sessão concluída" in _todo_texto(at2)
    # Encerrar: mensagem final e pedido de parada ao runtime.
    _botao(at2, "Encerrar app").click().run()
    assert chamadas == ["stop"] and any("App encerrado" in s.value for s in at2.success)
    assert not at2.radio and not at2.button


def test_conclusao_na_segunda_passada_nao_mostra_a_primeira(projeto_app, monkeypatch):
    _primeira_passada(projeto_app)
    monkeypatch.setenv(modulo_app.VAR_PASSADA, "segunda")
    monkeypatch.setenv(modulo_app.VAR_FRACAO, "0.5")
    monkeypatch.setenv(modulo_app.VAR_INTERPRETE, "bia")
    at = _app()
    for _ in range(2):
        _radio(at, "classe_ref").set_value("2").run()
        _radio(at, "confianca").set_value("alta").run()
        _botao(at, "Confirmar").click().run()
    texto = _todo_texto(at)
    assert "Universo desta sessão (segunda passada cega): 2/2" in texto
    assert "Já respondido" not in texto and "classe_ref = 1" not in texto and SENTINELA_VALOR not in texto
    assert "Segunda passada cega** — 2/2" in texto and "Consenso** — 1 divergências" in texto
    assert any("--consenso" in c.value for c in at.code)
