from __future__ import annotations

from typing import Any, Dict, List

from .storage import (
    ValidationError,
    ensure_unique_id,
    find_item,
    load_items,
    next_sequential_int,
    require_fields,
    save_items,
)

FILENAME = "calendars.json"
ID_FIELD = "id"
REQUIRED_FIELDS = ["ano", "dias_letivos"]


def list_calendars() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_calendar(calendar_id: int) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), calendar_id, id_field=ID_FIELD)


def create_calendar(payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, REQUIRED_FIELDS)
    items = load_items(FILENAME)
    payload[ID_FIELD] = next_sequential_int(items, id_field=ID_FIELD)
    ensure_unique_id(items, payload[ID_FIELD], id_field=ID_FIELD)
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_calendar(calendar_id: int, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    calendar = find_item(items, calendar_id, id_field=ID_FIELD)
    if not calendar:
        raise ValidationError(f"Calendário não encontrado: {calendar_id}")
    calendar.update(updates)
    require_fields(calendar, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return calendar


def delete_calendar(calendar_id: int) -> None:
    items = load_items(FILENAME)
    calendar = find_item(items, calendar_id, id_field=ID_FIELD)
    if not calendar:
        raise ValidationError(f"Calendário não encontrado: {calendar_id}")
    items.remove(calendar)
    save_items(FILENAME, items)
