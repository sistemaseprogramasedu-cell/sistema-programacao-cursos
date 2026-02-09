from __future__ import annotations

from datetime import datetime
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

FILENAME = "shifts.json"
REQUIRED_FIELDS = ["id", "nome", "horario_inicio", "horario_fim"]


def _parse_time(raw: str) -> datetime:
    try:
        return datetime.strptime(raw, "%H:%M")
    except ValueError as exc:
        raise ValidationError(f"Horário inválido: {raw}") from exc


def _calculate_hs_dia(start_raw: str, end_raw: str) -> str:
    start_dt = _parse_time(start_raw)
    end_dt = _parse_time(end_raw)
    delta_minutes = int((end_dt - start_dt).total_seconds() / 60)
    if delta_minutes <= 0:
        raise ValidationError("Horário fim deve ser maior que horário início.")
    hours = delta_minutes // 60
    minutes = delta_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def _normalize_shift(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    normalized["hs_dia"] = _calculate_hs_dia(
        str(normalized.get("horario_inicio", "")),
        str(normalized.get("horario_fim", "")),
    )
    return normalized


def list_shifts() -> List[Dict[str, Any]]:
    items = load_items(FILENAME)
    changed = False
    for item in items:
        if not item.get("horario_inicio") or not item.get("horario_fim"):
            continue
        if not item.get("hs_dia"):
            try:
                item["hs_dia"] = _calculate_hs_dia(
                    str(item.get("horario_inicio", "")),
                    str(item.get("horario_fim", "")),
                )
                changed = True
            except ValidationError:
                item["hs_dia"] = ""
                changed = True
    if changed:
        save_items(FILENAME, items)
    return items


def get_shift(shift_id: str) -> Dict[str, Any] | None:
    return find_item(load_items(FILENAME), shift_id)


def create_shift(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    if not payload.get("id"):
        payload["id"] = next_numeric_id(items)
    payload = _normalize_shift(payload)
    require_fields(payload, REQUIRED_FIELDS)
    ensure_unique_id(items, payload["id"])
    items.append(payload)
    save_items(FILENAME, items)
    return payload


def update_shift(shift_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    items = load_items(FILENAME)
    shift = find_item(items, shift_id)
    if not shift:
        raise ValidationError(f"Turno não encontrado: {shift_id}")
    shift.update(updates)
    shift.update(_normalize_shift(shift))
    require_fields(shift, REQUIRED_FIELDS)
    save_items(FILENAME, items)
    return shift


def delete_shift(shift_id: str) -> None:
    items = load_items(FILENAME)
    shift = find_item(items, shift_id)
    if not shift:
        raise ValidationError(f"Turno não encontrado: {shift_id}")
    items.remove(shift)
    save_items(FILENAME, items)
