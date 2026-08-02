from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from database.models.payment import PaymentStatus
from database.models.pix_manual_settings import PixManualSettings
from providers.base import ChargeRequest, ChargeResult, PaymentProvider
from utils.pix_payload import build_pix_payload, generate_qr_base64


class ManualProvider(PaymentProvider):
    """Provider padrao quando nenhum gateway real esta configurado: nao cobra
    nada de verdade num gateway externo, mas gera o payload EMV/QR do PIX
    localmente a partir da chave configurada em /config painel -> Monetizacao
    -> PIX Manual, e marca a cobranca como pendente pra um staff aprovar
    manualmente (botao no canal de aprovacao). Sem chave PIX configurada,
    cai no fallback antigo (cobranca pendente sem QR — staff combina o
    pagamento fora do bot). Serve tambem de referencia de implementacao pros
    providers reais (MercadoPago/Stripe/Asaas/Paypal)."""

    name = "manual"

    def __init__(self, pix_settings: PixManualSettings | None = None) -> None:
        self._pix = pix_settings

    async def create_payment(self, request: ChargeRequest) -> ChargeResult:
        external_id = f"manual:{uuid.uuid4()}"
        settings = self._pix

        if settings is None or not settings.is_configured:
            return ChargeResult(
                external_id=external_id,
                status=PaymentStatus.PENDING,
                checkout_url=None,
                raw={"external_reference": request.external_reference},
            )

        payload = None
        if settings.send_qr_code or settings.send_copy_paste:
            payload = build_pix_payload(
                pix_key=settings.pix_key or "",
                receiver_name=settings.receiver_name or "",
                receiver_city=settings.receiver_city,
                amount_cents=request.amount,
                txid=external_id,
            )

        return ChargeResult(
            external_id=external_id,
            status=PaymentStatus.PENDING,
            checkout_url=None,
            qr_code=payload if (payload and settings.send_copy_paste) else None,
            qr_code_base64=generate_qr_base64(payload) if (payload and settings.send_qr_code) else None,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.expiration_minutes),
            raw={"external_reference": request.external_reference},
        )

    async def cancel_payment(self, external_id: str) -> None:
        return None

    async def get_payment(self, external_id: str) -> ChargeResult:
        raise NotImplementedError(
            "ManualProvider nao suporta consulta remota de status — a confirmacao e feita "
            "manualmente por um staff no Discord."
        )

    async def create_subscription(self, request: ChargeRequest) -> ChargeResult:
        raise NotImplementedError("ManualProvider nao suporta assinaturas recorrentes.")

    async def cancel_subscription(self, external_id: str) -> None:
        raise NotImplementedError("ManualProvider nao suporta assinaturas recorrentes.")

    async def validate_webhook(self, headers: dict[str, str], raw_body: bytes, secret: str | None) -> bool:
        return False
