"""Parser e validador do ``projeto.yaml``.

O yaml descreve tudo o que a ferramenta precisa saber sobre um projeto de
validação: legenda, campos de resposta, pontos, colunas ocultas ao intérprete
e provedores de chips habilitados. Nada disso está codificado no pacote.

Estrutura (ver ``exemplos/`` para versões comentadas)::

    nome: ...
    ano_referencia: 2023
    pontos: {arquivo: pontos.csv, colunas_ocultas: [...]}
    legenda: [{codigo, nome, rotulo, descricao, tecla, cor}, ...]
    campos: [{nome, tipo, rotulo, obrigatorio, obrigatorio_se, opcoes, ajuda}, ...]
    chips: {pasta: chips, provedores: {nome_do_provedor: {config...}}}
    saida: {pasta: respostas, backups: 10}
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from miradouro.core.erros import ErroProjeto

# Nomes de coluna reservados ao CSV de pontos; nunca podem nomear um campo de resposta.
COLUNAS_RESERVADAS = frozenset({"plotid", "lon", "lat"})

TiposCampo = Literal["classe", "opcao", "texto", "numero", "booleano"]

_RE_NOME = re.compile(r"^[a-z][a-z0-9_]*$")
_RE_COR = re.compile(r"^#[0-9a-fA-F]{6}$")


class _Modelo(BaseModel):
    """Base: rejeita chaves desconhecidas para apanhar erros de digitação no yaml."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClasseLegenda(_Modelo):
    """Uma classe da legenda do mapa."""

    codigo: str = Field(description="Código gravado na resposta (ex.: '1', 'FLO').")
    nome: str = Field(description="Identificador curto, estável (ex.: veg_nativa).")
    rotulo: str | None = Field(default=None, description="Nome legível; assume `nome` se omitido.")
    descricao: str = Field(default="", description="Como a classe aparece nas imagens; dicas de decisão.")
    tecla: str = Field(description="Tecla de atalho (um caractere).")
    cor: str = Field(default="#808080", description="Cor hexadecimal (#rrggbb).")

    @field_validator("codigo", mode="before")
    @classmethod
    def _codigo_como_texto(cls, v: Any) -> str:
        if isinstance(v, bool) or v is None:
            raise ValueError("código da classe deve ser texto ou número")
        return str(v)

    @field_validator("tecla", mode="before")
    @classmethod
    def _tecla_um_caractere(cls, v: Any) -> str:
        v = str(v)
        if len(v) != 1:
            raise ValueError(f"tecla deve ter exatamente um caractere, recebido {v!r}")
        return v

    @field_validator("cor")
    @classmethod
    def _cor_hex(cls, v: str) -> str:
        if not _RE_COR.match(v):
            raise ValueError(f"cor deve estar no formato #rrggbb, recebido {v!r}")
        return v.lower()

    @model_validator(mode="after")
    def _rotulo_padrao(self) -> ClasseLegenda:
        if not self.rotulo:
            self.rotulo = self.nome
        return self


class OpcaoCampo(_Modelo):
    """Uma opção de um campo do tipo ``opcao``."""

    valor: str
    rotulo: str | None = None
    tecla: str | None = None

    @field_validator("valor", mode="before")
    @classmethod
    def _valor_como_texto(cls, v: Any) -> str:
        return str(v)

    @field_validator("tecla", mode="before")
    @classmethod
    def _tecla_um_caractere(cls, v: Any) -> str | None:
        if v is None:
            return None
        v = str(v)
        if len(v) != 1:
            raise ValueError(f"tecla deve ter exatamente um caractere, recebido {v!r}")
        return v

    @model_validator(mode="after")
    def _rotulo_padrao(self) -> OpcaoCampo:
        if not self.rotulo:
            self.rotulo = self.valor
        return self


class CondicaoCampo(_Modelo):
    """Condição que torna um campo obrigatório (ex.: confiança ≠ alta)."""

    campo: str
    igual_a: str | list[str] | None = None
    diferente_de: str | list[str] | None = None

    @model_validator(mode="after")
    def _exatamente_uma(self) -> CondicaoCampo:
        if (self.igual_a is None) == (self.diferente_de is None):
            raise ValueError("informe exatamente um de `igual_a` ou `diferente_de`")
        return self

    def valores(self) -> list[str]:
        v = self.igual_a if self.igual_a is not None else self.diferente_de
        return [str(x) for x in (v if isinstance(v, list) else [v])]

    def satisfeita(self, valor_do_campo: Any) -> bool:
        """True quando a condição se aplica ao valor atual do campo referido."""
        if valor_do_campo is None or valor_do_campo == "":
            # Sem valor no campo condicionante, a condição não pode ser avaliada.
            return False
        v = str(valor_do_campo)
        if self.igual_a is not None:
            return v in self.valores()
        return v not in self.valores()


class Campo(_Modelo):
    """Um campo de resposta preenchido pelo intérprete para cada ponto."""

    nome: str
    tipo: TiposCampo
    rotulo: str | None = None
    obrigatorio: bool = False
    obrigatorio_se: CondicaoCampo | None = None
    opcoes: list[OpcaoCampo] = Field(default_factory=list)
    padrao: str | None = Field(default=None, description="Regex que um campo `texto` deve satisfazer (ex.: AAAA-MM).")
    ajuda: str = ""

    @field_validator("nome")
    @classmethod
    def _nome_valido(cls, v: str) -> str:
        if not _RE_NOME.match(v):
            raise ValueError(
                f"nome de campo inválido {v!r}: use minúsculas, dígitos e '_' (ex.: classe_ref)"
            )
        if v in COLUNAS_RESERVADAS:
            raise ValueError(f"nome de campo {v!r} é reservado ao CSV de pontos")
        return v

    @field_validator("opcoes", mode="before")
    @classmethod
    def _opcoes_simples(cls, v: Any) -> Any:
        # Permite `opcoes: [hr, serie, s2]` além da forma longa com rotulo/tecla.
        if isinstance(v, list):
            return [{"valor": str(o)} if not isinstance(o, dict) else o for o in v]
        return v

    @model_validator(mode="after")
    def _coerencia(self) -> Campo:
        if not self.rotulo:
            self.rotulo = self.nome
        if self.tipo == "opcao":
            if not self.opcoes:
                raise ValueError(f"campo {self.nome!r} do tipo 'opcao' precisa de `opcoes`")
            _sem_duplicatas([o.valor for o in self.opcoes], f"valores do campo {self.nome!r}")
            _sem_duplicatas(
                [o.tecla.lower() for o in self.opcoes if o.tecla],
                f"teclas do campo {self.nome!r}",
            )
        elif self.opcoes:
            raise ValueError(f"campo {self.nome!r} do tipo {self.tipo!r} não aceita `opcoes`")
        if self.padrao is not None:
            if self.tipo != "texto":
                raise ValueError(f"campo {self.nome!r}: `padrao` só se aplica ao tipo 'texto'")
            try:
                re.compile(self.padrao)
            except re.error as e:
                raise ValueError(f"campo {self.nome!r}: `padrao` não é regex válida ({e})") from None
        if self.obrigatorio and self.obrigatorio_se is not None:
            raise ValueError(
                f"campo {self.nome!r}: `obrigatorio: true` e `obrigatorio_se` são excludentes"
            )
        if self.obrigatorio_se is not None and self.obrigatorio_se.campo == self.nome:
            raise ValueError(f"campo {self.nome!r}: `obrigatorio_se` não pode referir a si mesmo")
        return self

    @property
    def condicional(self) -> bool:
        return self.obrigatorio_se is not None


class ConfigPontos(_Modelo):
    arquivo: Path = Field(description="CSV de pontos; relativo à pasta do yaml.")
    colunas_ocultas: list[str] = Field(
        default_factory=list,
        description="Colunas extras do CSV que o intérprete NUNCA vê (ex.: classe do mapa).",
    )


class ConfigChips(_Modelo):
    pasta: Path = Field(default=Path("chips"), description="Cache local; relativo à pasta do yaml.")
    provedores: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Provedores habilitados e sua configuração. O nome deve estar registrado em miradouro.chips.",
    )

    @field_validator("provedores", mode="before")
    @classmethod
    def _config_vazia(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return {k: ({} if val is None else val) for k, val in v.items()}
        return v


class ConfigSaida(_Modelo):
    pasta: Path = Field(default=Path("respostas"), description="Onde ficam respostas e backups.")
    backups: int = Field(default=10, ge=0, description="Backups de sessão mantidos (rotativo).")


class Projeto(_Modelo):
    """Um projeto de validação carregado e validado."""

    nome: str
    ano_referencia: int = Field(ge=1972, le=2100)
    descricao: str = ""
    pontos: ConfigPontos
    legenda: list[ClasseLegenda] = Field(min_length=1)
    campos: list[Campo] = Field(min_length=1)
    chips: ConfigChips = Field(default_factory=ConfigChips)
    saida: ConfigSaida = Field(default_factory=ConfigSaida)

    # Preenchidos por carregar_projeto(); não vêm do yaml.
    caminho_yaml: Path | None = Field(default=None, exclude=True)
    hash_yaml: str | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _coerencia(self) -> Projeto:
        _sem_duplicatas([c.codigo for c in self.legenda], "códigos da legenda")
        _sem_duplicatas([c.nome for c in self.legenda], "nomes da legenda")
        _sem_duplicatas([c.tecla.lower() for c in self.legenda], "teclas da legenda")
        _sem_duplicatas([c.nome for c in self.campos], "nomes dos campos")
        por_nome = {c.nome: c for c in self.campos}
        for campo in self.campos:
            cond = campo.obrigatorio_se
            if cond is None:
                continue
            alvo = por_nome.get(cond.campo)
            if alvo is None:
                raise ValueError(
                    f"campo {campo.nome!r}: `obrigatorio_se` refere a campo inexistente {cond.campo!r}"
                )
            validos = self._valores_validos(alvo)
            if validos is not None:
                desconhecidos = [v for v in cond.valores() if v not in validos]
                if desconhecidos:
                    raise ValueError(
                        f"campo {campo.nome!r}: `obrigatorio_se` usa valores {desconhecidos} "
                        f"que não existem em {alvo.nome!r}"
                    )
        return self

    # ---- consultas -------------------------------------------------------

    def _valores_validos(self, campo: Campo) -> set[str] | None:
        if campo.tipo == "classe":
            return {c.codigo for c in self.legenda}
        if campo.tipo == "opcao":
            return {o.valor for o in campo.opcoes}
        return None

    @property
    def pasta_base(self) -> Path:
        """Pasta do yaml (ou o diretório atual quando o projeto não veio de um arquivo)."""
        return self.caminho_yaml.parent if self.caminho_yaml else Path.cwd()

    def _resolver(self, p: Path) -> Path:
        return p if p.is_absolute() else (self.pasta_base / p).resolve()

    @property
    def caminho_pontos(self) -> Path:
        return self._resolver(self.pontos.arquivo)

    @property
    def pasta_chips(self) -> Path:
        return self._resolver(self.chips.pasta)

    @property
    def pasta_saida(self) -> Path:
        return self._resolver(self.saida.pasta)

    @property
    def colunas_ocultas(self) -> frozenset[str]:
        return frozenset(self.pontos.colunas_ocultas)

    def classe(self, codigo: Any) -> ClasseLegenda | None:
        codigo = str(codigo)
        return next((c for c in self.legenda if c.codigo == codigo), None)

    def classe_por_tecla(self, tecla: str) -> ClasseLegenda | None:
        return next((c for c in self.legenda if c.tecla.lower() == tecla.lower()), None)

    def campo(self, nome: str) -> Campo | None:
        return next((c for c in self.campos if c.nome == nome), None)

    @property
    def campos_obrigatorios(self) -> list[Campo]:
        return [c for c in self.campos if c.obrigatorio]

    def provedores_habilitados(self) -> list[str]:
        return list(self.chips.provedores)


# ---------------------------------------------------------------------------


def _sem_duplicatas(valores: list[str], contexto: str) -> None:
    vistos: set[str] = set()
    repetidos: list[str] = []
    for v in valores:
        if v in vistos and v not in repetidos:
            repetidos.append(v)
        vistos.add(v)
    if repetidos:
        raise ValueError(f"{contexto} repetidos: {repetidos}")


def _formatar_erro_pydantic(erro: ValidationError) -> str:
    linhas = []
    for e in erro.errors():
        caminho = ".".join(str(p) for p in e["loc"]) or "(raiz)"
        msg = e["msg"]
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        linhas.append(f"  - {caminho}: {msg}")
    return "\n".join(linhas)


def hash_de_bytes(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def projeto_de_dict(dados: dict[str, Any], caminho: Path | None = None, hash_yaml: str | None = None) -> Projeto:
    """Constrói um :class:`Projeto` a partir de um dicionário já carregado."""
    if not isinstance(dados, dict):
        raise ErroProjeto("projeto.yaml deve ter um mapeamento no nível superior")
    try:
        projeto = Projeto.model_validate(dados)
    except ValidationError as e:
        raise ErroProjeto("projeto.yaml inválido:\n" + _formatar_erro_pydantic(e)) from None
    projeto.caminho_yaml = caminho
    projeto.hash_yaml = hash_yaml
    return projeto


def carregar_projeto(caminho: str | Path) -> Projeto:
    """Lê e valida um ``projeto.yaml``.

    Raises:
        ErroProjeto: arquivo ausente, yaml malformado ou conteúdo inconsistente.
    """
    caminho = Path(caminho)
    if not caminho.is_file():
        raise ErroProjeto(f"projeto.yaml não encontrado: {caminho}")
    dados_brutos = caminho.read_bytes()
    try:
        dados = yaml.safe_load(dados_brutos)
    except yaml.YAMLError as e:
        raise ErroProjeto(f"yaml malformado em {caminho}: {e}") from None
    if dados is None:
        raise ErroProjeto(f"projeto.yaml vazio: {caminho}")
    return projeto_de_dict(dados, caminho=caminho.resolve(), hash_yaml=hash_de_bytes(dados_brutos))


# ---------------------------------------------------------------------------
# Validação de respostas (usada pela gravação e pela interface)


def _vazio(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def validar_resposta(projeto: Projeto, valores: dict[str, Any]) -> list[str]:
    """Valida os valores de resposta de um ponto contra os campos do projeto.

    Returns:
        Lista de mensagens de erro (vazia quando a resposta é válida).
    """
    erros: list[str] = []
    conhecidos = {c.nome for c in projeto.campos}
    for nome in valores:
        if nome not in conhecidos:
            erros.append(f"campo desconhecido: {nome!r}")

    for campo in projeto.campos:
        valor = valores.get(campo.nome)
        if _vazio(valor):
            if campo.obrigatorio:
                erros.append(f"{campo.nome}: obrigatório")
            elif campo.obrigatorio_se is not None and campo.obrigatorio_se.satisfeita(
                valores.get(campo.obrigatorio_se.campo)
            ):
                erros.append(f"{campo.nome}: obrigatório quando {_descrever(campo.obrigatorio_se)}")
            continue

        if campo.tipo == "classe":
            if projeto.classe(valor) is None:
                erros.append(f"{campo.nome}: código de classe inválido {valor!r}")
        elif campo.tipo == "opcao":
            if str(valor) not in {o.valor for o in campo.opcoes}:
                erros.append(f"{campo.nome}: opção inválida {valor!r}")
        elif campo.tipo == "numero":
            try:
                float(valor)
            except (TypeError, ValueError):
                erros.append(f"{campo.nome}: valor numérico inválido {valor!r}")
        elif campo.tipo == "booleano":
            if not isinstance(valor, bool) and str(valor).lower() not in {"true", "false", "sim", "nao", "não"}:
                erros.append(f"{campo.nome}: valor booleano inválido {valor!r}")
        elif campo.tipo == "texto":
            if not isinstance(valor, str):
                erros.append(f"{campo.nome}: deve ser texto")
            elif campo.padrao and not re.fullmatch(campo.padrao, valor.strip()):
                erros.append(f"{campo.nome}: {valor!r} não segue o formato esperado ({campo.padrao})")
    return erros


def _descrever(cond: CondicaoCampo) -> str:
    op = "=" if cond.igual_a is not None else "≠"
    return f"{cond.campo} {op} {'/'.join(cond.valores())}"
