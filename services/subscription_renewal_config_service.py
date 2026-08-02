from __future__ import annotations

import uuid

from database.database import Database
from database.models.subscription_renewal import (
    SubscriptionMessage,
    SubscriptionMessageType,
    SubscriptionReminderDay,
    SubscriptionRenewalButton,
    SubscriptionRenewalButtonKey,
    SubscriptionRenewalSettings,
)
from database.repositories.subscription_renewal_repository import (
    SubscriptionMessageRepository,
    SubscriptionReminderDayRepository,
    SubscriptionRenewalButtonRepository,
    SubscriptionRenewalSettingsRepository,
)

# Textos padrao — usados so como fallback quando a guild ainda nao personalizou
# a mensagem. Todos sao editaveis pelo painel (Monetizacao > Renovacao >
# Mensagens), entao nenhum texto aqui e inalcancavel pelo admin.
DEFAULT_MESSAGES: dict[SubscriptionMessageType, str] = {
    SubscriptionMessageType.REMINDER: (
        "⏰ Olá {user}! Sua assinatura **{plan_name}** em {server_name} vence em "
        "**{days_left} dia(s)** ({expires_at}).\n"
        "Renove pra não perder {role_name} e seus benefícios."
    ),
    SubscriptionMessageType.LAST_REMINDER: (
        "🚨 {mention}, este é o **último aviso**: sua assinatura **{plan_name}** em "
        "{server_name} vence em **{days_left} dia(s)** ({expires_at}).\n"
        "Use {store_command} ou o botão abaixo pra renovar agora."
    ),
    SubscriptionMessageType.EXPIRED: (
        "❌ {user}, sua assinatura **{plan_name}** em {server_name} expirou em "
        "{expires_at} e os benefícios foram removidos.\n"
        "Você pode assinar de novo quando quiser pela loja."
    ),
    SubscriptionMessageType.RENEWED: (
        "✅ {user}, sua assinatura **{plan_name}** em {server_name} foi renovada!\n"
        "Válida até **{renew_date}**. Obrigado pelo apoio 💜"
    ),
    SubscriptionMessageType.GRACE_PERIOD: (
        "⚠️ {user}, sua assinatura **{plan_name}** em {server_name} venceu em "
        "{expires_at}, mas você está num período de carência de **{grace_days} dia(s)**.\n"
        "Renove antes do fim da carência pra manter {role_name}."
    ),
}

DEFAULT_BUTTONS: dict[SubscriptionRenewalButtonKey, tuple[str, str, int]] = {
    SubscriptionRenewalButtonKey.RENEW: ("Renovar", "🔄", 0),
    SubscriptionRenewalButtonKey.VIEW_PLAN: ("Ver Plano", "📋", 1),
    SubscriptionRenewalButtonKey.OPEN_STORE: ("Abrir Loja", "🛒", 2),
    SubscriptionRenewalButtonKey.CLOSE: ("Fechar", "✖️", 3),
}

# opcoes validadas na camada de UI (a coluna aceita qualquer inteiro)
CHECK_INTERVAL_CHOICES = (1, 6, 12, 24)
GRACE_PERIOD_CHOICES = (0, 1, 3, 5, 7, 10)


class SubscriptionRenewalConfigService:
    """CRUD da configuracao de renovacao de assinaturas (settings, dias de
    aviso, mensagens e botoes). Views/Cogs nunca tocam nos repositorios."""

    def __init__(self, database: Database) -> None:
        self._database = database

    # --- settings ---------------------------------------------------------

    async def get_settings(self, guild_id: int) -> SubscriptionRenewalSettings:
        async with self._database.session() as session:
            return await SubscriptionRenewalSettingsRepository(session).get_or_create(guild_id)

    async def update_settings(self, guild_id: int, **fields: object) -> SubscriptionRenewalSettings:
        async with self._database.session() as session:
            repo = SubscriptionRenewalSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
            return settings

    async def list_enabled_settings(self) -> list[SubscriptionRenewalSettings]:
        async with self._database.session() as session:
            return await SubscriptionRenewalSettingsRepository(session).list_enabled()

    # --- dias de aviso ----------------------------------------------------

    async def list_reminder_days(self, guild_id: int) -> list[SubscriptionReminderDay]:
        async with self._database.session() as session:
            return await SubscriptionReminderDayRepository(session).list_by_guild(guild_id)

    async def add_reminder_day(self, guild_id: int, days_before: int) -> SubscriptionReminderDay:
        if days_before < 0:
            raise ValueError("O aviso tem que ser de 0 dias ou mais antes do vencimento.")
        async with self._database.session() as session:
            repo = SubscriptionReminderDayRepository(session)
            if await repo.get_by_days_before(guild_id, days_before) is not None:
                raise ValueError(f"Já existe um aviso configurado para {days_before} dia(s) antes.")
            existing = await repo.list_by_guild(guild_id)
            return await repo.add(
                SubscriptionReminderDay(
                    guild_id=guild_id, days_before=days_before, position=len(existing)
                )
            )

    async def remove_reminder_day(self, day_id: uuid.UUID, *, guild_id: int) -> None:
        async with self._database.session() as session:
            repo = SubscriptionReminderDayRepository(session)
            day = await repo.get_by_id(day_id)
            if day is not None and day.guild_id == guild_id:
                await repo.delete(day)

    async def toggle_reminder_day(
        self, day_id: uuid.UUID, *, guild_id: int
    ) -> SubscriptionReminderDay | None:
        async with self._database.session() as session:
            repo = SubscriptionReminderDayRepository(session)
            day = await repo.get_by_id(day_id)
            if day is None or day.guild_id != guild_id:
                return None
            day.enabled = not day.enabled
            await session.flush()
            await session.refresh(day)
            return day

    async def move_reminder_day(self, day_id: uuid.UUID, *, guild_id: int, delta: int) -> None:
        """Reordena trocando a posicao com o vizinho — mantem a lista sem
        buracos e sem depender de o admin digitar indices."""
        async with self._database.session() as session:
            repo = SubscriptionReminderDayRepository(session)
            day = await repo.get_by_id(day_id)
            if day is None or day.guild_id != guild_id:
                return
            days = await repo.list_by_guild(day.guild_id)
            for index, item in enumerate(days):
                item.position = index
            current = next((i for i, item in enumerate(days) if item.id == day_id), None)
            if current is None:
                return
            target = current + delta
            if target < 0 or target >= len(days):
                await session.flush()
                return
            days[current].position, days[target].position = (
                days[target].position,
                days[current].position,
            )
            await session.flush()

    # --- mensagens --------------------------------------------------------

    async def get_message(
        self, guild_id: int, message_type: SubscriptionMessageType
    ) -> SubscriptionMessage | None:
        async with self._database.session() as session:
            return await SubscriptionMessageRepository(session).get_by_guild_and_type(
                guild_id, message_type
            )

    async def get_message_content(
        self, guild_id: int, message_type: SubscriptionMessageType
    ) -> str:
        record = await self.get_message(guild_id, message_type)
        return record.content if record is not None else DEFAULT_MESSAGES[message_type]

    async def set_message(
        self, guild_id: int, message_type: SubscriptionMessageType, content: str
    ) -> SubscriptionMessage:
        async with self._database.session() as session:
            repo = SubscriptionMessageRepository(session)
            existing = await repo.get_by_guild_and_type(guild_id, message_type)
            if existing is not None:
                existing.content = content
                await session.flush()
                return existing
            return await repo.add(
                SubscriptionMessage(
                    guild_id=guild_id, message_type=message_type, content=content
                )
            )

    async def reset_message(self, guild_id: int, message_type: SubscriptionMessageType) -> None:
        """Apaga a personalizacao — volta a usar DEFAULT_MESSAGES."""
        async with self._database.session() as session:
            repo = SubscriptionMessageRepository(session)
            existing = await repo.get_by_guild_and_type(guild_id, message_type)
            if existing is not None:
                await repo.delete(existing)

    # --- botoes -----------------------------------------------------------

    async def list_buttons(self, guild_id: int) -> list[SubscriptionRenewalButton]:
        """Semeia as 4 chaves padrao no primeiro acesso da guild."""
        async with self._database.session() as session:
            repo = SubscriptionRenewalButtonRepository(session)
            existing = {button.key for button in await repo.list_by_guild(guild_id)}
            for key, (label, emoji, position) in DEFAULT_BUTTONS.items():
                if key in existing:
                    continue
                await repo.add(
                    SubscriptionRenewalButton(
                        guild_id=guild_id,
                        key=key,
                        label=label,
                        emoji=emoji,
                        position=position,
                    )
                )
            return await repo.list_by_guild(guild_id)

    async def update_button(
        self, guild_id: int, key: SubscriptionRenewalButtonKey, **fields: object
    ) -> SubscriptionRenewalButton:
        async with self._database.session() as session:
            repo = SubscriptionRenewalButtonRepository(session)
            button = await repo.get_by_key(guild_id, key)
            if button is None:
                label, emoji, position = DEFAULT_BUTTONS[key]
                button = await repo.add(
                    SubscriptionRenewalButton(
                        guild_id=guild_id, key=key, label=label, emoji=emoji, position=position
                    )
                )
            for name, value in fields.items():
                setattr(button, name, value)
            await session.flush()
            await session.refresh(button)
            return button

    async def toggle_button(
        self, guild_id: int, key: SubscriptionRenewalButtonKey
    ) -> SubscriptionRenewalButton:
        buttons = await self.list_buttons(guild_id)
        current = next((b for b in buttons if b.key == key), None)
        enabled = not current.enabled if current is not None else False
        return await self.update_button(guild_id, key, enabled=enabled)
