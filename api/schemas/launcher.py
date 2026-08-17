from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class NewsItemResponse(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    cover_image_url: str | None
    published_at: str | None


class LauncherVersionResponse(BaseModel):
    platform: str
    version: str
    sha256: str
    size_bytes: int
    is_mandatory: bool
    release_notes: str | None


class ManifestResponse(BaseModel):
    product_id: uuid.UUID
    entry_type: str
    version: str
    sha256: str
    size_bytes: int
    depends_on: list[str]
    release_notes: str | None


class LicenseResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_slug: str | None
    product_name: str | None
    status: str
    purchase_source: str
    activated_at: str | None
    expires_at: str | None
    auto_renew: bool
    revoked_at: str | None
    revoked_reason: str | None


class ProductCatalogItemResponse(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    product_type: str
    description: str | None
    price_amount: int | None
    currency: str
    owned: bool
    license_status: str | None


class DlcCatalogItemResponse(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    access_type: str  # "free" | "paid" — free checa cargo (via License
    # source=role_grant), paid checa License concedida por pagamento; ver
    # services/dlc_service.py
    price_amount: int | None
    currency: str
    unlocked: bool
    license_status: str | None


class DlcPurchaseResponse(BaseModel):
    payment_id: uuid.UUID
    status: str
    checkout_url: str | None
    qr_code: str | None
    qr_code_base64: str | None
    expires_at: str | None


class DownloadRequest(BaseModel):
    product_id: uuid.UUID
    entry_type: str = Field(default="full")
    device_uuid: uuid.UUID | None = None


class DownloadResponse(BaseModel):
    download_id: uuid.UUID
    url: str
    version: str
    sha256: str
    size_bytes: int
    entry_type: str
    expires_at: str


class DownloadCompleteRequest(BaseModel):
    client_sha256: str = Field(min_length=64, max_length=64)
    bytes_transferred: int | None = None


class DownloadCompleteResponse(BaseModel):
    download_id: uuid.UUID
    status: str
    failure_reason: str | None


class UpdateRequest(BaseModel):
    platform: str


class UpdateResponse(BaseModel):
    url: str
    version: str
    sha256: str
    size_bytes: int
    is_mandatory: bool
    release_notes: str | None
    expires_at: str
