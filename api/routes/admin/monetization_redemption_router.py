from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, field_validator

from api.routes.admin.security import require_local_admin
from services.redemption_service import RedemptionError


def _require_local_host(request: Request) -> None:
    if urlsplit(str(request.url)).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "ORIGIN_DENIED", "message": "Origem não permitida."}},
        )


router = APIRouter(
    prefix="/admin/api/guild/{guild_id}/monetization/redemption-codes",
    tags=["admin-monetization-redemption"],
    dependencies=[Depends(require_local_admin), Depends(_require_local_host)],
)


class CodeMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = None
    reward_type: str | None = None
    role_id: int | None = None
    role_duration_seconds: int | None = None
    message: str | None = None
    delivery: str | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    max_uses: int | None = None
    active: bool | None = None
    temporary_role_ack: bool | None = None

    @field_validator("role_id", "role_duration_seconds", "max_uses", mode="before")
    @classmethod
    def reject_boolean_number(cls, value):
        if isinstance(value, bool):
            raise ValueError("Use um número inteiro positivo.")
        return value


def _context(request: Request, guild_id: int):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "GUILD_NOT_FOUND", "message": "Servidor não encontrado."}},
        )
    return bot.redemption_service, guild


def _invalid(error: RedemptionError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"error": {"code": "INVALID_REDEMPTION_CODE", "message": str(error)}},
    )


def _require_write_origin(request: Request) -> None:
    expected = urlsplit(str(request.url))
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if (parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc):
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "ORIGIN_DENIED", "message": "Origem não permitida."}},
            )
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "ORIGIN_DENIED", "message": "Origem não permitida."}},
        )
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(
            status_code=415, detail={"error": {"code": "JSON_REQUIRED", "message": "Envie JSON."}}
        )


@router.get("")
async def list_codes(request: Request, guild_id: int) -> dict:
    service, _ = _context(request, guild_id)
    return {"guild_id": str(guild_id), "items": await service.list_codes(guild_id)}


@router.post("", dependencies=[Depends(_require_write_origin)])
async def create_code(request: Request, guild_id: int, payload: CodeMutation) -> dict:
    service, _ = _context(request, guild_id)
    fields = payload.model_dump(exclude_unset=True)
    try:
        item = await service.create_code(guild_id, **fields)
    except RedemptionError as error:
        raise _invalid(error) from error
    return {"item": item}


@router.patch("/{code_id}", dependencies=[Depends(_require_write_origin)])
async def update_code(
    request: Request, guild_id: int, code_id: UUID, payload: CodeMutation
) -> dict:
    service, _ = _context(request, guild_id)
    fields = payload.model_dump(exclude_unset=True)
    if "code" in fields:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {"code": "IMMUTABLE_CODE", "message": "Código não pode ser alterado."}
            },
        )
    try:
        item = await service.update_code(guild_id, code_id, **fields)
    except RedemptionError as error:
        raise _invalid(error) from error
    return {"item": item}


@router.post("/{code_id}/toggle", dependencies=[Depends(_require_write_origin)])
async def toggle_code(
    request: Request, guild_id: int, code_id: UUID, payload: CodeMutation
) -> dict:
    if payload.active is None:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "INVALID_REDEMPTION_CODE", "message": "Informe active."}},
        )
    service, _ = _context(request, guild_id)
    try:
        item = await service.update_code(guild_id, code_id, active=payload.active)
    except RedemptionError as error:
        raise _invalid(error) from error
    return {"item": item}


@router.get("/{code_id}/history")
async def code_history(request: Request, guild_id: int, code_id: UUID) -> dict:
    service, _ = _context(request, guild_id)
    try:
        return {"items": await service.history(guild_id, code_id, limit=50)}
    except RedemptionError as error:
        raise _invalid(error) from error
