from __future__ import annotations

from datetime import date, datetime, time
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

FILENAME = "schedules.json"
COURSES_FILE = "courses.json"
INSTRUCTORS_FILE = "instructors.json"
ROOMS_FILE = "rooms.json"
SHIFTS_FILE = "shifts.json"
REQUIRED_FIELDS = [
    "id",
    "ano",
    "mes",
    "curso_id",
    "instrutor_id",
    "analista_id",
    "sala_id",
    "pavimento",
    "qtd_alunos",
    "turno_id",
    "data_inicio",
    "data_fim",
    "ch_total",
    "hora_inicio",
    "hora_fim",
    "turma",
    "dias_execucao",
]


def list_schedules() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def get_schedule(schedule_id: str) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), schedule_id)


def create_schedule(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    if not payload.get("id"):
        payload["id"] = next_numeric_id(items)
    require_fields(payload, REQUIRED_FIELDS)
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
    _ensure_instructor(payload["instrutor_id"], "Instrutor")
    _ensure_instructor(payload["analista_id"], "Analista")
    _ensure_exists(ROOMS_FILE, payload["sala_id"], "Ambiente")
    _ensure_exists(SHIFTS_FILE, payload["turno_id"], "Turno")


def _ensure_exists(filename: str, item_id: str, label: str) -> None:
    items = load_items(filename)
    if not find_item(items, item_id):
        raise ValidationError(f"{label} não encontrado: {item_id}")


def _ensure_instructor(instructor_id: str, role: str) -> None:
    items = load_items(INSTRUCTORS_FILE)
    instructor = find_item(items, instructor_id)
    if not instructor:
        raise ValidationError(f"Colaborador não encontrado: {instructor_id}")
    if instructor.get("role") != role:
        raise ValidationError(f"Colaborador informado não é da categoria {role}.")


def _parse_date(raw: str) -> date:
    formats = ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValidationError(f"Data inválida: {raw}")


def _parse_time(raw: str) -> time:
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError as exc:
        raise ValidationError(f"Horário inválido: {raw}") from exc


def _date_ranges_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    return start_a <= end_b and start_b <= end_a


def _times_overlap(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    return start_a < end_b and start_b < end_a


def _validate_conflicts(existing: List[Dict[str, Any]], payload: Dict[str, Any]) -> None:
    start = _parse_date(payload["data_inicio"])
    end = _parse_date(payload["data_fim"])
    if start > end:
        raise ValidationError("Data início não pode ser maior que data fim.")
    _validate_dates_and_times(payload)
    _validate_instructor_workload(existing, payload)

    payload_days = set(payload.get("dias_execucao") or [])
    start_time = _parse_time(payload["hora_inicio"])
    end_time = _parse_time(payload["hora_fim"])

    for item in existing:
        if not item.get("data_inicio") or not item.get("data_fim"):
            continue
        if not _date_ranges_overlap(
            start,
            end,
            _parse_date(item.get("data_inicio", "")),
            _parse_date(item.get("data_fim", "")),
        ):
            continue

        other_days = set(item.get("dias_execucao") or [])
        if payload_days and other_days and not payload_days.intersection(other_days):
            continue

        if item.get("hora_inicio") and item.get("hora_fim"):
            other_start = _parse_time(item.get("hora_inicio", ""))
            other_end = _parse_time(item.get("hora_fim", ""))
            if not _times_overlap(start_time, end_time, other_start, other_end):
                continue

        if item.get("sala_id") == payload["sala_id"]:
            raise ValidationError("Conflito de ambiente: horário já reservado.")
        if item.get("instrutor_id") == payload["instrutor_id"]:
            raise ValidationError("Conflito de instrutor: horário já reservado.")


def _validate_instructor_workload(
    existing: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> None:
    instructors = load_items(INSTRUCTORS_FILE)
    instructor = find_item(instructors, payload["instrutor_id"])
    if not instructor:
        raise ValidationError(f"Colaborador não encontrado: {payload['instrutor_id']}")
    limit = instructor.get("max_horas_semana")
    if limit is None:
        return

    duration_hours = _duration_hours(payload["hora_inicio"], payload["hora_fim"])
    weekly_hours = duration_hours * len(payload.get("dias_execucao") or [])

    total = weekly_hours
    for item in existing:
        if item.get("instrutor_id") != payload["instrutor_id"]:
            continue
        if item.get("hora_inicio") and item.get("hora_fim"):
            total += _duration_hours(item["hora_inicio"], item["hora_fim"]) * len(
                item.get("dias_execucao") or []
            )

    if total > float(limit):
        raise ValidationError(
            "Limite de carga horária semanal excedido para o colaborador."
        )


def _duration_hours(start_raw: str, end_raw: str) -> float:
    start_time = _parse_time(start_raw)
    end_time = _parse_time(end_raw)
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    if end_minutes <= start_minutes:
        raise ValidationError("Horário final deve ser maior que o inicial.")
    return (end_minutes - start_minutes) / 60


def _validate_dates_and_times(payload: Dict[str, Any]) -> None:
    _parse_date(payload["data_inicio"])
    _parse_date(payload["data_fim"])
    if not payload.get("dias_execucao"):
        raise ValidationError("Dias de execução são obrigatórios.")
    _duration_hours(payload["hora_inicio"], payload["hora_fim"])
    turma = payload.get("turma", "")
    if not turma:
        raise ValidationError("Número da turma é obrigatório.")
    import re

    if not re.fullmatch(r"\d{3}\.28\.\d{4}", turma):
        raise ValidationError("Número da turma inválido. Formato esperado: 000.28.0000.")
