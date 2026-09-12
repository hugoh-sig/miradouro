import json
import os
from pathlib import Path

import pytest

from miradouro import __version__
from miradouro.core import Armazenamento, ErroArquivoCorrompido, ErroRespostas, escrever_atomico


def _arm(projeto, interprete="ana", **kw):
    return Armazenamento(projeto, interprete=interprete, **kw)


def test_gravar_e_obter(projeto):
    arm = _arm(projeto)
    sessao = arm.abrir_sessao()
    r = arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    assert r.plotid == "p1" and r.revisoes == 0 and r.sessao_id == sessao
    assert r.interprete == "ana" and r.miradouro_versao == __version__
    assert r.yaml_sha256 == projeto.hash_yaml
    assert r.criado_em == r.atualizado_em

    # Persistiu em disco com metadados de auditoria.
    dados = json.loads(arm.arquivo.read_text(encoding="utf-8"))
    assert dados["formato"] == 1
    assert dados["projeto"]["yaml_sha256"] == projeto.hash_yaml
    assert dados["projeto"]["nome"] == "Teste"
    assert dados["sessoes"][0]["id"] == sessao and dados["sessoes"][0]["interprete"] == "ana"
    assert dados["respostas"]["p1"]["valores"] == {"classe_ref": "1", "confianca": "alta"}

    # Reabrir recupera tudo.
    arm2 = _arm(projeto, interprete="bia")
    assert arm2.obter("p1").valores["classe_ref"] == "1"
    assert arm2.obter("nao").__class__ is type(None)
    assert arm2.respondidos() == {"p1"}
    assert arm2.pendentes(["p1", "p2", "p3"]) == ["p2", "p3"]
    assert set(arm2.todas()) == {"p1"}


def test_atualizacao_incrementa_revisoes_e_preserva_criacao(projeto):
    arm = _arm(projeto)
    arm.abrir_sessao()
    r1 = arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    r2 = arm.gravar("p1", {"classe_ref": "2", "confianca": "media", "classe_alt": "1"})
    assert r2.revisoes == 1 and r2.criado_em == r1.criado_em
    assert arm.obter("p1").valores["classe_ref"] == "2"
    assert arm.remover("p1") is True and arm.remover("p1") is False
    assert arm.obter("p1") is None


def test_gravar_invalida_levanta_e_nao_persiste(projeto):
    arm = _arm(projeto)
    with pytest.raises(ErroRespostas, match="classe_ref: obrigatório"):
        arm.gravar("p1", {"confianca": "alta"})
    assert not arm.arquivo.exists()
    # Rascunho sem validação é permitido explicitamente.
    arm.gravar("p1", {"confianca": "alta"}, validar=False)
    assert arm.obter("p1").valores == {"confianca": "alta"}


def test_gravar_sem_sessao_marca_sem_sessao(projeto):
    arm = _arm(projeto)
    assert arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"}).sessao_id == "sem-sessao"


def test_interprete_obrigatorio(projeto):
    with pytest.raises(ErroRespostas):
        Armazenamento(projeto, interprete="  ")


def test_pasta_personalizada(projeto, tmp_path):
    arm = _arm(projeto, pasta=tmp_path / "outra")
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    assert (tmp_path / "outra" / "respostas.json").exists()


# ---- gravação atômica ---------------------------------------------------------


def test_escrever_atomico_nao_deixa_temporario(tmp_path):
    alvo = tmp_path / "sub" / "a.txt"
    escrever_atomico(alvo, "olá")
    escrever_atomico(alvo, b"\x89PNG")
    assert alvo.read_bytes() == b"\x89PNG"
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["a.txt"]


def test_falha_no_rename_preserva_original(tmp_path, monkeypatch):
    alvo = tmp_path / "a.json"
    alvo.write_text("original")

    def explode(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        escrever_atomico(alvo, "novo")
    assert alvo.read_text() == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]  # temporário removido


def test_falha_ao_gravar_resposta_preserva_arquivo(projeto, monkeypatch):
    arm = _arm(projeto)
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    antes = arm.arquivo.read_text(encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("falhou")))
    with pytest.raises(OSError):
        arm.gravar("p2", {"classe_ref": "2", "confianca": "alta"})
    assert arm.arquivo.read_text(encoding="utf-8") == antes


# ---- backups rotativos por sessão ---------------------------------------------


def test_backup_por_sessao_e_rotacao(projeto):
    arm = _arm(projeto)  # backups: 3 no projeto
    assert arm.abrir_sessao() and arm.listar_backups() == []  # sem arquivo, sem backup
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    for _ in range(5):
        arm.abrir_sessao()
    backups = arm.listar_backups()
    assert len(backups) == 3
    assert all(b.name.startswith("respostas_") for b in backups)
    # O mais recente vem primeiro e corresponde à última sessão.
    assert arm.sessao_id in backups[0].name
    assert len(arm.sessoes) == 6
    assert arm.resumo()["backups"] == 3 and arm.resumo()["respostas"] == 1


def test_backups_zero_desliga(projeto):
    arm = _arm(projeto, max_backups=0)
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    arm.abrir_sessao()
    assert arm.listar_backups() == []


# ---- recuperação --------------------------------------------------------------


def test_arquivo_corrompido_levanta(projeto):
    arm = _arm(projeto)
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    arm.arquivo.write_text("{ isto não é json")
    with pytest.raises(ErroArquivoCorrompido, match="JSON"):
        _arm(projeto)
    arm.arquivo.write_text('{"outro": 1}')
    with pytest.raises(ErroArquivoCorrompido, match="formato"):
        _arm(projeto)
    arm.arquivo.write_text('{"formato": 99, "respostas": {}}')
    with pytest.raises(ErroArquivoCorrompido, match="não suportado"):
        _arm(projeto)


def test_recuperar_de_backup(projeto):
    arm = _arm(projeto)
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    arm.abrir_sessao()  # cria backup com p1
    arm.gravar("p2", {"classe_ref": "2", "confianca": "alta"})
    arm.arquivo.write_text("corrompido")

    usado = Armazenamento.recuperar_de_backup(arm.pasta)
    assert usado.parent == arm.pasta_backups
    restaurado = _arm(projeto)
    assert restaurado.respondidos() == {"p1"}  # p2 foi gravado depois do backup
    corrompidos = list(arm.pasta.glob("respostas.json.corrompido-*"))
    assert len(corrompidos) == 1 and corrompidos[0].read_text() == "corrompido"


def test_recuperar_ignora_backup_ilegivel_e_falha_sem_backups(projeto, tmp_path):
    arm = _arm(projeto)
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    arm.abrir_sessao()
    for b in arm.listar_backups():
        b.write_text("lixo")
    with pytest.raises(ErroRespostas, match="nenhum backup"):
        Armazenamento.recuperar_de_backup(arm.pasta)
    with pytest.raises(ErroRespostas):
        Armazenamento.recuperar_de_backup(tmp_path / "vazia")


def test_hash_divergente_registrado(projeto, pasta_projeto):
    arm = _arm(projeto)
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    assert arm.hash_divergente is False
    from miradouro.core import carregar_projeto

    y = pasta_projeto / "projeto.yaml"
    y.write_text(y.read_text() + "\ndescricao: mudou\n")
    novo = carregar_projeto(y)
    arm2 = _arm(novo)
    assert arm2.hash_divergente is True
    assert arm2.obter("p1").yaml_sha256 == projeto.hash_yaml  # resposta antiga guarda o hash antigo
    r = arm2.gravar("p2", {"classe_ref": "1", "confianca": "alta"})
    assert r.yaml_sha256 == novo.hash_yaml


def test_projeto_sem_arquivo_usa_cwd(projeto_sem_arquivo, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert projeto_sem_arquivo.pasta_saida == Path(tmp_path / "respostas").resolve()
    assert projeto_sem_arquivo.hash_yaml is None
    arm = Armazenamento(projeto_sem_arquivo, interprete="x")
    arm.gravar("p1", {"classe_ref": "1", "confianca": "alta"})
    assert (tmp_path / "respostas" / "respostas.json").exists()
