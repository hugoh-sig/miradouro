"""Porta do servidor e encerramento gracioso do Streamlit (sem depender do Streamlit para a porta)."""

from __future__ import annotations

import errno
import socket

from miradouro.core.erros import ErroMiradouro


def porta_ocupada(porta: int, host: str = "127.0.0.1", timeout: float = 0.2) -> bool:
    """True se algo já atende em ``host:porta``.

    Tenta conectar: só uma recusa explícita (ECONNREFUSED) prova que a porta está
    livre; conexão aceita, fila cheia (EAGAIN) ou tempo esgotado contam como ocupada.
    TIME_WAIT não conta, porque não há quem recuse nem quem aceite.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            rc = s.connect_ex((host, int(porta)))
        except OSError:
            return True
        return rc != errno.ECONNREFUSED


def escolher_porta(preferida: int, tentativas: int = 20) -> tuple[int, bool]:
    """A ``preferida`` se livre, senão a próxima livre; devolve ``(porta, mudou)``.

    Raises:
        ErroMiradouro: nenhuma porta livre em ``tentativas`` a partir da preferida.
    """
    for porta in range(int(preferida), int(preferida) + max(1, tentativas)):
        if not porta_ocupada(porta):
            return porta, porta != int(preferida)
    raise ErroMiradouro(f"nenhuma porta livre entre {preferida} e {preferida + tentativas - 1}")


def desligar_servidor(atraso_s: float = 0.7) -> bool:
    """Encerra o ``streamlit run`` graciosamente, como um Ctrl+C: fecha sessões, para o
    servidor e libera a porta.

    Depois de ``atraso_s`` (tempo para a última mensagem chegar ao navegador) envia
    SIGINT ao próprio processo; o Streamlit trata o sinal com o mesmo caminho do Ctrl+C.
    Devolve False quando não há runtime (AppTest, execução fora do ``streamlit run``).
    """
    try:
        from streamlit.runtime import Runtime
    except ImportError:  # pragma: no cover
        return False
    if not Runtime.exists():
        return False
    import os
    import signal
    import threading

    def _sinal() -> None:
        if hasattr(signal, "SIGINT") and os.name != "nt":
            os.kill(os.getpid(), signal.SIGINT)
        else:  # pragma: no cover - Windows: sem SIGINT ao próprio processo
            try:
                Runtime.instance().stop()
            except RuntimeError:
                pass

    threading.Timer(max(0.0, atraso_s), _sinal).start()
    return True
