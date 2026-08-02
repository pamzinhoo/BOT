from __future__ import annotations

from database.models.automod import AutoModCategory, AutoModRiskLevel
from services.automod_service import AutoModService, EffectiveWord

_WORDS = [
    EffectiveWord("idiota", AutoModCategory.OFENSA, AutoModRiskLevel.BAIXO, is_builtin=True),
    EffectiveWord("free nitro", AutoModCategory.GOLPE_SPAM, AutoModRiskLevel.MEDIO, is_builtin=True),
    EffectiveWord("macaco", AutoModCategory.DISCRIMINACAO, AutoModRiskLevel.ALTO, is_builtin=True),
    EffectiveWord("preto", AutoModCategory.SUSPEITA, AutoModRiskLevel.BAIXO, is_builtin=True),
    EffectiveWord("cpf", AutoModCategory.PRIVACIDADE, AutoModRiskLevel.ALTO, is_builtin=True),
]

_service = AutoModService.__new__(AutoModService)  # analyze() nao usa self._database


def test_detects_low_risk_word_with_bypass_attempt() -> None:
    match = _service.analyze("voce e um 1d10t4", _WORDS, [])
    assert match is not None
    assert match.palavra == "idiota"
    assert match.nivel == AutoModRiskLevel.BAIXO


def test_detects_medium_risk_phrase() -> None:
    match = _service.analyze("ganhei free nitro, clica no link", _WORDS, [])
    assert match is not None
    assert match.palavra == "free nitro"
    assert match.nivel == AutoModRiskLevel.MEDIO


def test_context_sensitive_word_alone_does_not_punish() -> None:
    match = _service.analyze("meu carro e preto", _WORDS, [])
    assert match is not None
    assert match.context_only is True


def test_context_sensitive_word_escalates_when_combined_with_slur() -> None:
    match = _service.analyze("seu preto macaco", _WORDS, [])
    assert match is not None
    assert match.context_only is False
    assert match.palavra == "macaco"
    assert match.nivel == AutoModRiskLevel.ALTO


def test_allowed_words_exception_suppresses_match() -> None:
    match = _service.analyze("voce e um idiota", _WORDS, ["idiota"])
    assert match is None


def test_no_match_returns_none() -> None:
    match = _service.analyze("mensagem completamente normal", _WORDS, [])
    assert match is None


def test_short_word_requires_word_boundary_or_min_length() -> None:
    # "cpf" tem 3 letras — so bate por substring compacta se >=4, entao so
    # deteta quando aparece como palavra isolada (com espacos/limites).
    match = _service.analyze("meu cpf e 12345", _WORDS, [])
    assert match is not None
    assert match.palavra == "cpf"

    no_match = _service.analyze("escapei por pouco", _WORDS, [])
    assert no_match is None
