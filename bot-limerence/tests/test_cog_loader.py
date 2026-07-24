from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import Settings
from core.bot import LimerenceBot
from database.database import Database


@pytest.fixture
def settings() -> Settings:
    return Settings(
        discord_token="fake-token",
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        environment="development",
        log_level="DEBUG",
    )


@pytest.fixture
def database(settings: Settings) -> Database:
    return Database(settings.database_url)


@pytest.fixture
def bot(settings: Settings, database: Database) -> LimerenceBot:
    return LimerenceBot(settings=settings, database=database)


async def test_load_cogs_with_no_cogs_present(bot: LimerenceBot, tmp_path: Path, monkeypatch):
    import cogs

    monkeypatch.setattr(cogs, "__path__", [str(tmp_path)])

    await bot._load_cogs()
    assert bot.extensions == {}


async def test_load_cogs_loads_valid_extension(bot: LimerenceBot, tmp_path: Path, monkeypatch):
    fake_cog = tmp_path / "fake_feature.py"
    fake_cog.write_text(
        "from discord.ext import commands\n\n"
        "class FakeFeature(commands.Cog):\n"
        "    pass\n\n"
        "async def setup(bot):\n"
        "    await bot.add_cog(FakeFeature())\n",
        encoding="utf-8",
    )

    import sys

    import cogs

    monkeypatch.setattr(cogs, "__path__", [str(tmp_path)])
    sys.modules.pop("cogs.fake_feature", None)

    await bot._load_cogs()

    assert "cogs.fake_feature" in bot.extensions
    assert bot.get_cog("FakeFeature") is not None


async def test_load_cogs_ignores_modules_without_setup(
    bot: LimerenceBot, tmp_path: Path, monkeypatch
):
    (tmp_path / "not_a_cog.py").write_text("VALUE = 1\n", encoding="utf-8")

    import cogs

    monkeypatch.setattr(cogs, "__path__", [str(tmp_path)])

    await bot._load_cogs()

    assert bot.extensions == {}
