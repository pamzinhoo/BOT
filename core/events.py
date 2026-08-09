from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

# Nomes de evento publicados no EventBus — espelham LicenseEventType (mesmos
# 5 estados), mas como string solta (nao o enum) pra RoleSyncService e o
# endpoint HTTP interno (api/routes/internal_routes.py) nao precisarem
# importar o model de dominio inteiro so pra assinar/despachar eventos.
LICENSE_CREATED = "LICENSE_CREATED"
LICENSE_RENEWED = "LICENSE_RENEWED"
LICENSE_REVOKED = "LICENSE_REVOKED"
LICENSE_EXPIRED = "LICENSE_EXPIRED"
LICENSE_REACTIVATED = "LICENSE_REACTIVATED"

# Quem recebe estes eventos deve CONCEDER o cargo (o Product passou a estar
# coberto por uma License ACTIVE).
LICENSE_GRANT_EVENTS = (LICENSE_CREATED, LICENSE_RENEWED, LICENSE_REACTIVATED)
# Quem recebe estes eventos deve REMOVER o cargo.
LICENSE_REVOKE_EVENTS = (LICENSE_REVOKED, LICENSE_EXPIRED)


@dataclass(frozen=True, slots=True)
class LicenseEventPayload:
    """Payload publicado no EventBus (e aceito por POST /internal/license-events)
    toda vez que uma License muda de status. E o unico jeito pelo qual o bot
    fica sabendo que precisa conceder/remover um cargo — nunca reage a evento
    do Discord (member update, role manual) como fonte de verdade."""

    license_id: uuid.UUID
    player_id: uuid.UUID
    product_id: uuid.UUID
    status: str
    event_type: str
    occurred_at: datetime
