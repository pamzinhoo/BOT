# Dashboard Phase 2 status

Branch: `feat/dashboard-phase2-safe`
Base: `master` at `ea1bf87bb2e71a7e1c52db38e710a296b64a33ee`

## Current status

Phase A is implemented, Phase A.1 is implemented, Phase A.2 fixed boolean persistence/display, Phase C.1 is started, and Phase B.1 added the first real operational page: Giveaways.

## What is fixed now

- Settings keys are explicit and namespaced, such as `avaliacoes.enabled`, `verificacao.enabled`, `tickets.log_channel_id` and `dashboard.update_interval_minutes`.
- PATCH resolves the namespaced key to the real field attr before calling the existing updater/service.
- The dashboard now rejects ambiguous old keys instead of silently updating the wrong module.
- Settings are still read from the same sources used by `/config` through `views.master_config_view.iter_categories`.
- Channel/role fields are validated against the live Discord guild before saving.
- The UI highlights saved channels/roles that no longer exist in Discord.
- Boolean values now remain booleans in the settings API. This fixes toggles like `verificacao.enabled` appearing active again after saving `false`.
- Time fields show units and keep the value saved in the canonical database unit.
- A local SSE endpoint now pushes `dashboard.invalidate` events every 15 seconds.
- The frontend subscribes to the SSE stream and invalidates dashboard queries, so settings changed through Discord `/config` are refreshed without needing manual F5.
- The dashboard now has `/giveaways` as a real page, not a fake sidebar link.
- Giveaways can be listed, created/published, closed, canceled and rerolled through API routes that call the existing giveaway service/cog flow.
- The giveaway creation form now uses checkbox cards for allowed roles instead of native multi-select.
- Giveaway duration now supports minutes, hours and days in the web form/API.
- New giveaway audit logs created by the dashboard are attributed to `Painel web` instead of mentioning `<@0>`.

## Giveaway phase details

New backend files/changes:

- `api/routes/admin/giveaways_router.py`
- `services/giveaway_service.py` with `cancel_giveaway`
- `api/routes/admin/__init__.py` registering `giveaways_router`

New frontend files/changes:

- `frontend/src/pages/GiveawaysPage.tsx`
- `frontend/src/App.tsx` route `/giveaways`
- `frontend/src/components/AppShell.tsx` sidebar item
- `frontend/src/lib/api.ts` giveaway types
- `frontend/src/dashboard-overrides.css` page styles

The create action validates channel, roles, prize type, title, duration and winner count before publishing the Discord message.

## Why settings phase came first

The previous dashboard shape used raw attribute names as API keys. Different settings models reuse names like `enabled`, `log_channel_id`, `channel_id`, `verified_role_id` and `update_interval_minutes`. A dashboard save could therefore target the wrong module.

The new router makes dashboard keys explicit and namespaced. This prevents a web save from corrupting a different `/config` section.

## Files changed

- `api/routes/admin/settings_router.py`
- `api/routes/admin/events_router.py`
- `api/routes/admin/giveaways_router.py`
- `api/routes/admin/__init__.py`
- `services/giveaway_service.py`
- `views/embeds.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/SettingsControls.tsx`
- `frontend/src/components/AppShell.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/pages/GiveawaysPage.tsx`
- `frontend/src/App.tsx`
- `frontend/src/main.tsx`
- `frontend/src/dashboard-overrides.css`
- `tests/test_admin_settings_router_static.py`
- `docs/DASHBOARD_PHASE2_PLAN.md`
- `docs/DASHBOARD_100_PERCENT_PLAN.md`

## Risk controls

- No DB migration was added.
- Existing legacy admin router remains in the project.
- New settings router is registered before legacy routes so only the settings endpoints are replaced.
- The events router is separate from the legacy router and only exposes a local-only read/event stream.
- Giveaway write actions call `GiveawayService`, `close_and_announce` and the persistent Discord view instead of duplicating business logic.
- Channel and role IDs are validated against Discord before saving/creating actions.
- Ambiguous legacy keys are rejected instead of silently updating the wrong target.
- Auto refresh pauses while a user has unsaved local edits.
- Buttons for features without real web CRUD, such as DLCs, remain hidden until implemented.

## Local validation commands

Run from the repository root:

```bash
python -m pytest tests/test_admin_settings_router_static.py
python -m ruff check api/routes/admin/settings_router.py api/routes/admin/events_router.py api/routes/admin/giveaways_router.py api/routes/admin/__init__.py services/giveaway_service.py tests/test_admin_settings_router_static.py
cd frontend
npm run build
```

## Manual test checklist

1. Open `/admin/giveaways`.
2. Create a custom-prize giveaway with a short duration and a text channel.
3. Confirm the Discord message appears with the participation buttons.
4. Join/leave from Discord.
5. Confirm the dashboard participant count updates.
6. Close the giveaway from the dashboard.
7. Confirm the Discord result embed appears.
8. Reroll from the dashboard after closed.
9. Create another giveaway and cancel it from the dashboard.
10. Confirm canceled giveaways cannot be joined.
11. Create a giveaway restricted to one role and confirm only that role can join.
12. Confirm the audit log says `Executor: Painel web` for dashboard-created giveaways.

## Next phases

- Phase B.2: DLC read/write page using `DlcService`.
- Phase B.3: Discord panels page with real republish/refresh actions.
- Phase B.4: ticket/staff operational actions.
- Phase B.5: monetization/plan/coupon/payment pages.
- Phase B.6: moderation/appeals page.
- Phase C.2: replace broad heartbeat invalidation with targeted events emitted by config/save/action paths.
- Phase D: stronger admin identity, rate limits, CSRF/token and permission/hierarchy guards for future write actions.
