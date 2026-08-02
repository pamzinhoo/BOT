from __future__ import annotations

import re
import uuid

_DIGITS_RE = re.compile(r"\D")
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,63}(\.[^@\s]{2,63})+$")


class PixKeyValidationError(ValueError):
    """Erro de validação de chave PIX — a mensagem já é adequada pra exibir
    direto ao usuário no Discord (sem stacktrace/detalhe interno)."""


def _only_digits(value: str) -> str:
    return _DIGITS_RE.sub("", value)


def _validate_cpf(raw: str) -> str:
    digits = _only_digits(raw)
    if len(digits) != 11:
        raise PixKeyValidationError(
            "CPF inválido — precisa ter 11 dígitos (ex.: 123.456.789-00)."
        )
    if digits == digits[0] * 11:
        raise PixKeyValidationError("CPF inválido — todos os dígitos são iguais.")

    def _check_digit(base: str, start_weight: int) -> str:
        total = sum(int(n) * w for n, w in zip(base, range(start_weight, 1, -1), strict=True))
        remainder = (total * 10) % 11
        return "0" if remainder == 10 else str(remainder)

    d1 = _check_digit(digits[:9], 10)
    d2 = _check_digit(digits[:9] + d1, 11)
    if digits[-2:] != d1 + d2:
        raise PixKeyValidationError("CPF inválido — dígitos verificadores não conferem.")
    return digits


def _validate_cnpj(raw: str) -> str:
    digits = _only_digits(raw)
    if len(digits) != 14:
        raise PixKeyValidationError(
            "CNPJ inválido — precisa ter 14 dígitos (ex.: 12.345.678/0001-95)."
        )
    if digits == digits[0] * 14:
        raise PixKeyValidationError("CNPJ inválido — todos os dígitos são iguais.")

    weights_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]

    def _check_digit(base: str, weights: list[int]) -> str:
        total = sum(int(n) * w for n, w in zip(base, weights, strict=True))
        remainder = total % 11
        return "0" if remainder < 2 else str(11 - remainder)

    d1 = _check_digit(digits[:12], weights_1)
    d2 = _check_digit(digits[:12] + d1, weights_2)
    if digits[-2:] != d1 + d2:
        raise PixKeyValidationError("CNPJ inválido — dígitos verificadores não conferem.")
    return digits


def _validate_email(raw: str) -> str:
    cleaned = raw.strip().lower()
    if len(cleaned) > 77 or not _EMAIL_RE.match(cleaned):
        raise PixKeyValidationError("E-mail inválido — use o formato nome@dominio.com.")
    return cleaned


def _validate_phone(raw: str) -> str:
    """Aceita +5544999999999, 5544999999999, (44) 99999-9999, 44 99999-9999
    — normaliza pro formato E.164 (+55DDDNUMERO) exigido pelo Banco Central
    pra chave PIX do tipo telefone."""
    digits = _only_digits(raw)
    if not digits:
        raise PixKeyValidationError(
            "Telefone inválido — use um número BR com DDD, ex.: (44) 99999-9999."
        )

    if digits.startswith("55") and len(digits) in (12, 13):
        # ja veio com código do país (+55) e um DDD+número plausível
        normalized = digits
    elif len(digits) in (10, 11):
        # numero local (DDD + fixo de 8 digitos, ou DDD + celular de 9 digitos)
        normalized = "55" + digits
    else:
        raise PixKeyValidationError(
            "Telefone inválido — use um número BR com DDD, ex.: (44) 99999-9999 ou "
            "+5544999999999."
        )

    ddd = int(normalized[2:4])
    if not (11 <= ddd <= 99):
        raise PixKeyValidationError("Telefone inválido — DDD fora do intervalo válido (11 a 99).")
    return f"+{normalized}"


def _validate_random(raw: str) -> str:
    cleaned = raw.strip()
    try:
        parsed = uuid.UUID(cleaned)
    except ValueError as exc:
        raise PixKeyValidationError(
            "Chave aleatória inválida — precisa ser um UUID, ex.: "
            "123e4567-e12b-12d1-a456-426655440000."
        ) from exc
    return str(parsed)


_VALIDATORS = {
    "cpf": _validate_cpf,
    "cnpj": _validate_cnpj,
    "email": _validate_email,
    "telefone": _validate_phone,
    "aleatoria": _validate_random,
}


def validate_pix_key(key_type: str | None, raw_value: str) -> str:
    """Valida e NORMALIZA `raw_value` de acordo com `key_type` (um dos
    valores de PIX_KEY_TYPES: cpf/cnpj/email/telefone/aleatoria). Levanta
    PixKeyValidationError com mensagem pronta pra exibir ao usuário. O valor
    de retorno é sempre o normalizado — é ele que deve ser persistido em
    PixManualSettings.pix_key, nunca o texto bruto digitado."""
    if not key_type:
        raise PixKeyValidationError(
            "Selecione o **Tipo da chave PIX** antes de informar/alterar a chave."
        )
    validator = _VALIDATORS.get(key_type)
    if validator is None:
        raise PixKeyValidationError(f"Tipo de chave PIX desconhecido: {key_type!r}.")
    if not raw_value or not raw_value.strip():
        raise PixKeyValidationError("A chave PIX não pode ficar vazia.")
    return validator(raw_value)
