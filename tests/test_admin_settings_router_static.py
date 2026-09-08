from __future__ import annotations

from pathlib import Path


def test_dashboard_settings_router_uses_namespaced_keys() -> None:
    source = Path("api/routes/admin/settings_router.py").read_text(encoding="utf-8")

    assert 'f"{category_key}.{field.attr}"' in source
    assert 'grouped.setdefault(entry.updater, {})[entry.field.attr]' in source
    assert "Configuracao desconhecida ou ambigua." in source


def test_dashboard_settings_router_preserves_bool_values() -> None:
    source = Path("api/routes/admin/settings_router.py").read_text(encoding="utf-8")
    serialize_index = source.index("def _serialize_value")
    bool_index = source.index("isinstance(raw, bool)", serialize_index)
    int_index = source.index("isinstance(raw, int)", serialize_index)

    assert bool_index < int_index
    assert "bool herda de int" in source


def test_dashboard_settings_router_validates_discord_references() -> None:
    source = Path("api/routes/admin/settings_router.py").read_text(encoding="utf-8")

    assert "def _validate_reference" in source
    assert "Canal nao encontrado neste servidor." in source
    assert "Cargo nao encontrado ou invalido neste servidor." in source
    assert '"missing_reference": True' in source


def test_dashboard_settings_router_renders_empty_choices_as_text() -> None:
    source = Path("api/routes/admin/settings_router.py").read_text(encoding="utf-8")
    controls = Path("frontend/src/components/SettingsControls.tsx").read_text(encoding="utf-8")

    assert "field.kind == FieldKind.CHOICE and not field.choices" in source
    assert "return \"text\"" in source
    assert "Alguns campos antigos foram marcados como CHOICE" in source
    assert "if (!field.options.length)" in controls
    assert "isEmojiField(field)" in controls
    assert "field.type === \"choice\"" in controls
    assert controls.index("isEmojiField(field)") < controls.index('field.type === "choice"')


def test_dashboard_emoji_override_is_registered_before_generic_settings() -> None:
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")
    emoji_source = Path("api/routes/admin/settings_emoji_router.py").read_text(encoding="utf-8")

    assert "settings_emoji_router" in init_source
    assert init_source.index("router.include_router(settings_emoji_router)") < init_source.index("router.include_router(settings_router)")
    assert "_force_emoji_as_text" in emoji_source
    assert "avaliacoes.star_emoji" in emoji_source
    assert "update_evaluation_settings" in emoji_source
    assert "Painel web" in emoji_source


def test_dashboard_settings_patch_actor_override_is_registered() -> None:
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")
    patch_source = Path("api/routes/admin/settings_patch_router.py").read_text(encoding="utf-8")

    assert "settings_patch_router" in init_source
    assert init_source.index("router.include_router(settings_patch_router)") < init_source.index("router.include_router(settings_router)")
    assert "actor_id=None" in patch_source
    assert "actor_name=_DASHBOARD_ACTOR" in patch_source
    assert "<@0>" in patch_source


def test_audit_log_service_normalizes_zero_executor_id() -> None:
    service = Path("services/audit_log_service.py").read_text(encoding="utf-8")

    assert "executor_id is not None and executor_id <= 0" in service
    assert "executor_id = None" in service
    assert "virava <@0>" in service


def test_dashboard_events_router_is_registered_before_legacy_router() -> None:
    source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")

    assert "events_router" in source
    assert "settings_router" in source
    assert "giveaways_router" in source
    assert "dlcs_router" in source
    assert "panels_router" in source
    assert "staff_router" in source
    assert "ticket_actions_router" in source
    assert "legacy_router" in source
    assert source.index("router.include_router(settings_router)") < source.index("router.include_router(events_router)")
    assert source.index("router.include_router(events_router)") < source.index("router.include_router(giveaways_router)")
    assert source.index("router.include_router(giveaways_router)") < source.index("router.include_router(dlcs_router)")
    assert source.index("router.include_router(dlcs_router)") < source.index("router.include_router(panels_router)")
    assert source.index("router.include_router(panels_router)") < source.index("router.include_router(staff_router)")
    assert source.index("router.include_router(staff_router)") < source.index("router.include_router(ticket_actions_router)")
    assert source.index("router.include_router(ticket_actions_router)") < source.index("router.include_router(legacy_router)")


def test_dashboard_events_router_pushes_invalidation_events() -> None:
    source = Path("api/routes/admin/events_router.py").read_text(encoding="utf-8")

    assert "text/event-stream" in source
    assert "dashboard.invalidate" in source
    assert "settings" in source
    assert "discord-options" in source
    assert "tickets" in source
    assert "dlcs" in source
    assert "giveaways" in source


def test_dashboard_giveaways_use_existing_service_and_discord_view() -> None:
    source = Path("api/routes/admin/giveaways_router.py").read_text(encoding="utf-8")
    service = Path("services/giveaway_service.py").read_text(encoding="utf-8")
    app = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/GiveawaysPage.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/dashboard-overrides.css").read_text(encoding="utf-8")

    assert "bot.giveaway_service.create_giveaway" in source
    assert "GiveawayOpenView" in source
    assert "close_and_announce" in source
    assert "cancel_giveaway" in source
    assert "SORTEIO_CRIADO_PAINEL_WEB" in source
    assert "executor_name=_DASHBOARD_ACTOR" in source
    assert "duration_amount" in source
    assert "duration_unit" in source
    assert "async def cancel_giveaway" in service
    assert '<Route path="/giveaways" element={<GiveawaysPage />} />' in app
    assert '{ label: "Sorteios", to: "/giveaways"' in shell
    assert "role-checkbox" in page
    assert "toggleAllowedRole" in page
    assert "role-checkbox-grid" in css


def test_dashboard_dlcs_use_existing_service_and_safe_actor() -> None:
    source = Path("api/routes/admin/dlcs_router.py").read_text(encoding="utf-8")
    app = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/DlcsPage.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/dashboard-overrides.css").read_text(encoding="utf-8")

    assert "bot.dlc_service.create_free" in source
    assert "bot.dlc_service.create_paid" in source
    assert "bot.dlc_service.update_info" in source
    assert "bot.dlc_service.update_price" in source
    assert "bot.dlc_service.update_role" in source
    assert "bot.dlc_service.toggle_active" in source
    assert "bot.dlc_service.disable" in source
    assert "_DASHBOARD_EXECUTOR" in source
    assert "id = 0" in source
    assert "Painel web" in source
    assert "_price_cents" in source
    assert "role_missing" in source
    assert '<Route path="/dlcs" element={<DlcsPage />} />' in app
    assert '{ label: "DLCs", to: "/dlcs"' in shell
    assert "DLC grátis usa o cargo Verificado" in page
    assert "dlc-grid" in css


def test_dashboard_free_dlc_removal_cleans_announcement_message() -> None:
    source = Path("api/routes/admin/dlcs_router.py").read_text(encoding="utf-8")

    assert "_delete_free_dlc_announcements" in source
    assert "dlc_announcement_channel_id" in source
    assert "history(limit=100)" in source
    assert "message.delete" in source
    assert "await _delete_free_dlc_announcements(bot, guild_id, product" in source


def test_dashboard_free_dlc_edit_updates_existing_announcement() -> None:
    source = Path("api/routes/admin/dlcs_router.py").read_text(encoding="utf-8")

    assert "_sync_free_dlc_announcement" in source
    assert "await first.edit" in source
    assert "duplicates" in source
    assert "old_match_terms" in source
    assert "Se achar a mensagem antiga, edita a propria mensagem" in source
    assert "elif text_changed and is_free and product.is_active" in source


def test_license_role_sync_is_non_destructive_for_existing_roles() -> None:
    reconciliation = Path("services/reconciliation_service.py").read_text(encoding="utf-8")
    role_sync = Path("services/role_sync_service.py").read_text(encoding="utf-8")

    assert "propositalmente nao destrutiva" in reconciliation
    assert "nao remove cargos que alguem" in reconciliation
    assert "startup causou perda em massa" in reconciliation
    assert "Reconciliacao nao destrutiva bloqueou remocao" in reconciliation
    assert "RoleSync nao destrutivo bloqueou evento" in role_sync
    assert "Dublador" in role_sync
    assert "remocao deve ser acao explicita" in role_sync
    assert "await member.remove_roles" not in reconciliation
    assert "await member.remove_roles" not in role_sync


def test_dashboard_panels_use_real_services_and_safe_publish_flow() -> None:
    source = Path("api/routes/admin/panels_router.py").read_text(encoding="utf-8")
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/PanelsPage.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")
    css = Path("frontend/src/dashboard-overrides.css").read_text(encoding="utf-8")

    assert "panels_router" in init_source
    assert "bot.ticket_panel_service.publish_panel" in source
    assert "bot.ticket_panel_service.refresh_panel" in source
    assert "bot.ticket_panel_service.unpublish_panel" in source
    assert "bot.ticket_panel_service.publish_group" in source
    assert "bot.ticket_panel_service.refresh_group" in source
    assert "bot.painel_service.publish_ranking" in source
    assert "bot.painel_service.publish_shop_panel" in source
    assert "bot.painel_service.refresh_shop_panel" in source
    assert "_delete_saved_message" in source
    assert "executor_name=_DASHBOARD_ACTOR" in source
    assert "PAINEL_TICKET_PUBLICADO_WEB" in source
    assert "PAINEL_LOJA_PUBLICADO_WEB" in source
    assert "Painéis do Discord" in page
    assert "Atualizar edita a mensagem existente" in page
    assert "PanelStatus" in api
    assert "panel-grid" in css


def test_dashboard_ticket_actions_use_existing_ticket_services() -> None:
    source = Path("api/routes/admin/ticket_actions_router.py").read_text(encoding="utf-8")
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/TicketsPage.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/dashboard-overrides.css").read_text(encoding="utf-8")

    assert "ticket_actions_router" in init_source
    assert "bot.claim_service.claim_ticket" in source
    assert "bot.claim_service.unclaim_ticket" in source
    assert "bot.ticket_service.close_ticket" in source
    assert "bot.ticket_service.reopen_ticket" in source
    assert "bot.ticket_service.cancel_ticket" in source
    assert "schedule_channel_deletion" in source
    assert "executor_name=_DASHBOARD_ACTOR" in source
    assert "TICKET_ASSUMIDO_PAINEL_WEB" in source
    assert "TICKET_EXCLUIDO_PAINEL_WEB" in source
    assert "Ações do atendimento" in page
    assert "Excluir canal" in page
    assert "ticket-actions-panel" in css


def test_dashboard_ticket_actions_refresh_discord_ticket_embed() -> None:
    source = Path("api/routes/admin/ticket_actions_router.py").read_text(encoding="utf-8")

    assert "def _has_ticket_controls" in source
    assert "async def _refresh_ticket_message" in source
    assert "ticket_embed" in source
    assert "TicketActionsView" in source
    assert "channel.history(limit=25)" in source
    assert "message.edit(embed=embed, view=view)" in source
    assert "Assumido por" in source
    assert "await _refresh_ticket_message(bot, guild, channel, updated)" in source


def test_dashboard_staff_profile_uses_real_staff_tables() -> None:
    source = Path("api/routes/admin/staff_router.py").read_text(encoding="utf-8")
    schemas = Path("api/schemas/admin.py").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/StaffPage.tsx").read_text(encoding="utf-8")
    css = Path("frontend/src/dashboard-overrides.css").read_text(encoding="utf-8")
    init_source = Path("api/routes/admin/__init__.py").read_text(encoding="utf-8")

    assert "staff_router" in init_source
    assert "response_model=StaffDetail" in source
    assert "StaffStats" in source
    assert "Claim" in source
    assert "Evaluation" in source
    assert "current_tickets" in source
    assert "recent_tickets" in source
    assert "avaliacao_media" in source
    assert "StaffDetail" in schemas
    assert "StaffTicketItem" in schemas
    assert "Perfil completo" in page
    assert "Tickets atuais" in page
    assert "Avaliações recebidas" in page
    assert "staff-profile-drawer" in css


def test_dashboard_tickets_refresh_without_tab_switching() -> None:
    events = Path("api/routes/admin/events_router.py").read_text(encoding="utf-8")
    shell = Path("frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")

    assert "tickets" in events
    assert "await asyncio.sleep(5)" in events
    assert "sem o usuario precisar trocar de aba" in events
    assert "EventSource tenta reconectar sozinho" in shell
    assert "source.onerror" in shell
    assert "queryClient.invalidateQueries({ queryKey: [\"ready\"] })" in shell
    onerror_block = shell[shell.index("source.onerror"):shell.index("return () => source.close()")]
    assert "source.close()" not in onerror_block
