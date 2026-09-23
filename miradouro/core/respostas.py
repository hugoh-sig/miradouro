"""Gravação atômica de respostas, backup rotativo por sessão e auditoria.

Formato do arquivo ``respostas.json`` (versão 1)::

    {
      "formato": 1,
      "miradouro_versao": "0.1.0",
      "projeto": {"nome": ..., "ano_referencia": ..., "yaml_sha256": ..., "yaml_caminho": ...},
      "criado_em": "...", "atualizado_em": "...",
      "sessoes": [{"id": ..., "interprete": ..., "inicio": ..., "miradouro_versao": ..., "yaml_sha256": ...}],
      "respostas": {
        "<PLOTID>": {"valores": {...}, "interprete": ..., "sessao_id": ...,
                     "criado_em": ..., "atualizado_em": ..., "revisoes": 0,
                     "miradouro_versao": ..., "yaml_sha256": ...}
      }
    }

Toda gravação escreve o arquivo inteiro num temporário na mesma pasta e faz
``os.replace`` — o arquivo anterior nunca fica meio escrito.

Backups (``backups/respostas_<timestamp>_<sessao>.json``): são feitos **na
abertura de cada sessão** (:meth:`Armazenamento.abrir_sessao`), não a cada
gravação, e contêm o estado *anterior* à sessão. A primeira sessão de um
projeto não gera backup porque ainda não existe arquivo. A rotação mantém os
``saida.backups`` mais recentes.

Compatibilidade de valores: os valores gravados são normalizados pelo tipo do
campo no yaml em vigor ao ler e ao gravar (:func:`normalizar_valores`); um
campo que virou ``multiopcao`` lê respostas antigas com string como lista.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from miradouro import __version__
from miradouro.core.erros import ErroArquivoCorrompido, ErroRespostas
from miradouro.core.projeto import Projeto, normalizar_valores, validar_resposta

log = logging.getLogger(__name__)

FORMATO_ATUAL = 1
NOME_ARQUIVO = "respostas.json"
PASTA_BACKUPS = "backups"


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def escrever_atomico(caminho: Path, conteudo: str | bytes) -> None:
    """Escreve ``conteudo`` em ``caminho`` de forma atômica (temporário + rename).

    Se qualquer passo falhar, o arquivo original permanece intacto e o
    temporário é removido.
    """
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    modo = "wb" if isinstance(conteudo, bytes) else "w"
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=f".{caminho.name}.", suffix=".tmp")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, modo, **({} if modo == "wb" else {"encoding": "utf-8"})) as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, caminho)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


@dataclass
class Resposta:
    """Resposta de um ponto com metadados de auditoria."""

    plotid: str
    valores: dict[str, Any]
    interprete: str
    sessao_id: str
    criado_em: str
    atualizado_em: str
    revisoes: int = 0
    miradouro_versao: str = __version__
    yaml_sha256: str | None = None
    #: Auditoria extra, livre (ex.: duracao_s, modo, sem_subsidio). Nunca é validada.
    meta: dict[str, Any] = field(default_factory=dict)

    def para_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("plotid")
        return d

    @classmethod
    def de_dict(cls, plotid: str, d: dict[str, Any]) -> Resposta:
        return cls(plotid=plotid, **{"meta": {}, **d})


def _ler_json(caminho: Path) -> dict[str, Any]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ErroArquivoCorrompido(f"{caminho} não é JSON válido: {e}") from None
    if not isinstance(dados, dict) or "respostas" not in dados or "formato" not in dados:
        raise ErroArquivoCorrompido(f"{caminho} não tem o formato de respostas do MIRADOURO")
    if dados["formato"] != FORMATO_ATUAL:
        raise ErroArquivoCorrompido(
            f"{caminho}: formato {dados['formato']} não suportado (esperado {FORMATO_ATUAL})"
        )
    return dados


class Armazenamento:
    """Armazena as respostas de um projeto para um intérprete.

    Uso típico::

        arm = Armazenamento(projeto, interprete="hugo")
        arm.abrir_sessao()          # faz backup do arquivo atual
        arm.gravar("12", {"classe_ref": "2", "confianca": "alta", ...})

    Um arquivo por projeto/pasta de saída. Vários intérpretes podem usar pastas
    de saída distintas (``pasta=``) e ser consolidados depois (Sprint 3).
    """

    def __init__(
        self,
        projeto: Projeto,
        interprete: str,
        pasta: str | Path | None = None,
        max_backups: int | None = None,
    ) -> None:
        if not interprete or not str(interprete).strip():
            raise ErroRespostas("id do intérprete é obrigatório")
        self.projeto = projeto
        self.interprete = str(interprete).strip()
        self.pasta = Path(pasta) if pasta is not None else projeto.pasta_saida
        self.arquivo = self.pasta / NOME_ARQUIVO
        self.pasta_backups = self.pasta / PASTA_BACKUPS
        self.max_backups = projeto.saida.backups if max_backups is None else max_backups
        self.sessao_id: str | None = None
        self._dados = self._carregar_ou_criar()

    # ---- ciclo de vida ---------------------------------------------------

    def _novo_documento(self) -> dict[str, Any]:
        agora = agora_iso()
        return {
            "formato": FORMATO_ATUAL,
            "miradouro_versao": __version__,
            "projeto": {
                "nome": self.projeto.nome,
                "ano_referencia": self.projeto.ano_referencia,
                "yaml_sha256": self.projeto.hash_yaml,
                "yaml_caminho": str(self.projeto.caminho_yaml) if self.projeto.caminho_yaml else None,
            },
            "criado_em": agora,
            "atualizado_em": agora,
            "sessoes": [],
            "respostas": {},
        }

    def _carregar_ou_criar(self) -> dict[str, Any]:
        if not self.arquivo.exists():
            return self._novo_documento()
        dados = _ler_json(self.arquivo)
        hash_gravado = dados.get("projeto", {}).get("yaml_sha256")
        if hash_gravado and self.projeto.hash_yaml and hash_gravado != self.projeto.hash_yaml:
            log.warning(
                "projeto.yaml mudou desde que %s foi criado (sha256 %s → %s); "
                "as respostas antigas guardam o hash com que foram gravadas",
                self.arquivo,
                hash_gravado[:12],
                self.projeto.hash_yaml[:12],
            )
        return dados

    @property
    def hash_divergente(self) -> bool:
        """True se o yaml atual difere do yaml com que o arquivo foi criado."""
        gravado = self._dados.get("projeto", {}).get("yaml_sha256")
        return bool(gravado and self.projeto.hash_yaml and gravado != self.projeto.hash_yaml)

    def abrir_sessao(self, extra: dict[str, Any] | None = None) -> str:
        """Inicia uma sessão: faz backup do arquivo atual (estado anterior à sessão) e a registra.

        Sem arquivo prévio (primeira sessão) não há o que copiar e nenhum backup é criado.
        ``extra`` entra no registro da sessão (ex.: modo de revisão dirigida e a lista usada).
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        self.sessao_id = f"{ts}-{uuid.uuid4().hex[:6]}"
        if self.arquivo.exists():
            self._fazer_backup()
        self._dados["sessoes"].append(
            {
                "id": self.sessao_id,
                "interprete": self.interprete,
                "inicio": agora_iso(),
                "miradouro_versao": __version__,
                "yaml_sha256": self.projeto.hash_yaml,
                **dict(extra or {}),
            }
        )
        self._salvar()
        return self.sessao_id

    def _fazer_backup(self) -> Path:
        self.pasta_backups.mkdir(parents=True, exist_ok=True)
        # Timestamp com microssegundos: a ordenação por nome é a ordem cronológica.
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        destino = self.pasta_backups / f"respostas_{ts}_{self.sessao_id}.json"
        shutil.copyfile(self.arquivo, destino)
        self._rotacionar_backups()
        return destino

    def _rotacionar_backups(self) -> None:
        if self.max_backups <= 0:
            for b in self.listar_backups():
                b.unlink()
            return
        backups = self.listar_backups()
        for antigo in backups[self.max_backups :]:
            antigo.unlink()

    def listar_backups(self) -> list[Path]:
        """Backups do mais recente para o mais antigo."""
        if not self.pasta_backups.is_dir():
            return []
        return sorted(self.pasta_backups.glob("respostas_*.json"), key=lambda p: p.name, reverse=True)

    # ---- gravação ----------------------------------------------------------

    def _salvar(self) -> None:
        self._dados["atualizado_em"] = agora_iso()
        self._dados["miradouro_versao"] = __version__
        conteudo = json.dumps(self._dados, ensure_ascii=False, indent=2, sort_keys=False)
        escrever_atomico(self.arquivo, conteudo)

    def gravar(
        self,
        plotid: str,
        valores: dict[str, Any],
        *,
        validar: bool = True,
        meta: dict[str, Any] | None = None,
    ) -> Resposta:
        """Grava (ou atualiza) a resposta de um ponto e persiste imediatamente.

        Args:
            meta: auditoria extra gravada junto (duração, modo, falta de subsídio...).

        Raises:
            ErroRespostas: se ``validar`` e os valores violam os campos do projeto.
        """
        plotid = str(plotid)
        valores = normalizar_valores(self.projeto, valores)
        if validar:
            erros = validar_resposta(self.projeto, valores)
            if erros:
                raise ErroRespostas(f"resposta inválida para PLOTID {plotid}: " + "; ".join(erros))
        agora = agora_iso()
        sessao = self.sessao_id or "sem-sessao"
        existente = self._dados["respostas"].get(plotid)
        if existente is None:
            resposta = Resposta(
                plotid=plotid,
                valores=dict(valores),
                interprete=self.interprete,
                sessao_id=sessao,
                criado_em=agora,
                atualizado_em=agora,
                revisoes=0,
                yaml_sha256=self.projeto.hash_yaml,
                meta=dict(meta or {}),
            )
        else:
            resposta = Resposta(
                plotid=plotid,
                valores=dict(valores),
                interprete=self.interprete,
                sessao_id=sessao,
                criado_em=existente["criado_em"],
                atualizado_em=agora,
                revisoes=int(existente.get("revisoes", 0)) + 1,
                yaml_sha256=self.projeto.hash_yaml,
                meta=dict(meta or {}),
            )
        self._dados["respostas"][plotid] = resposta.para_dict()
        self._salvar()
        return resposta

    def remover(self, plotid: str) -> bool:
        """Remove a resposta de um ponto. Retorna False se não existia."""
        if str(plotid) not in self._dados["respostas"]:
            return False
        del self._dados["respostas"][str(plotid)]
        self._salvar()
        return True

    # ---- consultas ---------------------------------------------------------

    def _resposta(self, plotid: str, d: dict[str, Any]) -> Resposta:
        r = Resposta.de_dict(plotid, d)
        r.valores = normalizar_valores(self.projeto, r.valores)
        return r

    def obter(self, plotid: str) -> Resposta | None:
        d = self._dados["respostas"].get(str(plotid))
        return self._resposta(str(plotid), d) if d else None

    def todas(self) -> dict[str, Resposta]:
        return {pid: self._resposta(pid, d) for pid, d in self._dados["respostas"].items()}

    def respondidos(self) -> set[str]:
        return set(self._dados["respostas"])

    def pendentes(self, ids: list[str]) -> list[str]:
        """IDs (na ordem dada) ainda sem resposta."""
        feitos = self.respondidos()
        return [i for i in ids if str(i) not in feitos]

    @property
    def sessoes(self) -> list[dict[str, Any]]:
        return list(self._dados["sessoes"])

    def resumo(self) -> dict[str, Any]:
        return {
            "arquivo": str(self.arquivo),
            "respostas": len(self._dados["respostas"]),
            "sessoes": len(self._dados["sessoes"]),
            "backups": len(self.listar_backups()),
            "hash_divergente": self.hash_divergente,
            "criado_em": self._dados["criado_em"],
            "atualizado_em": self._dados["atualizado_em"],
        }

    # ---- recuperação -------------------------------------------------------

    @classmethod
    def recuperar_de_backup(cls, pasta: str | Path) -> Path:
        """Restaura o backup válido mais recente por cima de um ``respostas.json`` corrompido.

        O arquivo corrompido é preservado como ``respostas.json.corrompido-<timestamp>``.

        Returns:
            Caminho do backup usado.

        Raises:
            ErroRespostas: se não há backup legível.
        """
        pasta = Path(pasta)
        arquivo = pasta / NOME_ARQUIVO
        backups = sorted((pasta / PASTA_BACKUPS).glob("respostas_*.json"), key=lambda p: p.name, reverse=True)
        for b in backups:
            try:
                _ler_json(b)
            except ErroArquivoCorrompido:
                log.warning("backup ilegível ignorado: %s", b)
                continue
            if arquivo.exists():
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                arquivo.rename(pasta / f"{NOME_ARQUIVO}.corrompido-{ts}")
            escrever_atomico(arquivo, b.read_text(encoding="utf-8"))
            log.info("respostas restauradas de %s", b)
            return b
        raise ErroRespostas(f"nenhum backup legível em {pasta / PASTA_BACKUPS}")
