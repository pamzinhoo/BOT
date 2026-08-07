from __future__ import annotations

from core.security.tokens import (
    generate_device_code,
    generate_pkce_pair,
    generate_refresh_token,
    generate_state,
    generate_user_code,
    hash_token,
)


def test_refresh_token_hash_is_deterministic_and_one_way() -> None:
    token = generate_refresh_token()
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token


def test_refresh_tokens_are_unique() -> None:
    tokens = {generate_refresh_token() for _ in range(50)}
    assert len(tokens) == 50


def test_user_code_format() -> None:
    code = generate_user_code()
    assert len(code) == 9
    assert code[4] == "-"
    for char in code.replace("-", ""):
        assert char not in "0O1I"


def test_device_code_and_state_are_unique_and_url_safe() -> None:
    codes = {generate_device_code() for _ in range(20)}
    states = {generate_state() for _ in range(20)}
    assert len(codes) == 20
    assert len(states) == 20


def test_pkce_challenge_matches_verifier_sha256() -> None:
    import base64
    import hashlib

    pair = generate_pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(pair.verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    assert pair.challenge == expected
    assert pair.challenge_method == "S256"
