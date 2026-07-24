from __future__ import annotations

import json
import shutil
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import discord
from discord.ext import commands, tasks
from sqlalchemy import select

from core.bot import LimerenceBot
from core.logger import get_logger
from database.models.achievement import Achievement
from database.models.claim import Claim
from database.models.evaluation import Evaluation
from database.models.guild_settings import GuildSettings
from database.models.log import LogEntry
from database.models.staff import Staff
from database.models.staff_stats import StaffStats
from database.models.ticket import Ticket
from database.models.ticket_message import TicketMessage
from database.repositories.achievement_repository import AchievementRepository
from services.ranking_service import RankingPeriod
from utils.transcript import TRANSCRIPTS_DIR

logger = get_logger("backup")

_BACKUP_DIR = Path("data/backups")
_DUMPED_TABLES = [
    Achievement, Claim, Evaluation, GuildSettings, LogEntry, Staff, StaffStats, Ticket, TicketMessage,
]


def _json_default(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "value"):  # enums
        return value.value
    return str(value)


class BackupCog(commands.Cog):
    """Backup diario: dump de todas as tabelas + transcricoes salvas + snapshot
    de ranking/dashboard, tudo zipado. Salva sempre local; sobe no canal
    configurado se o zip couber no limite de upload do servidor."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.daily_backup.start()

    def cog_unload(self) -> None:
        self.daily_backup.cancel()

    @tasks.loop(hours=24)
    async def daily_backup(self) -> None:
        try:
            await self._run()
        except Exception:
            logger.exception("Falha ao rodar backup diario.")

    @daily_backup.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def _run(self) -> None:
        today = datetime.now(UTC)
        await self._check_monthly_top1(today)

        date_label = today.strftime("%Y-%m-%d")
        stage_dir = _BACKUP_DIR / date_label
        stage_dir.mkdir(parents=True, exist_ok=True)

        await self._dump_database(stage_dir / "database")
        await self._dump_ranking(stage_dir / "ranking")
        await self._dump_dashboard(stage_dir / "dashboard")
        await self._dump_config(stage_dir / "config")
        self._copy_transcripts(stage_dir / "transcricoes")

        zip_path = _BACKUP_DIR / f"backup-{date_label}.zip"
        self._zip_dir(stage_dir, zip_path)
        shutil.rmtree(stage_dir)

        for guild in self.bot.guilds:
            await self._maybe_upload(guild, zip_path, date_label)

    async def _dump_database(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        async with self.bot.database.session() as session:
            for model in _DUMPED_TABLES:
                result = await session.execute(select(model))
                rows = [
                    {column.name: getattr(row, column.name) for column in model.__table__.columns}
                    for row in result.scalars().all()
                ]
                (out_dir / f"{model.__tablename__}.json").write_text(
                    json.dumps(rows, default=_json_default, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    async def _dump_config(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for guild in self.bot.guilds:
            settings = await self.bot.config_service.get_settings(guild.id)
            data = {
                column.name: getattr(settings, column.name)
                for column in GuildSettings.__table__.columns
            }
            (out_dir / f"{guild.id}.json").write_text(
                json.dumps(data, default=_json_default, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    async def _dump_ranking(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for guild in self.bot.guilds:
            ranking = await self.bot.ranking_service.compute(guild.id, RankingPeriod.ALLTIME)
            data = [
                {
                    "staff": entry.staff.display_name,
                    "tickets": entry.tickets,
                    "avaliacao_media": entry.avaliacao_media,
                }
                for entry in ranking
            ]
            (out_dir / f"{guild.id}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    async def _dump_dashboard(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for guild in self.bot.guilds:
            open_tickets = await self.bot.ticket_service.list_open_by_guild(guild.id)
            data = {
                "open_tickets": len(open_tickets),
                "snapshot_at": datetime.now(UTC).isoformat(),
            }
            (out_dir / f"{guild.id}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _copy_transcripts(out_dir: Path) -> None:
        if not TRANSCRIPTS_DIR.exists():
            return
        shutil.copytree(TRANSCRIPTS_DIR, out_dir, dirs_exist_ok=True)

    @staticmethod
    def _zip_dir(stage_dir: Path, zip_path: Path) -> None:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in stage_dir.rglob("*"):
                if file_path.is_file():
                    zip_file.write(file_path, file_path.relative_to(stage_dir))

    async def _maybe_upload(self, guild: discord.Guild, zip_path: Path, date_label: str) -> None:
        settings = await self.bot.config_service.get_settings(guild.id)
        if settings.backup_channel_id is None:
            return
        channel = self.bot.get_channel(settings.backup_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        size = zip_path.stat().st_size
        if size > guild.filesize_limit:
            await channel.send(
                f"📦 Backup de {date_label} gerado ({size / 1_000_000:.1f}MB), mas passou do limite "
                f"de upload do servidor ({guild.filesize_limit / 1_000_000:.0f}MB). Salvo localmente "
                f"em `{zip_path}`."
            )
            return

        await channel.send(
            content=f"📦 Backup diário — {date_label}",
            file=discord.File(zip_path),
        )

    async def _check_monthly_top1(self, today: datetime) -> None:
        if today.day != 1:
            return
        previous_month = today.replace(day=1) - timedelta(days=1)
        key = f"monthly_top1_{previous_month.year}-{previous_month.month:02d}"

        for guild in self.bot.guilds:
            ranking = await self.bot.ranking_service.compute(guild.id, RankingPeriod.MONTHLY)
            if not ranking:
                continue
            top = ranking[0]

            async with self.bot.database.session() as session:
                awarded = await AchievementRepository(session).award(top.staff.id, key)

            if not awarded:
                continue

            settings = await self.bot.config_service.get_settings(guild.id)
            if settings.evaluations_channel_id is None:
                continue
            channel = self.bot.get_channel(settings.evaluations_channel_id)
            if isinstance(channel, discord.TextChannel):
                await channel.send(
                    embed=discord.Embed(
                        title="🏆 1º lugar do mês!",
                        description=f"{top.staff.display_name} fechou o mês passado em 1º no ranking!",
                    )
                )


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(BackupCog(bot))
