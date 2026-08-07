from __future__ import annotations

import importlib
import pkgutil
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

import cogs
from config.settings import Settings
from core.logger import get_logger
from database.database import Database
from services.audit_log_service import AuditLogService
from services.automod_service import AutoModService
from services.booster_service import BoosterService
from services.bot_status_service import BotStatusService
from services.claim_service import ClaimService
from services.config_service import ConfigService
from services.coupon_service import CouponService
from services.evaluation_service import EvaluationService
from services.giveaway_service import GiveawayService
from services.guild_service import GuildService
from services.help_service import HelpService
from services.log_service import LogService
from services.painel_service import PainelService
from services.partnership_service import PartnershipService
from services.payment_service import PaymentService
from services.plan_service import PlanService
from services.poll_service import PollService
from services.punishment_review_service import PunishmentReviewService
from services.punishment_service import PunishmentService
from services.ranking_service import RankingService
from services.staff_service import StaffService
from services.subscription_reminder_service import SubscriptionReminderService
from services.subscription_renewal_config_service import SubscriptionRenewalConfigService
from services.subscription_service import SubscriptionService
from services.ticket_panel_service import TicketPanelService
from services.ticket_service import TicketService
from services.verification_service import VerificationService
from services.vote_weight_service import VoteWeightService
from utils.checks import NotAdminError, NotStaffError

logger = get_logger("bot")


class LimerenceBot(commands.Bot):
    """Bot principal do BOT LIMERENCE, plataforma de gerenciamento da staff de suporte."""

    def __init__(self, settings: Settings, database: Database) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.presences = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            application_id=settings.discord_application_id,  # type: ignore[arg-type]
        )

        self.settings = settings
        self.database = database
        self.started_at = datetime.now(UTC)

        self.config_service = ConfigService(database)
        self.guild_service = GuildService(database)
        self.staff_service = StaffService(database)
        self.ticket_service = TicketService(database)
        self.ticket_panel_service = TicketPanelService(database, self)
        self.claim_service = ClaimService(database)
        self.evaluation_service = EvaluationService(database)
        self.ranking_service = RankingService(database)
        self.log_service = LogService(database, self)
        self.painel_service = PainelService(database, self)
        self.audit_log_service = AuditLogService(database, self)
        self.bot_status_service = BotStatusService(database, self)
        self.punishment_service = PunishmentService(database)
        self.punishment_review_service = PunishmentReviewService(
            database, self.punishment_service, self.audit_log_service
        )
        self.help_service = HelpService(database, self.audit_log_service)
        self.automod_service = AutoModService(database)
        self.booster_service = BoosterService(database, self)
        self.plan_service = PlanService(database, self)
        self.payment_service = PaymentService(database, settings)
        self.coupon_service = CouponService(database, self)
        self.subscription_service = SubscriptionService(database, self, self.payment_service)
        self.subscription_renewal_config_service = SubscriptionRenewalConfigService(database)
        self.subscription_reminder_service = SubscriptionReminderService(
            database, self, self.subscription_renewal_config_service, self.subscription_service
        )
        self.vote_weight_service = VoteWeightService(database)
        self.poll_service = PollService(
            database, self, self.vote_weight_service, self.subscription_service
        )
        self.verification_service = VerificationService(database, self)
        self.partnership_service = PartnershipService(database, self)
        self.giveaway_service = GiveawayService(database, self)

        self.tree.on_error = self._on_app_command_error
        self._patch_view_store_diagnostics()

    def _patch_view_store_diagnostics(self) -> None:
        """DEBUG TEMPORARIO: loga quando uma interacao de componente nao acha
        nenhum item registrado (dispatch silencioso, sem excecao, sem log).
        Remover depois de identificar a causa do bug do painel de config."""
        store = self._connection._view_store
        original = store.dispatch_view

        def _patched(component_type: int, custom_id: str, interaction: discord.Interaction) -> None:
            msg = interaction.message
            message_id = msg.id if msg is not None else None
            key = (component_type, custom_id)
            known = store._views.get(message_id, {})
            if key not in known and key not in store._views.get(None, {}):
                logger.warning(
                    "DISPATCH MISS: message_id=%s custom_id=%s tipo=%s tem %d itens conhecidos pra essa mensagem (chaves=%s)",
                    message_id, custom_id, component_type, len(known), list(known.keys()),
                )
            else:
                logger.info("DISPATCH OK: message_id=%s custom_id=%s", message_id, custom_id)
            return original(component_type, custom_id, interaction)

        store.dispatch_view = _patched  # type: ignore[method-assign]

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Calma aí! Tenta de novo em {error.retry_after:.0f}s."
        elif isinstance(error, NotStaffError):
            message = "Apenas a staff pode usar esse comando."
        elif isinstance(error, NotAdminError):
            message = "Apenas administradores podem usar esse comando."
        elif isinstance(error, app_commands.CheckFailure):
            message = "Você não tem permissão pra usar esse comando."
        else:
            logger.exception("Erro nao tratado em app command.", exc_info=error)
            message = "Deu erro ao executar esse comando. Já foi registrado nos logs."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def setup_hook(self) -> None:
        await self.database.check_connection()
        await self._load_cogs()
        await self._register_persistent_views()

        if self.settings.test_guild_id is not None:
            guild = discord.Object(id=self.settings.test_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            # limpa comandos globais antigos (ja propagados antes de TEST_GUILD_ID
            # existir) pra nao duplicar com os da guild de teste
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info(
                "Slash commands sincronizados instantaneamente na guild de teste (%s).",
                self.settings.test_guild_id,
            )
        else:
            await self.tree.sync()
            logger.info(
                "Slash commands sincronizados globalmente (propagacao pode levar ate 1h)."
            )

    async def _register_persistent_views(self) -> None:
        from cogs.giveaways import GiveawayCloseButton, GiveawayEnterButton, GiveawayRerollButton
        from cogs.polls import PollVoteButton
        from views.appeal_view import AppealAcceptButton, AppealButton, AppealDenyButton
        from views.evaluation_view import EvaluationView
        from views.help_views import HelpCategoryView, HelpMainView
        from views.painel_view import PainelView
        from views.pending_punishments_view import (
            AnalisesAcceptButton,
            AnalisesBackButton,
            AnalisesDenyButton,
            AnalisesNavButton,
            AnalisesSelect,
        )
        from views.partnership_view import PartnershipInfoView
        from views.shop_view import ShopPanelView
        from views.ticket_actions_view import TicketActionsView
        from views.ticket_approval_view import TicketApprovalView
        from views.ticket_closed_view import TicketClosedView

        self.add_view(PainelView())
        self.add_view(TicketActionsView())
        self.add_view(TicketClosedView())
        self.add_view(TicketApprovalView())
        self.add_view(EvaluationView())
        self.add_view(HelpMainView())
        self.add_view(HelpCategoryView())
        self.add_view(ShopPanelView())
        self.add_view(PartnershipInfoView())
        self.add_dynamic_items(AppealButton, AppealAcceptButton, AppealDenyButton)
        self.add_dynamic_items(
            AnalisesNavButton, AnalisesSelect, AnalisesAcceptButton, AnalisesDenyButton, AnalisesBackButton
        )
        self.add_dynamic_items(PollVoteButton)
        self.add_dynamic_items(GiveawayEnterButton, GiveawayCloseButton, GiveawayRerollButton)

        # botoes das mensagens de renovacao de assinatura (vao por DM/canal e
        # precisam responder mesmo depois de um restart)
        from views.subscription_renewal_buttons import (
            CloseRenewalMessageButton,
            OpenStoreButton,
            RenewSubscriptionButton,
            ViewPlanButton,
        )

        self.add_dynamic_items(
            RenewSubscriptionButton, ViewPlanButton, OpenStoreButton, CloseRenewalMessageButton
        )

        # botoes de aprovacao manual de pagamento (canal de aprovacao —
        # precisam responder mesmo depois de um restart)
        from views.shop_view import (
            PaymentApproveButton,
            PaymentCancelButton,
            PaymentPendingButton,
            PaymentRejectButton,
        )

        self.add_dynamic_items(
            PaymentApproveButton, PaymentRejectButton, PaymentPendingButton, PaymentCancelButton
        )

        # botoes do sistema de verificacao/CAPTCHA (DM ou canal de fallback) —
        # precisam responder mesmo depois de um restart, com o codigo/sessao
        # ainda validos.
        from views.verification_view import PickCaptchaButton, TypeCaptchaButton, VerificationPanelView

        self.add_dynamic_items(TypeCaptchaButton, PickCaptchaButton)
        self.add_view(VerificationPanelView())

        # cada painel de ticket configuravel tem um botao com custom_id proprio
        # (limerence:ticket_panel:<key>:open) — sem re-registrar aqui, os botoes
        # dos paineis ja publicados param de responder depois de um restart.
        try:
            registered = await self.ticket_panel_service.register_published_views()
            logger.info("Views persistentes de paineis de ticket registradas: %d", registered)
        except Exception:
            logger.exception("Falha ao registrar as views dos paineis de ticket publicados.")

    async def _load_cogs(self) -> None:
        loaded = 0
        for module_info in pkgutil.iter_modules(cogs.__path__):
            if module_info.name.startswith("_"):
                continue
            module_name = f"cogs.{module_info.name}"
            module = importlib.import_module(module_name)
            if not hasattr(module, "setup"):
                continue
            await self.load_extension(module_name)
            loaded += 1
            logger.info("Cog carregado: %s", module_name)
        logger.info("Total de cogs carregados: %d", loaded)

    async def on_ready(self) -> None:
        logger.info(
            "Bot conectado como %s (ID: %s).", self.user, self.user.id if self.user else "?"
        )

    async def close(self) -> None:
        await self.database.close()
        await super().close()
