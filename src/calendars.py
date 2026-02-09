from __future__ import annotations

from typing import Any, Dict, List

from .storage import (
    ValidationError,
    ensure_unique_id,
    find_item,
    load_items,
    next_numeric_id,
    require_fields,
    save_items,
)

FILENAME = "calendars.json"
ID_FIELD = "ano"
REQUIRED_FIELDS = ["id", "ano", "dias_letivos_por_mes"]


def _normalize_calendars(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    changed = False
    current_max = 0
    for item in items:
        value = item.get("id")
        if isinstance(value, int):
            current_max = max(current_max, value)
        elif isinstance(value, str) and value.isdigit():
            current_max = max(current_max, int(value))
    for item in items:
        if not item.get("id"):
            current_max += 1
            item["id"] = str(current_max)
            changed = True
        if "dias_letivos_por_mes" not in item:
            item["dias_letivos_por_mes"] = [[] for _ in range(12)]
            changed = True
        if "feriados_por_mes" not in item:
            item["feriados_por_mes"] = [[] for _ in range(12)]
            changed = True
    if changed:
        save_items(FILENAME, items)
    return items


def list_calendars() -> List[Dict[str, Any]]:
    return _normalize_calendars(load_items(FILENAME))


def get_calendar(year: int) -> Dict[str, Any] | None:
    return find_item(list_calendars(), year, id_field=ID_FIELD)


def create_calendar(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    if not payload.get("id"):
        payload["id"] = next_numeric_id(items)
    require_fields(payload, REQUIRED_FIELDS)
    ensure_unique_id(items, payload[ID_FIELD], id_field=ID_FIELD)
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_calendar(year: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    calendar = find_item(items, year, id_field=ID_FIELD)
    if not calendar:
        raise ValidationError(f"Calendário não encontrado para o ano: {year}")
    calendar.update(updates)
    require_fields(calendar, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return calendar


def delete_calendar(year: int) -> None:
    items = load_items(FILENAME)
    calendar = find_item(items, year, id_field=ID_FIELD)
    if not calendar:
        raise ValidationError(f"Calendário não encontrado para o ano: {year}")
    items.remove(calendar)
    save_items(FILENAME, items)
