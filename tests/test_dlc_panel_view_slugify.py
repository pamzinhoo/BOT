from __future__ import annotations

from views.dlc_panel_view import _slugify


def test_slugify_plain_ascii() -> None:
    assert _slugify("The Devil") == "the-devil"


def test_slugify_transliterates_accents_instead_of_stray_hyphens() -> None:
    """Regressao: 'Ⅰ GÉNESIS' virava slug 'g-nesis' (acento/numeral romano
    colapsavam em traco solto ao inves de virar a letra base), colidindo
    com nomes sem nenhuma relacao entre si. Ver incidente 2026-08-21."""
    assert _slugify("Ⅰ GÉNESIS") == "i-genesis"
    assert _slugify("Gênesis") == "genesis"
    assert _slugify("Edição Especial") == "edicao-especial"


def test_slugify_falls_back_to_dlc_when_nothing_survives() -> None:
    assert _slugify("!!!???") == "dlc"
