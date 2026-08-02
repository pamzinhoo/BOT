from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from database.models.verification_session import VerificationSessionStatus
from database.models.verification_settings import (
    CodeCharset,
    VerificationExceededAction,
    VerificationMethod,
)
from services.verification_service import (
    MIN_ATTEMPT_INTERVAL_SECONDS,
    VerificationService,
    codes_match,
    evaluate_attempt,
    generate_code,
    generate_decoys,
    render_placeholders,
)

_GUILD_ID = 111
_USER_ID = 222
_NOW = datetime.now(UTC)


def _evaluate(
    *,
    status: VerificationSessionStatus = VerificationSessionStatus.PENDING,
    generation: int = 1,
    code: str = "ABC123",
    case_sensitive: bool = False,
    expires_at: datetime | None = None,
    last_attempt_at: datetime | None = None,
    attempts_used: int = 0,
    max_attempts: int = 3,
    guild_id: int | None = _GUILD_ID,
    user_id: int = _USER_ID,
    expected_generation: int | None = None,
    submitted: str = "ABC123",
    now: datetime | None = None,
):
    return evaluate_attempt(
        record_user_id=_USER_ID,
        record_guild_id=_GUILD_ID,
        record_status=status,
        record_generation=generation,
        record_code=code,
        record_case_sensitive=case_sensitive,
        record_expires_at=expires_at or (_NOW + timedelta(minutes=10)),
        record_last_attempt_at=last_attempt_at,
        record_attempts_used=attempts_used,
        record_max_attempts=max_attempts,
        guild_id=guild_id,
        user_id=user_id,
        expected_generation=expected_generation,
        submitted=submitted,
        now=now or _NOW,
    )


# --- geracao de codigo / decoys -------------------------------------------------


def test_generate_code_respects_length_and_charset() -> None:
    for length in range(4, 9):
        code = generate_code(length, CodeCharset.ALPHANUMERIC)
        assert len(code) == length
        assert code.isalnum()

    letters_code = generate_code(6, CodeCharset.LETTERS)
    assert letters_code.isalpha()

    numbers_code = generate_code(6, CodeCharset.NUMBERS)
    assert numbers_code.isdigit()


def test_generate_decoys_never_include_the_correct_code() -> None:
    correct = generate_code(6, CodeCharset.ALPHANUMERIC)
    decoys = generate_decoys(correct, CodeCharset.ALPHANUMERIC, count=3)
    assert len(decoys) == 3
    assert correct not in decoys
    assert len(set(decoys)) == 3  # todos distintos entre si


def test_generate_decoys_handles_tiny_charset_without_infinite_loop() -> None:
    # charset de numeros com codigo curto — poucas combinacoes possiveis,
    # ainda assim tem que devolver `count` decoys distintos do correto.
    correct = "12"
    decoys = generate_decoys(correct, CodeCharset.NUMBERS, count=3)
    assert len(decoys) == 3
    assert correct not in decoys


def test_codes_match_case_insensitive_by_default() -> None:
    assert codes_match("abc123", "ABC123", case_sensitive=False) is True
    assert codes_match(" abc123 ", "ABC123", case_sensitive=False) is True


def test_codes_match_case_sensitive() -> None:
    assert codes_match("abc123", "ABC123", case_sensitive=True) is False
    assert codes_match("ABC123", "ABC123", case_sensitive=True) is True


def test_render_placeholders_substitutes_all_keys() -> None:
    result = render_placeholders(
        "Olá {user}, restam {tentativas_restantes} tentativas em {server_name}.",
        user="<@1>", tentativas_restantes=2, server_name="Meu Servidor",
    )
    assert result == "Olá <@1>, restam 2 tentativas em Meu Servidor."


# --- evaluate_attempt: acerto/erro -----------------------------------------------


def test_evaluate_attempt_correct_code_succeeds() -> None:
    decision = _evaluate(submitted="abc123")
    assert decision.kind == "success"


def test_evaluate_attempt_wrong_code_with_attempts_left() -> None:
    decision = _evaluate(submitted="ZZZZZZ", attempts_used=0, max_attempts=3)
    assert decision.kind == "wrong"
    assert decision.remaining == 2  # 3 - (0 + 1)


def test_evaluate_attempt_wrong_code_exhausts_attempts() -> None:
    decision = _evaluate(submitted="ZZZZZZ", attempts_used=2, max_attempts=3)
    assert decision.kind == "max_attempts"


# --- evaluate_attempt: expiracao -------------------------------------------------


def test_evaluate_attempt_expired_even_with_correct_code() -> None:
    decision = _evaluate(
        submitted="abc123",  # codigo certo, mas ja expirou
        expires_at=_NOW - timedelta(seconds=1),
    )
    assert decision.kind == "expired"


# --- evaluate_attempt: anti-reutilizacao / anti-abuso ----------------------------


def test_evaluate_attempt_rejects_already_resolved_session() -> None:
    decision = _evaluate(status=VerificationSessionStatus.SUCCEEDED, submitted="abc123")
    assert decision.kind == "invalid_status"


def test_evaluate_attempt_rejects_different_user() -> None:
    decision = _evaluate(user_id=_USER_ID + 1, submitted="abc123")
    assert decision.kind == "invalid_owner"


def test_evaluate_attempt_rejects_different_guild() -> None:
    decision = _evaluate(guild_id=_GUILD_ID + 1, submitted="abc123")
    assert decision.kind == "invalid_guild"


def test_evaluate_attempt_allows_dm_context_without_guild_id() -> None:
    # em DM a interacao nao tem guild_id — nao deve ser tratado como cross-guild.
    decision = _evaluate(guild_id=None, submitted="abc123")
    assert decision.kind == "success"


def test_evaluate_attempt_rejects_stale_button_generation() -> None:
    decision = _evaluate(generation=2, expected_generation=1, submitted="abc123")
    assert decision.kind == "stale"


def test_evaluate_attempt_accepts_matching_generation() -> None:
    decision = _evaluate(generation=2, expected_generation=2, submitted="abc123")
    assert decision.kind == "success"


def test_evaluate_attempt_enforces_cooldown_between_attempts() -> None:
    decision = _evaluate(
        submitted="ZZZZZZ", last_attempt_at=_NOW - timedelta(seconds=1)
    )
    assert decision.kind == "cooldown"
    assert decision.wait_seconds is not None and decision.wait_seconds > 0


def test_evaluate_attempt_allows_after_cooldown_elapses() -> None:
    decision = _evaluate(
        submitted="abc123",
        last_attempt_at=_NOW - timedelta(seconds=MIN_ATTEMPT_INTERVAL_SECONDS + 1),
    )
    assert decision.kind == "success"


def test_evaluate_attempt_tampered_candidate_is_just_a_wrong_guess() -> None:
    # um custom_id com candidate alterado pra um valor arbitrario (nao gerado
    # pelo servidor) nao quebra nada — vira so mais uma tentativa errada.
    decision = _evaluate(submitted="ZZZZ99", attempts_used=0, max_attempts=3)
    assert decision.kind == "wrong"


# --- DynamicItem custom_id (metodo Selecionar CAPTCHA / Digitar CAPTCHA) --------


def test_pick_captcha_button_template_parses_valid_custom_id() -> None:
    from views.verification_view import PickCaptchaButton

    session_id = uuid.uuid4()
    button = PickCaptchaButton(session_id, 3, "ABC123")
    match = button.template.fullmatch(f"limerence:verify:pick:{session_id}:3:ABC123")
    assert match is not None
    assert match["session_id"] == str(session_id)
    assert match["generation"] == "3"
    assert match["candidate"] == "ABC123"


def test_pick_captcha_button_template_rejects_tampered_session_id() -> None:
    from views.verification_view import PickCaptchaButton

    session_id = uuid.uuid4()
    button = PickCaptchaButton(session_id, 3, "ABC123")
    assert button.template.fullmatch("limerence:verify:pick:not-a-uuid:3:ABC123") is None


def test_type_captcha_button_template_rejects_extra_suffix() -> None:
    from views.verification_view import TypeCaptchaButton

    session_id = uuid.uuid4()
    button = TypeCaptchaButton(session_id)
    assert button.template.fullmatch(f"limerence:verify:type:{session_id}") is not None
    assert button.template.fullmatch(f"limerence:verify:type:{session_id}:extra") is None


def test_build_button_view_shuffles_and_includes_all_candidates() -> None:
    from views.verification_view import _build_button_view

    session_id = uuid.uuid4()
    code = "Q8L2PX"
    decoys = ["Q8P2LX", "QBL2PX", "Q8L3PX"]
    view = _build_button_view(session_id, 1, code, decoys)
    labels = {child.item.label for child in view.children}
    assert labels == {code, *decoys}
    assert len(view.children) == 4


# --- _finalize: acao ao exceder tentativas / expirar (kick/ban/restart/none) ----


class _FakeRecord:
    def __init__(self, *, attempts_used: int = 3) -> None:
        self.guild_id = _GUILD_ID
        self.user_id = _USER_ID
        self.method = VerificationMethod.TYPE
        self.attempts_used = attempts_used
        self.created_at = _NOW
        self.completed_at = _NOW
        self.status = VerificationSessionStatus.MAX_ATTEMPTS_EXCEEDED


def _make_service() -> VerificationService:
    service = VerificationService.__new__(VerificationService)
    service._bot = MagicMock()
    service._bot.audit_log_service.record = AsyncMock()
    return service


async def test_finalize_kicks_member_on_kick_action(monkeypatch) -> None:
    service = _make_service()
    member = MagicMock()
    member.kick = AsyncMock()
    member.ban = AsyncMock()
    monkeypatch.setattr(service, "_get_member", AsyncMock(return_value=member))
    monkeypatch.setattr(service, "_send_log", AsyncMock())

    await service._finalize(
        _FakeRecord(), MagicMock(), VerificationExceededAction.KICK, result_label="Excedeu tentativas"
    )

    member.kick.assert_awaited_once()
    member.ban.assert_not_awaited()


async def test_finalize_bans_member_on_ban_action(monkeypatch) -> None:
    service = _make_service()
    member = MagicMock()
    member.kick = AsyncMock()
    member.ban = AsyncMock()
    monkeypatch.setattr(service, "_get_member", AsyncMock(return_value=member))
    monkeypatch.setattr(service, "_send_log", AsyncMock())

    await service._finalize(
        _FakeRecord(), MagicMock(), VerificationExceededAction.BAN, result_label="Excedeu tentativas"
    )

    member.ban.assert_awaited_once()
    member.kick.assert_not_awaited()


async def test_finalize_does_nothing_destructive_on_none_action(monkeypatch) -> None:
    service = _make_service()
    member = MagicMock()
    member.kick = AsyncMock()
    member.ban = AsyncMock()
    monkeypatch.setattr(service, "_get_member", AsyncMock(return_value=member))
    monkeypatch.setattr(service, "_send_log", AsyncMock())

    await service._finalize(
        _FakeRecord(), MagicMock(), VerificationExceededAction.NONE, result_label="Excedeu tentativas"
    )

    member.kick.assert_not_awaited()
    member.ban.assert_not_awaited()


async def test_finalize_restarts_verification_on_restart_action(monkeypatch) -> None:
    service = _make_service()
    member = MagicMock()
    member.kick = AsyncMock()
    member.ban = AsyncMock()
    monkeypatch.setattr(service, "_get_member", AsyncMock(return_value=member))
    monkeypatch.setattr(service, "_send_log", AsyncMock())
    start_verification = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "start_verification", start_verification)

    await service._finalize(
        _FakeRecord(), MagicMock(), VerificationExceededAction.RESTART, result_label="Excedeu tentativas"
    )

    start_verification.assert_awaited_once_with(member)
    member.kick.assert_not_awaited()
    member.ban.assert_not_awaited()
