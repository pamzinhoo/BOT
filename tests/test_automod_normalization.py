from __future__ import annotations

from utils.automod_wordlist import compact_form, normalize_text


def test_lowercase_and_strip_accents() -> None:
    assert normalize_text("PRÉ-SENÇA Áéíóú") == "presenca aeiou"


def test_removes_separators_between_letters() -> None:
    assert normalize_text("i.d.i.o.t.a") == "idiota"
    assert normalize_text("f.d.p") == "fdp"


def test_resolves_leetspeak_substitution() -> None:
    assert normalize_text("1d10t4") == "idiota"


def test_preserves_spaces_for_phrases() -> None:
    assert normalize_text("Vai se FODER!!") == "vai se foder"
    assert normalize_text("cala   a    boca") == "cala a boca"


def test_compact_form_removes_all_spaces() -> None:
    assert compact_form(normalize_text("f d p")) == "fdp"
