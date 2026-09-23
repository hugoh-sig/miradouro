"""Porta livre e encerramento gracioso."""

import socket

import pytest

from miradouro.core.erros import ErroMiradouro
from miradouro.interface import servidor


@pytest.fixture
def porta_ocupada():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(8)
        yield s.getsockname()[1]


def test_escolher_porta(porta_ocupada):
    assert servidor.porta_ocupada(porta_ocupada)
    porta, mudou = servidor.escolher_porta(porta_ocupada)
    assert mudou and porta > porta_ocupada and not servidor.porta_ocupada(porta)
    with pytest.raises(ErroMiradouro):
        servidor.escolher_porta(porta_ocupada, tentativas=1)


def test_escolher_porta_livre():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        livre = s.getsockname()[1]
    assert servidor.escolher_porta(livre) == (livre, False)


def test_desligar_sem_runtime():
    assert servidor.desligar_servidor() is False
