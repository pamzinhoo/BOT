"""Validacao pos-auditoria: exercita contra o Postgres real configurado em
DATABASE_URL (nao SQLite/mock) os 3 caminhos que dependem de comportamento que
so um banco de verdade proporciona: FOR UPDATE (serializacao de corrida) e
guarda cross-guild em profundidade de servico. Cada teste cria suas proprias
linhas com guild_id sentinela (fora da faixa real de snowflakes do Discord) e
limpa tudo no finally, independente de sucesso ou falha.

Requer DATABASE_URL configurado e acessivel — se o banco nao estiver disponivel,
os testes falham com erro de conexao (nao sao pulados silenciosamente)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete

from config.settings import get_settings
from database.database import Database
from database.models.discount_coupon import DiscountCoupon, DiscountType
from database.models.discount_coupon_redemption import DiscountCouponRedemption
from database.models.payment import PaymentHistory, PaymentStatus
from database.models.plan import Plan
from database.models.punishment import Punishment, PunishmentStatus, PunishmentType
from database.models.punishment_appeal import AppealStatus, PunishmentAppeal
from database.models.ticket_panel import TicketPanel
from services.coupon_service import CouponGlobalLimitReachedError, CouponService
from services.payment_service import PaymentService
from services.plan_service import PlanService
from services.punishment_service import AppealError, PunishmentError, PunishmentService
from services.ticket_panel_service import TicketPanelService

# guild_id fora da faixa real de snowflakes do Discord (que sao ~19 digitos
# baseados em timestamp desde 2015) — evita qualquer colisao com dado real.
GUILD_A = 900_000_000_000_000_001
GUILD_B = 900_000_000_000_000_002


@dataclass
class _FakeGuild:
    id: int


@pytest.fixture
async def db() -> Database:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        await database.check_connection()
    except Exception as exc:  # pragma: no cover - falha explicita, nao skip
        await database.close()
        pytest.fail(
            f"Banco configurado em DATABASE_URL nao esta acessivel — "
            f"validacao de integracao requer Postgres real: {exc}"
        )
    yield database
    await database.close()


async def _cleanup(database: Database) -> None:
    async with database.session() as session:
        await session.execute(
            delete(DiscountCouponRedemption).where(
                DiscountCouponRedemption.guild_id.in_([GUILD_A, GUILD_B])
            )
        )
        await session.execute(
            delete(DiscountCoupon).where(DiscountCoupon.guild_id.in_([GUILD_A, GUILD_B]))
        )
        await session.execute(
            delete(PaymentHistory).where(PaymentHistory.guild_id.in_([GUILD_A, GUILD_B]))
        )
        await session.execute(delete(Plan).where(Plan.guild_id.in_([GUILD_A, GUILD_B])))
        await session.execute(
            delete(TicketPanel).where(TicketPanel.guild_id.in_([GUILD_A, GUILD_B]))
        )
        # PunishmentAppeal.punishment_id tem ondelete="CASCADE" — apagar a
        # punicao ja remove o recurso associado, nao precisa de delete separado.
        await session.execute(
            delete(Punishment).where(Punishment.guild_id.in_([GUILD_A, GUILD_B]))
        )


@pytest.mark.asyncio
async def test_cross_guild_appeal_guard_blocks_wrong_guild(db: Database) -> None:
    """C3: accept_appeal/deny_appeal tem que recusar um recurso cuja punicao
    pertence a uma guild diferente da guild que esta clicando aceitar/negar."""
    service = PunishmentService(db)
    async with db.session() as session:
        punishment = Punishment(
            guild_id=GUILD_A,
            punishment_code=f"TEST-{uuid.uuid4().hex[:8]}",
            user_id=111,
            staff_id=222,
            type=PunishmentType.BAN,
            reason="teste de validacao pos-auditoria",
            status=PunishmentStatus.ACTIVE,
        )
        session.add(punishment)
        await session.flush()
        appeal = PunishmentAppeal(
            punishment_id=punishment.id,
            user_id=111,
            message="recurso de teste",
            status=AppealStatus.PENDING,
        )
        session.add(appeal)
        await session.flush()
        punishment_id, appeal_id = punishment.id, appeal.id

    try:
        wrong_guild = _FakeGuild(id=GUILD_B)  # punicao e da GUILD_A
        reviewer = _FakeGuild(id=999)  # so precisa de .id pro staff_id != reviewer.id

        with pytest.raises(AppealError, match="não encontrad"):
            await service.accept_appeal(
                guild=wrong_guild,  # type: ignore[arg-type]
                appeal_id=appeal_id,
                reviewer=reviewer,  # type: ignore[arg-type]
            )

        with pytest.raises(AppealError, match="não encontrad"):
            await service.deny_appeal(
                guild=wrong_guild,  # type: ignore[arg-type]
                appeal_id=appeal_id,
                reviewer=reviewer,  # type: ignore[arg-type]
                reason="teste",
            )

        # confirma que a punicao NAO foi alterada (guarda bloqueou antes de agir)
        async with db.session() as session:
            fresh = await session.get(Punishment, punishment_id)
            assert fresh is not None
            assert fresh.status == PunishmentStatus.ACTIVE
            assert fresh.revoked_at is None
    finally:
        await _cleanup(db)


@pytest.mark.asyncio
async def test_payment_status_race_only_one_transition_wins(db: Database) -> None:
    """C4: dois "cliques" concorrentes em aprovar o mesmo pagamento so podem
    resultar em UMA transicao vencedora — a segunda tem que ver expected_statuses
    nao bater (porque a primeira ja mudou o status) e retornar None."""
    settings = get_settings()
    payments = PaymentService(db, settings)

    async with db.session() as session:
        plan = Plan(guild_id=GUILD_A, name=f"Plano Teste {uuid.uuid4().hex[:8]}")
        session.add(plan)
        await session.flush()
        payment = PaymentHistory(
            guild_id=GUILD_A,
            user_id=111,
            plan_id=plan.id,
            provider="manual",
            external_id=f"race-test-{uuid.uuid4().hex}",
            amount=1000,
            status=PaymentStatus.PENDING,
        )
        session.add(payment)
        await session.flush()
        payment_id = payment.id

    try:
        # duas "aprovacoes" disparadas ao mesmo tempo — mesma chamada que
        # confirm_payment faz internamente
        results = await asyncio.gather(
            payments.set_status(
                payment_id, PaymentStatus.APPROVED,
                paid_at=datetime.now(UTC),
                expected_statuses=(PaymentStatus.PENDING,),
            ),
            payments.set_status(
                payment_id, PaymentStatus.APPROVED,
                paid_at=datetime.now(UTC),
                expected_statuses=(PaymentStatus.PENDING,),
            ),
        )

        winners = [r for r in results if r is not None]
        losers = [r for r in results if r is None]
        assert len(winners) == 1, (
            f"esperado exatamente 1 transicao vencedora, obtido {len(winners)} "
            "— a guarda atomica (FOR UPDATE + expected_statuses) nao esta funcionando"
        )
        assert len(losers) == 1

        async with db.session() as session:
            fresh = await session.get(PaymentHistory, payment_id)
            assert fresh is not None
            assert fresh.status == PaymentStatus.APPROVED
    finally:
        await _cleanup(db)


@pytest.mark.asyncio
async def test_payment_status_history_not_duplicated_by_race(db: Database) -> None:
    """Efeito colateral do teste acima: confirma que so 1 linha de historico
    de status foi gravada (nao 2) — prova que a corrida nao duplicou efeito."""
    from sqlalchemy import select

    from database.models.payment_status_history import PaymentStatusHistory

    settings = get_settings()
    payments = PaymentService(db, settings)

    async with db.session() as session:
        plan = Plan(guild_id=GUILD_A, name=f"Plano Teste {uuid.uuid4().hex[:8]}")
        session.add(plan)
        await session.flush()
        payment = PaymentHistory(
            guild_id=GUILD_A,
            user_id=111,
            plan_id=plan.id,
            provider="manual",
            external_id=f"race-test-{uuid.uuid4().hex}",
            amount=1000,
            status=PaymentStatus.PENDING,
        )
        session.add(payment)
        await session.flush()
        payment_id = payment.id

    try:
        await asyncio.gather(
            payments.set_status(
                payment_id, PaymentStatus.APPROVED,
                expected_statuses=(PaymentStatus.PENDING,),
            ),
            payments.set_status(
                payment_id, PaymentStatus.APPROVED,
                expected_statuses=(PaymentStatus.PENDING,),
            ),
        )
        async with db.session() as session:
            result = await session.execute(
                select(PaymentStatusHistory).where(PaymentStatusHistory.payment_id == payment_id)
            )
            rows = list(result.scalars().all())
            assert len(rows) == 1, f"esperado 1 linha de historico, obtido {len(rows)}"
    finally:
        await _cleanup(db)


@pytest.mark.asyncio
async def test_coupon_redemption_race_respects_global_limit(db: Database) -> None:
    """C5: cupom com max_global_uses=1 disputado por 5 resgates concorrentes —
    so 1 pode vencer, os outros 4 tem que falhar com CouponGlobalLimitReachedError."""
    coupons = CouponService(db, bot=None)

    async with db.session() as session:
        coupon = DiscountCoupon(
            guild_id=GUILD_A,
            code=f"RACE{uuid.uuid4().hex[:6].upper()}",
            discount_type=DiscountType.PERCENTAGE,
            discount_value=10,
            max_global_uses=1,
            billing_cycles=[],
        )
        session.add(coupon)
        await session.flush()
        coupon_id = coupon.id

    try:
        async def _attempt(user_id: int) -> bool:
            try:
                await coupons.record_redemption(
                    coupon_id, GUILD_A, user_id, None, 1000, 100, 900
                )
                return True
            except CouponGlobalLimitReachedError:
                return False

        results = await asyncio.gather(*(_attempt(1000 + i) for i in range(5)))
        successes = sum(1 for r in results if r)
        assert successes == 1, (
            f"esperado exatamente 1 resgate bem-sucedido de 5 concorrentes, obtido {successes} "
            "— o limite do cupom foi ultrapassado sob concorrencia"
        )

        async with db.session() as session:
            result = await session.execute(
                delete(DiscountCouponRedemption)
                .where(DiscountCouponRedemption.coupon_id == coupon_id)
                .returning(DiscountCouponRedemption.id)
            )
            remaining = list(result.scalars().all())
            assert len(remaining) == 1, f"esperada 1 linha de resgate no banco, obtido {len(remaining)}"
    finally:
        await _cleanup(db)


@pytest.mark.asyncio
async def test_webhook_no_premature_status_write(db: Database) -> None:
    """C6: garante que set_status com expected_statuses=None (uso legado, ex.:
    REFUNDED/CHARGEBACK) continua funcionando sem guarda — e que o padrao
    correto (webhook_service chamando confirm_payment em vez de setar o status
    direto) e o que esta em services/webhook_service.py hoje."""
    import inspect

    import services.webhook_service as webhook_module

    source = inspect.getsource(webhook_module.WebhookService.handle_mercadopago_notification)
    # a linha que causava o bug (set_status direto ANTES de confirm_payment)
    # nao pode mais existir — a aprovacao tem que ser feita so por dentro de
    # confirm_payment (que agora e atomico)
    assert "await self._payments.set_status(payment.id, remote.status" not in source, (
        "regressao: webhook_service voltou a setar o status do pagamento antes de "
        "chamar confirm_payment/reject_payment/expire_payment — isso faz a aprovacao "
        "automatica cair no atalho idempotente e nunca entregar o beneficio (bug C6)"
    )
    assert "await self._subscriptions.confirm_payment(payment.id)" in source


@dataclass
class _FakeResponse:
    sent: list[dict] = field(default_factory=list)
    edited: list[dict] = field(default_factory=list)
    deferred: bool = False

    async def send_message(self, content: str | None = None, **kwargs: object) -> None:
        self.sent.append({"content": content, **kwargs})

    async def edit_message(self, **kwargs: object) -> None:
        self.edited.append(kwargs)

    async def defer(self, **kwargs: object) -> None:
        # Callbacks reais (Fase 1: defer-first evita timeout de 3s) chamam
        # isso antes de qualquer outra coisa — precisa existir no fake ou
        # todo callback de Select estoura AttributeError antes de chegar
        # na guarda cross-guild que o teste quer validar.
        self.deferred = True


@dataclass
class _FakeFollowup:
    response: _FakeResponse

    async def send(self, content: str | None = None, **kwargs: object) -> None:
        # Pos defer-first, a resposta de erro vai por followup (nao mais
        # por response.send_message) — registra no mesmo `sent` do
        # response pra manter as asserts dos testes existentes validas.
        self.response.sent.append({"content": content, **kwargs})


@dataclass
class _FakeBot:
    plan_service: PlanService | None = None
    ticket_panel_service: TicketPanelService | None = None


@dataclass
class _FakeInteraction:
    client: _FakeBot
    guild_id: int
    response: _FakeResponse = field(default_factory=_FakeResponse)
    followup: _FakeFollowup = field(init=False)

    def __post_init__(self) -> None:
        self.followup = _FakeFollowup(response=self.response)


@pytest.mark.asyncio
async def test_cross_guild_plan_select_blocks_wrong_guild(db: Database) -> None:
    """C1: _PlanSelect.callback (views/monetization_panel_view.py) tem que
    recusar um plano cujo guild_id nao bate com o da guild da interacao —
    mesmo se o UUID do plano vier certo no valor do select (forjavel pelo
    cliente)."""
    from views.monetization_panel_view import _PlanSelect

    async with db.session() as session:
        plan = Plan(guild_id=GUILD_A, name=f"Plano Cross {uuid.uuid4().hex[:8]}")
        session.add(plan)
        await session.flush()
        plan_id = plan.id

    try:
        import types

        bot = _FakeBot(plan_service=PlanService(db, None))
        # simula clique vindo da GUILD_B com o UUID do plano da GUILD_A —
        # so precisa do atributo `.values` que o callback le, sem montar o
        # discord.ui.Select real (que exige um Item completo pra inicializar)
        select = types.SimpleNamespace(values=[str(plan_id)])

        interaction = _FakeInteraction(client=bot, guild_id=GUILD_B)
        await _PlanSelect.callback(select, interaction)  # type: ignore[arg-type]

        assert len(interaction.response.sent) == 1
        assert "não encontrado" in interaction.response.sent[0]["content"]
        assert not interaction.response.edited, (
            "regressao: o painel de edicao do plano de outra guild foi renderizado "
            "(cross-guild plan edit — bug C1)"
        )
    finally:
        await _cleanup(db)


@pytest.mark.asyncio
async def test_cross_guild_ticket_panel_select_blocks_wrong_guild(db: Database) -> None:
    """C2: _PanelSelect.callback (views/ticket_panels_view.py) tem que recusar
    um painel de ticket cujo guild_id nao bate com o da guild da interacao."""
    from views.ticket_panels_view import _PanelSelect

    async with db.session() as session:
        panel = TicketPanel(guild_id=GUILD_A, key=f"cross-{uuid.uuid4().hex[:8]}", name="Painel Cross")
        session.add(panel)
        await session.flush()
        panel_id = panel.id

    try:
        import types

        bot = _FakeBot(ticket_panel_service=TicketPanelService(db, object()))  # type: ignore[arg-type]
        select = types.SimpleNamespace(values=[str(panel_id)], on_back=AsyncMock())

        interaction = _FakeInteraction(client=bot, guild_id=GUILD_B)
        await _PanelSelect.callback(select, interaction)  # type: ignore[arg-type]

        assert len(interaction.response.sent) == 1
        assert "não encontrado" in interaction.response.sent[0]["content"]
        assert not interaction.response.edited, (
            "regressao: o painel de edicao do ticket-panel de outra guild foi renderizado "
            "(cross-guild ticket panel edit — bug C2)"
        )
    finally:
        await _cleanup(db)


# --- auditoria de producao (multi-tenant/seguranca) ------------------------
#
# accept_appeal/deny_appeal ja tinham a guarda cross-guild (teste acima). Os
# testes abaixo cobrem os OUTROS 4 metodos de services/punishment_service.py
# que faltavam a mesma guarda: resolve_review, apply_pending, revoke e
# cancel_pending — todos recebem `punishment_id` + uma guild/membro de quem
# esta agindo, e nenhum deles conferia que a punicao pertencia aquela guild
# antes de aplicar a acao (ou, no caso de resolve_review, antes de banir/
# expulsar um membro da guild ERRADA usando os dados da punicao certa).


@pytest.mark.asyncio
async def test_resolve_review_blocks_punishment_from_another_guild(db: Database) -> None:
    service = PunishmentService(db)
    async with db.session() as session:
        punishment = Punishment(
            guild_id=GUILD_A,
            punishment_code=f"TEST-{uuid.uuid4().hex[:8]}",
            user_id=111,
            staff_id=222,
            type=PunishmentType.BAN,
            reason="teste de auditoria — resolve_review cross-guild",
            status=PunishmentStatus.PENDING_REVIEW,
        )
        session.add(punishment)
        await session.flush()
        punishment_id = punishment.id

    try:
        wrong_guild = _FakeGuild(id=GUILD_B)  # punicao e da GUILD_A

        with pytest.raises(PunishmentError, match="não encontrad"):
            await service.resolve_review(
                guild=wrong_guild,  # type: ignore[arg-type]
                punishment_id=punishment_id,
                approved=False,
                reviewer_id=999,
                reviewer_name="Staff Errado",
                reason="tentativa cross-guild",
                review_role_id=None,
            )

        async with db.session() as session:
            fresh = await session.get(Punishment, punishment_id)
            assert fresh is not None
            assert fresh.status == PunishmentStatus.PENDING_REVIEW, (
                "regressao: resolve_review aplicou a punicao (ban/kick) usando a guild "
                "de quem chamou, mesmo a punicao sendo de outra guild"
            )
    finally:
        await _cleanup(db)


@pytest.mark.asyncio
async def test_apply_pending_blocks_punishment_from_another_guild(db: Database) -> None:
    service = PunishmentService(db)
    async with db.session() as session:
        punishment = Punishment(
            guild_id=GUILD_A,
            punishment_code=f"TEST-{uuid.uuid4().hex[:8]}",
            user_id=111,
            staff_id=222,
            type=PunishmentType.KICK,
            reason="teste de auditoria — apply_pending cross-guild",
            status=PunishmentStatus.NOTIFIED,
        )
        session.add(punishment)
        await session.flush()
        punishment_id = punishment.id

    try:
        wrong_guild = _FakeGuild(id=GUILD_B)
        target = _FakeGuild(id=111)  # so precisa existir; a guarda barra antes de qualquer chamada Discord

        with pytest.raises(PunishmentError, match="não encontrad"):
            await service.apply_pending(
                guild=wrong_guild, punishment_id=punishment_id, target=target  # type: ignore[arg-type]
            )

        async with db.session() as session:
            fresh = await session.get(Punishment, punishment_id)
            assert fresh is not None
            assert fresh.status == PunishmentStatus.NOTIFIED
    finally:
        await _cleanup(db)


@pytest.mark.asyncio
async def test_revoke_blocks_punishment_from_another_guild(db: Database) -> None:
    service = PunishmentService(db)
    async with db.session() as session:
        punishment = Punishment(
            guild_id=GUILD_A,
            punishment_code=f"TEST-{uuid.uuid4().hex[:8]}",
            user_id=111,
            staff_id=222,
            type=PunishmentType.TIMEOUT,
            reason="teste de auditoria — revoke cross-guild",
            status=PunishmentStatus.ACTIVE,
            duration_seconds=3600,
        )
        session.add(punishment)
        await session.flush()
        punishment_id = punishment.id

    try:
        wrong_guild = _FakeGuild(id=GUILD_B)
        revoker = _FakeGuild(id=999)

        with pytest.raises(PunishmentError, match="não encontrad"):
            await service.revoke(
                guild=wrong_guild, punishment_id=punishment_id, revoked_by=revoker,  # type: ignore[arg-type]
                reason="tentativa cross-guild",
            )

        async with db.session() as session:
            fresh = await session.get(Punishment, punishment_id)
            assert fresh is not None
            assert fresh.status == PunishmentStatus.ACTIVE
            assert fresh.revoked_at is None
    finally:
        await _cleanup(db)


@pytest.mark.asyncio
async def test_cancel_pending_blocks_punishment_from_another_guild(db: Database) -> None:
    service = PunishmentService(db)
    async with db.session() as session:
        punishment = Punishment(
            guild_id=GUILD_A,
            punishment_code=f"TEST-{uuid.uuid4().hex[:8]}",
            user_id=111,
            staff_id=222,
            type=PunishmentType.ADVERTENCIA,
            reason="teste de auditoria — cancel_pending cross-guild",
            status=PunishmentStatus.PENDING,
        )
        session.add(punishment)
        await session.flush()
        punishment_id = punishment.id

    try:
        import types

        staff = types.SimpleNamespace(id=999, guild=_FakeGuild(id=GUILD_B))

        with pytest.raises(PunishmentError, match="não encontrad"):
            await service.cancel_pending(punishment_id=punishment_id, staff=staff)  # type: ignore[arg-type]

        async with db.session() as session:
            fresh = await session.get(Punishment, punishment_id)
            assert fresh is not None
            assert fresh.status == PunishmentStatus.PENDING
    finally:
        await _cleanup(db)
