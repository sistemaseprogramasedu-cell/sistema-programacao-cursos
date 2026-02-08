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
ALLOWED_ROLES = {"Instrutor", "Analista", "Assistente"}


def _normalize_role(value: Any) -> str:
    role = (value or "Instrutor").strip()
    if role not in ALLOWED_ROLES:
        raise ValidationError(f"Categoria inválida para colaborador: {role}")
    return role


def _with_default_role(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    normalized["role"] = _normalize_role(normalized.get("role"))
    return normalized


def list_instructors() -> List[Dict[str, Any]]:
    return [_with_default_role(item) for item in load_items(FILENAME)]


def get_instructor(instructor_id: str) -> Dict[str, Any] | None:
    item = find_item(load_items(FILENAME), instructor_id)
    return _with_default_role(item) if item else None


def create_instructor(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = _with_default_role(payload)
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
        raise ValidationError(f"Colaborador não encontrado: {instructor_id}")
    updates = _with_default_role(updates)
    instructor.update(updates)
    require_fields(instructor, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return instructor


def delete_instructor(instructor_id: str) -> None:
    items = load_items(FILENAME)
    instructor = find_item(items, instructor_id)
    if not instructor:
        raise ValidationError(f"Colaborador não encontrado: {instructor_id}")
    items.remove(instructor)
    save_items(FILENAME, items)
