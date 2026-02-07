from __future__ import annotations

from typing import Any, Dict, List

from .storage import (
    ValidationError,
    ensure_unique_id,
    find_item,
    load_items,
    require_fields,
    save_items,
)

FILENAME = "calendars.json"
ID_FIELD = "ano"
REQUIRED_FIELDS = ["ano", "periodos"]


def list_calendars() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_calendar(year: int) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), year, id_field=ID_FIELD)


def create_calendar(payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, REQUIRED_FIELDS)
    items = load_items(FILENAME)
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
