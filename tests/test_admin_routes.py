from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.admin import router
from database.models.audit_log import AuditLogCategory
from database.models.ticket import TicketCategory, TicketStatus


class _Service:
    def __init__(self) -> None:
        self.guild = SimpleNamespace(
            ticket_category_id=None,
            log_channel_id=None,
            transcript_channel_id=None,
            evaluations_channel_id=None,
            ticket_alert_channel_id=None,
            blacklist_channel_id=None,
            inactive_after_minutes=1440,
            owner_role_id=None,
            ceo_role_id=None,
            dev_role_id=None,
            moderator_role_id=None,
            support_role_id=None,
            partner_role_id=None,
            streamer_role_id=None,
            player_role_id=None,
            verified_role_id=None,
            dashboard_channel_id=None,
            ranking_channel_id=None,
            ranking_message_id=None,
            log_punishments_channel_id=None,
            appeal_channel_id=None,
            appeal_category_id=None,
            max_timeout_duration_minutes=60,
            moderation_enabled=True,
            require_proof=True,
            review_role_id=None,
            review_channel_id=None,
            review_timeout_minutes=60,
        )
        self.ticket = SimpleNamespace(
            enabled=True,
            max_tickets_per_user=2,
            allow_multiple_tickets=True,
            auto_close_enabled=True,
            delete_delay_seconds=10,
            category_selection_mode="buttons",
        )
        self.permission = SimpleNamespace(
            claim=[],
            unclaim=[],
            fechar=[],
            reabrir=[],
            excluir=[],
            auditoria=[],
            ranking=[],
            config=[],
            recurso_banimento=[],
            analises=[],
            convite=[],
        )
        self.dashboard = SimpleNamespace(auto_update_enabled=True, update_interval_minutes=5, top_count=10, show_chart=True)
        self.ranking = SimpleNamespace(criteria="tickets", default_period="alltime")
        self.evaluation = SimpleNamespace(
            enabled=True,
            min_comment_rating=2,
            star_emoji="*",
            evaluation_method="ticket",
            dm_embed_title=None,
            dm_embed_description=None,
            dm_prompt_text=None,
            dm_button_label=None,
            dm_thanks_message=None,
        )
        self.antispam = SimpleNamespace(
            window_seconds=60,
            cross_channel_threshold=3,
            flood_threshold=4,
            ignore_staff=True,
            default_action="alerta",
        )
        self.bot_status = SimpleNamespace(channel_id=None, update_interval_minutes=5)
        self.updated: dict[str, object] = {}

    async def get_settings(self, guild_id: int):
        return self.guild

    async def update(self, guild_id: int, **fields: object):
        self.updated.update(fields)
        for key, value in fields.items():
            setattr(self.guild, key, value)
        return self.guild

    async def get_ticket_settings(self, guild_id: int):
        return self.ticket

    async def update_ticket_settings(self, guild_id: int, **fields: object):
        self.updated.update(fields)
        for key, value in fields.items():
            setattr(self.ticket, key, value)
        return self.ticket

    async def get_permission_settings(self, guild_id: int):
        return self.permission

    async def update_permission_settings(self, guild_id: int, **fields: object):
        self.updated.update(fields)
        return self.permission

    async def get_dashboard_settings(self, guild_id: int):
        return self.dashboard

    async def update_dashboard_settings(self, guild_id: int, **fields: object):
        self.updated.update(fields)
        return self.dashboard

    async def get_ranking_settings(self, guild_id: int):
        return self.ranking

    async def update_ranking_settings(self, guild_id: int, **fields: object):
        self.updated.update(fields)
        return self.ranking

    async def get_evaluation_settings(self, guild_id: int):
        return self.evaluation

    async def update_evaluation_settings(self, guild_id: int, **fields: object):
        self.updated.update(fields)
        return self.evaluation

    async def get_anti_spam_settings(self, guild_id: int):
        return self.antispam

    async def update_anti_spam_settings(self, guild_id: int, **fields: object):
        self.updated.update(fields)
        return self.antispam

    async def get_bot_status_settings(self, guild_id: int):
        return self.bot_status

    async def update_bot_status_settings(self, guild_id: int, **fields: object):
        self.updated.update(fields)
        return self.bot_status


class _Audit:
    async def record_config_change(self, **kwargs: object) -> None:
        return None


class _Bot:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(api_port=8000, environment="development")
        self.config_service = _Service()
        self.audit_log_service = _Audit()
        self.painel_service = SimpleNamespace(refresh_dashboard=self._noop)
        self.bot_status_service = SimpleNamespace(refresh=self._noop)
        self.verification_service = SimpleNamespace(
            get_settings=self._verification_settings,
            update_settings=self._noop_return_settings,
            publish_panel=self._publish_result,
            refresh_panel=self._publish_result,
        )
        self.partnership_service = SimpleNamespace(get_settings=self._partnership_settings, update_settings=self._noop_return_settings)
        self.booster_service = SimpleNamespace(get_settings=self._booster_settings, update_settings=self._noop_return_settings)
        self.guilds = [SimpleNamespace(id=123, name="Guild", icon=None, member_count=10, channels=[], roles=[])]
        self.started_at = datetime.now(UTC)
        self.user = None
        self.latency = 0
        self.ready = True

    def is_closed(self) -> bool:
        return False

    def is_ready(self) -> bool:
        return self.ready

    def get_guild(self, guild_id: int):
        return self.guilds[0] if guild_id == 123 else None

    async def _noop(self, *args: object, **kwargs: object) -> None:
        return None

    async def _noop_return_settings(self, *args: object, **kwargs: object):
        return await self._verification_settings(123)

    async def _publish_result(self, *args: object, **kwargs: object):
        return SimpleNamespace(ok=True, reason="ok")

    async def _verification_settings(self, guild_id: int):
        return SimpleNamespace(
            enabled=True,
            method="type",
            unverified_role_id=None,
            verified_role_id=None,
            verification_channel_id=None,
            log_channel_id=None,
            code_length=6,
            code_charset="alphanumeric",
            case_sensitive=False,
            max_attempts=3,
            timeout_minutes=10,
            welcome_message=None,
            success_message=None,
            error_message=None,
            expired_message=None,
            max_attempts_message=None,
            on_max_attempts_action="none",
            on_expire_action="none",
        )

    async def _partnership_settings(self, guild_id: int):
        return SimpleNamespace(
            enabled=True,
            auto_create=True,
            auto_move=True,
            category_channel_id=None,
            archive_category_id=None,
            staff_role_id=None,
            welcome_message=None,
            announcement_message=None,
            announcement_channel_id=None,
            announcement_interval_minutes=60,
            mention_type="none",
            role_removed_action="none",
            log_channel_id=None,
        )

    async def _booster_settings(self, guild_id: int):
        return SimpleNamespace(
            enabled=True,
            booster_role_id=None,
            dm_enabled=True,
            dm_message=None,
            log_channel_id=None,
            public_message_enabled=False,
            public_channel_id=None,
            public_use_embed=True,
            public_message=None,
        )


def _app() -> tuple[FastAPI, _Bot]:
    app = FastAPI()
    bot = _Bot()
    app.state.bot = bot
    app.include_router(router)
    return app, bot


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, bot: _DataBot) -> None:
        self.bot = bot
        self.calls = 0

    async def scalar(self, query: object) -> int:
        return len(self.bot.ticket_rows)

    async def execute(self, query: object) -> _Rows:
        self.calls += 1
        sql = str(query)
        params = query.compile().params
        if "FROM claims" in sql:
            return _Rows(self.bot.claim_rows)
        if "FROM evaluations" in sql and "JOIN" not in sql:
            return _Rows([self.bot.evaluation] if self.bot.evaluation else [])
        if "tickets.id" in sql and "tickets.guild_id" in sql and "LIMIT" not in sql:
            ticket_id = next((value for key, value in params.items() if key.startswith("id_")), None)
            row = next((row for row in self.bot.ticket_rows if row[0].id == ticket_id), None)
            return _Rows([row[:2]] if row else [])
        offset = int(getattr(getattr(query, "_offset_clause", None), "value", 0) or 0)
        limit = int(getattr(getattr(query, "_limit_clause", None), "value", len(self.bot.ticket_rows)) or len(self.bot.ticket_rows))
        return _Rows(self.bot.ticket_rows[offset : offset + limit])


class _FakeDatabase:
    def __init__(self, bot: _DataBot) -> None:
        self.bot = bot

    @asynccontextmanager
    async def session(self):
        yield _FakeSession(self.bot)


class _AuditService:
    def __init__(self) -> None:
        self.entries = [
            SimpleNamespace(
                id=uuid.uuid4(),
                guild_id=123,
                category=AuditLogCategory.TICKETS,
                action="Ticket fechado",
                executor_id=10,
                executor_name="Staff",
                target_id=20,
                target_name="Usuario",
                reason="Resolvido",
                details={"ticket": "abc"},
                config_category=None,
                config_name=None,
                old_value=None,
                new_value=None,
                created_at=datetime.now(UTC),
            )
        ]

    async def list_entries(self, guild_id: int, **kwargs: object):
        assert guild_id == 123
        return self.entries

    async def count_entries(self, guild_id: int, **kwargs: object) -> int:
        assert guild_id == 123
        return len(self.entries)

    async def get_entry(self, guild_id: int, entry_id: uuid.UUID):
        return next((entry for entry in self.entries if entry.id == entry_id and guild_id == 123), None)


class _DataBot(_Bot):
    def __init__(self) -> None:
        super().__init__()
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        self.ticket_rows = [
            (
                SimpleNamespace(
                    id=first_id,
                    guild_id=123,
                    channel_id=111,
                    opened_by_discord_id=222,
                    category=TicketCategory.BUG,
                    status=TicketStatus.OPEN,
                    claimed_by_staff_id=None,
                    created_at=datetime.now(UTC),
                    first_response_at=None,
                    closed_at=None,
                    closed_by_discord_id=None,
                    deleted_before_service=False,
                    counts_for_stats=True,
                    voice_channel_id=None,
                    panel_id=None,
                    approval_status=SimpleNamespace(value="none"),
                    approval_reviewed_by=None,
                    approval_reviewed_at=None,
                ),
                None,
                None,
            ),
            (
                SimpleNamespace(
                    id=second_id,
                    guild_id=123,
                    channel_id=333,
                    opened_by_discord_id=444,
                    category=TicketCategory.OUTRO,
                    status=TicketStatus.CLOSED,
                    claimed_by_staff_id=uuid.uuid4(),
                    created_at=datetime.now(UTC),
                    first_response_at=datetime.now(UTC),
                    closed_at=datetime.now(UTC),
                    closed_by_discord_id=555,
                    deleted_before_service=False,
                    counts_for_stats=True,
                    voice_channel_id=None,
                    panel_id=None,
                    approval_status=SimpleNamespace(value="none"),
                    approval_reviewed_by=None,
                    approval_reviewed_at=None,
                ),
                "Staff",
                uuid.uuid4(),
            ),
        ]
        self.claim_rows = []
        self.evaluation = SimpleNamespace(
            rating=5,
            comment="Otimo",
            rated_by_discord_id=444,
            created_at=datetime.now(UTC),
        )
        self.database = _FakeDatabase(self)
        self.audit_log_service = _AuditService()
        self.ticket_service = SimpleNamespace(list_open_by_guild=self._noop)

    def get_channel(self, channel_id: int):
        return None


def _data_app() -> tuple[FastAPI, _DataBot]:
    app = FastAPI()
    bot = _DataBot()
    app.state.bot = bot
    app.include_router(router)
    return app, bot


@pytest.mark.asyncio
async def test_admin_api_rejects_non_local_client() -> None:
    app, _ = _app()
    transport = ASGITransport(app=app, client=("203.0.113.10", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/api/health")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_health_is_ok_before_discord_ready() -> None:
    app, bot = _app()
    bot.ready = False
    bot.guilds = []
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_admin_readiness_false_before_bot_ready() -> None:
    app, bot = _app()
    bot.ready = False
    bot.guilds = []
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/api/ready")
    assert response.status_code == 200
    assert response.json() == {
        "api": True,
        "discord_ready": False,
        "discord_closed": False,
        "guilds_loaded": False,
        "guild_count": 0,
        "ready": False,
    }


@pytest.mark.asyncio
async def test_admin_readiness_true_after_discord_ready_and_guild_cache() -> None:
    app, _ = _app()
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/api/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["discord_ready"] is True
    assert response.json()["guilds_loaded"] is True
    assert response.json()["guild_count"] == 1


@pytest.mark.asyncio
async def test_admin_settings_update_uses_config_service() -> None:
    app, bot = _app()
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/admin/api/guild/123/settings",
            json={"values": {"max_tickets_per_user": 4}},
        )
    assert response.status_code == 200
    assert bot.config_service.updated["max_tickets_per_user"] == 4


@pytest.mark.asyncio
async def test_admin_settings_response_does_not_include_env_secrets() -> None:
    app, _ = _app()
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/api/guild/123/settings")
    assert response.status_code == 200
    payload = response.text
    assert "DISCORD_TOKEN" not in payload
    assert "DATABASE_URL" not in payload
    assert "INTERNAL_API_SECRET" not in payload


@pytest.mark.asyncio
async def test_admin_tickets_are_paginated_and_isolated_by_guild() -> None:
    app, _ = _data_app()
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/api/guild/123/tickets?page=2&page_size=1&status=all")
        missing = await client.get("/admin/api/guild/999/tickets")
    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 2
    assert payload["page_size"] == 1
    assert payload["total"] == 2
    assert payload["pages"] == 2
    assert payload["items"][0]["channel_id"] == "333"
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_admin_ticket_detail_and_not_found() -> None:
    app, bot = _data_app()
    ticket_id = bot.ticket_rows[1][0].id
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/admin/api/guild/123/tickets/{ticket_id}")
        missing = await client.get(f"/admin/api/guild/123/tickets/{uuid.uuid4()}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(ticket_id)
    assert payload["staff_name"] == "Staff"
    assert payload["evaluation"]["rating"] == 5
    assert "DISCORD_TOKEN" not in response.text
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_admin_tickets_reject_page_size_above_maximum() -> None:
    app, _ = _data_app()
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/api/guild/123/tickets?page_size=500")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_admin_audit_list_and_detail() -> None:
    app, bot = _data_app()
    entry_id = bot.audit_log_service.entries[0].id
    transport = ASGITransport(app=app, client=("127.0.0.1", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/api/guild/123/audit?page=1&page_size=25&search=Ticket")
        detail = await client.get(f"/admin/api/guild/123/audit/{entry_id}")
        missing = await client.get(f"/admin/api/guild/123/audit/{uuid.uuid4()}")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["action"] == "Ticket fechado"
    assert payload["details"] == {"ticket": "abc"}
    assert "DATABASE_URL" not in detail.text
    assert missing.status_code == 404
