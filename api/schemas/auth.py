from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class DeviceCodeRequest(BaseModel):
    device_uuid: uuid.UUID
    os_info: str | None = Field(default=None, max_length=200)
    launcher_version: str | None = Field(default=None, max_length=32)


class DeviceCodeResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class DeviceTokenRequest(BaseModel):
    device_code: str


class DeviceTokenResponse(BaseModel):
    status: str
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None
    interval: int | None = None


class RefreshRequest(BaseModel):
    refresh_token: str
    device_uuid: uuid.UUID


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class LogoutRequest(BaseModel):
    refresh_token: str


class LogoutAllResponse(BaseModel):
    sessions_revoked: int


class PlayerResponse(BaseModel):
    id: uuid.UUID
    discord_id: int
    discord_username: str | None
    linked_at: str
    last_login_at: str | None


class ErrorResponse(BaseModel):
    error: str
    message: str
