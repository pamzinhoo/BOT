from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AdminError(BaseModel):
    code: str
    message: str
    field: str | None = None


class AdminErrorResponse(BaseModel):
    error: AdminError


class AdminGuild(BaseModel):
    id: str
    name: str
    icon_url: str | None = None
    member_count: int | None = None
    selected: bool = False


class AdminHealth(BaseModel):
    status: Literal["ok"]
    local_only: bool
    client_host: str | None


class AdminReadiness(BaseModel):
    api: bool
    discord_ready: bool
    discord_closed: bool
    guilds_loaded: bool
    guild_count: int
    ready: bool


class DiscordOption(BaseModel):
    id: str
    name: str
    type: str
    position: int | None = None
    color: str | None = None
    missing: bool = False


class SettingOption(BaseModel):
    value: str
    label: str


class SettingDefinition(BaseModel):
    key: str
    label: str
    description: str
    type: str
    section: str
    options: list[SettingOption] = Field(default_factory=list)
    required: bool = False


class SettingsSection(BaseModel):
    key: str
    title: str
    description: str
    fields: list[SettingDefinition]


class SettingsPayload(BaseModel):
    guild_id: str
    sections: list[SettingsSection]
    values: dict[str, Any]


class SettingsUpdateRequest(BaseModel):
    values: dict[str, Any]


class OverviewMetric(BaseModel):
    label: str
    value: int | float | str
    hint: str | None = None


class ActivityItem(BaseModel):
    id: str
    title: str
    category: str
    created_at: str
    actor: str | None = None
    target: str | None = None


class SystemStatus(BaseModel):
    name: str
    status: Literal["online", "degraded", "offline"]
    detail: str


class OverviewResponse(BaseModel):
    guild: AdminGuild | None
    bot: dict[str, Any]
    metrics: list[OverviewMetric]
    activity: list[ActivityItem]
    health: list[SystemStatus]


class TicketRow(BaseModel):
    id: str
    label: str
    channel_id: str
    channel_name: str | None = None
    user_id: str
    user_name: str | None = None
    category: str
    status: str
    staff_id: str | None
    staff_name: str | None = None
    created_at: str
    closed_at: str | None
    last_activity_at: str | None = None
    has_evaluation: bool = False


class TicketListResponse(BaseModel):
    items: list[TicketRow]
    page: int = 1
    page_size: int = 25
    total: int = 0
    pages: int = 0


class TicketClaimItem(BaseModel):
    staff_id: str
    staff_name: str | None = None
    claimed_at: str
    unclaimed_at: str | None = None


class TicketEvaluationItem(BaseModel):
    rating: int
    comment: str | None = None
    rated_by_id: str
    rated_by_name: str | None = None
    created_at: str


class TicketDetail(BaseModel):
    id: str
    label: str
    channel_id: str
    channel_name: str | None = None
    user_id: str
    user_name: str | None = None
    category: str
    status: str
    staff_id: str | None = None
    staff_name: str | None = None
    created_at: str
    first_response_at: str | None = None
    closed_at: str | None = None
    closed_by_id: str | None = None
    closed_by_name: str | None = None
    last_activity_at: str | None = None
    deleted_before_service: bool = False
    counts_for_stats: bool = True
    voice_channel_id: str | None = None
    voice_channel_name: str | None = None
    panel_id: str | None = None
    approval_status: str | None = None
    approval_reviewed_by: str | None = None
    approval_reviewed_by_name: str | None = None
    approval_reviewed_at: str | None = None
    claims: list[TicketClaimItem] = Field(default_factory=list)
    evaluation: TicketEvaluationItem | None = None


class StaffRow(BaseModel):
    id: str
    discord_user_id: str
    display_name: str
    tickets: int
    average_rating: float
    streak: int
    last_activity_at: str | None = None


class RankingRow(BaseModel):
    staff_id: str
    name: str
    tickets: int
    average_rating: float


class AuditListResponse(BaseModel):
    items: list[ActivityItem]
    total: int
    page: int = 1
    page_size: int = 50
    pages: int = 0


class AuditDetail(BaseModel):
    id: str
    action: str
    category: str
    created_at: str
    executor_id: str | None = None
    executor_name: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    reason: str | None = None
    config_category: str | None = None
    config_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SystemResponse(BaseModel):
    bot: dict[str, Any]
    api: dict[str, Any]
    database: dict[str, Any]
    version: dict[str, Any]
