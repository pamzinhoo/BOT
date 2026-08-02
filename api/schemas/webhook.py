from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MercadoPagoWebhookPayload(BaseModel):
    """Schema tolerante — o payload do Mercado Pago varia por tipo de evento
    (payment/subscription_preapproval/...), so os campos abaixo sao usados."""

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    action: str | None = None
    data: dict[str, object] | None = None
