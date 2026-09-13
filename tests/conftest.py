"""Fixtures comuns: um projeto mínimo válido em dict, yaml e csv temporários."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from miradouro.core.projeto import Projeto, carregar_projeto, projeto_de_dict

PROJETO_MINIMO: dict = {
    "nome": "Teste",
    "ano_referencia": 2023,
    "pontos": {"arquivo": "pontos.csv", "colunas_ocultas": ["classe_mapa"]},
    "legenda": [
        {"codigo": 1, "nome": "floresta", "tecla": "1", "cor": "#1a9850"},
        {"codigo": 2, "nome": "pasto", "tecla": "2", "cor": "#fee08b", "descricao": "gramíneas"},
        {"codigo": "6", "nome": "agua", "rotulo": "Água", "tecla": "6", "cor": "#4575B4"},
    ],
    "campos": [
        {"nome": "classe_ref", "tipo": "classe", "obrigatorio": True},
        {
            "nome": "confianca",
            "tipo": "opcao",
            "obrigatorio": True,
            "opcoes": [
                {"valor": "alta", "tecla": "A"},
                {"valor": "media", "rotulo": "média", "tecla": "M"},
                {"valor": "baixa", "tecla": "B"},
            ],
        },
        {"nome": "fonte", "tipo": "multiopcao", "opcoes": [{"valor": "hr", "tecla": "H"}, {"valor": "serie", "tecla": "N"}, {"valor": "sazonal", "tecla": "S"}]},
        {
            "nome": "classe_alt",
            "tipo": "classe",
            "obrigatorio_se": {"campo": "confianca", "diferente_de": "alta"},
        },
        {"nome": "observacao", "tipo": "texto"},
        {"nome": "cobertura_pct", "tipo": "numero"},
        {"nome": "revisar", "tipo": "booleano"},
    ],
    "chips": {"pasta": "chips", "provedores": {}},
    "saida": {"pasta": "respostas", "backups": 3},
}

CSV_MINIMO = """PLOTID,LON,LAT,classe_mapa,regiao
p1,-44.1,-19.9,1,norte
p2,-44.2,-20.0,2,sul
p3,-44.3,-20.1,6,sul
"""


@pytest.fixture
def dados_projeto() -> dict:
    return copy.deepcopy(PROJETO_MINIMO)


@pytest.fixture
def pasta_projeto(tmp_path: Path, dados_projeto: dict) -> Path:
    """Pasta temporária com projeto.yaml e pontos.csv válidos."""
    (tmp_path / "projeto.yaml").write_text(yaml.safe_dump(dados_projeto, allow_unicode=True), encoding="utf-8")
    (tmp_path / "pontos.csv").write_text(CSV_MINIMO, encoding="utf-8")
    return tmp_path


@pytest.fixture
def projeto(pasta_projeto: Path) -> Projeto:
    return carregar_projeto(pasta_projeto / "projeto.yaml")


@pytest.fixture
def projeto_sem_arquivo(dados_projeto: dict) -> Projeto:
    return projeto_de_dict(dados_projeto)
