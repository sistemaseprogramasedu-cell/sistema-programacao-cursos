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

FILENAME = "instructors.json"
REQUIRED_FIELDS = ["id", "nome", "nome_sobrenome", "email", "telefone", "role"]
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


def _build_short_name(full_name: str) -> str:
    parts = [part for part in full_name.split() if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1]}"


def _normalize_instructor(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _with_default_role(payload)
    full_name = str(normalized.get("nome", "")).strip()
    short_name = normalized.get("nome_sobrenome") or normalized.get("nome_curto")
    if not short_name and full_name:
        normalized["nome_sobrenome"] = _build_short_name(full_name)
    elif short_name:
        normalized["nome_sobrenome"] = str(short_name).strip()
    return normalized


def list_instructors() -> List[Dict[str, Any]]:
    return [_normalize_instructor(item) for item in load_items(FILENAME)]


def get_instructor(instructor_id: str) -> Dict[str, Any] | None:
    item = find_item(load_items(FILENAME), instructor_id)
    return _normalize_instructor(item) if item else None


def create_instructor(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = _normalize_instructor(payload)
    items = load_items(FILENAME)
    if not payload.get("id"):
        payload["id"] = next_numeric_id(items)
    require_fields(payload, REQUIRED_FIELDS)
    ensure_unique_id(items, payload["id"])
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_instructor(instructor_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    instructor = find_item(items, instructor_id)
    if not instructor:
        raise ValidationError(f"Colaborador não encontrado: {instructor_id}")
    updates = _normalize_instructor(updates)
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
