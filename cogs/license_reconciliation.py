from __future__ import annotations

from discord.ext import commands, tasks

from core.bot import LimerenceBot
from core.logger import get_logger

logger = get_logger("license_reconciliation")

# Fase 5: "adicionar reconciliacao periodica" — roda em todos os servidores a
# cada tick, corrigindo divergencia entre License (backend) e cargo Discord.
# Eventos (RoleSyncService) cobrem o caminho feliz; isto e so a rede de
# seguranca pro que passa por cima dos eventos (bot offline, cargo editado
# manualmente, membro que saiu/voltou).
_TICK_MINUTES = 60


class LicenseReconciliationCog(commands.Cog):
    """So o wrapper do loop — toda a regra vive em ReconciliationService
    (nenhuma logica de negocio dentro da Cog, mesmo padrao de
    SubscriptionRenewalCog)."""

    def __init__(self, bot: LimerenceBot) -> None:
        self.bot = bot
        self.reconcile_licenses.start()

    def cog_unload(self) -> None:
        self.reconcile_licenses.cancel()

    @tasks.loop(minutes=_TICK_MINUTES)
    async def reconcile_licenses(self) -> None:
        try:
            report = await self.bot.reconciliation_service.reconcile_all_guilds()
        except Exception:
            logger.exception("Falha no ciclo de reconciliacao de licencas.")
            return
        if report.roles_granted or report.roles_removed or report.errors:
            logger.info(
                "Reconciliacao: %s guilds, %s cargos concedidos, %s removidos, %s erros.",
                report.guilds_checked,
                report.roles_granted,
                report.roles_removed,
                report.errors,
            )

    @reconcile_licenses.before_loop
    async def _before_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: LimerenceBot) -> None:
    await bot.add_cog(LicenseReconciliationCog(bot))
