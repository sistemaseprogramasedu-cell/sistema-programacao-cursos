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

FILENAME = "rooms.json"
REQUIRED_FIELDS = ["nome", "capacidade"]


def list_rooms() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_room(room_id: str) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), room_id)


def create_room(payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, REQUIRED_FIELDS)
    items = load_items(FILENAME)
    payload["id"] = next_sequential_int(items)
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
