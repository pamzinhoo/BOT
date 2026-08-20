from __future__ import annotations

import contextlib
from collections.abc import Hashable, Iterator

_IN_FLIGHT: set[Hashable] = set()


@contextlib.contextmanager
def try_acquire(key: Hashable) -> Iterator[bool]:
    """Trava in-memory contra clique duplicado (mesmo usuario, mesmo recurso)
    enquanto o primeiro clique ainda esta em voo — usada em botoes publicos
    que um usuario pode spammar (Entrar/Sair de sorteio, Assumir ticket) antes
    da UI reeditada chegar de volta. Yielda False se ja tem uma chamada em
    andamento pra essa chave; quem chamou deve responder e retornar sem tocar
    banco/Discord de novo.

    So resolve duplo-clique do MESMO processo/cliente antes da resposta
    voltar — concorrencia real entre processos ainda depende da trava de
    banco (`FOR UPDATE`) ou de uma constraint unica, que continuam sendo a
    defesa de verdade contra corrida."""
    if key in _IN_FLIGHT:
        yield False
        return
    _IN_FLIGHT.add(key)
    try:
        yield True
    finally:
        _IN_FLIGHT.discard(key)
