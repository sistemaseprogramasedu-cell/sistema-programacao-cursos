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

FILENAME = "shifts.json"
REQUIRED_FIELDS = ["id", "nome", "horario_inicio", "horario_fim"]


def list_shifts() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_shift(shift_id: str) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), shift_id)


def create_shift(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    if not payload.get("id"):
        payload["id"] = next_numeric_id(items)
    require_fields(payload, REQUIRED_FIELDS)
    ensure_unique_id(items, payload["id"])
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_shift(shift_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    shift = find_item(items, shift_id)
    if not shift:
        raise ValidationError(f"Turno não encontrado: {shift_id}")
    shift.update(updates)
    require_fields(shift, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return shift


def delete_shift(shift_id: str) -> None:
    items = load_items(FILENAME)
    shift = find_item(items, shift_id)
    if not shift:
        raise ValidationError(f"Turno não encontrado: {shift_id}")
    items.remove(shift)
    save_items(FILENAME, items)
