from __future__ import annotations

from typing import Any, Dict, List

from .storage import (
    ValidationError,
    ensure_unique_id,
    find_item,
    load_items,
    next_numeric_id,
    next_sequential_id,
    require_fields,
    save_items,
)

FILENAME = "courses.json"
UNITS_FILE = "curricular_units.json"
REQUIRED_FIELDS = ["id", "nome", "tipo_curso", "carga_horaria_total"]


def _normalize_course(course: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not course:
        return None
    normalized = dict(course)
    if not normalized.get("tipo_curso") and normalized.get("nivel"):
        normalized["tipo_curso"] = normalized["nivel"]
    if normalized.get("tipo_curso") and not normalized.get("nivel"):
        normalized["nivel"] = normalized["tipo_curso"]
    return normalized


def list_courses() -> List[Dict[str, Any]]:
    return [_normalize_course(item) for item in load_items(FILENAME)]


def get_course(course_id: str) -> Dict[str, Any] | None:
    return _normalize_course(find_item(load_items(FILENAME), course_id))


def _parse_hours(value: Any) -> float:
    if value is None:
        raise ValidationError("Carga horária total inválida.")
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace(",", ".")
    if not cleaned:
        raise ValidationError("Carga horária total inválida.")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise ValidationError("Carga horária total inválida.") from exc


def _prepare_units(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prepared = []
    for index, unit in enumerate(units, start=1):
        name = str(unit.get("nome", "")).strip()
        if not name:
            raise ValidationError(f"Nome da UC {index} é obrigatório.")
        raw_hours = unit.get("carga_horaria")
        if raw_hours in (None, ""):
            raise ValidationError(f"Carga horária da UC {index} é obrigatória.")
        try:
            hours = float(str(raw_hours).replace(",", ".").strip())
        except ValueError as exc:
            raise ValidationError(f"Carga horária da UC {index} inválida.") from exc
        prepared.append({"nome": name, "carga_horaria": hours})
    return prepared


def _validate_units_sum(total_hours: float, units: List[Dict[str, Any]]) -> None:
    total_units = sum(unit["carga_horaria"] for unit in units)
    if total_units > total_hours:
        delta = total_units - total_hours
        raise ValidationError(
            f"A soma das CH das UCs está MAIOR que a Carga Horária Total do curso. Diferença: {delta:g}."
        )
    if total_units < total_hours:
        delta = total_hours - total_units
        raise ValidationError(
            f"A soma das CH das UCs está MENOR que a Carga Horária Total do curso. Diferença: {delta:g}."
        )


def _sync_units(course_id: str, units: List[Dict[str, Any]]) -> None:
    items = load_items(UNITS_FILE)
    existing = [unit for unit in items if unit.get("curso_id") == course_id]
    remaining = [unit for unit in items if unit.get("curso_id") != course_id]
    updated: List[Dict[str, Any]] = []

    for index, unit in enumerate(units):
        if index < len(existing):
            current = dict(existing[index])
            current.update(unit)
            updated.append(current)
        else:
            new_id = next_sequential_id(remaining + updated, prefix="UC-")
            payload = {"id": new_id, "curso_id": course_id, **unit}
            updated.append(payload)

    remaining.extend(updated)
    save_items(UNITS_FILE, remaining)


def create_course(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = _normalize_course(payload) or {}
    units = payload.pop("curricular_units", None)
    items = load_items(FILENAME)
    if not payload.get("id"):
        payload["id"] = next_numeric_id(items)
    if payload.get("tipo_curso") and not payload.get("nivel"):
        payload["nivel"] = payload["tipo_curso"]
    require_fields(payload, REQUIRED_FIELDS)
    ensure_unique_id(items, payload["id"])
    if units is not None:
        prepared_units = _prepare_units(units)
        total_hours = _parse_hours(payload.get("carga_horaria_total"))
        _validate_units_sum(total_hours, prepared_units)
    items.append(payload)
    save_items(FILENAME, items)
    if units is not None:
        _sync_units(payload["id"], prepared_units)
    return payload


def update_course(course_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    course = find_item(items, course_id)
    if not course:
        raise ValidationError(f"Curso não encontrado: {course_id}")
    updates = _normalize_course(updates) or {}
    units = updates.pop("curricular_units", None)
    course.update(updates)
    if course.get("tipo_curso") and not course.get("nivel"):
        course["nivel"] = course["tipo_curso"]
    require_fields(course, REQUIRED_FIELDS)
    if units is not None:
        prepared_units = _prepare_units(units)
        total_hours = _parse_hours(course.get("carga_horaria_total"))
        _validate_units_sum(total_hours, prepared_units)
    save_items(FILENAME, items)
    if units is not None:
        _sync_units(course_id, prepared_units)
    return course


def delete_course(course_id: str) -> None:
    items = load_items(FILENAME)
    course = find_item(items, course_id)
    if not course:
        raise ValidationError(f"Curso não encontrado: {course_id}")
    items.remove(course)
    save_items(FILENAME, items)
