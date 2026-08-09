from __future__ import annotations

import uuid
from datetime import UTC, datetime

from core.event_bus import EventBus
from core.events import (
    LICENSE_CREATED,
    LICENSE_EXPIRED,
    LICENSE_REACTIVATED,
    LICENSE_RENEWED,
    LICENSE_REVOKED,
    LicenseEventPayload,
)
from database.database import Database
from database.models.license import License, LicenseStatus
from database.models.license_event import LicenseEvent, LicenseEventType
from database.repositories.license_repository import LicenseEventRepository, LicenseRepository

_EVENT_NAME_BY_TYPE: dict[LicenseEventType, str] = {
    LicenseEventType.CREATED: LICENSE_CREATED,
    LicenseEventType.RENEWED: LICENSE_RENEWED,
    LicenseEventType.REVOKED: LICENSE_REVOKED,
    LicenseEventType.EXPIRED: LICENSE_EXPIRED,
    LicenseEventType.REACTIVATED: LICENSE_REACTIVATED,
}


class LicenseService:
    """Orquestra o ciclo de vida de License — concessao/renovacao/revogacao
    da posse de um Product por um Player. `LicenseService` e a UNICA fonte de
    verdade sobre posse (Fase 5: "o bot nao sera mais fonte oficial de
    beneficios, so refletira o estado do backend") — toda mudanca de status
    publica um evento no `event_bus` (se configurado) depois do commit, e
    quem reage a isso do lado Discord e RoleSyncService (services/
    role_sync_service.py), nunca este servico diretamente. `event_bus=None`
    (default) mantem o servico 100% utilizavel isolado (testes, scripts de
    staff) sem exigir um bot montado.

    Toda mudanca de status tambem escreve em LicenseEvent (equivalente a
    SubscriptionHistory) — essa e a auditoria do dominio de licenciamento,
    nao AuditLogEntry (guild-scoped) nem AuditLogLauncher (auth do Launcher).
    """

    def __init__(self, database: Database, event_bus: EventBus | None = None) -> None:
        self._database = database
        self._event_bus = event_bus

    async def _publish(self, license_row: License, event_type: LicenseEventType) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            _EVENT_NAME_BY_TYPE[event_type],
            LicenseEventPayload(
                license_id=license_row.id,
                player_id=license_row.player_id,
                product_id=license_row.product_id,
                status=license_row.status.value,
                event_type=_EVENT_NAME_BY_TYPE[event_type],
                occurred_at=license_row.updated_at,
            ),
        )

    # --- concessao/renovacao -------------------------------------------------

    async def grant_or_renew(
        self,
        player_id: uuid.UUID,
        product_id: uuid.UUID,
        *,
        purchase_source: str,
        external_reference: str | None = None,
        expires_at: datetime | None = None,
        auto_renew: bool = False,
        granted_by_staff_id: int | None = None,
        note: str | None = None,
    ) -> License:
        """Idempotente por design: License e unica por (player_id, product_id)
        (uq_licenses_player_product), entao uma recompra/renovacao sempre
        reaproveita a mesma linha em vez de tentar inserir outra. Se a linha
        ja estava ACTIVE isso e uma renovacao (evento RENEWED); se estava
        REVOKED/EXPIRED/PENDING isso e uma reativacao (evento REACTIVATED);
        se nao existia ainda, cria (evento CREATED)."""
        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = LicenseRepository(session)
            existing = await repo.get_by_player_product(player_id, product_id)

            if existing is None:
                license_row = await repo.add(
                    License(
                        player_id=player_id,
                        product_id=product_id,
                        status=LicenseStatus.ACTIVE,
                        purchase_source=purchase_source,
                        external_reference=external_reference,
                        activated_at=now,
                        expires_at=expires_at,
                        auto_renew=auto_renew,
                        granted_by_staff_id=granted_by_staff_id,
                    )
                )
                event_type = LicenseEventType.CREATED
            else:
                license_row = await repo.get_by_id_locked(existing.id)
                if license_row is None:
                    raise RuntimeError("License desapareceu entre a leitura e o lock.")
                event_type = (
                    LicenseEventType.RENEWED
                    if license_row.status == LicenseStatus.ACTIVE
                    else LicenseEventType.REACTIVATED
                )
                if license_row.status != LicenseStatus.ACTIVE:
                    license_row.activated_at = now
                    license_row.revoked_at = None
                    license_row.revoked_reason = None
                license_row.status = LicenseStatus.ACTIVE
                license_row.purchase_source = purchase_source
                license_row.external_reference = external_reference
                license_row.expires_at = expires_at
                license_row.auto_renew = auto_renew
                if granted_by_staff_id is not None:
                    license_row.granted_by_staff_id = granted_by_staff_id
                await session.flush()
                await session.refresh(license_row)

            await LicenseEventRepository(session).add(
                LicenseEvent(
                    license_id=license_row.id,
                    event_type=event_type,
                    note=note,
                    event_metadata={"purchase_source": purchase_source},
                    occurred_at=now,
                )
            )
        await self._publish(license_row, event_type)
        return license_row

    # --- revogacao/expiracao -------------------------------------------------

    async def revoke(
        self, license_id: uuid.UUID, *, reason: str, executor_id: int | None = None
    ) -> License | None:
        """Idempotente: so age sobre License ACTIVE. Chamado de volta ACTIVE
        (recompra/reconcessao) passa por grant_or_renew, nunca por aqui."""
        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = LicenseRepository(session)
            license_row = await repo.get_by_id_locked(license_id)
            if license_row is None or license_row.status != LicenseStatus.ACTIVE:
                return license_row
            license_row.status = LicenseStatus.REVOKED
            license_row.revoked_at = now
            license_row.revoked_reason = reason
            await session.flush()
            await session.refresh(license_row)
            await LicenseEventRepository(session).add(
                LicenseEvent(
                    license_id=license_row.id,
                    event_type=LicenseEventType.REVOKED,
                    note=reason,
                    event_metadata={"executor_id": executor_id} if executor_id is not None else {},
                    occurred_at=now,
                )
            )
        await self._publish(license_row, LicenseEventType.REVOKED)
        return license_row

    async def revoke_by_player_product(
        self,
        player_id: uuid.UUID,
        product_id: uuid.UUID,
        *,
        reason: str,
        executor_id: int | None = None,
    ) -> License | None:
        """Conveniencia pra chamadores (ex.: SubscriptionService) que sabem
        player+product mas nao o id da License. Retorna None se nunca existiu
        License pra esse par — nada a revogar."""
        async with self._database.session() as session:
            existing = await LicenseRepository(session).get_by_player_product(player_id, product_id)
        if existing is None:
            return None
        return await self.revoke(existing.id, reason=reason, executor_id=executor_id)

    async def expire_license(self, license_id: uuid.UUID) -> License | None:
        """Fim natural de periodo (distinto de revoke, que e administrativo/
        cancelamento) — idempotente, so age sobre License ACTIVE."""
        now = datetime.now(UTC)
        async with self._database.session() as session:
            repo = LicenseRepository(session)
            license_row = await repo.get_by_id_locked(license_id)
            if license_row is None or license_row.status != LicenseStatus.ACTIVE:
                return license_row
            license_row.status = LicenseStatus.EXPIRED
            await session.flush()
            await session.refresh(license_row)
            await LicenseEventRepository(session).add(
                LicenseEvent(
                    license_id=license_row.id,
                    event_type=LicenseEventType.EXPIRED,
                    occurred_at=now,
                )
            )
        await self._publish(license_row, LicenseEventType.EXPIRED)
        return license_row

    # --- consulta --------------------------------------------------------

    async def get(self, license_id: uuid.UUID) -> License | None:
        async with self._database.session() as session:
            return await LicenseRepository(session).get_by_id(license_id)

    async def get_by_player_product(self, player_id: uuid.UUID, product_id: uuid.UUID) -> License | None:
        async with self._database.session() as session:
            return await LicenseRepository(session).get_by_player_product(player_id, product_id)

    async def list_active_by_player(self, player_id: uuid.UUID) -> list[License]:
        async with self._database.session() as session:
            return await LicenseRepository(session).list_active_by_player(player_id)

    async def list_by_player(self, player_id: uuid.UUID) -> list[License]:
        async with self._database.session() as session:
            return await LicenseRepository(session).list_by_player(player_id)

    async def has_active_license(self, player_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        async with self._database.session() as session:
            return await LicenseRepository(session).has_active_license(player_id, product_id)

    async def list_active_by_product(self, product_id: uuid.UUID) -> list[License]:
        async with self._database.session() as session:
            return await LicenseRepository(session).list_active_by_product(product_id)
