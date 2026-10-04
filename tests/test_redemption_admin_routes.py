from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.admin.monetization_redemption_router import router
from api.routes.admin.security import require_local_admin
from services.redemption_service import RedemptionError


class FakeService:
    def __init__(self):
        self.items = []

    async def list_codes(self, guild_id):
        return self.items

    async def create_code(self, guild_id, **fields):
        if fields.get("message") == "erro":
            raise RedemptionError("Mensagem inválida.")
        item = {"id": str(uuid4()), "guild_id": str(guild_id), **fields}
        self.items.append(item)
        return item

    async def update_code(self, guild_id, code_id: UUID, **fields):
        item = next(item for item in self.items if item["id"] == str(code_id))
        item.update(fields)
        return item

    async def history(self, guild_id, code_id: UUID, limit=50):
        return [{"user_id": "123", "status": "delivered"}]


def client():
    guild = object()
    service = FakeService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_admin] = lambda: None
    app.state.bot = SimpleNamespace(
        redemption_service=service, get_guild=lambda guild_id: guild if guild_id == 1 else None
    )
    return TestClient(app, base_url="http://127.0.0.1"), service, guild


def test_write_requires_same_origin_json():
    http, service, _ = client()
    path = "/admin/api/guild/1/monetization/redemption-codes"
    assert (
        http.post(
            path, json={"message": "ok"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        http.post(
            path, json={"message": "ok"}, headers={"Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 403
    )
    assert http.post(path, content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert http.get(path, headers={"Host": "evil.example"}).status_code == 403
    assert http.get("/admin/api/guild/2/monetization/redemption-codes").status_code == 404
    assert service.items == []


def test_role_id_preserved_and_history_available():
    http, service, _ = client()
    path = "/admin/api/guild/1/monetization/redemption-codes"
    role_id = "1234567890123456789"
    created = http.post(
        path,
        json={
            "reward_type": "role",
            "role_id": role_id,
            "role_duration_seconds": 3600,
            "temporary_role_ack": True,
            "message": "Prêmio",
            "delivery": "dm",
        },
    )
    assert created.status_code == 200
    assert service.items[0]["role_id"] == int(role_id)
    code_id = created.json()["item"]["id"]
    assert http.patch(f"{path}/{code_id}", json={"code": "AB12CD34"}).status_code == 422
    assert (
        http.post(f"{path}/{code_id}/toggle", json={"active": False}).json()["item"]["active"]
        is False
    )
    assert http.get(f"{path}/{code_id}/history").json()["items"][0]["user_id"] == "123"


def test_invalid_payload_and_service_errors():
    http, service, _ = client()
    path = "/admin/api/guild/1/monetization/redemption-codes"
    assert http.post(path, json={"unknown": "value"}).status_code == 422
    assert http.post(path, json={"max_uses": True}).status_code == 422
    assert http.post(path, json={"role_duration_seconds": True}).status_code == 422
    response = http.post(path, json={"message": "erro"})
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["message"] == "Mensagem inválida."
    assert http.patch(f"{path}/invalid", json={"active": False}).status_code == 422
    assert http.post(f"{path}/{uuid4()}/toggle", json={}).status_code == 422
    assert service.items == []
