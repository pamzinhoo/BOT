from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.license import License, LicenseStatus
from database.models.license_event import LicenseEvent
from database.repositories.base_repository import BaseRepository


class LicenseRepository(BaseRepository[License]):
    model = License

    async def get_by_external_reference(self, external_reference: str) -> License | None:
        result = await self.session.execute(
            select(License).where(License.external_reference == external_reference)
        )
        return result.scalar_one_or_none()

    async def get_by_player_product(self, player_id: uuid.UUID, product_id: uuid.UUID) -> License | None:
        """Independente de status — usada pra reaproveitar a linha (unica por
        player+product, uq_licenses_player_product) numa recompra apos
        revogacao/expiracao, em vez de tentar inserir outra."""
        result = await self.session.execute(
            select(License).where(License.player_id == player_id, License.product_id == product_id)
        )
        return result.scalar_one_or_none()

    async def list_active_by_player(self, player_id: uuid.UUID) -> list[License]:
        result = await self.session.execute(
            select(License).where(License.player_id == player_id, License.status == LicenseStatus.ACTIVE)
        )
        return list(result.scalars().all())

    async def has_active_license(self, player_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        license_row = await self.get_by_player_product(player_id, product_id)
        return license_row is not None and license_row.status == LicenseStatus.ACTIVE

    async def list_expiring_active(self, *, before: object) -> list[License]:
        result = await self.session.execute(
            select(License).where(
                License.status == LicenseStatus.ACTIVE,
                License.expires_at.is_not(None),
                License.expires_at <= before,
            )
        )
        return list(result.scalars().all())


class LicenseEventRepository(BaseRepository[LicenseEvent]):
    model = LicenseEvent

    async def list_by_license(self, license_id: uuid.UUID) -> list[LicenseEvent]:
        result = await self.session.execute(
            select(LicenseEvent)
            .where(LicenseEvent.license_id == license_id)
            .order_by(LicenseEvent.occurred_at.desc())
        )
        return list(result.scalars().all())
