# Dashboard Phase 2 status

Branch: `feat/dashboard-phase2-safe`
Base: `master` at `ea1bf87bb2e71a7e1c52db38e710a296b64a33ee`

## Current status

Phase A is implemented. It focuses on the highest-risk dashboard bug: settings key collisions between modules.

## Why this phase came first

The previous dashboard shape used raw attribute names as API keys. Different settings models reuse names like `enabled`, `log_channel_id`, `channel_id`, `verified_role_id` and `update_interval_minutes`. A dashboard save could therefore target the wrong module.

The new router makes dashboard keys explicit and namespaced, such as `avaliacoes.enabled` and `verificacao.enabled`.

## Files changed

- `api/routes/admin/settings_router.py`
- `api/routes/admin/__init__.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/SettingsControls.tsx`
- `frontend/src/components/AppShell.tsx`
- `frontend/src/pages/SettingsPage.tsx`
- `frontend/src/main.tsx`
- `frontend/src/dashboard-overrides.css`
- `docs/DASHBOARD_PHASE2_PLAN.md`

## Risk controls

- No DB migration was added.
- Existing legacy admin router remains in the project.
- New settings router is registered before legacy routes so only the settings endpoints are replaced.
- Write operations still call the existing category update functions/services.
- Ambiguous legacy keys are rejected instead of silently updating the wrong target.
- Auto refresh pauses while a user has unsaved local edits.

## Next phases

- Phase B: web pages/actions for giveaways and DLCs.
- Phase C: SSE/live invalidation for dashboard updates.
- Phase D: stronger admin identity, rate limits, CSRF/token and permission/hierarchy guards for future write actions.
