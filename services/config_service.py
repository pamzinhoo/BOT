from __future__ import annotations

from database.database import Database
from database.models.anti_spam_settings import AntiSpamSettings
from database.models.bot_status_settings import BotStatusSettings
from database.models.dashboard_settings import DashboardSettings
from database.models.evaluation_settings import EvaluationSettings
from database.models.guild_settings import GuildSettings
from database.models.permission_settings import PermissionSettings
from database.models.ranking_settings import RankingSettings
from database.models.ticket_settings import TicketSettings
from database.repositories.anti_spam_settings_repository import AntiSpamSettingsRepository
from database.repositories.bot_status_settings_repository import BotStatusSettingsRepository
from database.repositories.dashboard_settings_repository import DashboardSettingsRepository
from database.repositories.evaluation_settings_repository import EvaluationSettingsRepository
from database.repositories.guild_settings_repository import GuildSettingsRepository
from database.repositories.permission_settings_repository import PermissionSettingsRepository
from database.repositories.ranking_settings_repository import RankingSettingsRepository
from database.repositories.ticket_settings_repository import TicketSettingsRepository
from utils.model_defaults import column_default, reset_row
from utils.ttl_cache import TTLCache

# guild_settings e permission_settings sao lidos em quase toda interacao e
# mensagem (checks de staff/admin, anti-spam) mas mudam raramente — cache
# curto com invalidacao manual em toda escrita evita bater no Postgres a
# cada mensagem/comando sem arriscar dado desatualizado por muito tempo.
_SETTINGS_TTL_SECONDS = 300.0


class ConfigService:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._settings_cache: TTLCache[int, GuildSettings] = TTLCache(_SETTINGS_TTL_SECONDS)
        self._ticket_settings_cache: TTLCache[int, TicketSettings] = TTLCache(_SETTINGS_TTL_SECONDS)
        self._permission_settings_cache: TTLCache[int, PermissionSettings] = TTLCache(
            _SETTINGS_TTL_SECONDS
        )
        self._anti_spam_settings_cache: TTLCache[int, AntiSpamSettings] = TTLCache(
            _SETTINGS_TTL_SECONDS
        )
        # mesmo padrao das 4 caches acima — estas 4 nao tinham cache ainda
        # (achado M da auditoria anterior). get_evaluation_settings em
        # particular e lido no caminho de fechamento de ticket
        # (views/ticket_actions_view.py), as outras 3 no refresh de dashboard
        # (chamado em ~15 pontos, hoje ja em background, mas ainda bate no
        # banco toda vez sem necessidade).
        self._evaluation_settings_cache: TTLCache[int, EvaluationSettings] = TTLCache(
            _SETTINGS_TTL_SECONDS
        )
        self._dashboard_settings_cache: TTLCache[int, DashboardSettings] = TTLCache(
            _SETTINGS_TTL_SECONDS
        )
        self._bot_status_settings_cache: TTLCache[int, BotStatusSettings] = TTLCache(
            _SETTINGS_TTL_SECONDS
        )
        self._ranking_settings_cache: TTLCache[int, RankingSettings] = TTLCache(_SETTINGS_TTL_SECONDS)

    async def get_settings(self, guild_id: int) -> GuildSettings:
        cached = self._settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await GuildSettingsRepository(session).get_or_create(guild_id)
        self._settings_cache.set(guild_id, settings)
        return settings

    async def update(self, guild_id: int, **fields: object) -> GuildSettings:
        async with self._database.session() as session:
            repo = GuildSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
        self._settings_cache.invalidate(guild_id)
        return settings

    # --- Tickets -----------------------------------------------------------

    async def get_ticket_settings(self, guild_id: int) -> TicketSettings:
        cached = self._ticket_settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await TicketSettingsRepository(session).get_or_create(guild_id)
        self._ticket_settings_cache.set(guild_id, settings)
        return settings

    async def update_ticket_settings(self, guild_id: int, **fields: object) -> TicketSettings:
        async with self._database.session() as session:
            repo = TicketSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
        self._ticket_settings_cache.invalidate(guild_id)
        return settings

    # --- Avaliações ----------------------------------------------------------

    async def get_evaluation_settings(self, guild_id: int) -> EvaluationSettings:
        cached = self._evaluation_settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await EvaluationSettingsRepository(session).get_or_create(guild_id)
        self._evaluation_settings_cache.set(guild_id, settings)
        return settings

    async def update_evaluation_settings(self, guild_id: int, **fields: object) -> EvaluationSettings:
        async with self._database.session() as session:
            repo = EvaluationSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
        self._evaluation_settings_cache.invalidate(guild_id)
        return settings

    # --- Dashboard ----------------------------------------------------------

    async def get_dashboard_settings(self, guild_id: int) -> DashboardSettings:
        cached = self._dashboard_settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await DashboardSettingsRepository(session).get_or_create(guild_id)
        self._dashboard_settings_cache.set(guild_id, settings)
        return settings

    async def update_dashboard_settings(self, guild_id: int, **fields: object) -> DashboardSettings:
        async with self._database.session() as session:
            repo = DashboardSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
        self._dashboard_settings_cache.invalidate(guild_id)
        return settings

    async def list_dashboards_with_auto_update(self) -> list[DashboardSettings]:
        async with self._database.session() as session:
            return await DashboardSettingsRepository(session).list_auto_update_enabled()

    # --- Status do Bot -------------------------------------------------------

    async def get_bot_status_settings(self, guild_id: int) -> BotStatusSettings:
        cached = self._bot_status_settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await BotStatusSettingsRepository(session).get_or_create(guild_id)
        self._bot_status_settings_cache.set(guild_id, settings)
        return settings

    async def update_bot_status_settings(self, guild_id: int, **fields: object) -> BotStatusSettings:
        async with self._database.session() as session:
            repo = BotStatusSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
        self._bot_status_settings_cache.invalidate(guild_id)
        return settings

    async def list_bot_status_with_channel(self) -> list[BotStatusSettings]:
        async with self._database.session() as session:
            return await BotStatusSettingsRepository(session).list_with_channel()

    # --- Ranking ------------------------------------------------------------

    async def get_ranking_settings(self, guild_id: int) -> RankingSettings:
        cached = self._ranking_settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await RankingSettingsRepository(session).get_or_create(guild_id)
        self._ranking_settings_cache.set(guild_id, settings)
        return settings

    async def update_ranking_settings(self, guild_id: int, **fields: object) -> RankingSettings:
        async with self._database.session() as session:
            repo = RankingSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
        self._ranking_settings_cache.invalidate(guild_id)
        return settings

    # --- Anti-Spam ----------------------------------------------------------

    async def get_anti_spam_settings(self, guild_id: int) -> AntiSpamSettings:
        cached = self._anti_spam_settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await AntiSpamSettingsRepository(session).get_or_create(guild_id)
        self._anti_spam_settings_cache.set(guild_id, settings)
        return settings

    async def update_anti_spam_settings(self, guild_id: int, **fields: object) -> AntiSpamSettings:
        async with self._database.session() as session:
            repo = AntiSpamSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
        self._anti_spam_settings_cache.invalidate(guild_id)
        return settings

    # --- Permissões ---------------------------------------------------------

    async def get_permission_settings(self, guild_id: int) -> PermissionSettings:
        cached = self._permission_settings_cache.get(guild_id)
        if cached is not None:
            return cached
        async with self._database.session() as session:
            settings = await PermissionSettingsRepository(session).get_or_create(guild_id)
        self._permission_settings_cache.set(guild_id, settings)
        return settings

    async def update_permission_settings(self, guild_id: int, **fields: object) -> PermissionSettings:
        async with self._database.session() as session:
            repo = PermissionSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
        self._permission_settings_cache.invalidate(guild_id)
        return settings

    # --- Reset (Etapa 3) -----------------------------------------------------

    async def reset_guild_settings_fields(
        self, guild_id: int, attrs: set[str]
    ) -> dict[str, tuple[object, object]]:
        """Restaura só os campos de `attrs` (nunca a linha inteira — guild_settings
        também guarda ids operacionais como ranking_message_id que não são config)."""
        async with self._database.session() as session:
            settings = await GuildSettingsRepository(session).get_or_create(guild_id)
            diffs: dict[str, tuple[object, object]] = {}
            for attr in attrs:
                default = column_default(GuildSettings, attr)
                before = getattr(settings, attr)
                if before != default:
                    diffs[attr] = (before, default)
                setattr(settings, attr, default)
        self._settings_cache.invalidate(guild_id)
        return diffs

    async def reset_ticket_settings(self, guild_id: int) -> dict[str, tuple[object, object]]:
        async with self._database.session() as session:
            settings = await TicketSettingsRepository(session).get_or_create(guild_id)
            diffs = reset_row(settings)
        self._ticket_settings_cache.invalidate(guild_id)
        return diffs

    async def reset_dashboard_settings(self, guild_id: int) -> dict[str, tuple[object, object]]:
        async with self._database.session() as session:
            settings = await DashboardSettingsRepository(session).get_or_create(guild_id)
            diffs = reset_row(settings)
        self._dashboard_settings_cache.invalidate(guild_id)
        return diffs

    async def reset_bot_status_settings(self, guild_id: int) -> dict[str, tuple[object, object]]:
        async with self._database.session() as session:
            settings = await BotStatusSettingsRepository(session).get_or_create(guild_id)
            diffs = reset_row(settings)
        self._bot_status_settings_cache.invalidate(guild_id)
        return diffs

    async def reset_ranking_settings(self, guild_id: int) -> dict[str, tuple[object, object]]:
        async with self._database.session() as session:
            settings = await RankingSettingsRepository(session).get_or_create(guild_id)
            diffs = reset_row(settings)
        self._ranking_settings_cache.invalidate(guild_id)
        return diffs

    async def reset_evaluation_settings(self, guild_id: int) -> dict[str, tuple[object, object]]:
        async with self._database.session() as session:
            settings = await EvaluationSettingsRepository(session).get_or_create(guild_id)
            diffs = reset_row(settings)
        self._evaluation_settings_cache.invalidate(guild_id)
        return diffs

    async def reset_anti_spam_settings(self, guild_id: int) -> dict[str, tuple[object, object]]:
        async with self._database.session() as session:
            settings = await AntiSpamSettingsRepository(session).get_or_create(guild_id)
            diffs = reset_row(settings)
        self._anti_spam_settings_cache.invalidate(guild_id)
        return diffs

    async def reset_permission_settings(self, guild_id: int) -> dict[str, tuple[object, object]]:
        async with self._database.session() as session:
            settings = await PermissionSettingsRepository(session).get_or_create(guild_id)
            diffs = reset_row(settings)
        self._permission_settings_cache.invalidate(guild_id)
        return diffs
