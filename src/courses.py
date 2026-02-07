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

FILENAME = "courses.json"
REQUIRED_FIELDS = ["id", "nome", "nivel", "carga_horaria_total"]


def list_courses() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_course(course_id: str) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), course_id)


def create_course(payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, REQUIRED_FIELDS)
    items = load_items(FILENAME)
    ensure_unique_id(items, payload["id"])
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_course(course_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    course = find_item(items, course_id)
    if not course:
        raise ValidationError(f"Curso não encontrado: {course_id}")
    course.update(updates)
    require_fields(course, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return course


def delete_course(course_id: str) -> None:
    items = load_items(FILENAME)
    course = find_item(items, course_id)
    if not course:
        raise ValidationError(f"Curso não encontrado: {course_id}")
    items.remove(course)
    save_items(FILENAME, items)
