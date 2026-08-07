from __future__ import annotations

import uuid

from sqlalchemy import select

from database.models.device import Device
from database.repositories.base_repository import BaseRepository


class DeviceRepository(BaseRepository[Device]):
    model = Device

    async def get_by_player_and_uuid(self, player_id: uuid.UUID, device_uuid: uuid.UUID) -> Device | None:
        result = await self.session.execute(
            select(Device).where(Device.player_id == player_id, Device.device_uuid == device_uuid)
        )
        return result.scalar_one_or_none()

    async def list_active_by_player(self, player_id: uuid.UUID) -> list[Device]:
        result = await self.session.execute(
            select(Device).where(Device.player_id == player_id, Device.revoked.is_(False))
        )
        return list(result.scalars().all())
