from __future__ import annotations

import base64
import io
import re
import unicodedata

import qrcode

_GUI = "br.gov.bcb.pix"
_MCC = "0000"
_CURRENCY_BRL = "986"
_COUNTRY_BR = "BR"

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def _tlv(field_id: str, value: str) -> str:
    if len(value) > 99:
        # o campo de tamanho do TLV EMV tem sempre 2 digitos (00-99) — um
        # valor maior geraria um length de 3+ digitos e corromperia
        # silenciosamente a leitura do payload por qualquer app de banco.
        # Falha alto (ValueError) em vez de truncar/corromper em silencio.
        raise ValueError(
            f"Campo '{field_id}' do payload PIX excede 99 caracteres ({len(value)}) — "
            "nao pode ser representado no formato EMV."
        )
    return f"{field_id}{len(value):02d}{value}"


def _to_ascii(value: str) -> str:
    """Remove acentos/caracteres nao-ASCII (ex.: 'João' -> 'Joao').

    O padrao EMV/BR Code exige que o valor declare seu comprimento em BYTES
    no campo de tamanho do TLV, mas o codigo monta o payload contando
    caracteres (`len(value)` em `_tlv`). Para qualquer caractere acentuado
    (2 bytes em UTF-8), esses dois numeros divergem e o payload fica
    estruturalmente invalido — a maioria dos apps de banco recusa o QR/copia-
    e-cola ou trunca campos seguintes. Alem disso o BCB nao permite acentos
    nesses campos. Normalizar pra ASCII antes de qualquer TLV resolve os dois
    problemas de uma vez."""
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _crc16_ccitt(payload: str) -> str:
    """CRC16-CCITT (poly 0x1021, init 0xFFFF) — algoritmo exigido pelo Banco
    Central no campo 63 do payload EMV do PIX."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            # if/else (em vez do ternario sugerido pelo ruff/SIM108) de proposito
            # — mantem 0x1021/0xFFFF legiveis como as constantes do algoritmo
            if crc & 0x8000:  # noqa: SIM108
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def _sanitize(value: str, max_length: int, *, fallback: str = "") -> str:
    cleaned = _to_ascii(value).strip()
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length]


def build_pix_payload(
    *,
    pix_key: str,
    receiver_name: str,
    receiver_city: str | None,
    amount_cents: int | None,
    txid: str,
    description: str | None = None,
) -> str:
    """Monta o payload EMV/BR Code (\"PIX copia e cola\"). `txid` identifica o
    pedido no extrato do recebedor — sanitizado pro alfabeto exigido pelo
    Banco Central (alfanumerico, ate 25 chars; \"***\" se vazio)."""
    merchant_account = _tlv("00", _GUI) + _tlv("01", _sanitize(pix_key, 77))
    if description:
        merchant_account += _tlv("02", _sanitize(description, 72))

    clean_txid = _NON_ALNUM.sub("", txid).upper()
    clean_txid = _sanitize(clean_txid, 25, fallback="***")

    parts = [
        _tlv("00", "01"),
        _tlv("01", "12"),  # ponto de iniciacao dinamico: valor varia por pedido
        _tlv("26", merchant_account),
        _tlv("52", _MCC),
        _tlv("53", _CURRENCY_BRL),
    ]
    if amount_cents is not None:
        if amount_cents < 0:
            raise ValueError("amount_cents nao pode ser negativo.")
        # divisao inteira em vez de amount_cents / 100 — evita qualquer
        # dependencia de arredondamento de ponto flutuante no valor exibido
        # ao pagador (mesmo que .2f ja arredonde corretamente na pratica).
        reais, centavos = divmod(amount_cents, 100)
        parts.append(_tlv("54", f"{reais}.{centavos:02d}"))
    parts.extend([
        _tlv("58", _COUNTRY_BR),
        _tlv("59", _sanitize(receiver_name, 25, fallback="RECEBEDOR")),
        _tlv("60", _sanitize(receiver_city or "", 15, fallback="BRASIL")),
        _tlv("62", _tlv("05", clean_txid)),
    ])

    payload_without_crc = "".join(parts) + "6304"
    crc = _crc16_ccitt(payload_without_crc)
    return payload_without_crc + crc


def generate_qr_base64(payload: str) -> str:
    """Gera o QR Code (PNG) do payload PIX e devolve como base64 — nunca
    persistido em disco, so mantido em memoria pelo tempo de gerar a resposta."""
    img = qrcode.make(payload)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
