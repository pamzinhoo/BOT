from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from config.settings import Settings
from database.database import Database
from database.models.download import Download, DownloadStatus
from database.models.game_manifest import ManifestEntryType
from database.models.launcher_version import LauncherPlatform, LauncherVersion
from database.models.player import Player
from database.repositories.download_repository import DownloadRepository
from database.repositories.game_manifest_repository import GameManifestRepository
from database.repositories.launcher_version_repository import LauncherVersionRepository
from providers.storage.base import StorageError, StorageProvider
from services.license_service import LicenseService


class DownloadError(Exception):
    """Erro de negocio do fluxo de download/atualizacao — sempre carrega um
    `code` estavel pra API mapear pro status HTTP certo (ver api/routes/
    download_routes.py), igual ao padrao de AuthError."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DownloadAuthorization:
    download_id: uuid.UUID
    url: str
    version: str
    sha256: str
    size_bytes: int
    entry_type: ManifestEntryType
    expires_at: datetime


@dataclass(frozen=True)
class UpdateAuthorization:
    url: str
    version: str
    sha256: str
    size_bytes: int
    is_mandatory: bool
    release_notes: str | None
    expires_at: datetime


class DownloadService:
    """Autoriza download de conteudo de Product (base game/DLC/etc, via
    manifest) e do proprio binario do Launcher (via LauncherVersion). Nunca
    serve bytes — so confere posse (License ACTIVE) e assina uma URL de
    curta duracao contra o StorageProvider configurado (R2/S3/B2).

    Autorizacao de conteudo (product) e sempre checada de novo aqui, mesmo
    que o Launcher ja tenha consultado /launcher/manifest antes — nunca
    reaproveita uma checagem anterior, pra minimizar a janela entre "podia" e
    "ainda pode" (ver docs/LIMERENCE_LAUNCHER_ARCHITECTURE.md secao 6)."""

    def __init__(
        self,
        database: Database,
        license_service: LicenseService,
        storage_provider: StorageProvider | None,
        settings: Settings,
    ) -> None:
        self._database = database
        self._licenses = license_service
        self._storage = storage_provider
        self._settings = settings

    def _require_storage(self) -> StorageProvider:
        if self._storage is None:
            raise DownloadError(
                "storage_not_configured",
                "Storage (R2/S3/B2) nao configurado neste backend — defina STORAGE_* no ambiente.",
            )
        return self._storage

    # --- conteudo de Product (base game/DLC/skin/wallpaper/soundtrack/...) --

    async def authorize_download(
        self,
        player: Player,
        product_id: uuid.UUID,
        *,
        entry_type: ManifestEntryType = ManifestEntryType.FULL,
        device_id: uuid.UUID | None = None,
        ip_address: str | None = None,
    ) -> DownloadAuthorization:
        storage = self._require_storage()

        has_license = await self._licenses.has_active_license(player.id, product_id)
        if not has_license:
            raise DownloadError(
                "license_required", "Nenhuma licenca ativa para este produto."
            )

        async with self._database.session() as session:
            entry = await GameManifestRepository(session).get_current(product_id, entry_type=entry_type)
        if entry is None:
            raise DownloadError("manifest_not_found", "Nenhuma versao publicada para este produto.")

        try:
            url = storage.generate_download_url(
                entry.storage_path,
                expires_in_seconds=self._settings.storage_download_ttl_seconds,
                filename=f"{entry.product_id}-{entry.version}.pkg",
            )
        except StorageError as exc:
            raise DownloadError("storage_error", str(exc)) from exc

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._settings.storage_download_ttl_seconds)
        async with self._database.session() as session:
            download = await DownloadRepository(session).add(
                Download(
                    player_id=player.id,
                    device_id=device_id,
                    product_id=product_id,
                    manifest_entry_id=entry.id,
                    status=DownloadStatus.AUTHORIZED,
                    signed_url_issued_at=now,
                    signed_url_expires_at=expires_at,
                    ip_address=ip_address,
                )
            )

        return DownloadAuthorization(
            download_id=download.id,
            url=url,
            version=entry.version,
            sha256=entry.sha256,
            size_bytes=entry.size_bytes,
            entry_type=entry.entry_type,
            expires_at=expires_at,
        )

    async def complete_download(
        self,
        download_id: uuid.UUID,
        player: Player,
        *,
        client_sha256: str,
        bytes_transferred: int | None = None,
    ) -> Download:
        """Idempotente: reportar conclusao de um download ja finalizado (
        COMPLETED/FAILED) so retorna o registro, sem sobrescrever o veredito
        original. Verifica o checksum reportado pelo Launcher contra o
        `sha256` do manifest que autorizou o download — divergencia marca
        FAILED (arquivo corrompido/incompleto), nunca COMPLETED."""
        async with self._database.session() as session:
            repo = DownloadRepository(session)
            download = await repo.get_by_id_locked(download_id)
            if download is None or download.player_id != player.id:
                raise DownloadError("download_not_found", "Download nao encontrado.")
            if download.status != DownloadStatus.AUTHORIZED:
                return download

            manifest_entry = None
            if download.manifest_entry_id is not None:
                manifest_entry = await GameManifestRepository(session).get_by_id(download.manifest_entry_id)
            expected_sha256 = manifest_entry.sha256 if manifest_entry is not None else None

            download.client_sha256 = client_sha256
            download.bytes_transferred = bytes_transferred
            download.completed_at = datetime.now(UTC)
            if expected_sha256 is not None and client_sha256.lower() != expected_sha256.lower():
                download.status = DownloadStatus.FAILED
                download.failure_reason = "checksum_mismatch"
            else:
                download.status = DownloadStatus.COMPLETED
            await session.flush()
            await session.refresh(download)
            return download

    # --- binario do proprio Launcher (auto-atualizacao) ----------------

    async def authorize_launcher_update(self, platform: LauncherPlatform) -> UpdateAuthorization:
        """Sem checagem de License — o binario do Launcher nao e um Product
        vendavel, precisa estar acessivel antes mesmo de logar."""
        storage = self._require_storage()

        async with self._database.session() as session:
            version: LauncherVersion | None = await LauncherVersionRepository(session).get_current(platform)
        if version is None:
            raise DownloadError("version_not_found", "Nenhuma versao publicada para esta plataforma.")

        try:
            url = storage.generate_download_url(
                version.storage_path,
                expires_in_seconds=self._settings.storage_download_ttl_seconds,
                filename=f"limerence-launcher-{version.version}-{platform.value}.pkg",
            )
        except StorageError as exc:
            raise DownloadError("storage_error", str(exc)) from exc

        expires_at = datetime.now(UTC) + timedelta(seconds=self._settings.storage_download_ttl_seconds)
        return UpdateAuthorization(
            url=url,
            version=version.version,
            sha256=version.sha256,
            size_bytes=version.size_bytes,
            is_mandatory=version.is_mandatory,
            release_notes=version.release_notes,
            expires_at=expires_at,
        )
