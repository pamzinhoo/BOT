from __future__ import annotations

import pytest

from services.social_notification_service import (
    SocialNotificationService,
    SocialNotificationValidationError,
    detect_platform,
    render_message,
)


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.youtube.com/watch?v=abc", "youtube"),
        ("https://youtu.be/abc", "youtube"),
        ("https://www.tiktok.com/@creator/video/123", "tiktok"),
        ("https://instagram.com/p/abc", "instagram"),
        ("https://www.twitch.tv/creator", "twitch"),
        ("https://kick.com/creator", "kick"),
        ("https://example.com/video/123", "other"),
    ],
)
def test_detect_platform(url: str, platform: str):
    assert detect_platform(url).value == platform


def test_render_message_replaces_url():
    result = render_message("Confira: {url}", "https://youtu.be/abc")
    assert result == "Confira: https://youtu.be/abc"


def test_render_message_is_case_insensitive():
    result = render_message("Link: {URL}", "https://youtu.be/abc")
    assert result == "Link: https://youtu.be/abc"


def test_render_message_falls_back_to_url_when_empty():
    assert render_message("", "https://youtu.be/abc") == "https://youtu.be/abc"


def test_validate_url_rejects_invalid():
    with pytest.raises(SocialNotificationValidationError):
        SocialNotificationService.validate_url("not-a-url")


def test_validate_url_accepts_http_https():
    assert SocialNotificationService.validate_url("https://example.com/video") == "https://example.com/video"
    assert SocialNotificationService.validate_url("http://example.com/video") == "http://example.com/video"


def test_render_message_rejects_discord_oversized_message():
    with pytest.raises(SocialNotificationValidationError, match="2000"):
        render_message("x" * 2001, "https://example.com/video")
