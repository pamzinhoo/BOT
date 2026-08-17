from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord

from core.logger import get_logger
from database.database import Database
from database.models.audit_log import AuditLogCategory
from database.models.plan import Plan
from database.models.product import Product, ProductType
from database.models.subscription import BillingCycle
from database.repositories.license_repository import LicenseRepository
from database.repositories.plan_repository import PlanRepository
from database.repositories.player_repository import PlayerRepository
from database.repositories.product_repository import ProductRepository
from services.product_service import ProductService

if TYPE_CHECKING:
    from core.bot import LimerenceBot
    from database.models.payment import PaymentHistory
    from database.models.subscription import Subscription
    from providers.base import ChargeResult
    from services.license_service import LicenseService

logger = get_logger("dlc_service")


class DlcError(ValueError):
    """Erro de negocio no fluxo de DLC (mostrado direto pro admin/jogador)."""


class DlcService:
    """CRUD e regras de acesso de DLC do jogo Limerence — camada fina sobre
    ProductService/LicenseService/PlanService/SubscriptionService ja
    existentes (ver docs/PRODUCTS_AND_LICENSES.md). DLC e sempre um
    `Product(product_type=DLC)`; FREE/PAID nao e um campo proprio, e derivado
    de `price_amount`:

    - `price_amount` None/0 -> DLC gratuita: acesso condicionado a posse de
      `required_role_id` (na guild `required_role_guild_id`). O CARGO e a
      fonte de verdade; a License gerada (`purchase_source="role_grant"`) e
      so a representacao persistida desse estado — nunca uma compra. Mantida
      em sincronia por `sync_role_gained`/`sync_role_lost` (listener de
      member_update, ver cogs/dlc.py) + `reconcile_guild` (malha de
      seguranca periodica). Nunca passa por Plan/PaymentService.
    - `price_amount` > 0 -> DLC paga: vendida atraves de um `Plan`
      guild-scoped com `price_one_time` vinculado ao Product
      (`Plan.product_id`). Reaproveita 100% do pipeline de compra/webhook/
      idempotencia que ja existe pra planos (SubscriptionService/
      PaymentService/WebhookService) — nenhum codigo novo de pagamento. O
      cargo desse caminho vive em `Plan.role_id`, sincronizado por
      RoleSyncService/ReconciliationService (ja existentes), nao por este
      servico.

    Em ambos os casos a posse persistida e sempre a mesma `License` — DLC nao
    introduz um segundo conceito de entitlement.
    """

    def __init__(
        self, database: Database, license_service: LicenseService, bot: LimerenceBot | None = None
    ) -> None:
        self._database = database
        self._license_service = license_service
        self._bot = bot
        self._products = ProductService(database)

    # --- consulta -----------------------------------------------------------

    async def list_dlcs(self, *, only_active: bool = False) -> list[Product]:
        async with self._database.session() as session:
            return await ProductRepository(session).list_dlc(only_active=only_active)

    async def get(self, product_id: uuid.UUID, *, include_deleted: bool = False) -> Product | None:
        return await self._products.get(product_id, include_deleted=include_deleted)

    async def get_purchase_plan(self, product_id: uuid.UUID) -> Plan | None:
        """Plano de venda (ONE_TIME, price>0) vinculado ao Product DLC — so
        existe pra DLC paga. Se mais de um Plan ativo vincular o mesmo
        Product (multi-guild), usa o primeiro — o catalogo hoje assume uma
        DLC vendida por uma unica guild oficial (ver decisao de escopo
        multi-guild no relatorio de auditoria)."""
        async with self._database.session() as session:
            plans = await PlanRepository(session).list_by_product(product_id)
        return next((p for p in plans if p.is_active and p.price_one_time), None)

    def is_free(self, product: Product) -> bool:
        return not product.price_amount

    async def has_access(self, player_id: uuid.UUID, product_id: uuid.UUID) -> bool:
        """Fonte de verdade de posse pro jogo: License ACTIVE — vale tanto
        pra DLC paga (concedida pelo pagamento) quanto gratuita (concedida
        pelo cargo, mantida em sincronia por sync_role_gained/lost e
        reconcile_guild). O jogo/cliente nunca decide isso sozinho."""
        return await self._license_service.has_active_license(player_id, product_id)

    # --- criacao --------------------------------------------------------

    async def create_free(
        self,
        *,
        guild_id: int,
        name: str,
        slug: str,
        description: str | None,
        required_role_id: int,
        currency: str = "BRL",
        position: int = 0,
        created_by_staff_id: int | None = None,
        executor: discord.Member | discord.User | None = None,
    ) -> Product:
        await self._ensure_slug_available(slug)
        async with self._database.session() as session:
            product = await ProductRepository(session).add(
                Product(
                    slug=slug,
                    name=name,
                    product_type=ProductType.DLC,
                    description=description,
                    price_amount=None,
                    currency=currency,
                    position=position,
                    is_active=True,
                    required_role_id=required_role_id,
                    required_role_guild_id=guild_id,
                    created_by_staff_id=created_by_staff_id,
                )
            )
        await self._audit(
            guild_id, action="DLC criada (gratuita)", executor=executor,
            details={"dlc": name, "slug": slug, "role_id": required_role_id},
        )
        return product

    async def create_paid(
        self,
        *,
        guild_id: int,
        name: str,
        slug: str,
        description: str | None,
        price_amount: int,
        currency: str = "BRL",
        role_id: int,
        position: int = 0,
        created_by_staff_id: int | None = None,
        executor: discord.Member | discord.User | None = None,
    ) -> tuple[Product, Plan]:
        if price_amount <= 0:
            raise DlcError("Preço de DLC paga tem que ser maior que zero.")
        await self._ensure_slug_available(slug)
        async with self._database.session() as session:
            product = await ProductRepository(session).add(
                Product(
                    slug=slug,
                    name=name,
                    product_type=ProductType.DLC,
                    description=description,
                    price_amount=price_amount,
                    currency=currency,
                    position=position,
                    is_active=True,
                    created_by_staff_id=created_by_staff_id,
                )
            )
            plan = await PlanRepository(session).add(
                Plan(
                    guild_id=guild_id,
                    name=name,
                    product_id=product.id,
                    price_one_time=price_amount,
                    currency=currency,
                    role_id=role_id,
                    is_active=True,
                )
            )
        await self._audit(
            guild_id, action="DLC criada (paga)", executor=executor,
            details={"dlc": name, "slug": slug, "preco_centavos": price_amount, "role_id": role_id},
        )
        await self._refresh_shop(guild_id)
        return product, plan

    async def _ensure_slug_available(self, slug: str) -> None:
        existing = await self._products.get_by_slug(slug, include_deleted=True)
        if existing is not None:
            raise DlcError(f"Já existe um produto com o slug '{slug}'.")

    # --- edicao -----------------------------------------------------------

    async def update_info(
        self,
        product_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        executor: discord.Member | discord.User | None = None,
    ) -> Product:
        fields: dict[str, object] = {}
        if name is not None:
            fields["name"] = name
        if description is not None:
            fields["description"] = description or None
        product = await self._products.update(product_id, **fields)
        if product is None:
            raise DlcError("DLC não encontrada.")
        await self._audit_product(product, action="DLC editada", executor=executor, details=fields)
        return product

    async def update_price(
        self,
        product_id: uuid.UUID,
        *,
        price_amount: int,
        executor: discord.Member | discord.User | None = None,
    ) -> Product:
        """So se aplica a DLC paga — altera o preço de NOVAS compras; nunca
        retroativo (License/PaymentHistory já aprovados não mudam de valor)."""
        if price_amount <= 0:
            raise DlcError("Preço de DLC paga tem que ser maior que zero.")
        plan = await self.get_purchase_plan(product_id)
        if plan is None:
            raise DlcError("Esta DLC é gratuita — não tem preço pra alterar.")
        async with self._database.session() as session:
            plan_row = await PlanRepository(session).get_by_id(plan.id)
            product_row = await ProductRepository(session).get_by_id(product_id)
            if plan_row is None or product_row is None:
                raise DlcError("DLC não encontrada.")
            plan_row.price_one_time = price_amount
            product_row.price_amount = price_amount
            await session.flush()
            await session.refresh(product_row)
        await self._audit_product(
            product_row, action="Preço de DLC alterado", executor=executor,
            details={"novo_preco_centavos": price_amount},
        )
        await self._refresh_shop(plan.guild_id)
        return product_row

    async def update_role(
        self,
        product_id: uuid.UUID,
        *,
        role_id: int,
        guild_id: int,
        executor: discord.Member | discord.User | None = None,
    ) -> Product:
        product = await self._products.get(product_id)
        if product is None:
            raise DlcError("DLC não encontrada.")
        plan = await self.get_purchase_plan(product_id)
        if plan is not None:
            # DLC paga: cargo vive em Plan.role_id (pipeline de pagamento existente)
            async with self._database.session() as session:
                plan_row = await PlanRepository(session).get_by_id(plan.id)
                if plan_row is None:
                    raise DlcError("Plano de venda da DLC não encontrado.")
                plan_row.role_id = role_id
                await session.flush()
            updated = product
            await self._refresh_shop(plan.guild_id)
        else:
            # DLC gratuita: cargo vive no proprio Product
            updated = await self._products.update(
                product_id, required_role_id=role_id, required_role_guild_id=guild_id
            )
            if updated is None:
                raise DlcError("DLC não encontrada.")
        await self._audit_product(
            updated, action="Cargo de DLC alterado", executor=executor,
            details={"role_id": role_id, "guild_id": guild_id},
        )
        return updated

    async def toggle_active(
        self,
        product_id: uuid.UUID,
        *,
        is_active: bool,
        executor: discord.Member | discord.User | None = None,
    ) -> Product:
        """Alterna disponibilidade sem apagar nada (License/histórico
        intactos) — DLC inativa some do catálogo e não pode gerar cobrança
        nova. Também alterna o Plan de venda vinculado (se DLC paga), pra
        impedir compra direto pelo Plano enquanto a DLC estiver desativada."""
        product = await self._products.update(product_id, is_active=is_active)
        if product is None:
            raise DlcError("DLC não encontrada.")
        guild_ids: set[int] = set()
        async with self._database.session() as session:
            plan_repo = PlanRepository(session)
            for plan in await plan_repo.list_by_product(product_id):
                plan_row = await plan_repo.get_by_id(plan.id)
                if plan_row is not None:
                    plan_row.is_active = is_active
                    guild_ids.add(plan_row.guild_id)
            await session.flush()
        await self._audit_product(
            product, action="DLC ativada" if is_active else "DLC desativada", executor=executor
        )
        for guild_id in guild_ids:
            await self._refresh_shop(guild_id)
        return product

    async def disable(
        self, product_id: uuid.UUID, *, executor: discord.Member | discord.User | None = None
    ) -> Product | None:
        """Soft delete — preserva histórico de License/Payment (ver
        ProductService.soft_delete). Nunca remove a linha de verdade."""
        product = await self._products.soft_delete(product_id)
        if product is None:
            return None
        guild_ids: set[int] = set()
        async with self._database.session() as session:
            plan_repo = PlanRepository(session)
            for plan in await plan_repo.list_by_product(product_id):
                plan_row = await plan_repo.get_by_id(plan.id)
                if plan_row is not None:
                    plan_row.is_active = False
                    guild_ids.add(plan_row.guild_id)
            await session.flush()
        await self._audit_product(product, action="DLC excluída do catálogo", executor=executor)
        for guild_id in guild_ids:
            await self._refresh_shop(guild_id)
        return product

    # --- DLC gratuita: cargo -> License ------------------------------------

    async def sync_role_gained(self, discord_id: int, product: Product) -> None:
        if product.required_role_id is None:
            return
        async with self._database.session() as session:
            player = await PlayerRepository(session).get_or_create_by_discord_id(
                discord_id, discord_username=None, linked_at=datetime.now(UTC)
            )
        await self._license_service.grant_or_renew(player.id, product.id, purchase_source="role_grant")

    async def sync_role_lost(self, discord_id: int, product: Product) -> None:
        if product.required_role_id is None:
            return
        async with self._database.session() as session:
            player = await PlayerRepository(session).get_by_discord_id(discord_id)
        if player is None:
            return
        await self._license_service.revoke_by_player_product(
            player.id, product.id, reason="Cargo de DLC removido"
        )

    async def list_free_dlcs_by_guild(self, guild_id: int) -> list[Product]:
        async with self._database.session() as session:
            return await ProductRepository(session).list_free_dlc_by_guild(guild_id)

    async def reconcile_guild(self, guild: discord.Guild) -> None:
        """Malha de segurança pra DLC gratuita — mesmo papel que
        ReconciliationService/PartnershipService.reconcile_guild têm pro
        resto do sistema: cobre bot offline no momento da troca de cargo,
        membro que saiu/voltou (Discord zera cargo), edição manual de cargo.
        Corrige nas duas direções reaproveitando sync_role_gained/lost
        (idempotentes)."""
        for product in await self.list_free_dlcs_by_guild(guild.id):
            role = guild.get_role(product.required_role_id)  # type: ignore[arg-type]
            if role is None:
                await self._revoke_all_for_missing_role(product)
                continue
            holder_ids = {member.id for member in role.members}

            async with self._database.session() as session:
                player_repo = PlayerRepository(session)
                license_repo = LicenseRepository(session)
                players_by_discord_id = {
                    p.discord_id: p for p in await player_repo.list_by_discord_ids(list(holder_ids))
                }
                player_ids_with_role = [p.id for p in players_by_discord_id.values()]
                player_ids_with_active_license = {
                    lic.player_id
                    for lic in await license_repo.list_active_by_players_and_product(
                        player_ids_with_role, product.id
                    )
                }
                active_licenses = await license_repo.list_active_by_product(product.id)
                players_by_id = {
                    p.id: p for p in await player_repo.list_by_ids([lic.player_id for lic in active_licenses])
                }

            for discord_id in holder_ids:
                player = players_by_discord_id.get(discord_id)
                if player is None or player.id not in player_ids_with_active_license:
                    try:
                        await self.sync_role_gained(discord_id, product)
                    except Exception:
                        logger.exception(
                            "Falha ao reconciliar concessão de DLC %s pra discord_id %s.", product.id, discord_id
                        )

            for lic in active_licenses:
                player = players_by_id.get(lic.player_id)
                if player is None or player.discord_id in holder_ids:
                    continue
                try:
                    await self.sync_role_lost(player.discord_id, product)
                except Exception:
                    logger.exception(
                        "Falha ao reconciliar revogação de DLC %s pra discord_id %s.", product.id, player.discord_id
                    )

    async def _revoke_all_for_missing_role(self, product: Product) -> None:
        """Cargo exigido pela DLC gratuita não existe mais na guild (staff
        deletou o cargo em vez de desativar a DLC) — a condição de acesso
        deixou de ser satisfazível pra qualquer jogador, então nenhuma
        License ACTIVE pode continuar assim. Reaproveita sync_role_lost
        (mesmo fluxo de LicenseService.revoke_by_player_product, mesma
        auditoria, purchase_source="role_grant" preservado — não é tratado
        como compra) em vez de lógica paralela. Idempotente: sync_role_lost/
        revoke só age sobre License ACTIVE, então repetir a chamada numa
        próxima reconciliação sem novas licenças ativas não gera efeito nem
        erro."""
        async with self._database.session() as session:
            license_repo = LicenseRepository(session)
            player_repo = PlayerRepository(session)
            active_licenses = await license_repo.list_active_by_product(product.id)
            if not active_licenses:
                return
            players_by_id = {
                p.id: p for p in await player_repo.list_by_ids([lic.player_id for lic in active_licenses])
            }

        logger.warning(
            "Cargo obrigatório (id=%s) da DLC gratuita %s (%s) não existe mais na guild %s — "
            "revogando %s License(s) ativa(s).",
            product.required_role_id, product.id, product.name, product.required_role_guild_id,
            len(active_licenses),
        )

        for lic in active_licenses:
            player = players_by_id.get(lic.player_id)
            if player is None:
                continue
            try:
                await self.sync_role_lost(player.discord_id, product)
            except Exception:
                logger.exception(
                    "Falha ao revogar DLC %s (cargo deletado) pra discord_id %s.", product.id, player.discord_id
                )

    # --- compra (DLC paga) -------------------------------------------------

    async def start_purchase(
        self,
        product_id: uuid.UUID,
        discord_id: int,
        *,
        payer_information: str | None = None,
    ) -> tuple[Subscription, PaymentHistory, ChargeResult]:
        """Inicia cobrança de uma DLC paga reaproveitando 100% do pipeline de
        Plano já existente (SubscriptionService.start_purchase) — nenhuma
        cobrança/gateway/webhook novo. O preço cobrado é sempre o do `Plan`
        lido do banco (`plan.price_one_time`), nunca um valor vindo do
        chamador/API."""
        if self._bot is None:
            raise DlcError("Compra indisponível (bot não montado).")
        product = await self._products.get(product_id)
        if product is None or not product.is_active:
            raise DlcError("DLC não encontrada ou desativada.")
        plan = await self.get_purchase_plan(product_id)
        if plan is None:
            raise DlcError("Esta DLC não está disponível para compra.")

        guild = self._bot.get_guild(plan.guild_id)
        if guild is None:
            raise DlcError("Servidor de venda desta DLC está indisponível no momento.")
        member = guild.get_member(discord_id)
        if member is None:
            try:
                member = await guild.fetch_member(discord_id)
            except discord.HTTPException:
                member = None
        if member is None:
            raise DlcError("Você precisa estar no servidor oficial pra comprar esta DLC.")

        return await self._bot.subscription_service.start_purchase(
            member, plan, BillingCycle.ONE_TIME, payer_information=payer_information
        )

    # --- painel da loja (Discord) ------------------------------------------

    async def _refresh_shop(self, guild_id: int) -> None:
        """DLC paga e vendida atraves de um Plan comum — o mesmo painel fixo
        da loja (views/shop_view.py, PainelService) que ja lista Planos de
        assinatura tambem lista Plan(billing_cycle=ONE_TIME) de DLC sem
        nenhuma mudanca de UI. So precisa ser avisado quando o Plan muda,
        igual PlanEditView ja faz pra planos comuns — sem isso o painel ja
        postado no canal fica desatualizado ate alguem reposta manualmente.
        Acoplamento opcional (sem bot montado, ex. testes, e no-op) e nunca
        derruba a operacao principal se falhar."""
        if self._bot is None:
            return
        try:
            await self._bot.painel_service.refresh_shop_panel(guild_id)
        except Exception:
            logger.exception("Falha ao atualizar painel da loja (guild %s) após mudança de DLC.", guild_id)

    # --- auditoria -----------------------------------------------------

    async def _audit_product(
        self,
        product: Product,
        *,
        action: str,
        executor: discord.Member | discord.User | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        guild_id = product.required_role_guild_id
        if guild_id is None:
            plan = await self.get_purchase_plan(product.id)
            guild_id = plan.guild_id if plan is not None else None
        if guild_id is None:
            return
        await self._audit(
            guild_id, action=action, executor=executor, details={"dlc": product.name, **(details or {})}
        )

    async def _audit(
        self,
        guild_id: int,
        *,
        action: str,
        executor: discord.Member | discord.User | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """Acoplamento opcional com o bot (igual PlanService._audit): sem bot
        montado (testes), o fluxo segue igual."""
        if self._bot is None:
            return
        try:
            await self._bot.audit_log_service.record(
                guild_id=guild_id,
                category=AuditLogCategory.PRODUCT,
                action=action,
                executor_id=executor.id if executor else None,
                executor_name=str(executor) if executor else None,
                details=details or {},
            )
        except Exception:
            logger.exception("Falha ao auditar evento de DLC '%s' na guild %s.", action, guild_id)
