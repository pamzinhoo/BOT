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

    async def get_by_id_locked(self, license_id: uuid.UUID) -> License | None:
        """Mesmo que get_by_id, mas com SELECT ... FOR UPDATE — trava a linha
        ate o fim da transacao, mesmo padrao de PaymentRepository.get_by_id_locked,
        pra evitar duas concessoes/revogacoes concorrentes (ex.: webhook +
        scheduler) baterem na mesma License ao mesmo tempo."""
        result = await self.session.execute(select(License).where(License.id == license_id).with_for_update())
        return result.scalar_one_or_none()

    async def get_by_player_product(self, player_id: uuid.UUID, product_id: uuid.UUID) -> License | None:
        """Independente de status — usada pra reaproveitar a linha (unica por
        player+product, uq_licenses_player_product) numa recompra apos
        revogacao/expiracao, em vez de tentar inserir outra."""
        result = await self.session.execute(
            select(License).where(License.player_id == player_id, License.product_id == product_id)
        )
        return result.scalar_one_or_none()

    async def list_by_player(self, player_id: uuid.UUID) -> list[License]:
        """Todas as licencas do player, qualquer status — base do inventario
        completo em /player/licenses (o launcher mostra revogada/expirada
        tambem, nao so ativa)."""
        result = await self.session.execute(
            select(License).where(License.player_id == player_id).order_by(License.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_active_by_player(self, player_id: uuid.UUID) -> list[License]:
        result = await self.session.execute(
            select(License).where(License.player_id == player_id, License.status == LicenseStatus.ACTIVE)
        )
        return list(result.scalars().all())

    async def has_active_license(self, player_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        license_row = await self.get_by_player_product(player_id, product_id)
        return license_row is not None and license_row.status == LicenseStatus.ACTIVE

    async def list_active_by_product(self, product_id: uuid.UUID) -> list[License]:
        """Base da reconciliacao (direcao 'tem License mas falta cargo') —
        todo player com posse ativa de um Product, cross-player de
        proposito."""
        result = await self.session.execute(
            select(License).where(License.product_id == product_id, License.status == LicenseStatus.ACTIVE)
        )
        return list(result.scalars().all())

    async def list_active_by_players_and_product(
        self, player_ids: list[uuid.UUID], product_id: uuid.UUID
    ) -> list[License]:
        """Batch de has_active_license — evita N+1 quando o chamador precisa
        checar varios players de uma vez pro mesmo product (ex.:
        ReconciliationService checando todo membro com um cargo)."""
        if not player_ids:
            return []
        result = await self.session.execute(
            select(License).where(
                License.player_id.in_(player_ids),
                License.product_id == product_id,
                License.status == LicenseStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

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
