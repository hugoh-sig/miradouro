"""Contrato de dados do MIRADOURO: projeto, pontos e respostas.

Este subpacote não depende de Earth Engine, matplotlib ou rede. Tudo o que a
interface (Sprint 2) e os exportadores (Sprint 3) precisam saber sobre um
projeto passa por aqui.
"""

from miradouro.core.erros import (
    ErroArquivoCorrompido,
    ErroMiradouro,
    ErroPontos,
    ErroProjeto,
    ErroRespostas,
)
from miradouro.core.pontos import ConjuntoPontos, Ponto, carregar_pontos
from miradouro.core.projeto import (
    Campo,
    ClasseLegenda,
    OpcaoCampo,
    Projeto,
    carregar_projeto,
    validar_resposta,
)
from miradouro.core.respostas import Armazenamento, Resposta, escrever_atomico

__all__ = [
    "Armazenamento",
    "Campo",
    "ClasseLegenda",
    "ConjuntoPontos",
    "ErroArquivoCorrompido",
    "ErroMiradouro",
    "ErroPontos",
    "ErroProjeto",
    "ErroRespostas",
    "OpcaoCampo",
    "Ponto",
    "Projeto",
    "Resposta",
    "carregar_pontos",
    "carregar_projeto",
    "escrever_atomico",
    "validar_resposta",
]
