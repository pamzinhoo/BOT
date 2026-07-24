from __future__ import annotations

from typing import Any

_DEFAULT_RESET_EXCLUDED = frozenset({"id", "guild_id", "updated_at"})


def column_default(model: type, attr: str) -> Any:
    """Valor padrão declarado na coluna do model — a mesma usada quando uma
    guild configura o bot pela primeira vez (get_or_create). Fonte única pra
    reset de configurações: nunca hardcodar o valor padrão em outro lugar."""
    column = model.__table__.columns[attr]
    default = column.default
    if default is None:
        return None
    if default.is_scalar:
        return default.arg
    if default.is_callable:
        try:
            return default.arg()
        except TypeError:
            return default.arg(None)
    return None


def diff_defaults(
    row: Any, *, excluded: frozenset[str] = _DEFAULT_RESET_EXCLUDED
) -> dict[str, tuple[Any, Any]]:
    """Compara `row` com os valores padrão do model. Retorna {campo: (antes, depois)}
    só dos campos que estão diferentes do padrão — não modifica `row`."""
    model = type(row)
    diffs: dict[str, tuple[Any, Any]] = {}
    for column in model.__table__.columns:
        if column.name in excluded:
            continue
        default = column_default(model, column.name)
        before = getattr(row, column.name)
        if before != default:
            diffs[column.name] = (before, default)
    return diffs


def reset_row(
    row: Any, *, excluded: frozenset[str] = _DEFAULT_RESET_EXCLUDED
) -> dict[str, tuple[Any, Any]]:
    """Restaura todos os campos de `row` (exceto id/guild_id/updated_at) pros
    valores padrão do model. Retorna {campo: (antes, depois)} só do que mudou."""
    diffs = diff_defaults(row, excluded=excluded)
    for name, (_, after) in diffs.items():
        setattr(row, name, after)
    return diffs
