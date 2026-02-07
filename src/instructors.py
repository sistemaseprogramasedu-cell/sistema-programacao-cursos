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

FILENAME = "instructors.json"
REQUIRED_FIELDS = ["id", "nome", "email"]


def list_instructors() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_instructor(instructor_id: str) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), instructor_id)


def create_instructor(payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, REQUIRED_FIELDS)
    items = load_items(FILENAME)
    ensure_unique_id(items, payload["id"])
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_instructor(instructor_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    instructor = find_item(items, instructor_id)
    if not instructor:
        raise ValidationError(f"Instrutor não encontrado: {instructor_id}")
    instructor.update(updates)
    require_fields(instructor, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return instructor


def delete_instructor(instructor_id: str) -> None:
    items = load_items(FILENAME)
    instructor = find_item(items, instructor_id)
    if not instructor:
        raise ValidationError(f"Instrutor não encontrado: {instructor_id}")
    items.remove(instructor)
    save_items(FILENAME, items)
