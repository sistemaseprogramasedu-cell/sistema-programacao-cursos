from __future__ import annotations

from typing import Any, Dict, List

from .storage import (
    ValidationError,
    ensure_unique_id,
    find_item,
    load_items,
    next_sequential_id,
    require_fields,
    save_items,
)

FILENAME = "curricular_units.json"
COURSES_FILE = "courses.json"
REQUIRED_FIELDS = ["id", "curso_id", "nome"]


def list_units() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_unit(unit_id: str) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), unit_id)


def _ensure_course_exists(course_id: str) -> None:
    courses = load_items(COURSES_FILE)
    if not find_item(courses, course_id):
        raise ValidationError(f"Curso não encontrado para a unidade: {course_id}")


def create_unit(payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, REQUIRED_FIELDS)
    _ensure_course_exists(payload["curso_id"])
    items = load_items(FILENAME)
    ensure_unique_id(items, payload["id"])
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_unit(unit_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    unit = find_item(items, unit_id)
    if not unit:
        raise ValidationError(f"Unidade curricular não encontrada: {unit_id}")
    if "curso_id" in updates:
        _ensure_course_exists(updates["curso_id"])
    unit.update(updates)
    require_fields(unit, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return unit


def delete_unit(unit_id: str) -> None:
    items = load_items(FILENAME)
    unit = find_item(items, unit_id)
    if not unit:
        raise ValidationError(f"Unidade curricular não encontrada: {unit_id}")
    items.remove(unit)
    save_items(FILENAME, items)


def _parse_names(raw_names: str | List[str]) -> List[str]:
    if isinstance(raw_names, str):
        names = [line.strip() for line in raw_names.splitlines()]
    else:
        names = [str(name).strip() for name in raw_names]
    return [name for name in names if name]


def create_units_batch(course_id: str, raw_names: str | List[str]) -> List[Dict[str, Any]]:
    _ensure_course_exists(course_id)
    names = _parse_names(raw_names)
    if not names:
        raise ValidationError("Nenhuma unidade curricular informada para cadastro em lote.")
    items = load_items(FILENAME)
    created: List[Dict[str, Any]] = []
    for name in names:
        new_id = next_sequential_id(items, prefix="UC-")
        payload = {"id": new_id, "curso_id": course_id, "nome": name}
        ensure_unique_id(items, new_id)
        items.append(payload)
        created.append(payload)
    save_items(FILENAME, items)
    return created


def _parse_batch_lines(raw_lines: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for line in raw_lines.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        parts = [part.strip() for part in cleaned.split(";", 1)]
        name = parts[0]
        hours = None
        if len(parts) > 1 and parts[1]:
            try:
                hours = float(parts[1])
            except ValueError:
                hours = parts[1]
        entries.append({"nome": name, "carga_horaria": hours})
    return entries


def create_units_batch_from_lines(course_id: str, raw_lines: str) -> List[Dict[str, Any]]:
    _ensure_course_exists(course_id)
    entries = _parse_batch_lines(raw_lines)
    if not entries:
        raise ValidationError("Nenhuma unidade curricular informada para cadastro em lote.")
    items = load_items(FILENAME)
    created: List[Dict[str, Any]] = []
    for entry in entries:
        new_id = next_sequential_id(items, prefix="UC-")
        payload: Dict[str, Any] = {
            "id": new_id,
            "curso_id": course_id,
            "nome": entry["nome"],
        }
        if entry.get("carga_horaria") is not None:
            payload["carga_horaria"] = entry["carga_horaria"]
        ensure_unique_id(items, new_id)
        items.append(payload)
        created.append(payload)
    save_items(FILENAME, items)
    return created
