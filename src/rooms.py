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

FILENAME = "rooms.json"
REQUIRED_FIELDS = ["id", "nome", "capacidade", "pavimento"]


def _normalize_room(room: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not room:
        return None
    normalized = dict(room)
    if not normalized.get("pavimento"):
        normalized["pavimento"] = "Térreo"
    return normalized


def list_rooms() -> List[Dict[str, Any]]:
    return [_normalize_room(item) for item in load_items(FILENAME)]


def get_room(room_id: str) -> Dict[str, Any] | None:
    return _normalize_room(find_item(load_items(FILENAME), room_id))


def create_room(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    if not payload.get("id"):
        payload["id"] = next_numeric_id(items)
    require_fields(payload, REQUIRED_FIELDS)
    ensure_unique_id(items, payload["id"])
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_room(room_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    room = find_item(items, room_id)
    if not room:
        raise ValidationError(f"Sala não encontrada: {room_id}")
    room.update(updates)
    if not room.get("pavimento"):
        room["pavimento"] = "Térreo"
    require_fields(room, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return room


def delete_room(room_id: str) -> None:
    items = load_items(FILENAME)
    room = find_item(items, room_id)
    if not room:
        raise ValidationError(f"Sala não encontrada: {room_id}")
    items.remove(room)
    save_items(FILENAME, items)
