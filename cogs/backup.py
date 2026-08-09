from __future__ import annotations

import asyncio
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

# cada consulta ja vem filtrada por guild_id — direto pras tabelas que tem a
# coluna, e via JOIN pras que so guardam staff_id/ticket_id (auditoria:
# achados que NAO tem guild_id direto e dependem de join pra isolar por
# tenant corretamente).
def _guild_scoped_queries(guild_id: int) -> dict[type, object]:
    return {
        Achievement: select(Achievement).join(Staff, Staff.id == Achievement.staff_id).where(
            Staff.guild_id == guild_id
        ),
        Claim: select(Claim).join(Ticket, Ticket.id == Claim.ticket_id).where(Ticket.guild_id == guild_id),
        Evaluation: select(Evaluation).join(Ticket, Ticket.id == Evaluation.ticket_id).where(
            Ticket.guild_id == guild_id
        ),
        GuildSettings: select(GuildSettings).where(GuildSettings.guild_id == guild_id),
        LogEntry: select(LogEntry).where(LogEntry.guild_id == guild_id),
        Staff: select(Staff).where(Staff.guild_id == guild_id),
        StaffStats: select(StaffStats).join(Staff, Staff.id == StaffStats.staff_id).where(
            Staff.guild_id == guild_id
        ),
        Ticket: select(Ticket).where(Ticket.guild_id == guild_id),
        TicketMessage: select(TicketMessage).join(Ticket, Ticket.id == TicketMessage.ticket_id).where(
            Ticket.guild_id == guild_id
        ),
    }


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
    """Backup diario: 1 ZIP POR GUILD (nunca um zip compartilhado entre
    servidores — ver achado de auditoria abaixo), com dump de todas as
    tabelas relevantes JA FILTRADAS por guild_id, transcricoes dos tickets
    dessa guild e snapshot de ranking/dashboard/config. Sobe no canal
    configurado da PROPRIA guild se o zip couber no limite de upload."""

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
        for guild in self.bot.guilds:
            try:
                await self._backup_guild(guild, date_label)
            except Exception:
                logger.exception("Falha ao gerar backup da guild %s.", guild.id)

    async def _backup_guild(self, guild: discord.Guild, date_label: str) -> None:
        """ACHADO DE AUDITORIA (critico, corrigido): a versao anterior gerava
        UM UNICO zip com o dump de TODAS as guilds juntas e fazia upload
        desse MESMO zip pro canal de backup de CADA servidor — ou seja, todo
        cliente recebia no proprio canal os tickets/staff/avaliacoes/logs de
        TODOS os outros clientes do bot. Agora cada guild tem seu proprio
        stage dir, seu proprio zip (so com os dados filtrados por guild_id
        via `_guild_scoped_queries`), e so o canal DAQUELA guild recebe esse
        zip especifico."""
        stage_dir = _BACKUP_DIR / f"{guild.id}-{date_label}"
        zip_path = _BACKUP_DIR / f"backup-{guild.id}-{date_label}.zip"
        try:
            ticket_ids = await self._dump_database(stage_dir / "database", guild.id)
            await self._dump_ranking(stage_dir / "ranking", guild.id)
            await self._dump_dashboard(stage_dir / "dashboard", guild.id)
            await self._dump_config(stage_dir / "config", guild.id)
            # copia de arquivo e compactacao sao sincronas/IO-bound — com
            # centenas de guilds, rodar isso direto no loop travaria o bot
            # inteiro pela duracao do backup diario inteiro, nao so dessa guild.
            await asyncio.to_thread(self._copy_transcripts, stage_dir / "transcricoes", ticket_ids)
            await asyncio.to_thread(self._zip_dir, stage_dir, zip_path)
            await self._maybe_upload(guild, zip_path, date_label)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)

    async def _dump_database(self, out_dir: Path, guild_id: int) -> set[str]:
        """Devolve os UUIDs completos dos tickets dessa guild — usado pra
        filtrar quais transcricoes locais pertencem a ela."""
        out_dir.mkdir(parents=True, exist_ok=True)
        ticket_ids: set[str] = set()
        async with self.bot.database.session() as session:
            for model, query in _guild_scoped_queries(guild_id).items():
                result = await session.execute(query)
                entities = result.scalars().all()
                rows = [
                    {column.name: getattr(row, column.name) for column in model.__table__.columns}
                    for row in entities
                ]
                if model is Ticket:
                    ticket_ids = {str(row.id) for row in entities}
                (out_dir / f"{model.__tablename__}.json").write_text(
                    json.dumps(rows, default=_json_default, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        return ticket_ids

    async def _dump_config(self, out_dir: Path, guild_id: int) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        settings = await self.bot.config_service.get_settings(guild_id)
        data = {
            column.name: getattr(settings, column.name) for column in GuildSettings.__table__.columns
        }
        (out_dir / "config.json").write_text(
            json.dumps(data, default=_json_default, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def _dump_ranking(self, out_dir: Path, guild_id: int) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        ranking = await self.bot.ranking_service.compute(guild_id, RankingPeriod.ALLTIME)
        data = [
            {
                "staff": entry.staff.display_name,
                "tickets": entry.tickets,
                "avaliacao_media": entry.avaliacao_media,
            }
            for entry in ranking
        ]
        (out_dir / "ranking.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _dump_dashboard(self, out_dir: Path, guild_id: int) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        open_tickets = await self.bot.ticket_service.list_open_by_guild(guild_id)
        data = {
            "open_tickets": len(open_tickets),
            "snapshot_at": datetime.now(UTC).isoformat(),
        }
        (out_dir / "dashboard.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    @staticmethod
    def _copy_transcripts(out_dir: Path, ticket_ids: set[str]) -> None:
        """So copia as transcricoes (.html/.pdf) dos tickets QUE PERTENCEM a
        esta guild — a pasta local `data/transcripts` e compartilhada entre
        todas as guilds do bot (nomeada pelo UUID completo do ticket), entao
        copiar a pasta inteira vazaria transcricoes de outros servidores."""
        if not TRANSCRIPTS_DIR.exists() or not ticket_ids:
            return
        out_dir.mkdir(parents=True, exist_ok=True)
        for file_path in TRANSCRIPTS_DIR.iterdir():
            if file_path.is_file() and file_path.stem in ticket_ids:
                shutil.copy2(file_path, out_dir / file_path.name)

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
