# Dashboard Phase 2 status

Branch: `feat/dashboard-phase2-safe`
Base: `master` at `ea1bf87bb2e71a7e1c52db38e710a296b64a33ee`

## Current status

Phase A is implemented, Phase A.1 is implemented and Phase C.1 is now started. This focuses on the highest-risk dashboard bugs before adding destructive actions like giveaways/DLC edits.

## What is fixed now

- Settings keys are explicit and namespaced, such as `avaliacoes.enabled`, `verificacao.enabled`, `tickets.log_channel_id` and `dashboard.update_interval_minutes`.
- PATCH resolves the namespaced key to the real field attr before calling the existing updater/service.
- The dashboard now rejects ambiguous old keys instead of silently updating the wrong module.
- Settings are still read from the same sources used by `/config` through `views.master_config_view.iter_categories`.
- Channel/role fields are validated against the live Discord guild before saving.
- The UI highlights saved channels/roles that no longer exist in Discord.
- The sidebar no longer shows a fake Sorteios page pointing to alert settings. Sorteios/DLCs must only appear when real CRUD pages exist.
- Time fields show units and keep the value saved in the canonical database unit.
- A local SSE endpoint now pushes `dashboard.invalidate` events every 15 seconds.
- The frontend subscribes to the SSE stream and invalidates dashboard queries, so settings changed through Discord `/config` are refreshed without needing manual F5.

## Why this phase came first

The previous dashboard shape used raw attribute names as API keys. Different settings models reuse names like `enabled`, `log_channel_id`, `channel_id`, `verified_role_id` and `update_interval_minutes`. A dashboard save could therefore target the wrong module.

The new router makes dashboard keys explicit and namespaced. This prevents a web save from corrupting a different `/config` section.

## Files changed

- `api/routes/admin/settings_router.py`
- `api/routes/admin/events_router.py`
- `api/routes/admin/__init__.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/SettingsControls.tsx`
- `frontend/src/components/AppShell.tsx`
- `frontend/src/pages/SettingsPage.tsx`
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
- Write operations still call the existing category update functions/services.
- Channel and role IDs are validated against Discord before saving.
- Ambiguous legacy keys are rejected instead of silently updating the wrong target.
- Auto refresh pauses while a user has unsaved local edits.
- Buttons for features without real web CRUD were not exposed as fake pages.

## Local validation commands

Run from the repository root:

```bash
python -m pytest tests/test_admin_settings_router_static.py
python -m ruff check api/routes/admin/settings_router.py api/routes/admin/events_router.py api/routes/admin/__init__.py tests/test_admin_settings_router_static.py
cd frontend
npm run build
```

## Next phases

- Phase B: read/write action pages for giveaways and DLCs using existing services.
- Phase C.2: replace broad heartbeat invalidation with targeted events emitted by config/save/action paths.
- Phase D: stronger admin identity, rate limits, CSRF/token and permission/hierarchy guards for future write actions.
