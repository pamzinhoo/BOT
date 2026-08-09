from __future__ import annotations

import uuid

from database.database import Database
from database.models.game_manifest import GameManifestEntry, ManifestEntryType
from database.models.launcher_news import LauncherNews
from database.models.launcher_version import LauncherPlatform, LauncherVersion
from database.repositories.game_manifest_repository import GameManifestRepository
from database.repositories.launcher_news_repository import LauncherNewsRepository
from database.repositories.launcher_version_repository import LauncherVersionRepository


class LauncherContentService:
    """Leitura de conteudo estatico do Launcher: novidades, versao atual do
    proprio binario (por plataforma) e manifest de conteudo (base game/DLC).
    Sem regra de negocio de posse aqui — quem decide se o player PODE baixar
    o que o manifest descreve e o DownloadService (License ACTIVE)."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_news(self, *, limit: int = 20) -> list[LauncherNews]:
        async with self._database.session() as session:
            return await LauncherNewsRepository(session).list_published(limit=limit)

    async def get_launcher_version(self, platform: LauncherPlatform) -> LauncherVersion | None:
        async with self._database.session() as session:
            return await LauncherVersionRepository(session).get_current(platform)

    async def get_manifest(
        self, product_id: uuid.UUID, *, entry_type: ManifestEntryType = ManifestEntryType.FULL
    ) -> GameManifestEntry | None:
        async with self._database.session() as session:
            return await GameManifestRepository(session).get_current(product_id, entry_type=entry_type)
