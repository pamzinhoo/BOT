from database.repositories.anti_spam_settings_repository import AntiSpamSettingsRepository
from database.repositories.audit_log_repository import AuditLogRepository
from database.repositories.audit_log_settings_repository import AuditLogSettingsRepository
from database.repositories.automod_repository import (
    AutoModLogRepository,
    AutoModSettingsRepository,
    AutoModWordRepository,
)
from database.repositories.base_repository import BaseRepository
from database.repositories.booster_repository import BoosterRepository
from database.repositories.booster_settings_repository import BoosterSettingsRepository
from database.repositories.claim_repository import ClaimRepository
from database.repositories.command_help_repository import CommandHelpRepository
from database.repositories.dashboard_settings_repository import DashboardSettingsRepository
from database.repositories.device_repository import DeviceRepository
from database.repositories.discount_coupon_repository import (
    DiscountCouponPlanRepository,
    DiscountCouponRedemptionRepository,
    DiscountCouponRepository,
)
from database.repositories.download_repository import DownloadRepository
from database.repositories.enquete_settings_repository import EnqueteSettingsRepository
from database.repositories.evaluation_repository import EvaluationRepository
from database.repositories.evaluation_settings_repository import EvaluationSettingsRepository
from database.repositories.game_manifest_repository import GameManifestRepository
from database.repositories.guild_repository import GuildRepository
from database.repositories.guild_settings_repository import GuildSettingsRepository
from database.repositories.launcher_news_repository import LauncherNewsRepository
from database.repositories.launcher_session_repository import LauncherSessionRepository
from database.repositories.launcher_version_repository import LauncherVersionRepository
from database.repositories.license_repository import LicenseEventRepository, LicenseRepository
from database.repositories.log_repository import LogRepository
from database.repositories.monetization_settings_repository import MonetizationSettingsRepository
from database.repositories.payment_dm_settings_repository import PaymentDmSettingsRepository
from database.repositories.payment_repository import PaymentRepository
from database.repositories.permission_settings_repository import PermissionSettingsRepository
from database.repositories.pix_manual_settings_repository import PixManualSettingsRepository
from database.repositories.plan_repository import (
    PlanBenefitRepository,
    PlanMessageRepository,
    PlanRepository,
)
from database.repositories.player_repository import PlayerRepository
from database.repositories.poll_repository import (
    PollOptionRepository,
    PollRepository,
    PollVoteRepository,
)
from database.repositories.product_repository import ProductRepository
from database.repositories.punishment_appeal_repository import PunishmentAppealRepository
from database.repositories.punishment_repository import PunishmentRepository
from database.repositories.ranking_settings_repository import RankingSettingsRepository
from database.repositories.staff_activity_repository import StaffActivityRepository
from database.repositories.staff_repository import StaffRepository
from database.repositories.staff_stats_repository import StaffStatsRepository
from database.repositories.subscription_history_repository import SubscriptionHistoryRepository
from database.repositories.subscription_renewal_repository import (
    SubscriptionMessageRepository,
    SubscriptionReminderDayRepository,
    SubscriptionReminderRepository,
    SubscriptionRenewalButtonRepository,
    SubscriptionRenewalSettingsRepository,
)
from database.repositories.subscription_repository import SubscriptionRepository
from database.repositories.ticket_message_repository import TicketMessageRepository
from database.repositories.ticket_panel_repository import (
    TicketFormResponseRepository,
    TicketPanelFormFieldRepository,
    TicketPanelRepository,
)
from database.repositories.ticket_repository import TicketRepository
from database.repositories.ticket_settings_repository import TicketSettingsRepository
from database.repositories.vote_weight_repository import VoteWeightRepository

__all__ = [
    "AntiSpamSettingsRepository",
    "AuditLogRepository",
    "AuditLogSettingsRepository",
    "AutoModLogRepository",
    "AutoModSettingsRepository",
    "AutoModWordRepository",
    "BaseRepository",
    "BoosterRepository",
    "BoosterSettingsRepository",
    "ClaimRepository",
    "CommandHelpRepository",
    "DashboardSettingsRepository",
    "DeviceRepository",
    "DiscountCouponPlanRepository",
    "DiscountCouponRedemptionRepository",
    "DiscountCouponRepository",
    "DownloadRepository",
    "EnqueteSettingsRepository",
    "EvaluationRepository",
    "EvaluationSettingsRepository",
    "GameManifestRepository",
    "GuildRepository",
    "GuildSettingsRepository",
    "LauncherNewsRepository",
    "LauncherSessionRepository",
    "LauncherVersionRepository",
    "LicenseEventRepository",
    "LicenseRepository",
    "LogRepository",
    "MonetizationSettingsRepository",
    "PaymentDmSettingsRepository",
    "PaymentRepository",
    "PermissionSettingsRepository",
    "PixManualSettingsRepository",
    "PlanBenefitRepository",
    "PlanMessageRepository",
    "PlanRepository",
    "PlayerRepository",
    "PollOptionRepository",
    "PollRepository",
    "PollVoteRepository",
    "ProductRepository",
    "PunishmentAppealRepository",
    "PunishmentRepository",
    "RankingSettingsRepository",
    "StaffActivityRepository",
    "StaffRepository",
    "StaffStatsRepository",
    "SubscriptionHistoryRepository",
    "SubscriptionMessageRepository",
    "SubscriptionReminderDayRepository",
    "SubscriptionReminderRepository",
    "SubscriptionRenewalButtonRepository",
    "SubscriptionRenewalSettingsRepository",
    "SubscriptionRepository",
    "TicketFormResponseRepository",
    "TicketMessageRepository",
    "TicketPanelFormFieldRepository",
    "TicketPanelRepository",
    "TicketRepository",
    "TicketSettingsRepository",
    "VoteWeightRepository",
]
