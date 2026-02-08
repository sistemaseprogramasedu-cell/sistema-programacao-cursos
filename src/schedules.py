from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Dict, List

from .storage import (
    ValidationError,
    ensure_unique_id,
    find_item,
    load_items,
    require_fields,
    save_items,
)

FILENAME = "schedules.json"
COURSES_FILE = "courses.json"
UNITS_FILE = "curricular_units.json"
INSTRUCTORS_FILE = "instructors.json"
ROOMS_FILE = "rooms.json"
SHIFTS_FILE = "shifts.json"
REQUIRED_FIELDS = [
    "id",
    "curso_id",
    "unidade_id",
    "instrutor_id",
    "sala_id",
    "turno_id",
    "data_inicio",
    "data_fim",
]


@dataclass(frozen=True)
class Shift:
    name: str
    start: time
    end: time
    days: List[str]


def list_schedules() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_schedule(schedule_id: str) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), schedule_id)


def create_schedule(payload: Dict[str, Any]) -> Dict[str, Any]:
    require_fields(payload, REQUIRED_FIELDS)
    items = load_items(FILENAME)
    ensure_unique_id(items, payload["id"])
    _validate_references(payload)
    _validate_conflicts(items, payload)
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_schedule(schedule_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    schedule = find_item(items, schedule_id)
    if not schedule:
        raise ValidationError(f"Programação não encontrada: {schedule_id}")
    schedule.update(updates)
    require_fields(schedule, REQUIRED_FIELDS)
    _validate_references(schedule)
    remaining = [item for item in items if item.get("id") != schedule_id]
    _validate_conflicts(remaining, schedule)
    save_items(FILENAME, items)
    return schedule


def delete_schedule(schedule_id: str) -> None:
    items = load_items(FILENAME)
    schedule = find_item(items, schedule_id)
    if not schedule:
        raise ValidationError(f"Programação não encontrada: {schedule_id}")
    items.remove(schedule)
    save_items(FILENAME, items)


def _validate_references(payload: Dict[str, Any]) -> None:
    _ensure_exists(COURSES_FILE, payload["curso_id"], "Curso")
    _ensure_exists(UNITS_FILE, payload["unidade_id"], "Unidade curricular")
    _ensure_exists(INSTRUCTORS_FILE, payload["instrutor_id"], "Colaborador")
    _ensure_exists(ROOMS_FILE, payload["sala_id"], "Sala")
    _ensure_exists(SHIFTS_FILE, payload["turno_id"], "Turno")


def _ensure_exists(filename: str, item_id: str, label: str) -> None:
    items = load_items(filename)
    if not find_item(items, item_id):
        raise ValidationError(f"{label} não encontrado: {item_id}")


def _parse_date(raw: str) -> datetime:
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError(f"Data inválida: {raw}") from exc


def _parse_time(raw: str) -> time:
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError as exc:
        raise ValidationError(f"Horário inválido: {raw}") from exc


def _load_shift(shift_id: str) -> Shift:
    shifts = load_items(SHIFTS_FILE)
    shift = find_item(shifts, shift_id)
    if not shift:
        raise ValidationError(f"Turno não encontrado: {shift_id}")
    start = _parse_time(shift.get("horario_inicio", ""))
    end = _parse_time(shift.get("horario_fim", ""))
    days = shift.get("dias_semana") or []
    if not days:
        raise ValidationError(f"Turno sem dias da semana configurados: {shift_id}")
    return Shift(name=shift.get("nome", ""), start=start, end=end, days=days)


def _date_ranges_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a <= end_b and start_b <= end_a


def _times_overlap(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    return start_a < end_b and start_b < end_a


def _validate_conflicts(existing: List[Dict[str, Any]], payload: Dict[str, Any]) -> None:
    start = _parse_date(payload["data_inicio"])
    end = _parse_date(payload["data_fim"])
    if start > end:
        raise ValidationError("Data início não pode ser maior que data fim.")
    shift = _load_shift(payload["turno_id"])
    _validate_instructor_workload(existing, payload, shift)

    for item in existing:
        if item.get("turno_id") != payload["turno_id"]:
            # horários diferentes só conflitam se o turno cruzar horários
            other_shift = _load_shift(item.get("turno_id"))
        else:
            other_shift = shift

        if not _date_ranges_overlap(
            start,
            end,
            _parse_date(item.get("data_inicio", "")),
            _parse_date(item.get("data_fim", "")),
        ):
            continue

        if not set(shift.days).intersection(other_shift.days):
            continue

        if not _times_overlap(shift.start, shift.end, other_shift.start, other_shift.end):
            continue

        if item.get("sala_id") == payload["sala_id"]:
            raise ValidationError("Conflito de sala: horário já reservado.")
        if item.get("instrutor_id") == payload["instrutor_id"]:
            raise ValidationError("Conflito de colaborador: horário já reservado.")


def _validate_instructor_workload(
    existing: List[Dict[str, Any]],
    payload: Dict[str, Any],
    shift: Shift,
) -> None:
    instructors = load_items(INSTRUCTORS_FILE)
    instructor = find_item(instructors, payload["instrutor_id"])
    if not instructor:
        raise ValidationError(f"Colaborador não encontrado: {payload['instrutor_id']}")
    limit = instructor.get("max_horas_semana")
    if limit is None:
        return

    duration_hours = _shift_duration_hours(shift)
    weekly_hours = duration_hours * len(shift.days)

    total = weekly_hours
    for item in existing:
        if item.get("instrutor_id") != payload["instrutor_id"]:
            continue
        other_shift = _load_shift(item.get("turno_id"))
        total += _shift_duration_hours(other_shift) * len(other_shift.days)

    if total > float(limit):
        raise ValidationError(
            "Limite de carga horária semanal excedido para o colaborador."
        )


def _shift_duration_hours(shift: Shift) -> float:
    start_minutes = shift.start.hour * 60 + shift.start.minute
    end_minutes = shift.end.hour * 60 + shift.end.minute
    if end_minutes <= start_minutes:
        raise ValidationError("Turno inválido: horário final deve ser maior que o inicial.")
    return (end_minutes - start_minutes) / 60
