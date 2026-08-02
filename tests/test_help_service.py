from __future__ import annotations

import pytest

from services.help_service import HelpService


@pytest.mark.parametrize(
    "is_admin, is_staff, expected",
    [
        (True, False, 2),
        (True, True, 2),
        (False, True, 1),
        (False, False, 0),
    ],
)
def test_member_rank(is_admin: bool, is_staff: bool, expected: int) -> None:
    assert HelpService._member_rank(is_admin=is_admin, is_staff=is_staff) == expected
