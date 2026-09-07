# Review notes

This branch should be reviewed before merging.

## Expected behavior changes

- Settings API keys are namespaced by dashboard section.
- Frontend saves namespaced keys.
- Ambiguous old keys are no longer accepted.
- All resettable/configurable categories from the Discord config registry are visible in the web settings response.
- Time fields are displayed with a selectable unit but stored in the original DB unit.

## Things to check locally

```bash
python -m pytest tests/test_admin_settings_router_static.py
python -m ruff check api/routes/admin/settings_router.py api/routes/admin/__init__.py tests/test_admin_settings_router_static.py
cd frontend
npm run build
```

## Manual dashboard checks

- `/admin/settings/avaliacoes`
- `/admin/settings/verificacao`
- `/admin/settings/tickets`
- `/admin/settings/dashboard`
- `/admin/settings/parcerias`
- `/admin/settings/boost`
- `/admin/settings/moderacao`

The critical regression check is changing `avaliacoes.enabled` without changing `verificacao.enabled`, then doing the opposite.
