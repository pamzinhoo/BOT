from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import aiohttp

from core.logger import get_logger
from database.models.payment import PaymentStatus
from database.models.subscription import BillingCycle
from providers.base import ChargeRequest, ChargeResult, PaymentGatewayError, PaymentProvider

logger = get_logger("mercadopago")

_BASE_URL = "https://api.mercadopago.com"
# Sem isso o aiohttp usa o default de 300s — uma resposta lenta do Mercado
# Pago prende a task da checagem de pagamento (chamada no caminho do
# webhook) por ate 5min em vez de falhar rapido.
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
# Janela de tolerancia pro `ts` do x-signature — sem isso, uma notificacao
# valida capturada (proxy malicioso, log vazado) pode ser reenviada pra
# sempre com assinatura ainda valida (replay attack). O processamento a
# jusante (confirm_payment/reject_payment/...) ja e idempotente por status
# (Fase 1), entao o impacto de um replay era baixo, mas rejeitar `ts` velho
# fecha a janela na borda, antes mesmo de tocar o banco.
_WEBHOOK_MAX_AGE_SECONDS = 300

_STATUS_MAP: dict[str, PaymentStatus] = {
    "pending": PaymentStatus.PENDING,
    "in_process": PaymentStatus.PROCESSING,
    "in_mediation": PaymentStatus.PROCESSING,
    "approved": PaymentStatus.APPROVED,
    "authorized": PaymentStatus.APPROVED,
    "rejected": PaymentStatus.REJECTED,
    "cancelled": PaymentStatus.CANCELED,
    "refunded": PaymentStatus.REFUNDED,
    "charged_back": PaymentStatus.CHARGEBACK,
}

_FREQUENCY_BY_CYCLE: dict[BillingCycle, tuple[int, str]] = {
    BillingCycle.MONTHLY: (1, "months"),
    BillingCycle.YEARLY: (1, "years"),
}


def _map_status(raw_status: str) -> PaymentStatus:
    return _STATUS_MAP.get(raw_status, PaymentStatus.PENDING)


class MercadoPagoProvider(PaymentProvider):
    """Integracao real com o Mercado Pago (PIX + assinatura via Preapproval
    hospedado). O 'sandbox' do MP e definido pelo access_token de teste usado —
    nao existe uma URL base separada. Nunca loga token nem corpo completo de
    resposta, so status code + id do pagamento."""

    name = "mercadopago"

    def __init__(self, access_token: str, webhook_secret: str | None) -> None:
        if not access_token:
            raise PaymentGatewayError(
                "Mercado Pago nao configurado — defina o access token (env) pro modo ativo."
            )
        self._access_token = access_token
        self._webhook_secret = webhook_secret

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        return headers

    async def _request(
        self, method: str, path: str, *, json: dict[str, object] | None = None, idempotency_key: str | None = None
    ) -> dict[str, object]:
        url = f"{_BASE_URL}{path}"
        try:
            async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                async with session.request(
                    method, url, json=json, headers=self._headers(idempotency_key=idempotency_key)
                ) as response:
                    body = await response.json(content_type=None)
                    if response.status >= 400:
                        logger.warning(
                            "Mercado Pago retornou %s em %s %s (payment/preapproval id nao exposto no log).",
                            response.status, method, path,
                        )
                        raise PaymentGatewayError(f"Mercado Pago respondeu {response.status} em {path}.")
                    return body if isinstance(body, dict) else {}
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.exception("Falha de rede ao chamar Mercado Pago (%s %s).", method, path)
            raise PaymentGatewayError("Falha de comunicacao com o Mercado Pago.") from exc

    def _payer_email(self, request: ChargeRequest) -> str:
        return f"discord{request.user_id}@guild{request.guild_id}.limerence.bot"

    def _charge_result_from_payment(self, data: dict[str, object]) -> ChargeResult:
        external_id = str(data.get("id"))
        status = _map_status(str(data.get("status") or "pending"))
        point_of_interaction = data.get("point_of_interaction")
        qr_code = None
        qr_code_base64 = None
        if isinstance(point_of_interaction, dict):
            transaction_data = point_of_interaction.get("transaction_data")
            if isinstance(transaction_data, dict):
                qr_code = transaction_data.get("qr_code")
                qr_code_base64 = transaction_data.get("qr_code_base64")
        expires_at = None
        raw_expiration = data.get("date_of_expiration")
        if isinstance(raw_expiration, str):
            try:
                expires_at = datetime.fromisoformat(raw_expiration.replace("Z", "+00:00"))
            except ValueError:
                expires_at = None
        return ChargeResult(
            external_id=external_id,
            status=status,
            qr_code=qr_code,
            qr_code_base64=qr_code_base64,
            expires_at=expires_at,
            raw=data,
        )

    # --- PaymentProvider ------------------------------------------------

    async def create_payment(self, request: ChargeRequest) -> ChargeResult:
        expiration_minutes = request.expires_in_minutes or 30
        date_of_expiration = (
            datetime.now(UTC) + timedelta(minutes=expiration_minutes)
        ).isoformat(timespec="seconds")
        body: dict[str, object] = {
            "transaction_amount": round(request.amount / 100, 2),
            "description": request.plan_name,
            "payment_method_id": "pix",
            "payer": {"email": self._payer_email(request)},
            "external_reference": request.external_reference,
            "date_of_expiration": date_of_expiration,
        }
        data = await self._request(
            "POST", "/v1/payments", json=body, idempotency_key=request.external_reference
        )
        return self._charge_result_from_payment(data)

    async def cancel_payment(self, external_id: str) -> None:
        try:
            await self._request("PUT", f"/v1/payments/{external_id}", json={"status": "cancelled"})
        except PaymentGatewayError:
            logger.warning("Nao foi possivel cancelar pagamento %s (pode ja estar em estado final).", external_id)

    async def get_payment(self, external_id: str) -> ChargeResult:
        data = await self._request("GET", f"/v1/payments/{external_id}")
        return self._charge_result_from_payment(data)

    async def create_subscription(self, request: ChargeRequest) -> ChargeResult:
        frequency = _FREQUENCY_BY_CYCLE.get(request.billing_cycle)
        if frequency is None:
            raise PaymentGatewayError("Ciclo de cobranca nao suporta assinatura recorrente.")
        frequency_value, frequency_type = frequency
        body = {
            "reason": request.plan_name,
            "external_reference": request.external_reference,
            "payer_email": self._payer_email(request),
            "auto_recurring": {
                "frequency": frequency_value,
                "frequency_type": frequency_type,
                "transaction_amount": round(request.amount / 100, 2),
                "currency_id": request.currency,
            },
            "status": "pending",
        }
        data = await self._request("POST", "/preapproval", json=body, idempotency_key=request.external_reference)
        return ChargeResult(
            external_id=str(data.get("id")),
            status=PaymentStatus.PENDING,
            checkout_url=str(data.get("init_point")) if data.get("init_point") else None,
            raw=data,
        )

    async def cancel_subscription(self, external_id: str) -> None:
        try:
            await self._request("PUT", f"/preapproval/{external_id}", json={"status": "cancelled"})
        except PaymentGatewayError:
            logger.warning("Nao foi possivel cancelar assinatura %s no Mercado Pago.", external_id)

    async def validate_webhook(self, headers: dict[str, str], raw_body: bytes, secret: str | None) -> bool:
        if not secret:
            return False
        signature_header = headers.get("x-signature") or headers.get("X-Signature")
        request_id = headers.get("x-request-id") or headers.get("X-Request-Id")
        data_id = headers.get("x-data-id")  # extraido da query string pelo route handler
        if not signature_header or not request_id or not data_id:
            return False

        ts = None
        v1 = None
        for part in signature_header.split(","):
            key, _, value = part.strip().partition("=")
            if key == "ts":
                ts = value
            elif key == "v1":
                v1 = value
        if not ts or not v1:
            return False

        manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
        digest = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(digest, v1):
            return False

        try:
            ts_seconds = int(ts) / 1000 if len(ts) > 10 else int(ts)
        except ValueError:
            return False
        age = abs(datetime.now(UTC).timestamp() - ts_seconds)
        if age > _WEBHOOK_MAX_AGE_SECONDS:
            logger.warning("Webhook Mercado Pago rejeitado: ts com %.0fs de idade (replay?).", age)
            return False
        return True
