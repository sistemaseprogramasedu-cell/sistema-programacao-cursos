from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .storage import ValidationError, load_items, save_items

FILENAME = "instructor_availability.json"
PERIOD_TYPES = {"month", "quarter", "semester", "year"}


def list_instructor_availability() -> List[Dict[str, Any]]:
    return load_items(FILENAME)


def build_record_id(instructor_id: str, year: int, period_type: str, period_value: str) -> str:
    return f"{str(instructor_id).strip()}|{int(year)}|{str(period_type).strip().lower()}|{str(period_value).strip()}"


def normalize_period(period_type: str, period_value: str) -> tuple[str, str]:
    p_type = str(period_type or "").strip().lower()
    if p_type not in PERIOD_TYPES:
        raise ValidationError("Tipo de período inválido.")
    raw_val = str(period_value or "").strip()
    if p_type == "month":
        num = int(raw_val or "0")
        if num < 1 or num > 12:
            raise ValidationError("Mês inválido.")
        return p_type, str(num)
    if p_type == "quarter":
        num = int(raw_val or "0")
        if num < 1 or num > 4:
            raise ValidationError("Trimestre inválido.")
        return p_type, str(num)
    if p_type == "semester":
        num = int(raw_val or "0")
        if num < 1 or num > 2:
            raise ValidationError("Semestre inválido.")
        return p_type, str(num)
    return p_type, "A"


def get_by_context(
    instructor_id: str,
    year: int,
    period_type: str,
    period_value: str,
) -> Optional[Dict[str, Any]]:
    record_id = build_record_id(instructor_id, year, period_type, period_value)
    for item in list_instructor_availability():
        if str(item.get("id") or "") == record_id:
            return item
    return None


def upsert_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    instructor_id = str(payload.get("instructor_id") or "").strip()
    if not instructor_id:
        raise ValidationError("Instrutor é obrigatório.")
    try:
        year = int(str(payload.get("year") or "").strip())
    except ValueError as exc:
        raise ValidationError("Ano inválido.") from exc
    if year <= 0:
        raise ValidationError("Ano inválido.")

    p_type, p_value = normalize_period(
        str(payload.get("period_type") or ""),
        str(payload.get("period_value") or ""),
    )
    record_id = build_record_id(instructor_id, year, p_type, p_value)

    slots_raw = payload.get("slots") or []
    slots: List[str] = []
    if isinstance(slots_raw, list):
        for value in slots_raw:
            key = str(value or "").strip()
            if key and key not in slots:
                slots.append(key)

    items = list_instructor_availability()
    now_iso = datetime.now().isoformat(timespec="seconds")
    existing = None
    for item in items:
        if str(item.get("id") or "") == record_id:
            existing = item
            break

    if existing:
        existing["slots"] = slots
        existing["notes"] = str(payload.get("notes") or "")
        existing["updated_at"] = now_iso
        existing["updated_by"] = str(payload.get("updated_by") or "Equipe interna")
        if payload.get("source") == "shared":
            existing["share_status"] = "respondido"
    else:
        existing = {
            "id": record_id,
            "instructor_id": instructor_id,
            "year": year,
            "period_type": p_type,
            "period_value": p_value,
            "slots": slots,
            "notes": str(payload.get("notes") or ""),
            "updated_at": now_iso,
            "updated_by": str(payload.get("updated_by") or "Equipe interna"),
            "share_token": "",
            "share_expires_at": "",
            "share_status": "nao_enviado",
        }
        if payload.get("source") == "shared":
            existing["share_status"] = "respondido"
        items.append(existing)

    save_items(FILENAME, items)
    return existing


def create_or_refresh_share_token(record_id: str, token: str, valid_days: int = 7) -> Dict[str, Any]:
    items = list_instructor_availability()
    target = None
    for item in items:
        if str(item.get("id") or "") == record_id:
            target = item
            break
    if not target:
        raise ValidationError("Registro de disponibilidade não encontrado.")

    expires_at = (datetime.now() + timedelta(days=max(1, int(valid_days)))).isoformat(timespec="seconds")
    target["share_token"] = token
    target["share_expires_at"] = expires_at
    target["share_status"] = "enviado"
    save_items(FILENAME, items)
    return target


def find_by_share_token(token: str) -> Optional[Dict[str, Any]]:
    key = str(token or "").strip()
    if not key:
        return None
    now = datetime.now()
    for item in list_instructor_availability():
        if str(item.get("share_token") or "") != key:
            continue
        exp_raw = str(item.get("share_expires_at") or "").strip()
        if exp_raw:
            try:
                exp_dt = datetime.fromisoformat(exp_raw)
                if now > exp_dt:
                    return None
            except ValueError:
                return None
        return item
    return None
