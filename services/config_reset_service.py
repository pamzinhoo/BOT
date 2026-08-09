from __future__ import annotations

from typing import TYPE_CHECKING

from database.models.guild_settings import GuildSettings
from views.master_config_view import iter_categories

if TYPE_CHECKING:
    from core.bot import LimerenceBot


async def reset_all_guild_config(bot: LimerenceBot, guild_id: int) -> dict[str, int]:
    """Restaura TODAS as categorias configuráveis do servidor pro padrão de fábrica
    (mesmo usado quando a guild configura o bot pela primeira vez). Não apaga
    tickets, estatísticas, ranking, auditoria, logs, histórico, transcrições ou
    avaliações recebidas — só as tabelas de configuração.

    Retorna {título_da_categoria: quantidade_de_campos_alterados}.
    """
    guild_attrs: set[str] = set()
    for _key, _title, fields, _get_settings, _update_settings in iter_categories(bot):
        guild_attrs.update(field.attr for field in fields if field.model is GuildSettings)

    changed: dict[str, int] = {}
    changed["👮 Cargos / Canais"] = len(
        await bot.config_service.reset_guild_settings_fields(guild_id, guild_attrs)
    )
    changed["🎫 Tickets"] = len(await bot.config_service.reset_ticket_settings(guild_id))
    changed["📊 Dashboard"] = len(await bot.config_service.reset_dashboard_settings(guild_id))
    changed["🤖 Status do Bot"] = len(await bot.config_service.reset_bot_status_settings(guild_id))
    changed["📈 Ranking"] = len(await bot.config_service.reset_ranking_settings(guild_id))
    changed["⭐ Avaliações"] = len(await bot.config_service.reset_evaluation_settings(guild_id))
    changed["🚫 Anti-Spam"] = len(await bot.config_service.reset_anti_spam_settings(guild_id))
    changed["🔐 Permissões"] = len(await bot.config_service.reset_permission_settings(guild_id))
    changed["📋 Auditoria"] = len(await bot.audit_log_service.reset_settings(guild_id))

    await bot.painel_service.refresh_dashboard(guild_id)
    return changed
