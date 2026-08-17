from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from database.models.product import ProductType
from services.dlc_service import DlcError, DlcService
from services.license_service import LicenseService
from tests._fakes_dlc import DlcFakeStore, install_dlc_fakes
from tests._fakes_dlc import FakeDatabase as DlcFakeDatabase
from tests._fakes_license import FakeDatabase as LicenseFakeDatabase
from tests._fakes_license import FakeLicenseRepository, LicenseFakeStore
from tests._fakes_license import install_fake_repositories as install_license_fakes

_GUILD_ID = 111
_ROLE_ID = 222


@pytest.fixture
def dlc_store() -> DlcFakeStore:
    return DlcFakeStore()


@pytest.fixture
def license_store() -> LicenseFakeStore:
    return LicenseFakeStore()


@pytest.fixture
def license_service(monkeypatch, license_store: LicenseFakeStore) -> LicenseService:
    install_license_fakes(monkeypatch, license_store)
    return LicenseService(LicenseFakeDatabase(license_store))


@pytest.fixture
def dlc_service(monkeypatch, dlc_store: DlcFakeStore, license_store: LicenseFakeStore, license_service: LicenseService) -> DlcService:
    install_dlc_fakes(monkeypatch, dlc_store)
    # reconcile_guild le License direto (mesmo padrao de ReconciliationService)
    # — reaproveita o MESMO store da LicenseService pra ficarem consistentes.
    monkeypatch.setattr(
        "services.dlc_service.LicenseRepository",
        lambda session: FakeLicenseRepository(session, store=license_store),
    )
    return DlcService(DlcFakeDatabase(dlc_store), license_service, bot=None)


# --- criacao ---------------------------------------------------------------


async def test_create_free_dlc(dlc_service: DlcService, dlc_store: DlcFakeStore) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="The Empress", slug="empress", description=None, required_role_id=_ROLE_ID
    )

    assert product.product_type == ProductType.DLC
    assert product.price_amount is None
    assert product.required_role_id == _ROLE_ID
    assert product.required_role_guild_id == _GUILD_ID
    assert dlc_service.is_free(product) is True


async def test_create_paid_dlc_creates_linked_plan(dlc_service: DlcService, dlc_store: DlcFakeStore) -> None:
    product, plan = await dlc_service.create_paid(
        guild_id=_GUILD_ID, name="The Devil", slug="devil", description=None,
        price_amount=1490, role_id=_ROLE_ID,
    )

    assert product.price_amount == 1490
    assert dlc_service.is_free(product) is False
    assert plan.product_id == product.id
    assert plan.price_one_time == 1490
    assert plan.role_id == _ROLE_ID
    assert plan.guild_id == _GUILD_ID


async def test_create_paid_dlc_rejects_zero_price(dlc_service: DlcService) -> None:
    with pytest.raises(DlcError):
        await dlc_service.create_paid(
            guild_id=_GUILD_ID, name="X", slug="x", description=None, price_amount=0, role_id=_ROLE_ID
        )


async def test_create_dlc_rejects_duplicate_slug(dlc_service: DlcService) -> None:
    await dlc_service.create_free(guild_id=_GUILD_ID, name="A", slug="dup", description=None, required_role_id=1)
    with pytest.raises(DlcError):
        await dlc_service.create_free(guild_id=_GUILD_ID, name="B", slug="dup", description=None, required_role_id=2)


# --- edicao ------------------------------------------------------------


async def test_update_price_on_free_dlc_fails(dlc_service: DlcService) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-1", description=None, required_role_id=1
    )
    with pytest.raises(DlcError):
        await dlc_service.update_price(product.id, price_amount=1000)


async def test_update_price_does_not_affect_past_purchases(dlc_service: DlcService, license_service: LicenseService) -> None:
    """Alterar preco afeta so NOVAS compras — License/PaymentHistory ja
    aprovados nao mudam de valor (aqui simulado: License concedida antes da
    mudanca de preco continua ativa e intacta depois)."""
    product, plan = await dlc_service.create_paid(
        guild_id=_GUILD_ID, name="Devil", slug="devil-2", description=None, price_amount=1490, role_id=_ROLE_ID
    )
    player_id = uuid.uuid4()
    lic = await license_service.grant_or_renew(player_id, product.id, purchase_source="mercadopago")

    updated = await dlc_service.update_price(product.id, price_amount=2990)

    assert updated.price_amount == 2990
    lic_after = await license_service.get(lic.id)
    assert lic_after is not None
    assert lic_after.status.value == "active"


async def test_update_role_routes_to_plan_when_paid(dlc_service: DlcService, dlc_store: DlcFakeStore) -> None:
    product, plan = await dlc_service.create_paid(
        guild_id=_GUILD_ID, name="Devil", slug="devil-3", description=None, price_amount=1490, role_id=_ROLE_ID
    )
    updated = await dlc_service.update_role(product.id, role_id=999, guild_id=_GUILD_ID)

    assert updated.required_role_id is None  # nao mexe no Product
    stored_plan = dlc_store.plans[plan.id]
    assert stored_plan.role_id == 999


async def test_update_role_routes_to_product_when_free(dlc_service: DlcService) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-2", description=None, required_role_id=1
    )
    updated = await dlc_service.update_role(product.id, role_id=999, guild_id=_GUILD_ID)

    assert updated.required_role_id == 999


async def test_toggle_active_also_disables_linked_plan(dlc_service: DlcService, dlc_store: DlcFakeStore) -> None:
    product, plan = await dlc_service.create_paid(
        guild_id=_GUILD_ID, name="Devil", slug="devil-4", description=None, price_amount=1490, role_id=_ROLE_ID
    )
    await dlc_service.toggle_active(product.id, is_active=False)

    assert dlc_store.products[product.id].is_active is False
    assert dlc_store.plans[plan.id].is_active is False


async def test_disable_preserves_license_history(dlc_service: DlcService, license_service: LicenseService) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-3", description=None, required_role_id=1
    )
    player_id = uuid.uuid4()
    lic = await license_service.grant_or_renew(player_id, product.id, purchase_source="role_grant")

    disabled = await dlc_service.disable(product.id)

    assert disabled is not None
    assert disabled.deleted_at is not None
    lic_after = await license_service.get(lic.id)
    assert lic_after is not None  # historico intacto, nao apagado


# --- acesso / DLC gratuita --------------------------------------------------


async def test_has_access_false_without_license(dlc_service: DlcService) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-4", description=None, required_role_id=1
    )
    assert await dlc_service.has_access(uuid.uuid4(), product.id) is False


async def test_sync_role_gained_grants_license_with_role_grant_source(
    dlc_service: DlcService, license_store: LicenseFakeStore
) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-5", description=None, required_role_id=_ROLE_ID
    )
    discord_id = 555

    await dlc_service.sync_role_gained(discord_id, product)

    lic = next(lic for lic in license_store.licenses.values() if lic.product_id == product.id)
    assert lic.status.value == "active"
    assert lic.purchase_source == "role_grant"


async def test_sync_role_lost_revokes_license(dlc_service: DlcService, license_store: LicenseFakeStore) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-6", description=None, required_role_id=_ROLE_ID
    )
    discord_id = 556
    await dlc_service.sync_role_gained(discord_id, product)

    await dlc_service.sync_role_lost(discord_id, product)

    lic = next(lic for lic in license_store.licenses.values() if lic.product_id == product.id)
    assert lic.status.value == "revoked"


async def test_sync_role_lost_without_player_is_noop(dlc_service: DlcService) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-7", description=None, required_role_id=_ROLE_ID
    )
    await dlc_service.sync_role_lost(999999, product)  # nunca teve Player — nao deve levantar


async def test_license_of_one_product_does_not_unlock_another(
    dlc_service: DlcService, license_service: LicenseService
) -> None:
    product_a = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="A", slug="dlc-a", description=None, required_role_id=1
    )
    product_b = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="B", slug="dlc-b", description=None, required_role_id=2
    )
    player_id = uuid.uuid4()
    await license_service.grant_or_renew(player_id, product_a.id, purchase_source="role_grant")

    assert await dlc_service.has_access(player_id, product_a.id) is True
    assert await dlc_service.has_access(player_id, product_b.id) is False


# --- reconciliacao (DLC gratuita) -----------------------------------------


def _role_with_members(role_id: int, member_ids: list[int]) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.members = [MagicMock(id=mid) for mid in member_ids]
    return role


async def test_reconcile_guild_grants_missing_license_for_role_holder(
    dlc_service: DlcService, license_store: LicenseFakeStore
) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-8", description=None, required_role_id=_ROLE_ID
    )
    role = _role_with_members(_ROLE_ID, [777])
    guild = MagicMock(spec=discord.Guild)
    guild.id = _GUILD_ID
    guild.get_role.return_value = role

    await dlc_service.reconcile_guild(guild)

    lic = next(lic for lic in license_store.licenses.values() if lic.product_id == product.id)
    assert lic.status.value == "active"


async def test_reconcile_guild_revokes_license_when_role_lost(
    dlc_service: DlcService, license_store: LicenseFakeStore
) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-9", description=None, required_role_id=_ROLE_ID
    )
    await dlc_service.sync_role_gained(888, product)

    role = _role_with_members(_ROLE_ID, [])  # membro nao tem mais o cargo
    guild = MagicMock(spec=discord.Guild)
    guild.id = _GUILD_ID
    guild.get_role.return_value = role

    await dlc_service.reconcile_guild(guild)

    lic = next(lic for lic in license_store.licenses.values() if lic.product_id == product.id)
    assert lic.status.value == "revoked"


async def test_reconcile_guild_keeps_access_when_member_still_has_role(
    dlc_service: DlcService, license_store: LicenseFakeStore
) -> None:
    """Cargo existente + membro com cargo -> acesso permanece (nao gera
    revogacao nem efeito colateral so por rodar a reconciliacao de novo)."""
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-role-keep", description=None, required_role_id=_ROLE_ID
    )
    await dlc_service.sync_role_gained(777, product)

    role = _role_with_members(_ROLE_ID, [777])  # ainda tem o cargo
    guild = MagicMock(spec=discord.Guild)
    guild.id = _GUILD_ID
    guild.get_role.return_value = role

    await dlc_service.reconcile_guild(guild)

    lic = next(lic for lic in license_store.licenses.values() if lic.product_id == product.id)
    assert lic.status.value == "active"
    assert lic.purchase_source == "role_grant"


async def test_reconcile_guild_revokes_all_active_licenses_when_role_deleted(
    dlc_service: DlcService, license_store: LicenseFakeStore
) -> None:
    """Cargo deletado (guild.get_role retorna None) -> TODAS as License
    ACTIVE dessa DLC sao revogadas, sem continue silencioso."""
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-role-deleted", description=None, required_role_id=_ROLE_ID
    )
    await dlc_service.sync_role_gained(111, product)
    await dlc_service.sync_role_gained(222, product)
    await dlc_service.sync_role_gained(333, product)

    guild = MagicMock(spec=discord.Guild)
    guild.id = _GUILD_ID
    guild.get_role.return_value = None  # cargo deletado

    await dlc_service.reconcile_guild(guild)

    licenses = [lic for lic in license_store.licenses.values() if lic.product_id == product.id]
    assert len(licenses) == 3
    assert all(lic.status.value == "revoked" for lic in licenses)
    # continua marcada como concessao por cargo, nunca vira compra
    assert all(lic.purchase_source == "role_grant" for lic in licenses)


async def test_reconcile_guild_role_deleted_is_idempotent(
    dlc_service: DlcService, license_store: LicenseFakeStore
) -> None:
    """Cargo deletado -> segunda reconciliacao nao gera novas revogacoes nem
    erro (sync_role_lost/revoke so agem sobre License ACTIVE)."""
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-role-deleted-2", description=None, required_role_id=_ROLE_ID
    )
    await dlc_service.sync_role_gained(444, product)

    guild = MagicMock(spec=discord.Guild)
    guild.id = _GUILD_ID
    guild.get_role.return_value = None

    await dlc_service.reconcile_guild(guild)
    lic_after_first = next(lic for lic in license_store.licenses.values() if lic.product_id == product.id)
    revoked_at_first = lic_after_first.revoked_at
    events_after_first = len(license_store.events)

    await dlc_service.reconcile_guild(guild)  # segunda rodada, mesmo estado

    lic_after_second = next(lic for lic in license_store.licenses.values() if lic.product_id == product.id)
    assert lic_after_second.status.value == "revoked"
    assert lic_after_second.revoked_at == revoked_at_first  # nao regrava/nao gera novo evento
    assert len(license_store.events) == events_after_first


async def test_reconcile_guild_role_deleted_does_not_affect_paid_dlc(
    dlc_service: DlcService, license_store: LicenseFakeStore
) -> None:
    """DLC paga nao passa por required_role_id/reconcile_guild — License
    concedida por pagamento nao pode ser revogada so porque um cargo de
    OUTRA DLC (gratuita) na mesma guild foi deletado."""
    free_product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-role-deleted-3", description=None, required_role_id=_ROLE_ID
    )
    paid_product, _plan = await dlc_service.create_paid(
        guild_id=_GUILD_ID, name="Devil", slug="devil-paid-untouched", description=None,
        price_amount=1490, role_id=999,
    )
    player_id = uuid.uuid4()
    paid_lic = await dlc_service._license_service.grant_or_renew(
        player_id, paid_product.id, purchase_source="mercadopago"
    )
    await dlc_service.sync_role_gained(555, free_product)

    guild = MagicMock(spec=discord.Guild)
    guild.id = _GUILD_ID
    guild.get_role.return_value = None  # cargo da DLC gratuita foi deletado

    await dlc_service.reconcile_guild(guild)

    free_lic = next(lic for lic in license_store.licenses.values() if lic.product_id == free_product.id)
    assert free_lic.status.value == "revoked"

    paid_lic_after = license_store.licenses[paid_lic.id]
    assert paid_lic_after.status.value == "active"
    assert paid_lic_after.purchase_source == "mercadopago"


# --- compra (DLC paga) -------------------------------------------------


async def test_start_purchase_uses_plan_price_never_caller_supplied(dlc_service: DlcService) -> None:
    product, plan = await dlc_service.create_paid(
        guild_id=_GUILD_ID, name="Devil", slug="devil-5", description=None, price_amount=1490, role_id=_ROLE_ID
    )

    member = MagicMock(spec=discord.Member)
    member.id = 42
    guild = MagicMock(spec=discord.Guild)
    guild.get_member.return_value = member

    bot = MagicMock()
    bot.get_guild.return_value = guild
    bot.subscription_service.start_purchase = AsyncMock(return_value=("sub", "payment", "result"))
    dlc_service._bot = bot

    await dlc_service.start_purchase(product.id, 42)

    called_plan = bot.subscription_service.start_purchase.call_args.args[1]
    assert called_plan.price_one_time == 1490  # sempre o preco do banco


async def test_start_purchase_fails_for_free_dlc(dlc_service: DlcService) -> None:
    product = await dlc_service.create_free(
        guild_id=_GUILD_ID, name="Free", slug="free-10", description=None, required_role_id=1
    )
    bot = MagicMock()
    dlc_service._bot = bot

    with pytest.raises(DlcError):
        await dlc_service.start_purchase(product.id, 42)


async def test_start_purchase_fails_when_member_not_in_guild(dlc_service: DlcService) -> None:
    product, _plan = await dlc_service.create_paid(
        guild_id=_GUILD_ID, name="Devil", slug="devil-6", description=None, price_amount=1490, role_id=_ROLE_ID
    )
    guild = MagicMock(spec=discord.Guild)
    guild.get_member.return_value = None
    guild.fetch_member = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "not found"))
    bot = MagicMock()
    bot.get_guild.return_value = guild
    dlc_service._bot = bot

    with pytest.raises(DlcError):
        await dlc_service.start_purchase(product.id, 42)


async def test_start_purchase_fails_for_inactive_dlc(dlc_service: DlcService) -> None:
    product, _plan = await dlc_service.create_paid(
        guild_id=_GUILD_ID, name="Devil", slug="devil-7", description=None, price_amount=1490, role_id=_ROLE_ID
    )
    await dlc_service.toggle_active(product.id, is_active=False)
    bot = MagicMock()
    dlc_service._bot = bot

    with pytest.raises(DlcError):
        await dlc_service.start_purchase(product.id, 42)
