from __future__ import annotations

import uuid

from config.settings import Settings
from database.database import Database
from database.models.monetization_gateway_settings import MonetizationGatewaySettings
from database.models.payment import PaymentHistory, PaymentStatus
from database.models.payment_dm_settings import PaymentDmSettings
from database.models.payment_status_history import PaymentStatusHistory
from database.models.pix_manual_settings import PixManualSettings
from database.repositories.monetization_gateway_settings_repository import (
    MonetizationGatewaySettingsRepository,
)
from database.repositories.payment_dm_settings_repository import PaymentDmSettingsRepository
from database.repositories.payment_repository import PaymentRepository
from database.repositories.payment_status_history_repository import PaymentStatusHistoryRepository
from database.repositories.pix_manual_settings_repository import PixManualSettingsRepository
from providers.base import ChargeRequest, ChargeResult, PaymentGatewayError, PaymentProvider
from providers.manual import ManualProvider
from providers.mercadopago import MercadoPagoProvider
from utils.pix_validation import validate_pix_key


class PaymentService:
    """Camada fina sobre gateways de pagamento: resolve qual provider cada
    guild usa, cria/consulta cobranca e registra em payment_history +
    payment_status_history. Idempotente via UNIQUE(provider, external_id) —
    se o provider (ou um webhook) reenviar a mesma cobranca, retorna o
    registro ja existente em vez de duplicar."""

    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self._database = database
        self._settings = settings

    # --- gateway settings -----------------------------------------------

    async def get_gateway_settings(self, guild_id: int) -> MonetizationGatewaySettings:
        async with self._database.session() as session:
            return await MonetizationGatewaySettingsRepository(session).get_or_create(guild_id)

    async def update_gateway_settings(self, guild_id: int, **fields: object) -> MonetizationGatewaySettings:
        async with self._database.session() as session:
            repo = MonetizationGatewaySettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
            return settings

    async def resolve_provider(self, guild_id: int) -> PaymentProvider:
        gateway_settings = await self.get_gateway_settings(guild_id)
        if gateway_settings.provider == "mercadopago":
            if self._settings is None:
                raise PaymentGatewayError("Mercado Pago nao configurado neste bot (settings ausente).")
            return MercadoPagoProvider(
                access_token=self._settings.mercadopago_access_token or "",
                webhook_secret=self._settings.mercadopago_webhook_secret,
            )
        return ManualProvider(await self.get_pix_manual_settings(guild_id))

    # --- config PIX manual --------------------------------------------------

    async def get_pix_manual_settings(self, guild_id: int) -> PixManualSettings:
        async with self._database.session() as session:
            return await PixManualSettingsRepository(session).get_or_create(guild_id)

    async def update_pix_manual_settings(self, guild_id: int, **fields: object) -> PixManualSettings:
        async with self._database.session() as session:
            repo = PixManualSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                # expiration_minutes vem da CHOICE do painel como string
                # ("60") — a coluna e Integer (usada direto em timedelta()
                # no ManualProvider), entao converte antes de gravar.
                if key == "expiration_minutes" and isinstance(value, str):
                    value = int(value)
                setattr(settings, key, value)
            # ultima linha de defesa: a UI (views/pix_manual_panel_view.py) ja
            # valida antes de chamar isto, mas revalida aqui tambem — este e
            # o UNICO ponto de escrita de PixManualSettings, entao qualquer
            # chamador futuro (script, outra view, comando) tambem fica
            # protegido contra salvar uma chave PIX mal formada/incompativel
            # com o tipo. Sempre persiste a chave NORMALIZADA, nunca o texto
            # bruto que foi digitado.
            if ("pix_key" in fields or "pix_key_type" in fields) and settings.pix_key:
                settings.pix_key = validate_pix_key(settings.pix_key_type, settings.pix_key)
            await session.flush()
            await session.refresh(settings)
            return settings

    # --- cobranca ---------------------------------------------------------

    async def charge(
        self,
        request: ChargeRequest,
        provider: PaymentProvider,
        *,
        payer_information: str | None = None,
    ) -> tuple[ChargeResult, PaymentHistory]:
        result = await provider.create_payment(request)
        async with self._database.session() as session:
            repo = PaymentRepository(session)
            existing = await repo.get_by_provider_external_id(provider.name, result.external_id)
            if existing is not None:
                return result, existing
            payment = await repo.add(
                PaymentHistory(
                    guild_id=request.guild_id,
                    user_id=request.user_id,
                    plan_id=uuid.UUID(request.plan_id),
                    provider=provider.name,
                    external_id=result.external_id,
                    amount=request.amount,
                    currency=request.currency,
                    status=result.status,
                    expires_at=result.expires_at,
                    pix_qr_code=result.qr_code,
                    pix_qr_code_base64=result.qr_code_base64,
                    checkout_url=result.checkout_url,
                    payer_information=payer_information,
                )
            )
            await PaymentStatusHistoryRepository(session).add(
                PaymentStatusHistory(
                    payment_id=payment.id,
                    previous_status=None,
                    new_status=payment.status,
                    provider_payload=dict(result.raw),
                )
            )
        return result, payment

    async def get(self, payment_id: uuid.UUID) -> PaymentHistory | None:
        async with self._database.session() as session:
            return await PaymentRepository(session).get_by_id(payment_id)

    async def get_by_provider_external_id(self, provider: str, external_id: str) -> PaymentHistory | None:
        async with self._database.session() as session:
            return await PaymentRepository(session).get_by_provider_external_id(provider, external_id)

    async def list_pending_expired(self, *, before: object) -> list[PaymentHistory]:
        async with self._database.session() as session:
            return await PaymentRepository(session).list_pending_expired(before=before)

    async def link_subscription(self, payment_id: uuid.UUID, subscription_id: uuid.UUID) -> None:
        async with self._database.session() as session:
            repo = PaymentRepository(session)
            payment = await repo.get_by_id(payment_id)
            if payment is not None:
                payment.subscription_id = subscription_id
                await session.flush()

    async def set_status(
        self,
        payment_id: uuid.UUID,
        status: PaymentStatus,
        *,
        paid_at: object = None,
        provider_payload: dict[str, object] | None = None,
        expected_statuses: tuple[PaymentStatus, ...] | None = None,
    ) -> PaymentHistory | None:
        """expected_statuses, se informado, restringe a transicao a partir
        desses status — a linha e travada (FOR UPDATE) antes da checagem, entao
        duas chamadas concorrentes (dois cliques de staff, webhook + clique
        manual) nunca conseguem transicionar a mesma linha duas vezes: a
        segunda encontra o status ja alterado e recebe None."""
        async with self._database.session() as session:
            repo = PaymentRepository(session)
            payment = await repo.get_by_id_locked(payment_id)
            if payment is None:
                return None
            if expected_statuses is not None and payment.status not in expected_statuses:
                return None
            previous_status = payment.status
            payment.status = status
            if paid_at is not None:
                payment.paid_at = paid_at
            await session.flush()
            await session.refresh(payment)
            if previous_status != status:
                await PaymentStatusHistoryRepository(session).add(
                    PaymentStatusHistory(
                        payment_id=payment.id,
                        previous_status=previous_status,
                        new_status=status,
                        provider_payload=provider_payload or {},
                    )
                )
            return payment

    async def cancel(self, external_id: str, provider: PaymentProvider) -> None:
        await provider.cancel_payment(external_id)

    # --- config DM ao comprador (aprovacao/rejeicao) ------------------------

    async def get_payment_dm_settings(self, guild_id: int) -> PaymentDmSettings:
        async with self._database.session() as session:
            return await PaymentDmSettingsRepository(session).get_or_create(guild_id)

    async def update_payment_dm_settings(self, guild_id: int, **fields: object) -> PaymentDmSettings:
        async with self._database.session() as session:
            repo = PaymentDmSettingsRepository(session)
            settings = await repo.get_or_create(guild_id)
            for key, value in fields.items():
                setattr(settings, key, value)
            await session.flush()
            await session.refresh(settings)
            return settings
