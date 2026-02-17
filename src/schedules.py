from __future__ import annotations

from datetime import date, datetime, time, timedelta
import re
from typing import Any, Dict, List

from .instructor_availability import get_by_context, normalize_period
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
        payload["id"] = _next_offer_id(items, _resolve_year(payload.get("ano")))
    _normalize_instructors(payload)
    _normalize_dates(payload)
    require_fields(payload, REQUIRED_FIELDS)
    ensure_unique_id(items, payload["id"])
    _validate_references(payload)
    _validate_conflicts(items, payload)
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_schedule(
    schedule_id: str,
    updates: Dict[str, Any],
    validate_schedule: bool = True,
) -> Dict[str, Any]:
    items = load_items(FILENAME)
    schedule = find_item(items, schedule_id)
    if not schedule:
        raise ValidationError(f"ProgramaÃ§Ã£o nÃ£o encontrada: {schedule_id}")
    schedule.update(updates)
    _normalize_instructors(schedule)
    _normalize_dates(schedule)
    if validate_schedule:
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
        raise ValidationError(f"ProgramaÃ§Ã£o nÃ£o encontrada: {schedule_id}")
    items.remove(schedule)
    save_items(FILENAME, items)


def _validate_references(payload: Dict[str, Any]) -> None:
    _ensure_exists(COURSES_FILE, payload["curso_id"], "Curso")
    for instructor_id in _get_instructor_ids(payload):
        _ensure_instructor(instructor_id, "Instrutor")
    _ensure_instructor(payload["analista_id"], "Analista")
    assistente_id = str(payload.get("assistente_id") or "").strip()
    if assistente_id:
        _ensure_instructor(assistente_id, "Assistente")
    _ensure_exists(ROOMS_FILE, payload["sala_id"], "Ambiente")
    _ensure_exists(SHIFTS_FILE, payload["turno_id"], "Turno")


def _ensure_exists(filename: str, item_id: str, label: str) -> None:
    items = load_items(filename)
    if not find_item(items, item_id):
        raise ValidationError(f"{label} nÃ£o encontrado: {item_id}")


def _ensure_instructor(instructor_id: str, role: str) -> None:
    items = load_items(INSTRUCTORS_FILE)
    instructor = find_item(items, instructor_id)
    if not instructor:
        raise ValidationError(f"Colaborador nÃ£o encontrado: {instructor_id}")
    if instructor.get("role") != role:
        raise ValidationError(f"Colaborador informado nÃ£o Ã© da categoria {role}.")


def _parse_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError as exc:
        raise ValidationError(f"Data invÃ¡lida: {raw}") from exc


def _normalize_dates(payload: Dict[str, Any]) -> None:
    payload["data_inicio"] = _parse_date(payload["data_inicio"]).strftime("%d/%m/%Y")
    payload["data_fim"] = _parse_date(payload["data_fim"]).strftime("%d/%m/%Y")


def _normalize_instructors(payload: Dict[str, Any]) -> None:
    raw_ids = payload.get("instrutor_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]

    cleaned: List[str] = []
    if isinstance(raw_ids, list):
        for value in raw_ids:
            instructor_id = str(value or "").strip()
            if instructor_id and instructor_id not in cleaned:
                cleaned.append(instructor_id)

    primary = str(payload.get("instrutor_id") or "").strip()
    if primary and primary not in cleaned:
        cleaned.insert(0, primary)

    if cleaned:
        payload["instrutor_ids"] = cleaned
        payload["instrutor_id"] = cleaned[0]


def _get_instructor_ids(payload: Dict[str, Any]) -> List[str]:
    raw_ids = payload.get("instrutor_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]

    cleaned = [str(value).strip() for value in raw_ids if str(value).strip()]
    if cleaned:
        return cleaned

    primary = str(payload.get("instrutor_id") or "").strip()
    return [primary] if primary else []


def _parse_time(raw: str) -> time:
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError as exc:
        raise ValidationError(f"HorÃ¡rio invÃ¡lido: {raw}") from exc


def _date_ranges_overlap(start_a: date, end_a: date, start_b: date, end_b: date) -> bool:
    return start_a <= end_b and start_b <= end_a


def _times_overlap(start_a: time, end_a: time, start_b: time, end_b: time) -> bool:
    return start_a < end_b and start_b < end_a


def _validate_conflicts(existing: List[Dict[str, Any]], payload: Dict[str, Any]) -> None:
    start = _parse_date(payload["data_inicio"])
    end = _parse_date(payload["data_fim"])
    if start > end:
        raise ValidationError("Data inicio nao pode ser maior que data fim.")
    _validate_dates_and_times(payload)
    _validate_instructor_availability(payload)
    _validate_instructor_workload(existing, payload)

    payload_days = set(payload.get("dias_execucao") or [])
    payload_instructors = set(_get_instructor_ids(payload))
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
            raise ValidationError("Conflito de ambiente: horario ja reservado.")

        item_instructors = set(_get_instructor_ids(item))
        if payload_instructors.intersection(item_instructors):
            raise ValidationError("Conflito de instrutor: horario ja reservado.")


def _canonical_weekday(raw: str) -> str:
    token = str(raw or "").strip().upper().replace("Á", "A")
    aliases = {
        "SEG": "SEG",
        "TER": "TER",
        "QUA": "QUA",
        "QUI": "QUI",
        "SEX": "SEX",
        "SAB": "SAB",
    }
    return aliases.get(token, "")


def _weekday_to_index(raw: str) -> int | None:
    mapping = {"SEG": 0, "TER": 1, "QUA": 2, "QUI": 3, "SEX": 4, "SAB": 5}
    return mapping.get(_canonical_weekday(raw))


def _month_last_day(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def _month_ranges_between(start_day: date, end_day: date) -> List[tuple[int, int, date, date]]:
    out: List[tuple[int, int, date, date]] = []
    cursor = date(start_day.year, start_day.month, 1)
    while cursor <= end_day:
        y = cursor.year
        m = cursor.month
        m_start = date(y, m, 1)
        m_end = date(y, m, _month_last_day(y, m))
        out.append((y, m, max(start_day, m_start), min(end_day, m_end)))
        if m == 12:
            cursor = date(y + 1, 1, 1)
        else:
            cursor = date(y, m + 1, 1)
    return out


def _has_weekday_between(start_day: date, end_day: date, weekday_idx: int) -> bool:
    if start_day > end_day:
        return False
    offset = (weekday_idx - start_day.weekday()) % 7
    return (start_day + timedelta(days=offset)) <= end_day


def _availability_candidates_for_month(year: int, month: int) -> List[tuple[str, str]]:
    quarter = ((month - 1) // 3) + 1
    semester = 1 if month <= 6 else 2
    return [("month", str(month)), ("quarter", str(quarter)), ("semester", str(semester)), ("year", "A")]


def _first_availability_record(instructor_id: str, year: int, month: int) -> Dict[str, Any] | None:
    for p_type, p_value in _availability_candidates_for_month(year, month):
        try:
            n_type, n_value = normalize_period(p_type, p_value)
        except ValidationError:
            continue
        record = get_by_context(instructor_id, year, n_type, n_value)
        if record:
            return record
    return None


def _validate_instructor_availability(payload: Dict[str, Any]) -> None:
    start = _parse_date(payload["data_inicio"])
    end = _parse_date(payload["data_fim"])
    if start > end:
        return

    turno_id = str(payload.get("turno_id") or "").strip()
    if not turno_id:
        return

    selected_weekdays = [_canonical_weekday(day) for day in (payload.get("dias_execucao") or [])]
    selected_weekdays = [day for day in selected_weekdays if day]
    if not selected_weekdays:
        return

    required_slots = {f"{day}|{turno_id}" for day in selected_weekdays}
    for instructor_id in _get_instructor_ids(payload):
        for year, month, window_start, window_end in _month_ranges_between(start, end):
            # skip months where there is no actual class day according to selected weekdays
            has_execution_day = False
            for day in selected_weekdays:
                idx = _weekday_to_index(day)
                if idx is not None and _has_weekday_between(window_start, window_end, idx):
                    has_execution_day = True
                    break
            if not has_execution_day:
                continue

            record = _first_availability_record(instructor_id, year, month)
            if not record:
                continue

            slots = {str(value or "").strip().upper().replace("Á", "A") for value in (record.get("slots") or [])}
            missing = [
                slot for slot in required_slots if slot.replace("Á", "A") not in slots
            ]
            if missing:
                pretty_missing = ", ".join(sorted(missing))
                raise ValidationError(
                    f"Instrutor indisponivel no periodo {month:02d}/{year}. "
                    f"Slots ausentes para o turno selecionado: {pretty_missing}."
                )


def _validate_instructor_workload(
    existing: List[Dict[str, Any]],
    payload: Dict[str, Any],
) -> None:
    instructors = load_items(INSTRUCTORS_FILE)
    duration_hours = _duration_hours(payload["hora_inicio"], payload["hora_fim"])
    weekly_hours = duration_hours * len(payload.get("dias_execucao") or [])

    for instructor_id in _get_instructor_ids(payload):
        instructor = find_item(instructors, instructor_id)
        if not instructor:
            raise ValidationError(f"Colaborador nao encontrado: {instructor_id}")
        limit = instructor.get("max_horas_semana")
        if limit is None:
            continue

        total = weekly_hours
        for item in existing:
            if instructor_id not in _get_instructor_ids(item):
                continue
            if item.get("hora_inicio") and item.get("hora_fim"):
                total += _duration_hours(item["hora_inicio"], item["hora_fim"]) * len(
                    item.get("dias_execucao") or []
                )

        if total > float(limit):
            raise ValidationError(
                "Limite de carga horaria semanal excedido para o colaborador."
            )


def _duration_hours(start_raw: str, end_raw: str) -> float:
    start_time = _parse_time(start_raw)
    end_time = _parse_time(end_raw)
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    if end_minutes <= start_minutes:
        raise ValidationError("HorÃ¡rio final deve ser maior que o inicial.")
    return (end_minutes - start_minutes) / 60


def _validate_dates_and_times(payload: Dict[str, Any]) -> None:
    _parse_date(payload["data_inicio"])
    _parse_date(payload["data_fim"])
    if not payload.get("dias_execucao"):
        raise ValidationError("Dias de execuÃ§Ã£o sÃ£o obrigatÃ³rios.")
    _duration_hours(payload["hora_inicio"], payload["hora_fim"])
    turma = payload.get("turma", "")
    if not turma:
        raise ValidationError("NÃºmero da turma Ã© obrigatÃ³rio.")

    if not re.fullmatch(r"\d{4}\.\d{2}\.\d{3}", turma):
        raise ValidationError("NÃºmero da turma invÃ¡lido. Formato esperado: 0000.00.000.")


def _resolve_year(raw: Any) -> int:
    try:
        value = int(str(raw or "").strip())
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    return datetime.now().year


def _next_offer_id(items: List[Dict[str, Any]], year: int) -> str:
    highest = 0
    year_str = str(year)
    pattern = re.compile(r"^\s*(\d+)\s*/\s*(\d{4})\s*$")
    for item in items:
        raw_id = str(item.get("id") or "").strip()
        match = pattern.match(raw_id)
        if not match:
            continue
        seq_text, item_year = match.groups()
        if item_year != year_str:
            continue
        try:
            seq = int(seq_text)
        except ValueError:
            continue
        highest = max(highest, seq)
    next_seq = highest + 1
    seq_text = f"{next_seq:02d}" if next_seq < 100 else str(next_seq)
    return f"{seq_text}/{year_str}"

