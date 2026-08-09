from __future__ import annotations

import base64
import hashlib
import secrets
import string
from dataclasses import dataclass

_USER_CODE_ALPHABET = "".join(sorted(set(string.ascii_uppercase + string.digits) - set("0O1I")))


def generate_refresh_token() -> str:
    """Token opaco entregue ao Launcher. O backend nunca reconstitui o valor
    a partir do banco — so guarda `hash_token(...)` (sha256) pra comparar."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_device_code() -> str:
    """Identificador interno da tentativa de login, usado pelo Launcher pra
    dar poll — nunca mostrado ao usuario (isso e o `user_code`)."""
    return secrets.token_urlsafe(32)


def generate_user_code() -> str:
    """Codigo curto tipo `XXXX-XXXX`, digitavel a mao, mostrado na tela do
    Launcher e conferido na pagina de autorizacao do backend. Alfabeto sem
    0/O/1/I pra evitar ambiguidade visual."""
    part = lambda: "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(4))
    return f"{part()}-{part()}"


def generate_state() -> str:
    """Parametro OAuth `state`, protecao de CSRF no callback do Discord."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True, slots=True)
class PKCEPair:
    verifier: str
    challenge: str
    challenge_method: str = "S256"


def generate_pkce_pair() -> PKCEPair:
    """Gerado pelo backend (nao pelo Launcher) — ver decisao de arquitetura
    em bot/docs/AUTH_API_CONTRACT.md. Verifier fica em memoria no backend,
    ligado ao device_code, ate a troca de codigo com o Discord."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PKCEPair(verifier=verifier, challenge=challenge)
