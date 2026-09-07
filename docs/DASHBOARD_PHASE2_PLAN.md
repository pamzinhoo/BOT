# Web Dashboard — Phase 2 plan

This branch is intentionally split into safe layers so the dashboard does not corrupt bot configuration.

## Done in this branch

### Phase A — settings foundation

- Added a dedicated dashboard settings router registered before the legacy admin router.
- Settings are now addressed by namespaced keys, for example:
  - `avaliacoes.enabled`
  - `verificacao.enabled`
  - `tickets.log_channel_id`
  - `moderacao.log_channel_id`
- Legacy unqualified keys are accepted only when they resolve to exactly one setting. Ambiguous keys are rejected instead of updating the wrong module.
- `PATCH /admin/api/guild/{guild_id}/settings` now maps every namespaced key back to the exact original `SettingsField.attr` before calling the existing services.
- All categories exposed by `views.master_config_view.iter_categories()` are returned to the web dashboard instead of only the previous partial subset.
- Numeric time fields expose metadata with storage unit and display unit options.
- The frontend settings screen renders duration controls with selectable seconds/minutes/hours/days while still saving the canonical DB unit.
- Settings refresh automatically every 30 seconds while there are no unsaved edits, avoiding accidental overwrite of a local draft.
- Discord channel/role options refresh every 60 seconds.
- Sidebar now exposes the main settings sections that already exist in the Discord `/config` system.

## Not done yet

These are intentionally left out of Phase A because they create/edit operational entities and need service-level permission/audit rules:

- Web CRUD for giveaways.
- Web CRUD for DLCs/products/plans.
- Web moderation/punishment actions.
- SSE/WebSocket live events.
- Real admin login/actor identity beyond the current local dashboard guard.

## Manual validation checklist

1. Run `setup_dashboard.bat` after pulling this branch.
2. Run `start_dashboard.bat`.
3. Open `/admin/settings/avaliacoes` and `/admin/settings/verificacao`.
4. Change only `avaliacoes.enabled`, save, and confirm `verificacao.enabled` did not change.
5. Change only `verificacao.enabled`, save, and confirm `avaliacoes.enabled` did not change.
6. Test a channel field that appears in more than one section and confirm the intended section is the one changed.
7. Test a duration field such as ticket inactivity or delete delay using hours/minutes and confirm the saved value remains correct.
8. Confirm no Discord `/config` behavior changed.

## Rollback

Because the legacy admin router is still present, rollback is low-risk:

1. Revert the commits from this branch, or
2. Restore `api/routes/admin/__init__.py` to import only `router` from `api.routes.admin.router`.

No database migration was added in Phase A.
