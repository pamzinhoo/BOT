from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from database.models.payment import PaymentStatus
from database.models.subscription import BillingCycle


class PaymentGatewayError(RuntimeError):
    """Erro de comunicacao com um gateway real (rede, HTTP, resposta invalida).
    Nunca deve carregar token/segredo na mensagem — so status code/id do pagamento."""


@dataclass(frozen=True)
class ChargeRequest:
    """Pedido de cobranca independente de gateway. `external_reference` e
    gerada pelo SubscriptionService antes de chamar o provider — e a chave de
    idempotencia usada tanto pra criar a assinatura quanto pra casar o
    webhook/confirmacao de volta com o pedido certo."""

    guild_id: int
    user_id: int
    plan_id: str
    plan_name: str
    amount: int  # centavos
    currency: str
    billing_cycle: BillingCycle
    external_reference: str
    expires_in_minutes: int | None = None


@dataclass(frozen=True)
class ChargeResult:
    """Resposta de um provider a uma ChargeRequest. `checkout_url` fica None
    quando o provider nao tem checkout externo (ex.: ManualProvider, onde a
    confirmacao e feita por um staff dentro do proprio Discord). `qr_code`/
    `qr_code_base64` sao preenchidos por gateways que suportam PIX."""

    external_id: str
    status: PaymentStatus
    checkout_url: str | None = None
    qr_code: str | None = None
    qr_code_base64: str | None = None
    expires_at: datetime | None = None
    raw: dict[str, object] = field(default_factory=dict)


class PaymentProvider(ABC):
    """Camada de abstracao de gateway de pagamento. Nenhuma regra de negocio
    (entrega de cargo, assinatura, mensagens) vive aqui — providers so criam/
    consultam cobrancas. Novos gateways (MercadoPagoProvider, StripeProvider,
    AsaasProvider, PaypalProvider, ...) implementam esta interface sem exigir
    mudanca em services/cogs/views."""

    name: str

    @abstractmethod
    async def create_payment(self, request: ChargeRequest) -> ChargeResult: ...

    @abstractmethod
    async def cancel_payment(self, external_id: str) -> None: ...

    @abstractmethod
    async def get_payment(self, external_id: str) -> ChargeResult: ...

    @abstractmethod
    async def create_subscription(self, request: ChargeRequest) -> ChargeResult: ...

    @abstractmethod
    async def cancel_subscription(self, external_id: str) -> None: ...

    @abstractmethod
    async def validate_webhook(self, headers: dict[str, str], raw_body: bytes, secret: str | None) -> bool: ...
