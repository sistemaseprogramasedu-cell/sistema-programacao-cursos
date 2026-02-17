from __future__ import annotations

import calendar as calendar_module
import colorsys
import io
import json
import math
import re
import secrets
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from src.calendars import (
    create_calendar,
    delete_calendar,
    get_calendar,
    list_calendars,
    update_calendar,
)
from src.courses import create_course, delete_course, get_course, list_courses, update_course
from src.curricular_units import (
    create_unit,
    create_units_batch_from_lines,
    delete_unit,
    get_unit,
    list_units,
    update_unit,
)
from src.instructors import (
    create_instructor,
    delete_instructor,
    get_instructor,
    list_instructors,
    update_instructor,
)
from src.instructor_availability import (
    build_record_id,
    create_or_refresh_share_token,
    find_by_share_token,
    get_by_context,
    normalize_period,
    upsert_record,
)
from src.rooms import create_room, delete_room, get_room, list_rooms, update_room
from src.schedules import (
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from src.shifts import create_shift, delete_shift, get_shift, list_shifts, update_shift
from src.storage import ValidationError, next_numeric_id

MONTHS = [
    {"value": "1", "label": "Janeiro"},
    {"value": "2", "label": "Fevereiro"},
    {"value": "3", "label": "Mar\u00e7o"},
    {"value": "4", "label": "Abril"},
    {"value": "5", "label": "Maio"},
    {"value": "6", "label": "Junho"},
    {"value": "7", "label": "Julho"},
    {"value": "8", "label": "Agosto"},
    {"value": "9", "label": "Setembro"},
    {"value": "10", "label": "Outubro"},
    {"value": "11", "label": "Novembro"},
    {"value": "12", "label": "Dezembro"},
]

WEEKDAYS = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB"]

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="sistema-programacao-cursos")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")


def _flash(request: Request, message: str, category: str = "success") -> None:
    request.session.setdefault("flash", []).append({"message": message, "category": category})


def _render(request: Request, template_name: str, **context: Any):
    context["request"] = request
    context["flashes"] = request.session.pop("flash", [])
    return templates.TemplateResponse(template_name, context)


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _parse_days(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _availability_period_options(period_type: str) -> List[Dict[str, str]]:
    ptype = str(period_type or "month").strip().lower()
    if ptype == "quarter":
        return [{"value": str(i), "label": f"{i}º trimestre"} for i in range(1, 5)]
    if ptype == "semester":
        return [{"value": str(i), "label": f"{i}º semestre"} for i in range(1, 3)]
    if ptype == "year":
        return [{"value": "A", "label": "Ano completo"}]
    return [{"value": str(i), "label": month["label"]} for i, month in enumerate(MONTHS, start=1)]


def _availability_period_label(period_type: str, period_value: str) -> str:
    ptype = str(period_type or "").strip().lower()
    pval = str(period_value or "").strip()
    if ptype == "quarter":
        return f"{pval}º trimestre"
    if ptype == "semester":
        return f"{pval}º semestre"
    if ptype == "year":
        return "Ano completo"
    if ptype == "month":
        idx = _parse_int(pval)
        if idx and 1 <= idx <= 12:
            return MONTHS[idx - 1]["label"]
    return pval or "—"


def _parse_availability_slots(raw_slots: List[str], valid_shift_ids: set[str]) -> List[str]:
    out: List[str] = []
    valid_days = set(WEEKDAYS)
    for item in raw_slots or []:
        key = str(item or "").strip().upper()
        if "|" not in key:
            continue
        day, shift_id = [p.strip() for p in key.split("|", 1)]
        if day not in valid_days:
            continue
        if shift_id not in valid_shift_ids:
            continue
        merged = f"{day}|{shift_id}"
        if merged not in out:
            out.append(merged)
    return out


def _normalize_instructor_ids(instrutor_ids: List[str], fallback_instrutor_id: str = "") -> List[str]:
    cleaned: List[str] = []
    for iid in instrutor_ids or []:
        value = (iid or "").strip()
        if value and value not in cleaned:
            cleaned.append(value)
    if not cleaned and (fallback_instrutor_id or "").strip():
        cleaned.append((fallback_instrutor_id or "").strip())
    return cleaned


def _parse_json(text: str, default: Any) -> Any:
    cleaned = text.strip()
    if not cleaned:
        return default
    return json.loads(cleaned)


def _next_id(items: List[Dict[str, Any]]) -> str:
    return next_numeric_id(items)


def _next_schedule_offer_id(items: List[Dict[str, Any]], year: int) -> str:
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
        if seq > highest:
            highest = seq
    next_seq = highest + 1
    seq_text = f"{next_seq:02d}" if next_seq < 100 else str(next_seq)
    return f"{seq_text}/{year_str}"


def _parse_days_list(raw: str) -> List[int]:
    if not raw:
        return []
    items: List[int] = []
    for part in raw.split(","):
        cleaned = part.strip()
        if not cleaned:
            continue
        if cleaned.isdigit():
            value = int(cleaned)
            if 1 <= value <= 31:
                items.append(value)
    return items


def _sum_uc_hours(ucs: List[Dict[str, Any]]) -> str:
    total = 0.0
    for unit in ucs:
        value = unit.get("carga_horaria")
        if isinstance(value, (int, float)):
            total += float(value)
        elif isinstance(value, str):
            parsed = _parse_float(value)
            if parsed is not None:
                total += parsed
    total_str = f"{total:.2f}".replace(".00", "")
    return total_str


def _sanitize_days_list(items: List[Any]) -> List[int]:
    sanitized: List[int] = []
    for item in items:
        if isinstance(item, int):
            value = item
        elif isinstance(item, str) and item.strip().isdigit():
            value = int(item.strip())
        else:
            continue
        if 1 <= value <= 31:
            sanitized.append(value)
    return sanitized


def _sum_calendar_totals(dias_letivos: List[List[Any]], feriados: List[List[Any]]) -> Dict[str, int]:
    total_dias = 0
    total_feriados = 0
    for month_days in dias_letivos:
        total_dias += len(set(_sanitize_days_list(month_days)))
    for month_days in feriados:
        total_feriados += len(set(_sanitize_days_list(month_days)))
    return {"dias_letivos": total_dias, "feriados": total_feriados}


def _parse_hours_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if ":" in cleaned:
            parts = cleaned.split(":")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                hours = int(parts[0])
                minutes = int(parts[1])
                return hours + minutes / 60
        parsed = _parse_float(cleaned)
        if parsed is not None:
            return parsed
    return None


def _calculate_end_date(
    year: int,
    start_date_raw: str,
    days_execucao: List[str],
    ch_total: float,
    hs_dia: float,
    calendario: Dict[str, Any],
) -> tuple[Optional[date], Optional[str]]:
    if not calendario:
        return None, "CalendÃ¡rio nÃ£o encontrado para o ano informado."
    if not start_date_raw:
        return None, "Informe a data inicial."
    if not days_execucao:
        return None, "Selecione ao menos um dia de execuÃ§Ã£o."
    if ch_total <= 0 or hs_dia <= 0:
        return None, "Carga horÃ¡ria e horas/dia devem ser maiores que zero."

    try:
        start_date = datetime.strptime(start_date_raw, "%d/%m/%Y").date()
    except ValueError:
        return None, "Data inicial invÃ¡lida."

    if start_date.year != year:
        return None, "Ano e data inicial precisam estar no mesmo ano."

    weekday_map = {"SEG": 0, "TER": 1, "QUA": 2, "QUI": 3, "SEX": 4, "SÃB": 5, "SAB": 5}
    selected_weekdays = {weekday_map[day] for day in days_execucao if day in weekday_map}
    if not selected_weekdays:
        return None, "Dias de execuÃ§Ã£o invÃ¡lidos."

    dias_letivos = calendario.get("dias_letivos_por_mes", [[] for _ in range(12)])
    month_sets = [set(_sanitize_days_list(days)) for days in dias_letivos]

    total_days_needed = int(math.ceil(ch_total / hs_dia))
    if total_days_needed <= 0:
        return None, "NÃ£o foi possÃ­vel calcular o total de dias."

    current = start_date
    counted = 0
    while current.year == year:
        if current.weekday() in selected_weekdays:
            month_idx = current.month - 1
            if current.day in month_sets[month_idx]:
                counted += 1
                if counted >= total_days_needed:
                    return current, None
        current += timedelta(days=1)

    return None, "NÃ£o hÃ¡ dias letivos suficientes no calendÃ¡rio para o perÃ­odo informado."


def _build_month_grid(year: int, month: int) -> List[List[Optional[int]]]:
    days_in_month = calendar_module.monthrange(year, month)[1]
    weeks: List[List[Optional[int]]] = []
    week: List[Optional[int]] = []
    for day in range(1, days_in_month + 1):
        weekday = date(year, month, day).weekday()
        if weekday == 6:
            if week:
                while len(week) < 6:
                    week.append(None)
                weeks.append(week)
            week = []
            continue
        if not week and weekday > 0:
            week.extend([None] * weekday)
        week.append(day)
        if len(week) == 6:
            weeks.append(week)
            week = []
    if week:
        while len(week) < 6:
            week.append(None)
        weeks.append(week)
    return weeks

def _chunk_list(items: List[Any], size: int) -> List[List[Any]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _weekday_abbrev_pt(d: date) -> str:
    labels = ["SEG", "TER", "QUA", "QUI", "SEX", "SÃB", "DOM"]
    try:
        return labels[d.weekday()]
    except Exception:
        return ""


def _sigla_nome(nome: str) -> str:
    parts = [p for p in (nome or "").strip().split() if p]
    if not parts:
        return ""
    return parts[0][:3].upper()


def _build_hour_slots(hora_inicio: str, hora_fim: str) -> List[Dict[str, str]]:
    try:
        hi = datetime.strptime((hora_inicio or "").strip(), "%H:%M")
        hf = datetime.strptime((hora_fim or "").strip(), "%H:%M")
    except Exception:
        return []
    if hf <= hi:
        return []

    slots: List[Dict[str, str]] = []
    cur = hi
    while cur < hf:
        nxt = cur + timedelta(hours=1)
        if nxt > hf:
            break
        slots.append({"label": f"{cur.strftime('%Hh')}-{nxt.strftime('%Hh')}"})
        cur = nxt
    return slots


def _extract_course_units(course: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not course:
        return []

    # no teu sistema vocÃª salva UCs no course como "curricular_units"
    raw = course.get("curricular_units") or []

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []

    normalized: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            desc = (item.get("nome") or "").strip()
            ch = item.get("carga_horaria") or ""
            try:
                ch_val = float(str(ch).replace(",", ".").strip()) if str(ch).strip() else 0.0
            except Exception:
                ch_val = 0.0
            if desc:
                normalized.append({"desc": desc, "carga_horaria": ch_val})

    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(normalized, start=1):
        desc_upper = item["desc"].upper()
        out.append(
            {
                "label": f"UC{idx}",
                "desc": item["desc"],
                "carga_horaria": float(item["carga_horaria"]),
                "is_pi": ("PROJETO INTEGRADOR" in desc_upper),
            }
        )
    return out


def _days_needed(hours: float, slots_per_day: int) -> int:
    if slots_per_day <= 0:
        return 0
    return max(1, int(math.ceil(hours / float(slots_per_day))))


def _build_day_sequence_with_pi(units: List[Dict[str, Any]], slots_per_day: int) -> List[Dict[str, Any]]:
    if not units or slots_per_day <= 0:
        return []

    pi_units = [u for u in units if u.get("is_pi")]
    non_pi_units = [u for u in units if not u.get("is_pi")]

    non_pi_days: List[Dict[str, Any]] = []
    for u in non_pi_units:
        for _ in range(_days_needed(u["carga_horaria"], slots_per_day)):
            non_pi_days.append({"label": u["label"], "is_pi": False})

    pi_days: List[Dict[str, Any]] = []
    for u in pi_units:
        for _ in range(_days_needed(u["carga_horaria"], slots_per_day)):
            pi_days.append({"label": u["label"], "is_pi": True})

    if not pi_days:
        return non_pi_days
    if not non_pi_days:
        return pi_days

    mixed: List[Dict[str, Any]] = []
    n = len(non_pi_days)
    p = len(pi_days)
    step = max(1, int(round(n / float(p))))

    pi_i = 0
    for i, item in enumerate(non_pi_days, start=1):
        mixed.append(item)
        if (i % step == 0) and pi_i < p:
            mixed.append(pi_days[pi_i])
            pi_i += 1

    insert_pos = max(1, len(mixed) // 2)
    while pi_i < p:
        mixed.insert(insert_pos, pi_days[pi_i])
        pi_i += 1
        insert_pos = min(len(mixed), insert_pos + 2)

    return mixed


def _map_class_days_to_uc(class_days: List[date], day_sequence: List[Dict[str, Any]]) -> Dict[date, Dict[str, Any]]:
    mapping: Dict[date, Dict[str, Any]] = {}
    for idx, d in enumerate(class_days):
        if idx < len(day_sequence):
            mapping[d] = day_sequence[idx]
        else:
            mapping[d] = {"label": "", "is_pi": False}
    return mapping


def _compute_schedule_end_date(
    ano: Any,
    data_inicio: str,
    dias_execucao: List[str],
    curso_id: str,
    turno_id: str,
) -> tuple[Optional[str], Optional[str]]:
    year_value = _parse_int(str(ano)) if ano is not None else None
    if not year_value:
        return None, "Informe o ano."
    course = get_course(curso_id) if curso_id else None
    if not course:
        return None, "Curso nÃ£o encontrado."
    shift = get_shift(turno_id) if turno_id else None
    if not shift:
        return None, "Turno nÃ£o encontrado."

    ch_total = _parse_hours_value(course.get("carga_horaria_total"))
    hs_dia = _parse_hours_value(shift.get("hs_dia"))
    if ch_total is None or hs_dia is None:
        return None, "Carga horÃ¡ria ou horas/dia invÃ¡lidas."

    calendario = get_calendar(year_value)
    end_date, error = _calculate_end_date(
        year_value,
        data_inicio,
        dias_execucao,
        ch_total,
        hs_dia,
        calendario or {},
    )
    if error or not end_date:
        return None, error or "NÃ£o foi possÃ­vel calcular a data final."
    return end_date.strftime("%d/%m/%Y"), None


def _build_room_map_view(pavimento: str = "", turno_id: str = "") -> Dict[str, Any]:
    rooms_all = list_rooms()
    shifts = [item for item in list_shifts() if item.get("ativo", True)]
    schedules = list_schedules()
    courses = list_courses()
    instructors = list_instructors()

    floor_options = sorted(
        {
            str(item.get("pavimento") or "").strip()
            for item in rooms_all
            if str(item.get("pavimento") or "").strip()
        }
    )
    selected_floor = str(pavimento or "").strip()
    if selected_floor not in floor_options:
        selected_floor = floor_options[0] if floor_options else ""

    selected_turno_id = str(turno_id or "").strip()
    shift_ids = {str(item.get("id") or "").strip() for item in shifts}
    if selected_turno_id not in shift_ids:
        selected_turno_id = str(shifts[0].get("id") or "").strip() if shifts else ""
    shift_map = {str(item.get("id") or "").strip(): item for item in shifts}
    selected_shift = shift_map.get(selected_turno_id)

    course_map = {str(item.get("id") or "").strip(): item for item in courses}
    instructor_map = {str(item.get("id") or "").strip(): item for item in instructors}

    rooms_filtered = [
        item
        for item in rooms_all
        if (not selected_floor) or (str(item.get("pavimento") or "").strip() == selected_floor)
    ]
    rooms_filtered.sort(
        key=lambda item: (
            str(item.get("abreviacao") or "").strip() or str(item.get("nome") or ""),
            str(item.get("nome") or ""),
        )
    )

    def _schedule_for_room(room_id: str) -> Optional[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for schedule in schedules:
            if str(schedule.get("sala_id") or "").strip() != room_id:
                continue
            if selected_turno_id and str(schedule.get("turno_id") or "").strip() != selected_turno_id:
                continue
            candidates.append(schedule)
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                _parse_br_date(str(item.get("data_inicio") or "")) or date.min,
                str(item.get("id") or ""),
            ),
            reverse=True,
        )
        return candidates[0]

    map_rooms: List[Dict[str, Any]] = []
    occupied_count = 0
    available_count = 0
    inactive_count = 0

    for room in rooms_filtered:
        room_id = str(room.get("id") or "").strip()
        is_active = bool(room.get("ativo", True))
        label = str(room.get("abreviacao") or "").strip() or str(room.get("nome") or "").strip() or room_id

        if not is_active:
            status = "inactive"
            inactive_count += 1
            map_rooms.append(
                {
                    "id": room_id,
                    "label": label,
                    "status": status,
                    "instructor": "—",
                    "analista": "—",
                    "turma": "—",
                    "course": "Inativo",
                    "periodo": "—",
                }
            )
            continue

        selected_schedule = _schedule_for_room(room_id)
        if selected_schedule:
            status = "occupied"
            occupied_count += 1
            instructor_ids = [str(v).strip() for v in (selected_schedule.get("instrutor_ids") or []) if str(v).strip()]
            primary_id = str(selected_schedule.get("instrutor_id") or "").strip()
            if primary_id and primary_id not in instructor_ids:
                instructor_ids.insert(0, primary_id)
            instructor_names: List[str] = []
            for iid in instructor_ids:
                instructor = instructor_map.get(iid)
                if not instructor:
                    continue
                name = instructor.get("nome_sobrenome") or instructor.get("nome") or iid
                if name not in instructor_names:
                    instructor_names.append(name)
            analyst = instructor_map.get(str(selected_schedule.get("analista_id") or "").strip())
            course = course_map.get(str(selected_schedule.get("curso_id") or "").strip())
            map_rooms.append(
                {
                    "id": room_id,
                    "label": label,
                    "status": status,
                    "instructor": ", ".join(instructor_names) if instructor_names else "—",
                    "analista": (
                        analyst.get("nome_sobrenome") or analyst.get("nome") or "—"
                    ) if analyst else "—",
                    "turma": selected_schedule.get("turma") or "—",
                    "course": (course.get("nome") if course else "—"),
                    "periodo": f"{selected_schedule.get('data_inicio') or '—'} a {selected_schedule.get('data_fim') or '—'}",
                }
            )
        else:
            status = "free"
            available_count += 1
            map_rooms.append(
                {
                    "id": room_id,
                    "label": label,
                    "status": status,
                    "instructor": "—",
                    "analista": "—",
                    "turma": "—",
                    "course": "Livre",
                    "periodo": "—",
                }
            )

    def _room_key(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(text or ""))
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^A-Z0-9]", "", ascii_text.upper())

    rooms_by_key: Dict[str, Dict[str, Any]] = {}
    for item in map_rooms:
        room_label = str(item.get("label") or "")
        keys = {_room_key(room_label)}
        if " " in room_label:
            keys.add(_room_key(room_label.replace(" ", "")))
        for k in keys:
            if k and k not in rooms_by_key:
                rooms_by_key[k] = item

    floor_layouts: Dict[str, List[List[Optional[str]]]] = {
        "TERREO": [
            ["REDES", "LABMAC", "LABTEC3", "LABTEC2", "LABTEC1", "LABGAMES"],
            ["AUDIO", "CONHEC4", "CONHEC3", "CONHEC2", "CONHEC1", None],
        ],
        "1PISO": [
            ["HARDWARE", "EDICAO", "LABTEC5", "LABTEC4", "CONHEC5"],
            ["FOTO", "MODA", "OPTICA", "COMPART", "AUDITORIO"],
        ],
    }
    alias_map: Dict[str, List[str]] = {
        "AUDIO": ["ESTAUDIO", "AUDIO", "ESTUDIOAUDIO"],
        "FOTO": ["ESTFOTO", "ESTUDIOFOTO", "FOTOGRAFIA", "ESTUDIODEFOTOGRAFIA"],
        "COMPART": ["COMPART", "COMPARTILHADO"],
        "AUDITORIO": ["AUDITORIO"],
    }

    selected_floor_key = _room_key(selected_floor)
    selected_layout = floor_layouts.get(selected_floor_key)
    used_room_ids: set[str] = set()
    room_rows: List[List[Dict[str, Any]]] = []
    map_columns = 0

    if selected_layout:
        map_columns = max(len(row) for row in selected_layout) if selected_layout else 1
        for layout_row in selected_layout:
            row_cards: List[Dict[str, Any]] = []
            for slot in layout_row:
                if slot is None:
                    row_cards.append({"placeholder": True})
                    continue
                search_keys = [slot] + alias_map.get(slot, [])
                room_data: Optional[Dict[str, Any]] = None
                for candidate in search_keys:
                    found = rooms_by_key.get(candidate)
                    if found:
                        room_data = found
                        break
                if room_data:
                    used_room_ids.add(str(room_data.get("id") or ""))
                    row_cards.append(room_data)
                else:
                    row_cards.append(
                        {
                            "id": "",
                            "label": slot,
                            "status": "free",
                            "instructor": "—",
                            "turma": "—",
                            "course": "Livre",
                            "virtual": True,
                        }
                    )
            room_rows.append(row_cards)

        extras = [item for item in map_rooms if str(item.get("id") or "") not in used_room_ids]
        if extras:
            if not map_columns:
                map_columns = max(1, int(math.ceil(len(extras) / 2.0)))
            for i in range(0, len(extras), map_columns):
                row = extras[i : i + map_columns]
                if len(row) < map_columns:
                    row = row + [{"placeholder": True} for _ in range(map_columns - len(row))]
                room_rows.append(row)
    else:
        map_columns = max(1, int(math.ceil(len(map_rooms) / 2.0))) if map_rooms else 1
        room_rows = [
            map_rooms[i : i + map_columns]
            for i in range(0, len(map_rooms), map_columns)
        ]
        room_rows = [
            row + [{"placeholder": True} for _ in range(map_columns - len(row))]
            if len(row) < map_columns
            else row
            for row in room_rows
        ]
    active_total = occupied_count + available_count
    occupancy_pct = (occupied_count / active_total * 100.0) if active_total > 0 else 0.0
    return {
        floor_options=floor_options,
        shifts=shifts,
        selected_floor=selected_floor,
        selected_turno_id=selected_turno_id,
        selected_turno_nome=(selected_shift.get("nome") if selected_shift else "—"),
        map_rooms=map_rooms,
        room_rows=room_rows,
        map_columns=map_columns,
        occupancy_pct=occupancy_pct,
        occupied_count=occupied_count,
        available_count=available_count,
        inactive_count=inactive_count,
    }


@app.get("/")
def dashboard(request: Request, pavimento: str = "", turno_id: str = ""):
    context = _build_room_map_view(pavimento=pavimento, turno_id=turno_id)
    return _render(request, "dashboard.html", **context)


@app.get("/dashboard/report")
def dashboard_report(request: Request, pavimento: str = "", turno_id: str = ""):
    context = _build_room_map_view(pavimento=pavimento, turno_id=turno_id)
    rows = []
    for item in context["map_rooms"]:
        status = str(item.get("status") or "free")
        rows.append(
            {
                "ambiente": item.get("label") or "—",
                "status": (
                    "Ocupado"
                    if status == "occupied"
                    else ("Inativo" if status == "inactive" else "Livre")
                ),
                "instrutor": item.get("instructor") or "—",
                "analista": item.get("analista") or "—",
                "curso": item.get("course") or "—",
                "turma": item.get("turma") or "—",
                "turno": context.get("selected_turno_nome") or "—",
                "periodo": item.get("periodo") or "—",
            }
        )
    rows.sort(key=lambda row: str(row.get("ambiente") or ""))
    return _render(
        request,
        "dashboard_report.html",
        rows=rows,
        selected_floor=context.get("selected_floor") or "—",
        selected_turno_nome=context.get("selected_turno_nome") or "—",
        occupancy_pct=context.get("occupancy_pct") or 0.0,
        occupied_count=context.get("occupied_count") or 0,
        available_count=context.get("available_count") or 0,
        inactive_count=context.get("inactive_count") or 0,
        total=len(rows),
    )


@app.get("/courses")
def courses_list(request: Request):
    return _render(request, "courses.html", courses=list_courses())


@app.get("/courses/new")
def courses_new(request: Request):
    return _render(
        request,
        "course_form.html",
        course=None,
        course_id=_next_id(list_courses()),
        ucs=[],
        total_ucs_ch=0,
    )


@app.post("/courses/new")
def courses_create(
    request: Request,
    course_id: str = Form(""),
    nome: str = Form(...),
    tipo_curso: str = Form(...),
    carga_horaria_total: str = Form(...),
    ativo: str = Form("true"),
    ucs_payload: str = Form("[]"),
):
    ucs = _parse_json(ucs_payload, [])
    payload = {
        "id": course_id,
        "nome": nome,
        "tipo_curso": tipo_curso,
        "carga_horaria_total": _parse_int(carga_horaria_total) or carga_horaria_total,
        "ativo": ativo == "true",
        "curricular_units": ucs,
    }
    try:
        create_course(payload)
        _flash(request, "Curso cadastrado com sucesso.")
        return RedirectResponse("/courses", status_code=303)
    except (ValidationError, json.JSONDecodeError) as exc:
        _flash(request, str(exc), "error")
        return _render(
            request,
            "course_form.html",
            course=payload,
            course_id=payload.get("id"),
            ucs=ucs,
            total_ucs_ch=_sum_uc_hours(ucs),
        )


@app.get("/courses/{course_id}/edit")
def courses_edit(request: Request, course_id: str):
    course = get_course(course_id)
    ucs = [unit for unit in list_units() if unit.get("curso_id") == course_id]
    return _render(
        request,
        "course_form.html",
        course=course,
        course_id=course_id,
        ucs=ucs,
        total_ucs_ch=_sum_uc_hours(ucs),
    )


@app.post("/courses/{course_id}/edit")
def courses_update(
    request: Request,
    course_id: str,
    nome: str = Form(...),
    tipo_curso: str = Form(...),
    carga_horaria_total: str = Form(...),
    ativo: str = Form("true"),
    ucs_payload: str = Form("[]"),
):
    ucs = _parse_json(ucs_payload, [])
    updates = {
        "nome": nome,
        "tipo_curso": tipo_curso,
        "carga_horaria_total": _parse_int(carga_horaria_total) or carga_horaria_total,
        "ativo": ativo == "true",
        "curricular_units": ucs,
    }
    try:
        update_course(course_id, updates)
        _flash(request, "Curso atualizado com sucesso.")
        return RedirectResponse("/courses", status_code=303)
    except (ValidationError, json.JSONDecodeError) as exc:
        updates["id"] = course_id
        _flash(request, str(exc), "error")
        return _render(
            request,
            "course_form.html",
            course=updates,
            course_id=course_id,
            ucs=ucs,
            total_ucs_ch=_sum_uc_hours(ucs),
        )


@app.post("/courses/{course_id}/delete")
def courses_delete(request: Request, course_id: str):
    try:
        delete_course(course_id)
        _flash(request, "Curso removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/courses", status_code=303)


@app.get("/rooms")
def rooms_list(request: Request):
    return _render(request, "rooms.html", rooms=list_rooms())


@app.get("/rooms/report")
def rooms_report(request: Request, organize: str = "alpha"):
    rooms = list_rooms()
    organize_mode = str(organize or "alpha").strip().lower()
    if organize_mode not in {"floor", "alpha", "capacity"}:
        organize_mode = "alpha"

    if organize_mode == "floor":
        rooms.sort(
            key=lambda item: (
                str(item.get("pavimento") or ""),
                str(item.get("nome") or ""),
            )
        )
    elif organize_mode == "capacity":
        rooms.sort(
            key=lambda item: (
                _parse_int(str(item.get("capacidade") or "")) or 0,
                str(item.get("nome") or ""),
            )
        )
    else:
        rooms.sort(key=lambda item: str(item.get("nome") or ""))

    floor_totals: Dict[str, int] = {}
    for room in rooms:
        floor = str(room.get("pavimento") or "Não informado").strip() or "Não informado"
        floor_totals[floor] = floor_totals.get(floor, 0) + 1
    floor_totals_rows = [
        {"pavimento": floor, "total": total}
        for floor, total in sorted(floor_totals.items(), key=lambda item: item[0])
    ]

    return _render(
        request,
        "rooms_report.html",
        rooms=rooms,
        organize_mode=organize_mode,
        floor_totals=floor_totals_rows,
        total_rooms=len(rooms),
    )


@app.get("/rooms/new")
def rooms_new(request: Request):
    return _render(
        request,
        "room_form.html",
        room=None,
        room_id=_next_id(list_rooms()),
    )


@app.post("/rooms/new")
def rooms_create(
    request: Request,
    room_id: str = Form(""),
    nome: str = Form(...),
    abreviacao: str = Form(""),
    capacidade: str = Form(...),
    pavimento: str = Form(...),
    recursos: str = Form(""),
    ativo: str = Form("true"),
):
    payload = {
        "id": room_id,
        "nome": nome,
        "abreviacao": abreviacao.strip(),
        "capacidade": _parse_int(capacidade) or capacidade,
        "pavimento": pavimento,
        "recursos": [item.strip() for item in recursos.split(",") if item.strip()],
        "ativo": ativo == "true",
    }
    try:
        create_room(payload)
        _flash(request, "Ambiente cadastrado com sucesso.")
        return RedirectResponse("/rooms", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(
            request,
            "room_form.html",
            room=payload,
            room_id=payload.get("id"),
        )


@app.get("/rooms/{room_id}/edit")
def rooms_edit(request: Request, room_id: str):
    return _render(request, "room_form.html", room=get_room(room_id))


@app.post("/rooms/{room_id}/edit")
def rooms_update(
    request: Request,
    room_id: str,
    nome: str = Form(...),
    abreviacao: str = Form(""),
    capacidade: str = Form(...),
    pavimento: str = Form(...),
    recursos: str = Form(""),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
        "abreviacao": abreviacao.strip(),
        "capacidade": _parse_int(capacidade) or capacidade,
        "pavimento": pavimento,
        "recursos": [item.strip() for item in recursos.split(",") if item.strip()],
        "ativo": ativo == "true",
    }
    try:
        update_room(room_id, updates)
        _flash(request, "Ambiente atualizado com sucesso.")
        return RedirectResponse("/rooms", status_code=303)
    except ValidationError as exc:
        updates["id"] = room_id
        _flash(request, str(exc), "error")
        return _render(
            request,
            "room_form.html",
            room=updates,
            room_id=room_id,
        )


@app.post("/rooms/{room_id}/delete")
def rooms_delete(request: Request, room_id: str):
    try:
        delete_room(room_id)
        _flash(request, "Ambiente removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/rooms", status_code=303)


@app.get("/collaborators")
def collaborators_list(request: Request, category: str = ""):
    instructors = list_instructors()
    selected = category.strip()
    if selected and selected != "Todos":
        instructors = [item for item in instructors if item.get("role") == selected]
    return _render(
        request,
        "collaborators.html",
        instructors=instructors,
        category_filter=selected or "Todos",
    )


@app.get("/instructors")
def instructors_redirect():
    return RedirectResponse("/collaborators", status_code=302)


def _canonical_weekday_token(raw: str) -> str:
    token = str(raw or "").strip().upper().replace("Á", "A")
    aliases = {
        "SEG": "SEG",
        "TER": "TER",
        "QUA": "QUA",
        "QUI": "QUI",
        "SEX": "SEX",
        "SAB": "SÁB",
        "DOM": "DOM",
    }
    return aliases.get(token, "")


def _weekday_index_from_token(raw: str) -> Optional[int]:
    day = _canonical_weekday_token(raw)
    mapping = {"SEG": 0, "TER": 1, "QUA": 2, "QUI": 3, "SEX": 4, "SÁB": 5, "DOM": 6}
    return mapping.get(day)


def _period_bounds(year_value: int, period_type: str, period_value: str) -> tuple[date, date]:
    p_type, p_value = normalize_period(period_type, period_value)
    if p_type == "month":
        month = int(p_value)
        last = calendar_module.monthrange(year_value, month)[1]
        return date(year_value, month, 1), date(year_value, month, last)
    if p_type == "quarter":
        quarter = int(p_value)
        start_month = ((quarter - 1) * 3) + 1
        end_month = start_month + 2
        return date(year_value, start_month, 1), date(
            year_value,
            end_month,
            calendar_module.monthrange(year_value, end_month)[1],
        )
    if p_type == "semester":
        semester = int(p_value)
        start_month = 1 if semester == 1 else 7
        end_month = 6 if semester == 1 else 12
        return date(year_value, start_month, 1), date(
            year_value,
            end_month,
            calendar_module.monthrange(year_value, end_month)[1],
        )
    return date(year_value, 1, 1), date(year_value, 12, 31)


def _has_weekday_between(start_day: date, end_day: date, weekday_idx: int) -> bool:
    if start_day > end_day:
        return False
    offset = (weekday_idx - start_day.weekday()) % 7
    return (start_day + timedelta(days=offset)) <= end_day


def _instructor_busy_slots_in_period(
    instructor_id: str,
    year_value: int,
    period_type: str,
    period_value: str,
) -> set[str]:
    target_start, target_end = _period_bounds(year_value, period_type, period_value)
    busy: set[str] = set()
    for item in list_schedules():
        instructor_ids = {str(v).strip() for v in (item.get("instrutor_ids") or []) if str(v).strip()}
        primary = str(item.get("instrutor_id") or "").strip()
        if primary:
            instructor_ids.add(primary)
        if str(instructor_id).strip() not in instructor_ids:
            continue
        shift_id = str(item.get("turno_id") or "").strip()
        if not shift_id:
            continue
        sch_start = _parse_br_date(str(item.get("data_inicio") or ""))
        sch_end = _parse_br_date(str(item.get("data_fim") or ""))
        if not sch_start or not sch_end:
            continue
        overlap_start = max(target_start, sch_start)
        overlap_end = min(target_end, sch_end)
        if overlap_start > overlap_end:
            continue
        for raw_day in (item.get("dias_execucao") or []):
            day = _canonical_weekday_token(str(raw_day))
            if day not in WEEKDAYS:
                continue
            weekday_idx = _weekday_index_from_token(day)
            if weekday_idx is None:
                continue
            if _has_weekday_between(overlap_start, overlap_end, weekday_idx):
                busy.add(f"{day}|{shift_id}")
    return busy


def _availability_instructors_context(
    request: Request,
    selected_instructor_id: str = "",
    selected_year: str = "",
    period_type: str = "month",
    period_value: str = "",
    shared_mode: bool = False,
    shared_token: str = "",
):
    instructors = [item for item in list_instructors() if item.get("role") == "Instrutor"]
    instructors.sort(key=lambda item: (item.get("nome_sobrenome") or item.get("nome") or ""))
    shifts = list_shifts()
    shifts.sort(key=lambda item: (item.get("nome") or "", item.get("horario_inicio") or ""))

    selected_instructor_id = str(selected_instructor_id or "").strip()
    selected_year = str(selected_year or "").strip() or str(datetime.now().year)
    selected_period_type = str(period_type or "month").strip().lower()
    period_opts = _availability_period_options(selected_period_type)
    selected_period_value = str(period_value or "").strip() or period_opts[0]["value"]

    selected_record = None
    selected_slots: List[str] = []
    occupied_slots: set[str] = set()
    notes = ""
    share_status = "nao_enviado"
    share_url = ""

    if selected_instructor_id:
        try:
            _ptype, _pvalue = normalize_period(selected_period_type, selected_period_value)
            selected_period_type = _ptype
            selected_period_value = _pvalue
            year_int = _parse_int(selected_year) or datetime.now().year
            selected_record = get_by_context(
                selected_instructor_id,
                year_int,
                selected_period_type,
                selected_period_value,
            )
            if selected_record:
                selected_slots = [str(item or "").upper() for item in selected_record.get("slots") or []]
                notes = str(selected_record.get("notes") or "")
                share_status = str(selected_record.get("share_status") or "nao_enviado")
                share_token = str(selected_record.get("share_token") or "").strip()
                if share_token:
                    share_url = f"{str(request.base_url).rstrip('/')}/availability/instructors/shared/{share_token}"
            occupied_slots = _instructor_busy_slots_in_period(
                selected_instructor_id,
                year_int,
                selected_period_type,
                selected_period_value,
            )
        except ValidationError:
            pass

    instructor_map = {str(item.get("id")): item for item in instructors}
    selected_instructor = instructor_map.get(selected_instructor_id)

    return {
        "instructors": instructors,
        "shifts": shifts,
        "weekdays": WEEKDAYS,
        "selected_instructor_id": selected_instructor_id,
        "selected_instructor": selected_instructor,
        "selected_year": selected_year,
        "selected_period_type": selected_period_type,
        "selected_period_value": selected_period_value,
        "period_options": period_opts,
        "period_type_options": [
            {"value": "month", "label": "Mês"},
            {"value": "quarter", "label": "Trimestre"},
            {"value": "semester", "label": "Semestre"},
            {"value": "year", "label": "Ano"},
        ],
        "selected_period_label": _availability_period_label(selected_period_type, selected_period_value),
        "selected_slots": set(selected_slots).union(occupied_slots),
        "occupied_slots": occupied_slots,
        "manual_slots_count": len(set(selected_slots)),
        "occupied_slots_count": len(occupied_slots),
        "notes": notes,
        "share_status": share_status,
        "share_url": share_url,
        "shared_mode": shared_mode,
        "shared_token": shared_token,
    }


@app.get("/availability/instructors")
def availability_instructors(
    request: Request,
    instructor_id: str = "",
    year: str = "",
    period_type: str = "month",
    period_value: str = "",
):
    context = _availability_instructors_context(
        request,
        selected_instructor_id=instructor_id,
        selected_year=year,
        period_type=period_type,
        period_value=period_value,
    )
    return _render(request, "availability_instructors.html", **context)


@app.post("/availability/instructors/save")
def availability_instructors_save(
    request: Request,
    instructor_id: str = Form(""),
    year: str = Form(""),
    period_type: str = Form("month"),
    period_value: str = Form(""),
    slots: List[str] = Form([]),
    notes: str = Form(""),
):
    instructor_id = str(instructor_id or "").strip()
    if not instructor_id:
        _flash(request, "Selecione um instrutor.", "error")
        return RedirectResponse("/availability/instructors", status_code=303)

    valid_shift_ids = {str(item.get("id") or "").strip() for item in list_shifts()}
    normalized_slots = _parse_availability_slots(slots, valid_shift_ids)
    year_int = _parse_int(year) or datetime.now().year

    try:
        p_type, p_value = normalize_period(period_type, period_value)
        upsert_record(
            {
                "instructor_id": instructor_id,
                "year": year_int,
                "period_type": p_type,
                "period_value": p_value,
                "slots": normalized_slots,
                "notes": notes,
                "updated_by": "Equipe interna",
            }
        )
        _flash(request, "Disponibilidade salva com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")

    return RedirectResponse(
        f"/availability/instructors?instructor_id={instructor_id}&year={year_int}&period_type={period_type}&period_value={period_value}",
        status_code=303,
    )


@app.post("/availability/instructors/share")
def availability_instructors_share(
    request: Request,
    instructor_id: str = Form(""),
    year: str = Form(""),
    period_type: str = Form("month"),
    period_value: str = Form(""),
):
    instructor_id = str(instructor_id or "").strip()
    if not instructor_id:
        _flash(request, "Selecione um instrutor para gerar o link.", "error")
        return RedirectResponse("/availability/instructors", status_code=303)

    year_int = _parse_int(year) or datetime.now().year
    try:
        p_type, p_value = normalize_period(period_type, period_value)
        record = get_by_context(instructor_id, year_int, p_type, p_value)
        if not record:
            record = upsert_record(
                {
                    "instructor_id": instructor_id,
                    "year": year_int,
                    "period_type": p_type,
                    "period_value": p_value,
                    "slots": [],
                    "notes": "",
                    "updated_by": "Equipe interna",
                }
            )
        token = secrets.token_urlsafe(24)
        updated = create_or_refresh_share_token(str(record.get("id")), token, valid_days=7)
        share_url = f"{str(request.base_url).rstrip('/')}/availability/instructors/shared/{token}"
        _flash(request, f"Link gerado: {share_url}", "success")
        if updated:
            pass
    except ValidationError as exc:
        _flash(request, str(exc), "error")

    return RedirectResponse(
        f"/availability/instructors?instructor_id={instructor_id}&year={year_int}&period_type={period_type}&period_value={period_value}",
        status_code=303,
    )


@app.get("/availability/instructors/shared/{token}")
def availability_instructors_shared(request: Request, token: str):
    record = find_by_share_token(token)
    if not record:
        _flash(request, "Link inválido ou expirado.", "error")
        return RedirectResponse("/availability/instructors", status_code=302)

    context = _availability_instructors_context(
        request,
        selected_instructor_id=str(record.get("instructor_id") or ""),
        selected_year=str(record.get("year") or ""),
        period_type=str(record.get("period_type") or "month"),
        period_value=str(record.get("period_value") or ""),
        shared_mode=True,
        shared_token=token,
    )
    return _render(request, "availability_instructors.html", **context)


@app.post("/availability/instructors/shared/{token}/save")
def availability_instructors_shared_save(
    request: Request,
    token: str,
    slots: List[str] = Form([]),
    notes: str = Form(""),
):
    record = find_by_share_token(token)
    if not record:
        _flash(request, "Link inválido ou expirado.", "error")
        return RedirectResponse("/availability/instructors", status_code=302)

    instructor_id = str(record.get("instructor_id") or "").strip()
    year_int = _parse_int(str(record.get("year") or "")) or datetime.now().year
    period_type = str(record.get("period_type") or "month")
    period_value = str(record.get("period_value") or "")
    valid_shift_ids = {str(item.get("id") or "").strip() for item in list_shifts()}
    normalized_slots = _parse_availability_slots(slots, valid_shift_ids)

    try:
        upsert_record(
            {
                "instructor_id": instructor_id,
                "year": year_int,
                "period_type": period_type,
                "period_value": period_value,
                "slots": normalized_slots,
                "notes": notes,
                "updated_by": "Instrutor (link)",
                "source": "shared",
            }
        )
        _flash(request, "Disponibilidade enviada com sucesso.", "success")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse(f"/availability/instructors/shared/{token}", status_code=303)


def _parse_date_iso(value: str) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_br_date(value: str) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d/%m/%Y").date()
    except ValueError:
        return None


def _parse_hhmm(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%H:%M")
    except ValueError:
        return None


def _weekday_key(dt: date) -> str:
    labels = {0: "SEG", 1: "TER", 2: "QUA", 3: "QUI", 4: "SEX", 5: "SAB", 6: "DOM"}
    return labels.get(dt.weekday(), "")


def _schedule_active_on_day(item: Dict[str, Any], target_day: date) -> bool:
    start = _parse_br_date(str(item.get("data_inicio") or ""))
    end = _parse_br_date(str(item.get("data_fim") or ""))
    if not start or not end:
        return False
    if not (start <= target_day <= end):
        return False
    target_weekday = _weekday_key(target_day)
    weekdays = {str(day or "").strip().upper().replace("Á", "A") for day in (item.get("dias_execucao") or [])}
    return target_weekday in weekdays


def _schedule_running_now(item: Dict[str, Any], now_dt: datetime) -> bool:
    if not _schedule_active_on_day(item, now_dt.date()):
        return False
    start_dt = _parse_hhmm(str(item.get("hora_inicio") or ""))
    end_dt = _parse_hhmm(str(item.get("hora_fim") or ""))
    if not start_dt or not end_dt:
        return False
    now_minutes = now_dt.hour * 60 + now_dt.minute
    start_minutes = start_dt.hour * 60 + start_dt.minute
    end_minutes = end_dt.hour * 60 + end_dt.minute
    return start_minutes <= now_minutes < end_minutes


def _schedule_has_execution_between(item: Dict[str, Any], start_day: date, end_day: date) -> bool:
    sch_start = _parse_br_date(str(item.get("data_inicio") or ""))
    sch_end = _parse_br_date(str(item.get("data_fim") or ""))
    if not sch_start or not sch_end:
        return False
    overlap_start = max(start_day, sch_start)
    overlap_end = min(end_day, sch_end)
    if overlap_start > overlap_end:
        return False
    for raw_day in (item.get("dias_execucao") or []):
        day = _canonical_weekday_token(str(raw_day))
        idx = _weekday_index_from_token(day)
        if idx is None:
            continue
        if _has_weekday_between(overlap_start, overlap_end, idx):
            return True
    return False


def _schedule_range_bounds(items: List[Dict[str, Any]]) -> Optional[tuple[date, date]]:
    starts: List[date] = []
    ends: List[date] = []
    for item in items:
        start = _parse_br_date(str(item.get("data_inicio") or ""))
        end = _parse_br_date(str(item.get("data_fim") or ""))
        if not start or not end:
            continue
        starts.append(start)
        ends.append(end)
    if not starts or not ends:
        return None
    return min(starts), max(ends)


def _resolve_report_dates(
    date_from: str,
    date_to: str,
    schedules: List[Dict[str, Any]],
) -> tuple[date, date]:
    parsed_from = _parse_date_iso(date_from)
    parsed_to = _parse_date_iso(date_to)
    if parsed_from and parsed_to:
        return (parsed_to, parsed_from) if parsed_from > parsed_to else (parsed_from, parsed_to)
    bounds = _schedule_range_bounds(schedules)
    if bounds:
        return bounds
    today = date.today()
    return today, today


def _room_report_rows(
    rooms: List[Dict[str, Any]],
    schedules: List[Dict[str, Any]],
    shifts: List[Dict[str, Any]],
    start_day: date,
    end_day: date,
    selected_shift_id: str,
    selected_status: str,
) -> List[Dict[str, Any]]:
    shift_map = {str(item.get("id") or ""): item for item in shifts}
    rows: List[Dict[str, Any]] = []
    for room in rooms:
        room_id = str(room.get("id") or "")
        matches: List[Dict[str, Any]] = []
        for item in schedules:
            if str(item.get("sala_id") or "") != room_id:
                continue
            if selected_shift_id and str(item.get("turno_id") or "") != selected_shift_id:
                continue
            if not _schedule_has_execution_between(item, start_day, end_day):
                continue
            matches.append(item)
        is_occupied = len(matches) > 0
        status = "occupied" if is_occupied else "free"
        if selected_status in {"free", "occupied"} and status != selected_status:
            continue
        first = matches[0] if matches else {}
        first_shift = shift_map.get(str(first.get("turno_id") or "")) if first else None
        rows.append(
            {
                "room_id": room_id,
                "nome": room.get("nome") or room_id,
                "pavimento": room.get("pavimento") or "—",
                "capacidade": room.get("capacidade") or "—",
                "status": status,
                "agendamentos": len(matches),
                "turno": (first_shift.get("nome") if first_shift else "—") if matches else "—",
                "periodo": (
                    f"{first.get('data_inicio', '—')} a {first.get('data_fim', '—')}" if matches else "—"
                ),
                "turma": first.get("turma") or "—",
            }
        )
    rows.sort(key=lambda row: (0 if row["status"] == "occupied" else 1, str(row["nome"])))
    return rows


def _instructor_report_rows(
    instructors: List[Dict[str, Any]],
    schedules: List[Dict[str, Any]],
    shifts: List[Dict[str, Any]],
    rooms: List[Dict[str, Any]],
    start_day: date,
    end_day: date,
    selected_shift_id: str,
    selected_status: str,
) -> List[Dict[str, Any]]:
    shift_map = {str(item.get("id") or ""): item for item in shifts}
    room_map = {str(item.get("id") or ""): item for item in rooms}
    rows: List[Dict[str, Any]] = []
    for instructor in instructors:
        instructor_id = str(instructor.get("id") or "")
        matches: List[Dict[str, Any]] = []
        for item in schedules:
            item_instructors = {str(v).strip() for v in (item.get("instrutor_ids") or []) if str(v).strip()}
            primary = str(item.get("instrutor_id") or "").strip()
            if primary:
                item_instructors.add(primary)
            if instructor_id not in item_instructors:
                continue
            if selected_shift_id and str(item.get("turno_id") or "") != selected_shift_id:
                continue
            if not _schedule_has_execution_between(item, start_day, end_day):
                continue
            matches.append(item)
        is_occupied = len(matches) > 0
        status = "occupied" if is_occupied else "free"
        if selected_status in {"free", "occupied"} and status != selected_status:
            continue
        first = matches[0] if matches else {}
        first_shift = shift_map.get(str(first.get("turno_id") or "")) if first else None
        first_room = room_map.get(str(first.get("sala_id") or "")) if first else None
        rows.append(
            {
                "instructor_id": instructor_id,
                "nome": instructor.get("nome_sobrenome") or instructor.get("nome") or instructor_id,
                "status": status,
                "agendamentos": len(matches),
                "turno": (first_shift.get("nome") if first_shift else "—") if matches else "—",
                "periodo": (
                    f"{first.get('data_inicio', '—')} a {first.get('data_fim', '—')}" if matches else "—"
                ),
                "turma": first.get("turma") or "—",
                "ambiente": (first_room.get("nome") if first_room else "—") if matches else "—",
            }
        )
    rows.sort(key=lambda row: (0 if row["status"] == "occupied" else 1, str(row["nome"])))
    return rows


def _xlsx_col_name(index_1_based: int) -> str:
    if index_1_based <= 0:
        return "A"
    name = ""
    n = index_1_based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def _xml_escape(value: Any) -> str:
    text = str(value if value is not None else "")
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    # remove control characters invalid in XML 1.0 (except tab/newline/carriage return)
    text = "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 32)
    return text


def _build_xlsx_bytes(sheet_name: str, headers: List[str], rows: List[List[Any]]) -> bytes:
    safe_sheet = _xml_escape(sheet_name)[:31] or "Relatorio"

    sheet_rows: List[str] = []
    all_rows = [headers] + rows
    for r_idx, row_values in enumerate(all_rows, start=1):
        cells: List[str] = []
        for c_idx, value in enumerate(row_values, start=1):
            cell_ref = f"{_xlsx_col_name(c_idx)}{r_idx}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
            else:
                escaped = _xml_escape(value)
                cells.append(
                    f'<c r="{cell_ref}" t="inlineStr"><is><t xml:space="preserve">{escaped}</t></is></c>'
                )
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        + "".join(sheet_rows)
        + "</sheetData></worksheet>"
    )

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""
    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
    workbook_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{safe_sheet}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""
    workbook_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>"""

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        zf.writestr("xl/styles.xml", styles_xml)
    return output.getvalue()


@app.get("/availability/rooms")
def availability_rooms(request: Request, view: str = "current"):
    mode = str(view or "current").strip().lower()
    if mode not in {"current", "free"}:
        mode = "current"

    rooms = [item for item in list_rooms() if item.get("ativo", True)]
    schedules = list_schedules()
    courses_map = {str(item.get("id") or ""): item for item in list_courses()}
    shifts_map = {str(item.get("id") or ""): item for item in list_shifts()}
    instructors_map = {str(item.get("id") or ""): item for item in list_instructors()}

    occupied_now: List[Dict[str, Any]] = []
    for item in schedules:
        room_id = str(item.get("sala_id") or "")
        if not room_id:
            continue
        room = next((r for r in rooms if str(r.get("id") or "") == room_id), None)
        if not room:
            continue
        course = courses_map.get(str(item.get("curso_id") or ""))
        shift = shifts_map.get(str(item.get("turno_id") or ""))
        instructor_ids = [str(v).strip() for v in (item.get("instrutor_ids") or []) if str(v).strip()]
        primary_id = str(item.get("instrutor_id") or "").strip()
        if primary_id and primary_id not in instructor_ids:
            instructor_ids.insert(0, primary_id)
        instructor_names = []
        for instructor_id in instructor_ids:
            instructor = instructors_map.get(instructor_id)
            if not instructor:
                continue
            display = instructor.get("nome_sobrenome") or instructor.get("nome") or instructor_id
            if display not in instructor_names:
                instructor_names.append(display)
        occupied_now.append(
            {
                "room_id": room_id,
                "ambiente": room.get("nome") or room_id,
                "pavimento": room.get("pavimento") or "—",
                "capacidade": room.get("capacidade") or "—",
                "curso": (course.get("nome") if course else "—"),
                "turma": item.get("turma") or "—",
                "instrutor": ", ".join(instructor_names) if instructor_names else "—",
                "turno": (shift.get("nome") if shift else "—"),
                "horario": f"{item.get('hora_inicio') or '—'} - {item.get('hora_fim') or '—'}",
                "periodo": f"{item.get('data_inicio') or '—'} a {item.get('data_fim') or '—'}",
            }
        )
    occupied_room_ids = {str(row.get("room_id") or "") for row in occupied_now}

    free_now = [
        {
            "room_id": str(room.get("id") or ""),
            "ambiente": room.get("nome") or str(room.get("id") or ""),
            "pavimento": room.get("pavimento") or "—",
            "capacidade": room.get("capacidade") or "—",
        }
        for room in rooms
        if str(room.get("id") or "") not in occupied_room_ids
    ]
    occupied_now.sort(key=lambda row: (str(row["ambiente"]), str(row["periodo"])))
    free_now.sort(key=lambda row: str(row["ambiente"]))

    return _render(
        request,
        "availability_rooms.html",
        selected_view=mode,
        now_label="Baseado na programação cadastrada",
        occupied_now=occupied_now,
        free_now=free_now,
        total_rooms=len(rooms),
        total_occupied=len(occupied_room_ids),
        total_free=len(free_now),
    )


@app.get("/availability/rooms/report")
def availability_rooms_report(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    shift_id: str = "",
    status: str = "all",
):
    selected_status = str(status or "all").strip().lower()
    if selected_status not in {"all", "free", "occupied"}:
        selected_status = "all"

    rooms = [item for item in list_rooms() if item.get("ativo", True)]
    schedules = list_schedules()
    selected_from, selected_to = _resolve_report_dates(date_from, date_to, schedules)
    shifts = [item for item in list_shifts() if item.get("ativo", True)]
    rows = _room_report_rows(
        rooms=rooms,
        schedules=schedules,
        shifts=shifts,
        start_day=selected_from,
        end_day=selected_to,
        selected_shift_id=str(shift_id or "").strip(),
        selected_status=selected_status,
    )

    total = len(rows)
    occupied_count = sum(1 for row in rows if row["status"] == "occupied")
    free_count = sum(1 for row in rows if row["status"] == "free")
    return _render(
        request,
        "availability_rooms_report.html",
        rows=rows,
        shifts=shifts,
        selected_shift_id=str(shift_id or "").strip(),
        selected_status=selected_status,
        selected_from=selected_from.isoformat(),
        selected_to=selected_to.isoformat(),
        total=total,
        occupied_count=occupied_count,
        free_count=free_count,
    )


@app.get("/availability/rooms/report.xlsx")
def availability_rooms_report_xlsx(
    date_from: str = "",
    date_to: str = "",
    shift_id: str = "",
    status: str = "all",
):
    selected_status = str(status or "all").strip().lower()
    if selected_status not in {"all", "free", "occupied"}:
        selected_status = "all"

    rooms = [item for item in list_rooms() if item.get("ativo", True)]
    schedules = list_schedules()
    selected_from, selected_to = _resolve_report_dates(date_from, date_to, schedules)
    shifts = [item for item in list_shifts() if item.get("ativo", True)]
    rows = _room_report_rows(
        rooms=rooms,
        schedules=schedules,
        shifts=shifts,
        start_day=selected_from,
        end_day=selected_to,
        selected_shift_id=str(shift_id or "").strip(),
        selected_status=selected_status,
    )

    xlsx_headers = [
        "Ambiente",
        "Pavimento",
        "Capacidade",
        "Status",
        "Qtd. Agendamentos",
        "Turno (1o)",
        "Periodo (1o)",
        "Turma (1o)",
    ]
    xlsx_rows: List[List[Any]] = []
    for item in rows:
        xlsx_rows.append(
            [
                item.get("nome") or "",
                item.get("pavimento") or "",
                item.get("capacidade") or "",
                "Ocupado" if item.get("status") == "occupied" else "Livre",
                int(item.get("agendamentos") or 0),
                item.get("turno") or "",
                item.get("periodo") or "",
                item.get("turma") or "",
            ]
        )
    xlsx_data = _build_xlsx_bytes("Relatorio Ambientes", xlsx_headers, xlsx_rows)
    filename = f"relatorio_ambientes_{selected_from.isoformat()}_{selected_to.isoformat()}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(
        content=xlsx_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.get("/availability/instructors/report")
def availability_instructors_report(
    request: Request,
    date_from: str = "",
    date_to: str = "",
    shift_id: str = "",
    status: str = "all",
):
    selected_status = str(status or "all").strip().lower()
    if selected_status not in {"all", "free", "occupied"}:
        selected_status = "all"

    schedules = list_schedules()
    selected_from, selected_to = _resolve_report_dates(date_from, date_to, schedules)
    shifts = [item for item in list_shifts() if item.get("ativo", True)]
    rooms = [item for item in list_rooms() if item.get("ativo", True)]
    instructors = [
        item for item in list_instructors() if item.get("role") == "Instrutor" and item.get("ativo", True)
    ]
    instructors.sort(key=lambda item: (item.get("nome_sobrenome") or item.get("nome") or ""))

    rows = _instructor_report_rows(
        instructors=instructors,
        schedules=schedules,
        shifts=shifts,
        rooms=rooms,
        start_day=selected_from,
        end_day=selected_to,
        selected_shift_id=str(shift_id or "").strip(),
        selected_status=selected_status,
    )
    total = len(rows)
    occupied_count = sum(1 for row in rows if row["status"] == "occupied")
    free_count = sum(1 for row in rows if row["status"] == "free")
    return _render(
        request,
        "availability_instructors_report.html",
        rows=rows,
        shifts=shifts,
        selected_shift_id=str(shift_id or "").strip(),
        selected_status=selected_status,
        selected_from=selected_from.isoformat(),
        selected_to=selected_to.isoformat(),
        total=total,
        occupied_count=occupied_count,
        free_count=free_count,
    )


@app.get("/collaborators/new")
def collaborators_new(request: Request):
    return _render(
        request,
        "collaborator_form.html",
        instructor=None,
        instructor_id=_next_id(list_instructors()),
    )


@app.get("/instructors/new")
def instructors_new_redirect():
    return RedirectResponse("/collaborators/new", status_code=302)


@app.post("/collaborators/new")
@app.post("/instructors/new")
def collaborators_create(
    request: Request,
    instructor_id: str = Form(""),
    nome: str = Form(...),
    nome_sobrenome: str = Form(""),
    email: str = Form(...),
    telefone: str = Form(...),
    role: str = Form("Instrutor"),
    especialidades: str = Form(""),
    max_horas_semana: str = Form(""),
    ativo: str = Form("true"),
):
    payload = {
        "id": instructor_id,
        "nome": nome,
        "nome_sobrenome": nome_sobrenome,
        "email": email,
        "telefone": telefone,
        "role": role,
        "especialidades": [item.strip() for item in especialidades.split(",") if item.strip()],
        "max_horas_semana": _parse_float(max_horas_semana),
        "ativo": ativo == "true",
    }
    try:
        create_instructor(payload)
        _flash(request, "Colaborador cadastrado com sucesso.")
        return RedirectResponse("/collaborators", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(
            request,
            "collaborator_form.html",
            instructor=payload,
            instructor_id=payload.get("id"),
        )


@app.get("/collaborators/{instructor_id}/edit")
def collaborators_edit(request: Request, instructor_id: str):
    return _render(
        request,
        "collaborator_form.html",
        instructor=get_instructor(instructor_id),
    )


@app.get("/instructors/{instructor_id}/edit")
def instructors_edit_redirect(instructor_id: str):
    return RedirectResponse(f"/collaborators/{instructor_id}/edit", status_code=302)


@app.post("/collaborators/{instructor_id}/edit")
@app.post("/instructors/{instructor_id}/edit")
def collaborators_update(
    request: Request,
    instructor_id: str,
    nome: str = Form(...),
    nome_sobrenome: str = Form(""),
    email: str = Form(...),
    telefone: str = Form(...),
    role: str = Form("Instrutor"),
    especialidades: str = Form(""),
    max_horas_semana: str = Form(""),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
        "nome_sobrenome": nome_sobrenome,
        "email": email,
        "telefone": telefone,
        "role": role,
        "especialidades": [item.strip() for item in especialidades.split(",") if item.strip()],
        "max_horas_semana": _parse_float(max_horas_semana),
        "ativo": ativo == "true",
    }
    try:
        update_instructor(instructor_id, updates)
        _flash(request, "Colaborador atualizado com sucesso.")
        return RedirectResponse("/collaborators", status_code=303)
    except ValidationError as exc:
        updates["id"] = instructor_id
        _flash(request, str(exc), "error")
        return _render(
            request,
            "collaborator_form.html",
            instructor=updates,
            instructor_id=instructor_id,
        )


@app.post("/collaborators/{instructor_id}/delete")
@app.post("/instructors/{instructor_id}/delete")
def collaborators_delete(request: Request, instructor_id: str):
    try:
        delete_instructor(instructor_id)
        _flash(request, "Colaborador removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/collaborators", status_code=303)


@app.get("/shifts")
def shifts_list(request: Request):
    return _render(request, "shifts.html", shifts=list_shifts())


@app.get("/shifts/new")
def shifts_new(request: Request):
    return _render(
        request,
        "shift_form.html",
        shift=None,
        shift_id=_next_id(list_shifts()),
    )


@app.post("/shifts/new")
def shifts_create(
    request: Request,
    shift_id: str = Form(""),
    nome: str = Form(...),
    horario_inicio: str = Form(...),
    horario_fim: str = Form(...),
    ativo: str = Form("true"),
):
    payload = {
        "id": shift_id,
        "nome": nome,
        "horario_inicio": horario_inicio,
        "horario_fim": horario_fim,
        "ativo": ativo == "true",
    }
    try:
        create_shift(payload)
        _flash(request, "Turno cadastrado com sucesso.")
        return RedirectResponse("/shifts", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(
            request,
            "shift_form.html",
            shift=payload,
            shift_id=payload.get("id"),
        )


@app.get("/shifts/{shift_id}/edit")
def shifts_edit(request: Request, shift_id: str):
    return _render(request, "shift_form.html", shift=get_shift(shift_id))


@app.post("/shifts/{shift_id}/edit")
def shifts_update(
    request: Request,
    shift_id: str,
    nome: str = Form(...),
    horario_inicio: str = Form(...),
    horario_fim: str = Form(...),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
        "horario_inicio": horario_inicio,
        "horario_fim": horario_fim,
        "ativo": ativo == "true",
    }
    try:
        update_shift(shift_id, updates)
        _flash(request, "Turno atualizado com sucesso.")
        return RedirectResponse("/shifts", status_code=303)
    except ValidationError as exc:
        updates["id"] = shift_id
        _flash(request, str(exc), "error")
        return _render(
            request,
            "shift_form.html",
            shift=updates,
            shift_id=shift_id,
        )


@app.post("/shifts/{shift_id}/delete")
def shifts_delete(request: Request, shift_id: str):
    try:
        delete_shift(shift_id)
        _flash(request, "Turno removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/shifts", status_code=303)


@app.get("/calendars")
def calendars_list(request: Request):
    return _render(request, "calendars.html", calendars=list_calendars())


@app.get("/calendars/new")
def calendars_new(request: Request):
    totals = _sum_calendar_totals([[] for _ in range(12)], [[] for _ in range(12)])
    return _render(
        request,
        "calendar_form.html",
        calendar=None,
        calendar_id=_next_id(list_calendars()),
        months=MONTHS,
        total_dias_letivos=totals["dias_letivos"],
        total_feriados=totals["feriados"],
    )


@app.post("/calendars/new")
async def calendars_create(
    request: Request,
    ano: str = Form(...),
    ativo: str = Form("true"),
    calendar_id: str = Form(""),
):
    form_data = await request.form()
    dias_letivos = [_parse_days_list(form_data.get(f"dias_letivos_{idx}", "")) for idx in range(1, 13)]
    feriados = [_parse_days_list(form_data.get(f"feriados_{idx}", "")) for idx in range(1, 13)]
    if not any(dias_letivos):
        _flash(request, "Preencha ao menos um dia letivo no calendÃ¡rio.", "error")
        totals = _sum_calendar_totals(dias_letivos, feriados)
        return _render(
            request,
            "calendar_form.html",
            calendar={
                "id": calendar_id,
                "ano": ano,
                "dias_letivos_por_mes": dias_letivos,
                "feriados_por_mes": feriados,
                "ativo": ativo == "true",
            },
            calendar_id=calendar_id,
            months=MONTHS,
            total_dias_letivos=totals["dias_letivos"],
            total_feriados=totals["feriados"],
        )
    payload = {
        "id": calendar_id,
        "ano": _parse_int(ano) or ano,
        "dias_letivos_por_mes": dias_letivos,
        "feriados_por_mes": feriados,
        "ativo": ativo == "true",
    }
    try:
        create_calendar(payload)
        _flash(request, "CalendÃ¡rio cadastrado com sucesso.")
        return RedirectResponse("/calendars", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        totals = _sum_calendar_totals(dias_letivos, feriados)
        return _render(
            request,
            "calendar_form.html",
            calendar=payload,
            calendar_id=payload.get("id"),
            months=MONTHS,
            total_dias_letivos=totals["dias_letivos"],
            total_feriados=totals["feriados"],
        )


@app.get("/calendars/{year}/edit")
def calendars_edit(request: Request, year: int):
    calendar = get_calendar(year)
    totals = _sum_calendar_totals(
        calendar.get("dias_letivos_por_mes", [[] for _ in range(12)]) if calendar else [[] for _ in range(12)],
        calendar.get("feriados_por_mes", [[] for _ in range(12)]) if calendar else [[] for _ in range(12)],
    )
    return _render(
        request,
        "calendar_form.html",
        calendar=calendar,
        calendar_id=calendar.get("id") if calendar else "",
        months=MONTHS,
        total_dias_letivos=totals["dias_letivos"],
        total_feriados=totals["feriados"],
    )


@app.post("/calendars/{year}/edit")
async def calendars_update(
    request: Request,
    year: int,
    ativo: str = Form("true"),
    calendar_id: str = Form(""),
):
    form_data = await request.form()
    dias_letivos = [_parse_days_list(form_data.get(f"dias_letivos_{idx}", "")) for idx in range(1, 13)]
    feriados = [_parse_days_list(form_data.get(f"feriados_{idx}", "")) for idx in range(1, 13)]
    if not any(dias_letivos):
        _flash(request, "Preencha ao menos um dia letivo no calendÃ¡rio.", "error")
        totals = _sum_calendar_totals(dias_letivos, feriados)
        return _render(
            request,
            "calendar_form.html",
            calendar={
                "id": calendar_id,
                "ano": year,
                "dias_letivos_por_mes": dias_letivos,
                "feriados_por_mes": feriados,
                "ativo": ativo == "true",
            },
            calendar_id=calendar_id,
            months=MONTHS,
            total_dias_letivos=totals["dias_letivos"],
            total_feriados=totals["feriados"],
        )
    updates = {
        "id": calendar_id,
        "dias_letivos_por_mes": dias_letivos,
        "feriados_por_mes": feriados,
        "ativo": ativo == "true",
    }
    try:
        update_calendar(year, updates)
        _flash(request, "CalendÃ¡rio atualizado com sucesso.")
        return RedirectResponse("/calendars", status_code=303)
    except ValidationError as exc:
        updates["ano"] = year
        _flash(request, str(exc), "error")
        totals = _sum_calendar_totals(dias_letivos, feriados)
        return _render(
            request,
            "calendar_form.html",
            calendar=updates,
            calendar_id=calendar_id,
            months=MONTHS,
            total_dias_letivos=totals["dias_letivos"],
            total_feriados=totals["feriados"],
        )


@app.post("/calendars/{year}/delete")
def calendars_delete(request: Request, year: int):
    try:
        delete_calendar(year)
        _flash(request, "CalendÃ¡rio removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/calendars", status_code=303)


@app.get("/calendars/{year}/calendar-view")
def calendars_view(request: Request, year: int):
    calendar = get_calendar(year)
    if not calendar:
        _flash(request, "CalendÃ¡rio nÃ£o encontrado.", "error")
        return RedirectResponse("/calendars", status_code=302)
    months_view = []
    for idx, month in enumerate(MONTHS, start=1):
        letivos_set = set(calendar.get("dias_letivos_por_mes", [[] for _ in range(12)])[idx - 1])
        months_view.append(
            {
                "label": month["label"],
                "weeks": _build_month_grid(year, idx),
                "letivos": letivos_set,
                "letivos_count": len(letivos_set),
                "feriados": set(calendar.get("feriados_por_mes", [[] for _ in range(12)])[idx - 1]),
            }
        )
    return _render(
        request,
        "calendar_view.html",
        calendar=calendar,
        months_view=months_view,
    )


@app.get("/curricular-units")
def units_list(request: Request, course_id: str = ""):
    items = list_units()
    course_name = None
    if course_id:
        items = [unit for unit in items if unit.get("curso_id") == course_id]
        course = get_course(course_id)
        course_name = course.get("nome") if course else None
    return _render(
        request,
        "curricular_units.html",
        units=items,
        courses=list_courses(),
        course_filter=course_id or None,
        course_name=course_name,
    )


@app.get("/curricular-units/new")
def units_new(request: Request):
    return _render(request, "curricular_unit_form.html", unit=None, courses=list_courses())


@app.post("/curricular-units/new")
def units_create(
    request: Request,
    unit_id: str = Form(...),
    curso_id: str = Form(...),
    nome: str = Form(...),
    carga_horaria: str = Form(""),
    modulo: str = Form(""),
    ativo: str = Form("true"),
):
    payload: Dict[str, Any] = {
        "id": unit_id,
        "curso_id": curso_id,
        "nome": nome,
        "ativo": ativo == "true",
    }
    if carga_horaria.strip():
        payload["carga_horaria"] = _parse_float(carga_horaria) or carga_horaria
    if modulo.strip():
        payload["modulo"] = modulo
    try:
        create_unit(payload)
        _flash(request, "Unidade curricular cadastrada com sucesso.")
        return RedirectResponse("/curricular-units", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(request, "curricular_unit_form.html", unit=payload, courses=list_courses())


@app.get("/curricular-units/{unit_id}/edit")
def units_edit(request: Request, unit_id: str):
    return _render(
        request,
        "curricular_unit_form.html",
        unit=get_unit(unit_id),
        courses=list_courses(),
    )


@app.post("/curricular-units/{unit_id}/edit")
def units_update(
    request: Request,
    unit_id: str,
    curso_id: str = Form(...),
    nome: str = Form(...),
    carga_horaria: str = Form(""),
    modulo: str = Form(""),
    ativo: str = Form("true"),
):
    updates: Dict[str, Any] = {
        "curso_id": curso_id,
        "nome": nome,
        "ativo": ativo == "true",
    }
    if carga_horaria.strip():
        updates["carga_horaria"] = _parse_float(carga_horaria) or carga_horaria
    else:
        updates.pop("carga_horaria", None)
    if modulo.strip():
        updates["modulo"] = modulo
    try:
        update_unit(unit_id, updates)
        _flash(request, "Unidade curricular atualizada com sucesso.")
        return RedirectResponse("/curricular-units", status_code=303)
    except ValidationError as exc:
        updates["id"] = unit_id
        _flash(request, str(exc), "error")
        return _render(request, "curricular_unit_form.html", unit=updates, courses=list_courses())


@app.post("/curricular-units/{unit_id}/delete")
def units_delete(request: Request, unit_id: str):
    try:
        delete_unit(unit_id)
        _flash(request, "Unidade curricular removida com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/curricular-units", status_code=303)


@app.get("/curricular-units/batch")
def units_batch(request: Request, course_id: str = ""):
    return _render(
        request,
        "curricular_unit_batch.html",
        courses=list_courses(),
        course_id=course_id,
    )


@app.post("/curricular-units/batch")
def units_batch_create(
    request: Request,
    curso_id: str = Form(...),
    linhas: str = Form(...),
):
    try:
        created = create_units_batch_from_lines(curso_id, linhas)
        _flash(request, f"{len(created)} unidades curriculares cadastradas.")
        redirect_url = "/curricular-units"
        if curso_id:
            redirect_url = f"{redirect_url}?course_id={curso_id}"
        return RedirectResponse(redirect_url, status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(
            request,
            "curricular_unit_batch.html",
            courses=list_courses(),
            course_id=curso_id,
            linhas=linhas,
        )


@app.get("/programming")
def programming_list(
    request: Request,
    ano: str = "",
    mes: str = "",
    trimestre: str = "",
    print_mode: str = "",
):
    quarter_map = {
        "1": {"label": "1º Trimestre", "months": {"1", "2", "3"}},
        "2": {"label": "2º Trimestre", "months": {"4", "5", "6"}},
        "3": {"label": "3º Trimestre", "months": {"7", "8", "9"}},
        "4": {"label": "4º Trimestre", "months": {"10", "11", "12"}},
    }

    # Regra de exclusao mutua: mes tem prioridade sobre trimestre.
    if mes:
        trimestre = ""

    items = list_schedules()

    if ano:
        items = [item for item in items if str(item.get("ano", "")) == str(ano)]
    if mes:
        items = [item for item in items if str(item.get("mes", "")) == str(mes)]
    elif trimestre in quarter_map:
        quarter_months = quarter_map[trimestre]["months"]
        items = [item for item in items if str(item.get("mes", "")) in quarter_months]

    all_items = list_schedules()
    if ano:
        all_items = [item for item in all_items if str(item.get("ano", "")) == str(ano)]
    if trimestre in quarter_map:
        all_items = [
            item for item in all_items if str(item.get("mes", "")) in quarter_map[trimestre]["months"]
        ]
    months_available = {str(item.get("mes")) for item in all_items if item.get("mes")}
    month_options = [month for month in MONTHS if month["value"] in months_available]
    courses = list_courses()
    rooms = list_rooms()
    shifts = list_shifts()
    instructors = list_instructors()
    course_map = {item["id"]: item.get("nome", item["id"]) for item in courses}
    course_type_map = {item["id"]: item.get("tipo_curso", "—") for item in courses}
    room_map = {item["id"]: item.get("nome", item["id"]) for item in rooms}
    room_abbr_map = {item["id"]: (item.get("abreviacao") or "") for item in rooms}
    shift_map = {item["id"]: item.get("nome", item["id"]) for item in shifts}
    instructor_map = {
        item["id"]: item.get("nome_sobrenome") or item.get("nome", item["id"])
        for item in instructors
    }

    month_name_map = {m["value"]: m["label"] for m in MONTHS}

    def _abbr_ambiente(name: str) -> str:
        words = [w for w in (name or "").replace("/", " ").split() if w]
        if not words:
            return "—"
        ignored = {"de", "da", "do", "das", "dos", "e"}
        key_words = [w for w in words if w.lower() not in ignored]
        source = key_words if key_words else words
        if len(source) == 1:
            return source[0][:12]
        return "".join([w[0].upper() for w in source[:4]])

    def _format_pavimento(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return "—"
        if "ter" in text or text == "0":
            return "Térreo"
        if text.startswith("1") or "1o" in text or "1º" in text:
            return "1º Andar"
        return str(value)

    def _format_horario(inicio: Any, fim: Any) -> str:
        hi = str(inicio or "").strip()
        hf = str(fim or "").strip()
        if not hi or not hf:
            return "—"
        hi_h = hi.split(":")[0].zfill(2) if ":" in hi else hi
        hf_h = hf.split(":")[0].zfill(2) if ":" in hf else hf
        return f"{hi_h}h às {hf_h}h"

    def _first_name(full_name: Any) -> str:
        text = str(full_name or "").strip()
        if not text:
            return "—"
        return text.split()[0]

    def _short_date(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return "—"
        parts = text.split("/")
        if len(parts) == 3 and len(parts[2]) == 4:
            return f"{parts[0]}/{parts[1]}/{parts[2][2:]}"
        return text

    def _format_periodo_short(inicio: Any, fim: Any) -> str:
        return f"{_short_date(inicio)} a {_short_date(fim)}"

    def _compress_days(days_list: List[str]) -> str:
        order = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "SAB", "DOM"]
        idx_map = {d: i for i, d in enumerate(order)}
        clean = [str(d).strip().upper() for d in (days_list or []) if str(d).strip()]
        clean = [d for d in clean if d in idx_map]
        if not clean:
            return "—"
        uniq = sorted(set(clean), key=lambda d: idx_map[d])

        ranges: List[str] = []
        start = uniq[0]
        prev = uniq[0]
        for cur in uniq[1:]:
            if idx_map[cur] == idx_map[prev] + 1:
                prev = cur
                continue
            ranges.append(start if start == prev else f"{start}-{prev}")
            start = cur
            prev = cur
        ranges.append(start if start == prev else f"{start}-{prev}")
        return ", ".join(ranges)

    def _schedule_instructors(schedule_item: Dict[str, Any]) -> str:
        ids = schedule_item.get("instrutor_ids") or []
        if isinstance(ids, str):
            ids = [ids]
        ids = [str(i).strip() for i in ids if str(i).strip()]
        if not ids and schedule_item.get("instrutor_id"):
            ids = [str(schedule_item.get("instrutor_id"))]
        names = [instructor_map.get(i, i) for i in ids]
        return " / ".join(names) if names else "—"

    report_rows: List[Dict[str, Any]] = []
    for item in items:
        month_value = str(item.get("mes") or "")
        report_rows.append(
            {
                "mes": month_value,
                "mes_label": month_name_map.get(month_value, month_value or "—"),
                "turno": shift_map.get(item.get("turno_id"), item.get("turno_id") or "—"),
                "pavimento": _format_pavimento(item.get("pavimento")),
                "ambiente": (
                    room_abbr_map.get(item.get("sala_id")) or
                    _abbr_ambiente(room_map.get(item.get("sala_id"), item.get("sala_id") or ""))
                ),
                "qtd_alunos": item.get("qtd_alunos") or "—",
                "curso": course_map.get(item.get("curso_id"), item.get("curso_id") or "—"),
                "tipo": course_type_map.get(item.get("curso_id"), "—"),
                "periodo": _format_periodo_short(item.get("data_inicio"), item.get("data_fim")),
                "ch": item.get("ch_total") or "—",
                "turma": item.get("turma") or "—",
                "horario": _format_horario(item.get("hora_inicio"), item.get("hora_fim")),
                "analista": _first_name(
                    instructor_map.get(item.get("analista_id"), item.get("analista_id") or "—")
                ),
                "assistente": instructor_map.get(item.get("assistente_id"), item.get("assistente_id") or "—"),
                "instrutor": _schedule_instructors(item),
                "dias": _compress_days(item.get("dias_execucao") or []),
            }
        )

    def _turno_order(value: str) -> int:
        text = (value or "").strip().lower()
        text = (
            text.replace("ã", "a")
            .replace("á", "a")
            .replace("â", "a")
            .replace("é", "e")
            .replace("ê", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ô", "o")
            .replace("õ", "o")
            .replace("ú", "u")
        )
        if "manha" in text:
            return 0
        if "tarde" in text:
            return 1
        if "noite" in text:
            return 2
        return 9

    report_rows.sort(
        key=lambda row: (
            int(row["mes"]) if str(row.get("mes", "")).isdigit() else 99,
            _turno_order(row.get("turno", "")),
            row.get("horario", ""),
            row.get("curso", ""),
        )
    )

    report_month_groups: List[Dict[str, Any]] = []
    if mes:
        label = month_name_map.get(str(mes), str(mes))
        report_month_groups.append(
            {
                "value": str(mes),
                "label": label,
                "rows": [row for row in report_rows if row["mes"] == str(mes)],
            }
        )
    elif trimestre in quarter_map:
        for month in MONTHS:
            if month["value"] not in quarter_map[trimestre]["months"]:
                continue
            report_month_groups.append(
                {
                    "value": month["value"],
                    "label": month["label"],
                    "rows": [row for row in report_rows if row["mes"] == month["value"]],
                }
            )
    else:
        for month in MONTHS:
            month_rows = [row for row in report_rows if row["mes"] == month["value"]]
            if not month_rows:
                continue
            report_month_groups.append(
                {
                    "value": month["value"],
                    "label": month["label"],
                    "rows": month_rows,
                }
            )

    return _render(
        request,
        "schedules.html",
        schedules=items,
        courses=courses,
        instructors=instructors,
        rooms=rooms,
        shifts=shifts,
        course_map=course_map,
        room_map=room_map,
        shift_map=shift_map,
        instructor_map=instructor_map,
        report_rows=report_rows,
        report_month_groups=report_month_groups,
        months=month_options,
        all_months=MONTHS,
        quarter_options=[
            {"value": "", "label": "Todos"},
            {"value": "1", "label": "1º Trimestre"},
            {"value": "2", "label": "2º Trimestre"},
            {"value": "3", "label": "3º Trimestre"},
            {"value": "4", "label": "4º Trimestre"},
        ],
        filters={
            "ano": ano,
            "mes": mes,
            "trimestre": trimestre,
        },
        auto_print=(print_mode == "1"),
    )


@app.get("/programming/current")
def programming_current(request: Request):
    today = date.today()
    year_value = str(today.year)
    month_value = str(today.month)

    items = [
        item
        for item in list_schedules()
        if str(item.get("ano", "")) == year_value and str(item.get("mes", "")) == month_value
    ]

    courses = list_courses()
    rooms = list_rooms()
    shifts = list_shifts()
    instructors = list_instructors()
    course_map = {item["id"]: item.get("nome", item["id"]) for item in courses}
    room_map = {item["id"]: item.get("nome", item["id"]) for item in rooms}
    room_abbr_map = {item["id"]: (item.get("abreviacao") or "") for item in rooms}
    shift_map = {item["id"]: item.get("nome", item["id"]) for item in shifts}
    instructor_map = {
        item["id"]: item.get("nome_sobrenome") or item.get("nome", item["id"])
        for item in instructors
    }
    month_name_map = {m["value"]: m["label"] for m in MONTHS}

    def _abbr_ambiente(name: str) -> str:
        words = [w for w in (name or "").replace("/", " ").split() if w]
        if not words:
            return "—"
        ignored = {"de", "da", "do", "das", "dos", "e"}
        key_words = [w for w in words if w.lower() not in ignored]
        source = key_words if key_words else words
        if len(source) == 1:
            return source[0][:12]
        return "".join([w[0].upper() for w in source[:4]])

    def _format_pavimento(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return "—"
        if "ter" in text or text == "0":
            return "Térreo"
        if text.startswith("1") or "1o" in text or "1º" in text:
            return "1º Andar"
        return str(value)

    def _first_name(full_name: Any) -> str:
        text = str(full_name or "").strip()
        if not text:
            return "—"
        return text.split()[0]

    def _short_date(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return "—"
        parts = text.split("/")
        if len(parts) == 3 and len(parts[2]) == 4:
            return f"{parts[0]}/{parts[1]}/{parts[2][2:]}"
        return text

    def _format_horario(inicio: Any, fim: Any) -> str:
        hi = str(inicio or "").strip()
        hf = str(fim or "").strip()
        if not hi or not hf:
            return "—"
        hi_h = hi.split(":")[0].zfill(2) if ":" in hi else hi
        hf_h = hf.split(":")[0].zfill(2) if ":" in hf else hf
        return f"{hi_h}h às {hf_h}h"

    def _compress_days(days_list: List[str]) -> str:
        order = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "SAB", "DOM"]
        idx_map = {d: i for i, d in enumerate(order)}
        clean = [str(d).strip().upper() for d in (days_list or []) if str(d).strip()]
        clean = [d for d in clean if d in idx_map]
        if not clean:
            return "—"
        uniq = sorted(set(clean), key=lambda d: idx_map[d])
        ranges: List[str] = []
        start = uniq[0]
        prev = uniq[0]
        for cur in uniq[1:]:
            if idx_map[cur] == idx_map[prev] + 1:
                prev = cur
                continue
            ranges.append(start if start == prev else f"{start}-{prev}")
            start = cur
            prev = cur
        ranges.append(start if start == prev else f"{start}-{prev}")
        return ", ".join(ranges)

    def _schedule_instructors(schedule_item: Dict[str, Any]) -> str:
        ids = schedule_item.get("instrutor_ids") or []
        if isinstance(ids, str):
            ids = [ids]
        ids = [str(i).strip() for i in ids if str(i).strip()]
        if not ids and schedule_item.get("instrutor_id"):
            ids = [str(schedule_item.get("instrutor_id"))]
        names = [instructor_map.get(i, i) for i in ids]
        return " / ".join(names) if names else "—"

    def _turno_order(value: str) -> int:
        text = (value or "").strip().lower()
        text = (
            text.replace("ã", "a")
            .replace("á", "a")
            .replace("â", "a")
            .replace("é", "e")
            .replace("ê", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ô", "o")
            .replace("õ", "o")
            .replace("ú", "u")
        )
        if "manha" in text:
            return 0
        if "tarde" in text:
            return 1
        if "noite" in text:
            return 2
        return 9

    rows: List[Dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "turno": shift_map.get(item.get("turno_id"), item.get("turno_id") or "—"),
                "pavimento": _format_pavimento(item.get("pavimento")),
                "ambiente": (
                    room_abbr_map.get(item.get("sala_id")) or
                    _abbr_ambiente(room_map.get(item.get("sala_id"), item.get("sala_id") or ""))
                ),
                "qtd_alunos": item.get("qtd_alunos") or "—",
                "curso": course_map.get(item.get("curso_id"), item.get("curso_id") or "—"),
                "periodo": f"{_short_date(item.get('data_inicio'))} a {_short_date(item.get('data_fim'))}",
                "ch": item.get("ch_total") or "—",
                "turma": item.get("turma") or "—",
                "horario": _format_horario(item.get("hora_inicio"), item.get("hora_fim")),
                "analista": _first_name(
                    instructor_map.get(item.get("analista_id"), item.get("analista_id") or "—")
                ),
                "assistente": instructor_map.get(item.get("assistente_id"), item.get("assistente_id") or "—"),
                "instrutor": _schedule_instructors(item),
                "dias": _compress_days(item.get("dias_execucao") or []),
            }
        )

    rows.sort(key=lambda row: (_turno_order(row.get("turno", "")), row.get("horario", ""), row.get("curso", "")))

    return _render(
        request,
        "programming_current.html",
        month_label=month_name_map.get(month_value, month_value),
        year_value=year_value,
        rows=rows,
    )


@app.get("/programming/compute-end-date")
def programming_compute_end_date(
    year: int,
    start: str,
    days: str = "",
    course_id: str = "",
    shift_id: str = "",
):
    days_execucao = _parse_days(days) if days else []
    end_date, error = _compute_schedule_end_date(
        year,
        start,
        days_execucao,
        course_id,
        shift_id,
    )
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return JSONResponse({"end_date": end_date})


@app.get("/programming/next-offer-id")
def programming_next_offer_id(year: str = ""):
    year_value = _parse_int(year) or datetime.now().year
    offer_id = _next_schedule_offer_id(list_schedules(), year_value)
    return JSONResponse({"offer_id": offer_id, "year": year_value})

@app.get("/schedules")
def schedules_redirect(request: Request):
    query = request.url.query
    url = "/programming"
    if query:
        url = f"{url}?{query}"
    return RedirectResponse(url, status_code=302)


@app.get("/programming/new")
@app.get("/schedules/new")
def schedules_new(request: Request):
    collaborators = list_instructors()
    analysts = [item for item in collaborators if item.get("role") == "Analista"]
    instructors = [item for item in collaborators if item.get("role") == "Instrutor"]
    assistants = [item for item in collaborators if item.get("role") == "Assistente"]
    current_year = datetime.now().year
    return _render(
        request,
        "schedule_form.html",
        schedule=None,
        schedule_id=_next_schedule_offer_id(list_schedules(), current_year),
        default_year=current_year,
        courses=list_courses(),
        instructors=instructors,
        analysts=analysts,
        assistants=assistants,
        rooms=list_rooms(),
        shifts=list_shifts(),
        months=MONTHS,
    )


@app.post("/programming/new")
@app.post("/schedules/new")
def schedules_create(
    request: Request,
    schedule_id: str = Form(""),
    ano: str = Form(...),
    mes: str = Form(...),
    turno_id: str = Form(...),
    pavimento: str = Form(...),
    curso_id: str = Form(...),
    sala_id: str = Form(...),
    qtd_alunos: str = Form(...),
    recurso_tipo: str = Form(""),
    programa_parceria: str = Form(""),
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
    ch_total: str = Form(...),
    turma: str = Form(...),
    hora_inicio: str = Form(...),
    hora_fim: str = Form(...),
    analista_id: str = Form(...),
    assistente_id: str = Form(""),
    instrutor_id: str = Form(""),
    instrutor_ids: List[str] = Form([]),
    dias_execucao: List[str] = Form([]),
    observacoes: str = Form(""),
):
    course = get_course(curso_id)
    room = get_room(sala_id)

    ch_value = course.get("carga_horaria_total") if course else ch_total
    floor_value = room.get("pavimento") if room else pavimento
    capacity_value = room.get("capacidade") if room else qtd_alunos

    selected_instructors = _normalize_instructor_ids(instrutor_ids, instrutor_id)

    payload = {
        "id": schedule_id,
        "ano": _parse_int(ano) or ano,
        "mes": _parse_int(mes) or mes,
        "curso_id": curso_id,
        "instrutor_id": selected_instructors[0] if selected_instructors else "",
        "instrutor_ids": selected_instructors,
        "analista_id": analista_id,
        "assistente_id": assistente_id,
        "sala_id": sala_id,
        "pavimento": floor_value,
        "qtd_alunos": _parse_int(qtd_alunos) or capacity_value,
        "turno_id": turno_id,
        "recurso_tipo": recurso_tipo,
        "programa_parceria": programa_parceria,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "ch_total": _parse_int(ch_total) or ch_value,
        "turma": turma,
        "hora_inicio": hora_inicio,
        "hora_fim": hora_fim,
        "dias_execucao": dias_execucao,
        "observacoes": observacoes,
    }
    year_for_id = _parse_int(str(payload.get("ano") or "")) or datetime.now().year
    payload["id"] = _next_schedule_offer_id(list_schedules(), year_for_id)

    try:
        if not selected_instructors:
            raise ValidationError("Informe ao menos um instrutor.")
        computed_end_date, error = _compute_schedule_end_date(
            payload.get("ano"),
            payload.get("data_inicio", ""),
            payload.get("dias_execucao", []),
            payload.get("curso_id", ""),
            payload.get("turno_id", ""),
        )

        if error:
            raise ValidationError(error)

        if payload.get("data_fim") != computed_end_date:
            raise ValidationError(
                "Data final nÃ£o confere com o calendÃ¡rio. Recalcule antes de salvar."
            )

        create_schedule(payload)
        _flash(request, "Oferta criada com sucesso.")
        return RedirectResponse("/programming/new", status_code=303)

    except ValidationError as exc:
        _flash(request, str(exc), "error")

        collaborators = list_instructors()
        analysts = [c for c in collaborators if c.get("role") == "Analista"]
        instructors = [c for c in collaborators if c.get("role") == "Instrutor"]
        assistants = [c for c in collaborators if c.get("role") == "Assistente"]

        return _render(
            request,
            "schedule_form.html",
            schedule=payload,
            schedule_id=payload.get("id"),
            default_year=year_for_id,
            courses=list_courses(),
            instructors=instructors,
            analysts=analysts,
            assistants=assistants,
            rooms=list_rooms(),
            shifts=list_shifts(),
            months=MONTHS,
        )




@app.get("/programming/{schedule_id}/edit")
@app.get("/schedules/{schedule_id}/edit")
def schedules_edit(request: Request, schedule_id: str):
    collaborators = list_instructors()
    analysts = [item for item in collaborators if item.get("role") == "Analista"]
    instructors = [item for item in collaborators if item.get("role") == "Instrutor"]
    assistants = [item for item in collaborators if item.get("role") == "Assistente"]
    return _render(
        request,
        "schedule_form.html",
        schedule=get_schedule(schedule_id),
        schedule_id=schedule_id,
        courses=list_courses(),
        instructors=instructors,
        analysts=analysts,
        assistants=assistants,
        rooms=list_rooms(),
        shifts=list_shifts(),
        months=MONTHS,
    )


@app.post("/programming/{schedule_id}/edit")
@app.post("/schedules/{schedule_id}/edit")
def schedules_update(
    request: Request,
    schedule_id: str,
    ano: str = Form(...),
    mes: str = Form(...),
    turno_id: str = Form(...),
    pavimento: str = Form(...),
    curso_id: str = Form(...),
    sala_id: str = Form(...),
    qtd_alunos: str = Form(...),
    recurso_tipo: str = Form(""),
    programa_parceria: str = Form(""),
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
    ch_total: str = Form(...),
    turma: str = Form(...),
    hora_inicio: str = Form(...),
    hora_fim: str = Form(...),
    analista_id: str = Form(...),
    assistente_id: str = Form(""),
    instrutor_id: str = Form(""),
    instrutor_ids: List[str] = Form([]),
    dias_execucao: List[str] = Form([]),
    observacoes: str = Form(""),
):
    course = get_course(curso_id)
    room = get_room(sala_id)
    ch_value = course.get("carga_horaria_total") if course else ch_total
    floor_value = room.get("pavimento") if room else pavimento
    capacity_value = room.get("capacidade") if room else qtd_alunos
    selected_instructors = _normalize_instructor_ids(instrutor_ids, instrutor_id)

    updates = {
        "ano": _parse_int(ano) or ano,
        "mes": _parse_int(mes) or mes,
        "curso_id": curso_id,
        "instrutor_id": selected_instructors[0] if selected_instructors else "",
        "instrutor_ids": selected_instructors,
        "analista_id": analista_id,
        "assistente_id": assistente_id,
        "sala_id": sala_id,
        "pavimento": floor_value,
        "qtd_alunos": _parse_int(qtd_alunos) or capacity_value,
        "turno_id": turno_id,
        "recurso_tipo": recurso_tipo,
        "programa_parceria": programa_parceria,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "ch_total": _parse_int(ch_total) or ch_value,
        "turma": turma,
        "hora_inicio": hora_inicio,
        "hora_fim": hora_fim,
        "dias_execucao": dias_execucao,
        "observacoes": observacoes,
    }
    try:
        if not selected_instructors:
            raise ValidationError("Informe ao menos um instrutor.")
        computed_end_date, _ = _compute_schedule_end_date(
            updates.get("ano"),
            updates.get("data_inicio", ""),
            updates.get("dias_execucao", []),
            updates.get("curso_id", ""),
            updates.get("turno_id", ""),
        )
        if computed_end_date and updates.get("data_fim") != computed_end_date:
            raise ValidationError(
                "Data final nÃ£o confere com o calendÃ¡rio. Recalcule a data final antes de salvar."
            )
        update_schedule(schedule_id, updates)
        _flash(request, "Oferta atualizada com sucesso.")
        return RedirectResponse("/programming", status_code=303)
    except ValidationError as exc:
        updates["id"] = schedule_id
        _flash(request, str(exc), "error")
        collaborators = list_instructors()
        analysts = [item for item in collaborators if item.get("role") == "Analista"]
        instructors = [item for item in collaborators if item.get("role") == "Instrutor"]
        assistants = [item for item in collaborators if item.get("role") == "Assistente"]
        return _render(
            request,
            "schedule_form.html",
            schedule=updates,
            schedule_id=schedule_id,
            courses=list_courses(),
            instructors=instructors,
            analysts=analysts,
            assistants=assistants,
            rooms=list_rooms(),
            shifts=list_shifts(),
            months=MONTHS,
        )


@app.post("/programming/{schedule_id}/delete")
@app.post("/schedules/{schedule_id}/delete")
def schedules_delete(request: Request, schedule_id: str):
    try:
        delete_schedule(schedule_id)
        _flash(request, "Oferta removida com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/programming", status_code=303)


@app.get("/chronograms")
def chronograms_list(
    request: Request,
    id: str = "",
    ano: str = "",
    mes: str = "",
    turno_id: str = "",
    instrutor_id: str = "",
    analista_id: str = "",
    assistente_id: str = "",
):
    current_year = str(date.today().year)
    default_year = "" if id else current_year
    filters = {
        "id": id,
        "ano": ano or default_year,
        "mes": mes,
        "turno_id": turno_id,
        "instrutor_id": instrutor_id,
        "analista_id": analista_id,
        "assistente_id": assistente_id,
    }
    items = list_schedules()
    if id:
        items = [item for item in items if str(item.get("id", "")).strip() == str(id).strip()]
    if filters["ano"]:
        items = [item for item in items if str(item.get("ano", "")) == str(filters["ano"])]
    if mes:
        items = [item for item in items if str(item.get("mes", "")) == str(mes)]
    if turno_id:
        items = [item for item in items if str(item.get("turno_id", "")) == str(turno_id)]
    if instrutor_id:
        filtered: List[Dict[str, Any]] = []
        for item in items:
            schedule_instructors = _normalize_instructor_ids(
                item.get("instrutor_ids") or [],
                str(item.get("instrutor_id") or ""),
            )
            if str(instrutor_id) in schedule_instructors:
                filtered.append(item)
        items = filtered
    if analista_id:
        items = [item for item in items if str(item.get("analista_id", "")) == str(analista_id)]
    if assistente_id:
        items = [item for item in items if str(item.get("assistente_id", "")) == str(assistente_id)]

    collaborators = list_instructors()
    instructors = [item for item in collaborators if item.get("role") == "Instrutor"]
    analysts = [item for item in collaborators if item.get("role") == "Analista"]
    assistants = [item for item in collaborators if item.get("role") == "Assistente"]
    courses = list_courses()
    shifts = list_shifts()
    rooms = list_rooms()
    instructor_map = {
        item["id"]: item.get("nome_sobrenome") or item.get("nome") or item.get("id")
        for item in collaborators
    }
    course_map = {item["id"]: item.get("nome", item["id"]) for item in courses}
    shift_map = {item["id"]: item.get("nome", item["id"]) for item in shifts}
    room_map = {item["id"]: item.get("nome", item["id"]) for item in rooms}
    month_map = {item["value"]: item["label"] for item in MONTHS}

    rows: List[Dict[str, Any]] = []
    for item in items:
        schedule_instructors = _normalize_instructor_ids(
            item.get("instrutor_ids") or [],
            str(item.get("instrutor_id") or ""),
        )
        instrutores = [instructor_map.get(i, i) for i in schedule_instructors]
        status_key = str(item.get("chronogram_status") or "").strip().lower()
        if status_key == "alterado_instrutor":
            status_label = "Alterado pelo instrutor"
        elif status_key == "alterado_interno":
            status_label = "Alterado internamente"
        else:
            status_label = "Automático"
        rows.append(
            {
                "id": item.get("id"),
                "ano": item.get("ano"),
                "mes_ord": _parse_int(str(item.get("mes") or "")) or 99,
                "mes_label": month_map.get(str(item.get("mes", "")), str(item.get("mes") or "—")),
                "curso": course_map.get(item.get("curso_id"), item.get("curso_id") or "—"),
                "turma": item.get("turma") or "—",
                "turno": shift_map.get(item.get("turno_id"), item.get("turno_id") or "—"),
                "ambiente": room_map.get(item.get("sala_id"), item.get("sala_id") or "—"),
                "instrutor": " / ".join(instrutores) if instrutores else "—",
                "analista": instructor_map.get(item.get("analista_id"), item.get("analista_id") or "—"),
                "assistente": instructor_map.get(item.get("assistente_id"), item.get("assistente_id") or "—"),
                "status": status_label,
                "updated_at": _format_timestamp_br(item.get("chronogram_updated_at")),
                "updated_by": item.get("chronogram_updated_by") or "—",
                "has_share": bool(item.get("chronogram_share_token")),
            }
        )

    rows.sort(
        key=lambda row: (
            int(_parse_int(str(row.get("ano") or "")) or 0),
            int(row.get("mes_ord") or 99),
            str(row.get("turno") or ""),
            str(row.get("curso") or ""),
        )
    )

    return _render(
        request,
        "chronograms.html",
        rows=rows,
        filters=filters,
        months=MONTHS,
        shifts=shifts,
        instructors=instructors,
        analysts=analysts,
        assistants=assistants,
    )
def _parse_date_br(value: str) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _weekday_set_from_execucao(dias_execucao: List[str]) -> set[int]:
    weekday_map = {"SEG": 0, "TER": 1, "QUA": 2, "QUI": 3, "SEX": 4, "SÃB": 5, "SAB": 5}
    return {weekday_map[d] for d in dias_execucao if d in weekday_map}


def _calc_hs_dia_from_shift(shift: Optional[Dict[str, Any]]) -> float:
    if not shift:
        return 0.0

    hs_dia = _parse_hours_value(shift.get("hs_dia"))
    if hs_dia:
        return float(hs_dia)

    # Se hs_dia nÃ£o estiver salvo, calcula pelo horÃ¡rio inicio/fim
    inicio = shift.get("horario_inicio") or ""
    fim = shift.get("horario_fim") or ""
    try:
        sh, sm = [int(x) for x in inicio.split(":")]
        eh, em = [int(x) for x in fim.split(":")]
    except Exception:
        return 0.0

    start = sh * 60 + sm
    end = eh * 60 + em
    if end <= start:
        return 0.0
    diff = end - start
    return diff / 60.0


def _get_course_units_for_pre(course_id: str) -> List[Dict[str, Any]]:
    # Prioridade: UCs cadastradas no prÃ³prio curso (curricular_units)
    course = get_course(course_id) if course_id else None
    if course and isinstance(course.get("curricular_units"), list) and course["curricular_units"]:
        units = course["curricular_units"]
        # normaliza
        cleaned = []
        for u in units:
            cleaned.append(
                {
                    "id": u.get("id") or "",
                    "nome": u.get("nome") or "",
                    "carga_horaria": u.get("carga_horaria") if u.get("carga_horaria") is not None else "",
                }
            )
        return cleaned

    # Fallback: UCs do mÃ³dulo src.curricular_units (relacionadas por curso_id)
    items = [u for u in list_units() if str(u.get("curso_id", "")) == str(course_id)]
    # ordena por id se existir, senÃ£o por nome
    items.sort(key=lambda x: (str(x.get("id", "")), str(x.get("nome", ""))))
    return items


def _is_pi_unit(unit: Dict[str, Any]) -> bool:
    nome = (unit.get("nome") or "").lower()
    uid = (unit.get("id") or "").lower()
    return ("projeto integrador" in nome) or (uid in ("pi", "ucpi"))


def _distribute_units_over_dates(
    exec_dates: List[date],
    units: List[Dict[str, Any]],
    hs_dia: float,
) -> Dict[str, Dict[str, str]]:
    """
    Retorna: map[YYYY-MM-DD][uc_key] = "UCx" (ou "PI") para renderizar em cada cÃ©lula.
    """
    grid: Dict[str, Dict[str, str]] = {}
    if not exec_dates or not units or hs_dia <= 0:
        return grid

    idx_date = 0
    for i, unit in enumerate(units, start=1):
        ch = _parse_hours_value(unit.get("carga_horaria"))
        ch_val = float(ch) if ch is not None else 0.0
        if ch_val <= 0:
            continue

        needed_days = int(math.ceil(ch_val / hs_dia))
        label = f"UC{i}"

        for _ in range(needed_days):
            if idx_date >= len(exec_dates):
                break
            d = exec_dates[idx_date]
            key = d.isoformat()
            grid.setdefault(key, {})
            grid[key][str(i)] = label
            idx_date += 1

    return grid


def _build_unit_day_sequence(units: List[Dict[str, Any]], slots_per_day: int) -> List[str]:
    """
    Sequencia de labels por dia (UCx/PI), mantendo blocos por UC e distribuindo PI entre as demais.
    """
    if not units or slots_per_day <= 0:
        return []

    non_pi_days: List[str] = []
    pi_days: List[str] = []

    for i, unit in enumerate(units, start=1):
        ch = _parse_hours_value(unit.get("carga_horaria"))
        ch_val = float(ch) if ch is not None else 0.0
        if ch_val <= 0:
            continue

        needed_days = int(math.ceil(ch_val / float(slots_per_day)))
        label = f"UC{i}"
        if _is_pi_unit(unit):
            pi_days.extend([label] * needed_days)
        else:
            non_pi_days.extend([label] * needed_days)

    if not pi_days:
        return non_pi_days
    if not non_pi_days:
        return pi_days

    mixed: List[str] = []
    step = max(1, int(round(len(non_pi_days) / float(len(pi_days)))))
    pi_idx = 0

    for i, label in enumerate(non_pi_days, start=1):
        mixed.append(label)
        if i % step == 0 and pi_idx < len(pi_days):
            mixed.append(pi_days[pi_idx])
            pi_idx += 1

    insert_pos = max(1, len(mixed) // 2)
    while pi_idx < len(pi_days):
        mixed.insert(insert_pos, pi_days[pi_idx])
        pi_idx += 1
        insert_pos = min(len(mixed), insert_pos + 2)

    return mixed


def _map_dates_to_uc_label(
    exec_dates: List[date],
    units: List[Dict[str, Any]],
    slots_per_day: int,
) -> Dict[str, str]:
    """
    map[YYYY-MM-DD] = UCx/PI (aplicado nas linhas de horario do dia).
    """
    mapping: Dict[str, str] = {}
    if not exec_dates or slots_per_day <= 0:
        return mapping

    day_sequence = _build_unit_day_sequence(units, slots_per_day)
    for idx, d in enumerate(exec_dates):
        mapping[d.isoformat()] = day_sequence[idx] if idx < len(day_sequence) else ""
    return mapping


def _build_day_instructor_sigla_map(
    exec_dates: List[date],
    day_uc_map: Dict[str, str],
    instructor_names: List[str],
) -> Dict[str, str]:
    """
    Alterna instrutores por UC: cada UC recebe um instrutor em round-robin.
    """
    siglas = [_sigla_nome(name) for name in instructor_names if (name or "").strip()]
    if not exec_dates or not siglas:
        return {}

    uc_to_sigla: Dict[str, str] = {}
    next_idx = 0
    result: Dict[str, str] = {}

    for d in exec_dates:
        key = d.isoformat()
        uc_label = (day_uc_map.get(key) or "").strip()
        if not uc_label:
            result[key] = ""
            continue

        if uc_label not in uc_to_sigla:
            uc_to_sigla[uc_label] = siglas[next_idx % len(siglas)]
            next_idx += 1

        result[key] = uc_to_sigla[uc_label]

    return result


def _build_uc_catalog(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    catalog: List[Dict[str, Any]] = []
    for idx, unit in enumerate(units, start=1):
        label = f"UC{idx}"
        catalog.append(
            {
                "label": label,
                "nome": unit.get("nome") or "",
                "carga_horaria": unit.get("carga_horaria") or "",
                "is_pi": _is_pi_unit(unit),
            }
        )
    return catalog


def _build_uc_color_map(uc_catalog: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    def _rgb_to_hex(r: float, g: float, b: float) -> str:
        return "#{:02X}{:02X}{:02X}".format(
            int(max(0, min(255, round(r * 255)))),
            int(max(0, min(255, round(g * 255)))),
            int(max(0, min(255, round(b * 255)))),
        )

    def _hls_hex(hue_deg: float, light: float, sat: float) -> str:
        r, g, b = colorsys.hls_to_rgb((hue_deg % 360) / 360.0, light, sat)
        return _rgb_to_hex(r, g, b)

    def _is_red_hue(hue_deg: float) -> bool:
        h = hue_deg % 360
        return h <= 20 or h >= 340

    def _next_non_red_hue(seed: int) -> float:
        hue = (137.508 * seed) % 360.0
        while _is_red_hue(hue):
            hue = (hue + 29.0) % 360.0
        return hue

    color_map: Dict[str, Dict[str, str]] = {}
    non_pi_idx = 0
    for item in uc_catalog:
        label = str(item.get("label") or "").strip().upper()
        if not label:
            continue
        is_pi = bool(item.get("is_pi"))
        if is_pi:
            color_map[label] = {"bg": "#FEE2E2", "border": "#FCA5A5", "text": "#991B1B"}
            continue

        cycle = non_pi_idx // 18
        hue = _next_non_red_hue(non_pi_idx + cycle * 3 + 1)
        sat = max(0.45, 0.70 - (cycle * 0.06))
        bg_light = min(0.92, 0.90 + (cycle * 0.01))
        border_light = min(0.80, 0.74 + (cycle * 0.015))
        text_light = max(0.24, 0.28 - (cycle * 0.01))
        color_map[label] = {
            "bg": _hls_hex(hue, bg_light, sat),
            "border": _hls_hex(hue, border_light, sat),
            "text": _hls_hex(hue, text_light, min(0.85, sat + 0.08)),
        }
        non_pi_idx += 1
    return color_map


def _normalize_day_uc_map(
    exec_dates: List[date],
    raw_map: Any,
    allowed_labels: set[str],
) -> Dict[str, str]:
    if not isinstance(raw_map, dict):
        return {}
    valid_keys = {d.isoformat() for d in exec_dates}
    normalized: Dict[str, str] = {}
    for key, value in raw_map.items():
        date_key = str(key or "").strip()
        label = str(value or "").strip().upper()
        if date_key not in valid_keys:
            continue
        if label and label not in allowed_labels:
            continue
        normalized[date_key] = label
    return normalized


def _slot_key(day: date, slot_idx: int) -> str:
    return f"{day.isoformat()}#{slot_idx}"


def _normalize_slot_uc_map(
    exec_dates: List[date],
    slots_per_day: int,
    raw_map: Any,
    allowed_labels: set[str],
) -> Dict[str, str]:
    if not isinstance(raw_map, dict) or slots_per_day <= 0:
        return {}
    valid_keys = {_slot_key(d, idx) for d in exec_dates for idx in range(slots_per_day)}
    normalized: Dict[str, str] = {}
    for key, value in raw_map.items():
        map_key = str(key or "").strip()
        label = str(value or "").strip().upper()
        if map_key not in valid_keys:
            continue
        if label and label not in allowed_labels:
            continue
        normalized[map_key] = label
    return normalized


def _build_slot_uc_map_from_day_map(
    exec_dates: List[date],
    slots_per_day: int,
    day_uc_map: Dict[str, str],
) -> Dict[str, str]:
    if slots_per_day <= 0:
        return {}
    slot_map: Dict[str, str] = {}
    for day in exec_dates:
        label = str(day_uc_map.get(day.isoformat(), "") or "").strip().upper()
        for idx in range(slots_per_day):
            slot_map[_slot_key(day, idx)] = label
    return slot_map


def _build_day_map_from_slot_map(
    exec_dates: List[date],
    slots_per_day: int,
    slot_uc_map: Dict[str, str],
) -> Dict[str, str]:
    day_map: Dict[str, str] = {}
    for day in exec_dates:
        picked = ""
        for idx in range(slots_per_day):
            value = str(slot_uc_map.get(_slot_key(day, idx), "") or "").strip().upper()
            if value:
                picked = value
                break
        day_map[day.isoformat()] = picked
    return day_map


def _slot_counts_match_expected(
    slot_uc_map: Dict[str, str],
    expected_counts: Dict[str, int],
) -> bool:
    actual: Dict[str, int] = {label: 0 for label in expected_counts}
    for raw in slot_uc_map.values():
        label = str(raw or "").strip().upper()
        if label in actual:
            actual[label] += 1
    for label, expected in expected_counts.items():
        if actual.get(label, 0) != expected:
            return False
    return True


def _build_auto_slot_uc_map(
    exec_dates: List[date],
    slots_per_day: int,
    uc_catalog: List[Dict[str, Any]],
) -> Dict[str, str]:
    if slots_per_day <= 0:
        return {}

    slot_map: Dict[str, str] = {}

    def _unit_chunks(label: str, needed: int) -> List[List[str]]:
        chunks: List[List[str]] = []
        remaining = max(0, needed)
        while remaining > 0:
            take = min(slots_per_day, remaining)
            chunks.append([label] * take)
            remaining -= take
        return chunks

    normal_chunks: List[List[str]] = []
    pi_chunks: List[List[str]] = []
    for item in uc_catalog:
        label = str(item.get("label") or "").strip().upper()
        if not label:
            continue
        ch = _parse_hours_value(item.get("carga_horaria"))
        needed = max(0, int(math.ceil(float(ch)))) if ch is not None else 0
        if needed <= 0:
            continue
        chunks = _unit_chunks(label, needed)
        if bool(item.get("is_pi")):
            pi_chunks.extend(chunks)
        else:
            normal_chunks.extend(chunks)

    def _insert_chunks_spread(base: List[List[str]], to_insert: List[List[str]]) -> List[List[str]]:
        if not to_insert:
            return list(base)
        if not base:
            return list(to_insert)
        out = list(base)
        base_len = len(base)
        inserted = 0
        for i, chunk in enumerate(to_insert):
            # Espalha do inicio ao fim sem concentrar no fim.
            gap = int(round((i + 1) * (base_len + 1) / float(len(to_insert) + 1)))
            gap = max(1, min(base_len, gap))
            pos = min(len(out), max(1, gap + inserted))
            out.insert(pos, chunk)
            inserted += 1
        return out

    pi_full_chunks = [chunk for chunk in pi_chunks if len(chunk) >= slots_per_day]
    pi_partial_chunks = [chunk for chunk in pi_chunks if len(chunk) < slots_per_day]

    mixed_chunks = _insert_chunks_spread(normal_chunks, pi_full_chunks)
    mixed_chunks = _insert_chunks_spread(mixed_chunks, pi_partial_chunks)

    packed_days: List[List[str]] = []
    current_day: List[str] = []
    for chunk in mixed_chunks:
        if not chunk:
            continue
        pending = list(chunk)

        # Preserva blocos de dia inteiro sempre que possivel.
        if len(pending) == slots_per_day and current_day:
            packed_days.append(current_day)
            current_day = []

        while pending:
            free_slots = slots_per_day - len(current_day)
            take = min(free_slots, len(pending))
            current_day.extend(pending[:take])
            pending = pending[take:]
            if len(current_day) == slots_per_day:
                packed_days.append(current_day)
                current_day = []
    if current_day:
        packed_days.append(current_day)

    flat_values: List[str] = []
    for values in packed_days:
        flat_values.extend(values)

    cursor = 0
    for day in exec_dates:
        for slot_idx in range(slots_per_day):
            slot_map[_slot_key(day, slot_idx)] = flat_values[cursor] if cursor < len(flat_values) else ""
            cursor += 1

    return slot_map


def _build_chronogram_data(
    schedule: Dict[str, Any],
    use_saved_distribution: bool = True,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not schedule:
        return None, "Programação não encontrada."

    course = get_course(schedule.get("curso_id"))
    schedule_instructor_ids = _normalize_instructor_ids(
        schedule.get("instrutor_ids") or [],
        str(schedule.get("instrutor_id") or ""),
    )
    instructor_items = [get_instructor(iid) for iid in schedule_instructor_ids]
    instructor_items = [item for item in instructor_items if item]
    instructor = instructor_items[0] if instructor_items else None
    analyst = get_instructor(schedule.get("analista_id"))
    shift = get_shift(schedule.get("turno_id"))
    room = get_room(schedule.get("sala_id"))

    start_date = _parse_date_br(schedule.get("data_inicio") or "")
    end_date = _parse_date_br(schedule.get("data_fim") or "")
    if not start_date or not end_date:
        return None, "Datas inválidas para gerar pré-cronograma."

    year_value = _parse_int(str(schedule.get("ano") or start_date.year)) or start_date.year
    calendario = get_calendar(year_value) or {}
    dias_letivos = calendario.get("dias_letivos_por_mes", [[] for _ in range(12)])
    letivos_sets = [set(_sanitize_days_list(m)) for m in dias_letivos]

    selected_weekdays = _weekday_set_from_execucao(schedule.get("dias_execucao") or [])
    if not selected_weekdays:
        return None, "Dias de execução não definidos."

    hs_dia = _calc_hs_dia_from_shift(shift)
    if hs_dia <= 0:
        hs_dia = 0.0
    hour_slots = _build_hour_slots(schedule.get("hora_inicio") or "", schedule.get("hora_fim") or "")
    slots_per_day = len(hour_slots)
    if slots_per_day <= 0 and hs_dia > 0:
        slots_per_day = max(1, int(round(hs_dia)))

    exec_dates: List[date] = []
    cur = start_date
    while cur <= end_date:
        if cur.year == year_value and cur.weekday() in selected_weekdays:
            month_idx = cur.month - 1
            if cur.day in letivos_sets[month_idx]:
                exec_dates.append(cur)
        cur += timedelta(days=1)

    units = _get_course_units_for_pre(schedule.get("curso_id") or "")
    uc_catalog = _build_uc_catalog(units)
    uc_color_map = _build_uc_color_map(uc_catalog)
    allowed_labels = {item["label"] for item in uc_catalog}
    expected_counts = _expected_uc_slot_counts(uc_catalog)

    auto_slot_uc_map = _build_auto_slot_uc_map(exec_dates, slots_per_day, uc_catalog)
    auto_day_uc_map = _build_day_map_from_slot_map(exec_dates, slots_per_day, auto_slot_uc_map)
    saved_day_uc_map = {}
    if use_saved_distribution:
        saved_day_uc_map = _normalize_day_uc_map(
            exec_dates,
            schedule.get("chronogram_day_uc_map") or {},
            allowed_labels,
        )
    day_uc_map = saved_day_uc_map if saved_day_uc_map else auto_day_uc_map
    if not day_uc_map:
        day_uc_map = {d.isoformat(): "" for d in exec_dates}
    if not auto_slot_uc_map:
        auto_slot_uc_map = _build_slot_uc_map_from_day_map(exec_dates, slots_per_day, day_uc_map)
    saved_slot_uc_map = {}
    if use_saved_distribution:
        saved_slot_uc_map = _normalize_slot_uc_map(
            exec_dates,
            slots_per_day,
            schedule.get("chronogram_slot_uc_map") or {},
            allowed_labels,
        )
    can_use_saved = bool(saved_slot_uc_map) and _slot_counts_match_expected(saved_slot_uc_map, expected_counts)
    slot_uc_map = saved_slot_uc_map if can_use_saved else auto_slot_uc_map
    if not slot_uc_map:
        slot_uc_map = auto_slot_uc_map
    if slots_per_day > 0:
        day_uc_map = _build_day_map_from_slot_map(exec_dates, slots_per_day, slot_uc_map)

    instructor_names = [
        (item.get("nome") or item.get("nome_sobrenome") or "")
        for item in instructor_items
    ]
    instructor_siglas: List[str] = []
    for name in instructor_names:
        sigla = _sigla_nome(name)
        if sigla and sigla not in instructor_siglas:
            instructor_siglas.append(sigla)

    auto_day_instrutor_map = _build_day_instructor_sigla_map(exec_dates, day_uc_map, instructor_names)
    saved_day_instrutor_map = {}
    if use_saved_distribution and instructor_siglas:
        saved_day_instrutor_map = _normalize_day_uc_map(
            exec_dates,
            schedule.get("chronogram_day_instrutor_map") or {},
            set(instructor_siglas),
        )
    day_instrutor_map = saved_day_instrutor_map if saved_day_instrutor_map else auto_day_instrutor_map
    if not day_instrutor_map:
        day_instrutor_map = {d.isoformat(): "" for d in exec_dates}

    months_data: List[Dict[str, Any]] = []
    month_cursor = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)

    while month_cursor <= end_month:
        y = month_cursor.year
        m = month_cursor.month
        label = next((x["label"] for x in MONTHS if int(x["value"]) == m), f"Mês {m}")
        month_exec = [d for d in exec_dates if d.year == y and d.month == m]
        letivos_count = len(month_exec)
        letivos_text = (
            f"{letivos_count} DIA LETIVO" if letivos_count == 1 else f"{letivos_count} DIAS LETIVOS"
        )
        months_data.append(
            {
                "year": y,
                "month": m,
                "label": label,
                "dates": month_exec,
                "letivos_count": letivos_count,
                "letivos_text": letivos_text,
            }
        )

        if m == 12:
            month_cursor = date(y + 1, 1, 1)
        else:
            month_cursor = date(y, m + 1, 1)

    header = {
        "curso": course.get("nome") if course else "—",
        "tipo": course.get("tipo_curso") if course else "—",
        "ch_total": course.get("carga_horaria_total") if course else schedule.get("ch_total") or "—",
        "turma": schedule.get("turma") or "—",
        "instrutor": (
            ", ".join(
                [(item.get("nome_sobrenome") or item.get("nome") or "—") for item in instructor_items]
            )
            if instructor_items
            else "—"
        ),
        "analista": (analyst.get("nome_sobrenome") or analyst.get("nome")) if analyst else "—",
        "ambiente": room.get("nome") if room else "—",
        "pavimento": schedule.get("pavimento") or (room.get("pavimento") if room else "—"),
        "periodo": f"{schedule.get('data_inicio') or '—'} a {schedule.get('data_fim') or '—'}",
        "horario": f"{schedule.get('hora_inicio') or '—'} às {schedule.get('hora_fim') or '—'}",
        "dias": ", ".join(schedule.get("dias_execucao") or []),
        "turno": shift.get("nome") if shift else "—",
        "hs_dia": f"{hs_dia:.2f}".replace(".00", "") if hs_dia else "—",
        "recurso": schedule.get("recurso_tipo") or "—",
        "programa_parceria": schedule.get("programa_parceria") or "—",
    }
    header["instrutor_sigla"] = _sigla_nome(
        (instructor.get("nome") or instructor.get("nome_sobrenome") or "") if instructor else ""
    ) or "—"

    return (
        {
            "header": header,
            "layout_data": months_data,
            "hour_slots": hour_slots,
            "units": units,
            "uc_catalog": uc_catalog,
            "uc_color_map": uc_color_map,
            "instructor_siglas": instructor_siglas,
            "pi_labels": [item["label"] for item in uc_catalog if item.get("is_pi")],
            "day_uc_map": day_uc_map,
            "slot_uc_map": slot_uc_map,
            "day_instrutor_map": day_instrutor_map,
            "exec_dates": exec_dates,
            "slots_per_day": slots_per_day,
            "day_sequence": [day_uc_map.get(d.isoformat(), "") for d in exec_dates],
            "slot_sequence": [
                slot_uc_map.get(_slot_key(d, idx), "")
                for d in exec_dates
                for idx in range(slots_per_day)
            ],
            "instructor_sequence": [day_instrutor_map.get(d.isoformat(), "") for d in exec_dates],
        },
        None,
    )


def _parse_day_sequence(raw: str) -> List[str]:
    text = (raw or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item or "").strip().upper() for item in parsed]
    except json.JSONDecodeError:
        pass
    return [item.strip().upper() for item in text.split(",")]


def _expected_uc_slot_counts(uc_catalog: List[Dict[str, Any]]) -> Dict[str, int]:
    expected: Dict[str, int] = {}
    for item in uc_catalog:
        label = str(item.get("label") or "").strip().upper()
        if not label:
            continue
        ch = _parse_hours_value(item.get("carga_horaria"))
        if ch is None:
            expected[label] = 0
            continue
        expected[label] = max(0, int(math.ceil(float(ch))))
    return expected


def _format_timestamp_br(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text)
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


def _find_schedule_by_share_token(token: str) -> Optional[Dict[str, Any]]:
    key = (token or "").strip()
    if not key:
        return None
    for item in list_schedules():
        if str(item.get("chronogram_share_token") or "") == key:
            return item
    return None


def _save_chronogram_distribution(
    schedule_id: str,
    slot_sequence_raw: str,
    instructor_sequence_raw: str,
    updated_by: str,
    mark_instrutor: bool,
) -> tuple[bool, str]:
    schedule = get_schedule(schedule_id)
    if not schedule:
        return False, "Programação não encontrada."

    chronogram_data, error = _build_chronogram_data(schedule, use_saved_distribution=False)
    if error or not chronogram_data:
        return False, error or "Não foi possível carregar os dados do cronograma."

    labels = _parse_day_sequence(slot_sequence_raw)
    exec_dates = chronogram_data["exec_dates"]
    slots_per_day = int(chronogram_data.get("slots_per_day") or 0)
    allowed = {item["label"] for item in chronogram_data["uc_catalog"]}
    expected_slots = max(0, len(exec_dates) * slots_per_day)
    normalized: List[str] = []
    for idx in range(expected_slots):
        label = labels[idx] if idx < len(labels) else ""
        if label not in allowed:
            label = ""
        normalized.append(label)
    slot_map: Dict[str, str] = {}
    cursor = 0
    for d in exec_dates:
        for slot_idx in range(slots_per_day):
            slot_map[_slot_key(d, slot_idx)] = normalized[cursor] if cursor < len(normalized) else ""
            cursor += 1
    chronogram_map = _build_day_map_from_slot_map(exec_dates, slots_per_day, slot_map)

    expected_counts = _expected_uc_slot_counts(chronogram_data.get("uc_catalog") or [])
    actual_counts: Dict[str, int] = {label: 0 for label in expected_counts}
    for label in normalized:
        if label in actual_counts:
            actual_counts[label] += 1

    mismatches: List[str] = []
    for label, expected in expected_counts.items():
        actual = actual_counts.get(label, 0)
        if actual != expected:
            mismatches.append(f"{label}: esperado {expected}h, distribuído {actual}h")
    if mismatches:
        return (
            False,
            "Distribuição inválida. Ajuste a carga horária das UCs: " + "; ".join(mismatches),
        )
    instructor_labels = _parse_day_sequence(instructor_sequence_raw)
    allowed_instructors = set(chronogram_data.get("instructor_siglas") or [])
    normalized_instructors: List[str] = []
    for idx, _ in enumerate(exec_dates):
        label = instructor_labels[idx] if idx < len(instructor_labels) else ""
        if label and label not in allowed_instructors:
            label = ""
        normalized_instructors.append(label)
    chronogram_instrutor_map = {
        d.isoformat(): normalized_instructors[idx]
        for idx, d in enumerate(exec_dates)
    }

    updates = {
        "chronogram_slot_uc_map": slot_map,
        "chronogram_day_uc_map": chronogram_map,
        "chronogram_day_instrutor_map": chronogram_instrutor_map,
        "chronogram_updated_by": updated_by,
        "chronogram_updated_at": datetime.now().isoformat(timespec="seconds"),
        "chronogram_status": "alterado_instrutor" if mark_instrutor else "alterado_interno",
    }
    try:
        update_schedule(schedule_id, updates, validate_schedule=False)
        return True, "Cronograma atualizado com sucesso."
    except ValidationError as exc:
        return False, str(exc)


def _apply_chronogram_operation(
    schedule_id: str,
    operation: str,
    updated_by: str,
    mark_instrutor: bool,
) -> tuple[bool, str]:
    schedule = get_schedule(schedule_id)
    if not schedule:
        return False, "Programação não encontrada."

    chrono_auto, error = _build_chronogram_data(schedule, use_saved_distribution=False)
    if error or not chrono_auto:
        return False, error or "Não foi possível carregar o cronograma."

    exec_dates = chrono_auto["exec_dates"]
    slots_per_day = int(chrono_auto.get("slots_per_day") or 0)
    updated_status = "alterado_instrutor" if mark_instrutor else "alterado_interno"

    if operation == "reset_ucs":
        slot_map: Dict[str, str] = {}
        for d in exec_dates:
            for slot_idx in range(slots_per_day):
                slot_map[_slot_key(d, slot_idx)] = ""
        day_uc_map = _build_day_map_from_slot_map(exec_dates, slots_per_day, slot_map)
        updates = {
            "chronogram_slot_uc_map": slot_map,
            "chronogram_day_uc_map": day_uc_map,
            "chronogram_updated_by": updated_by,
            "chronogram_updated_at": datetime.now().isoformat(timespec="seconds"),
            "chronogram_status": updated_status,
        }
        try:
            update_schedule(schedule_id, updates, validate_schedule=False)
            return True, "UCs zeradas com sucesso."
        except ValidationError as exc:
            return False, str(exc)

    if operation == "restore_default":
        updates = {
            "chronogram_slot_uc_map": chrono_auto.get("slot_uc_map") or {},
            "chronogram_day_uc_map": chrono_auto.get("day_uc_map") or {},
            "chronogram_day_instrutor_map": chrono_auto.get("day_instrutor_map") or {},
            "chronogram_updated_by": updated_by,
            "chronogram_updated_at": datetime.now().isoformat(timespec="seconds"),
            "chronogram_status": updated_status,
        }
        try:
            update_schedule(schedule_id, updates, validate_schedule=False)
            return True, "Distribuição padrão restaurada."
        except ValidationError as exc:
            return False, str(exc)

    return False, "Operação inválida."


@app.get("/chronograms/{schedule_id}/edit")
def chronogram_edit(request: Request, schedule_id: str):
    schedule = get_schedule(schedule_id)
    if not schedule:
        _flash(request, "Programação não encontrada.", "error")
        return RedirectResponse("/chronograms", status_code=302)

    chronogram_data, error = _build_chronogram_data(schedule, use_saved_distribution=True)
    if error or not chronogram_data:
        _flash(request, error or "Não foi possível montar o cronograma.", "error")
        return RedirectResponse("/chronograms", status_code=302)

    share_token = str(schedule.get("chronogram_share_token") or "").strip()
    share_url = (
        f"{str(request.base_url).rstrip('/')}/chronograms/shared/{share_token}"
        if share_token
        else ""
    )
    return _render(
        request,
        "chronogram_editor.html",
        schedule=schedule,
        header=chronogram_data["header"],
        months_data=chronogram_data["layout_data"],
        hour_slots=chronogram_data["hour_slots"],
        slots_per_day=chronogram_data["slots_per_day"],
        day_uc_map=chronogram_data["day_uc_map"],
        slot_uc_map=chronogram_data["slot_uc_map"],
        day_instrutor_map=chronogram_data["day_instrutor_map"],
        units=chronogram_data["units"],
        uc_catalog=chronogram_data["uc_catalog"],
        uc_color_map=chronogram_data["uc_color_map"],
        pi_labels=chronogram_data["pi_labels"],
        instructor_siglas=chronogram_data["instructor_siglas"],
        share_url=share_url,
        shared_mode=False,
    )


@app.post("/chronograms/{schedule_id}/edit")
def chronogram_edit_save(
    request: Request,
    schedule_id: str,
    slot_sequence: str = Form(""),
    instructor_sequence: str = Form(""),
    operation: str = Form("save"),
):
    if operation in {"reset_ucs", "restore_default"}:
        ok, message = _apply_chronogram_operation(
            schedule_id=schedule_id,
            operation=operation,
            updated_by="Equipe interna",
            mark_instrutor=False,
        )
        _flash(request, message, "success" if ok else "error")
        return RedirectResponse(f"/chronograms/{schedule_id}/edit", status_code=303)

    ok, message = _save_chronogram_distribution(
        schedule_id=schedule_id,
        slot_sequence_raw=slot_sequence,
        instructor_sequence_raw=instructor_sequence,
        updated_by="Equipe interna",
        mark_instrutor=False,
    )
    _flash(request, message, "success" if ok else "error")
    return RedirectResponse(f"/chronograms/{schedule_id}/edit", status_code=303)


@app.post("/chronograms/{schedule_id}/share")
def chronogram_share_link(request: Request, schedule_id: str):
    schedule = get_schedule(schedule_id)
    if not schedule:
        _flash(request, "Programação não encontrada.", "error")
        return RedirectResponse("/chronograms", status_code=302)

    token = secrets.token_urlsafe(24)
    try:
        update_schedule(
            schedule_id,
            {
                "chronogram_share_token": token,
                "chronogram_share_created_at": datetime.now().isoformat(timespec="seconds"),
            },
            validate_schedule=False,
        )
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return RedirectResponse(f"/chronograms/{schedule_id}/edit", status_code=303)
    share_url = f"{str(request.base_url).rstrip('/')}/chronograms/shared/{token}"
    _flash(request, f"Link de edição gerado: {share_url}", "success")
    return RedirectResponse(f"/chronograms/{schedule_id}/edit", status_code=303)


@app.get("/chronograms/shared/{token}")
def chronogram_shared_edit(request: Request, token: str):
    schedule = _find_schedule_by_share_token(token)
    if not schedule:
        _flash(request, "Link de cronograma inválido ou expirado.", "error")
        return RedirectResponse("/chronograms", status_code=302)

    chronogram_data, error = _build_chronogram_data(schedule, use_saved_distribution=True)
    if error or not chronogram_data:
        _flash(request, error or "Não foi possível montar o cronograma.", "error")
        return RedirectResponse("/chronograms", status_code=302)

    return _render(
        request,
        "chronogram_editor.html",
        schedule=schedule,
        header=chronogram_data["header"],
        months_data=chronogram_data["layout_data"],
        hour_slots=chronogram_data["hour_slots"],
        slots_per_day=chronogram_data["slots_per_day"],
        day_uc_map=chronogram_data["day_uc_map"],
        slot_uc_map=chronogram_data["slot_uc_map"],
        day_instrutor_map=chronogram_data["day_instrutor_map"],
        units=chronogram_data["units"],
        uc_catalog=chronogram_data["uc_catalog"],
        uc_color_map=chronogram_data["uc_color_map"],
        pi_labels=chronogram_data["pi_labels"],
        instructor_siglas=chronogram_data["instructor_siglas"],
        share_url="",
        shared_mode=True,
        shared_token=token,
    )


@app.post("/chronograms/shared/{token}/save")
def chronogram_shared_save(
    request: Request,
    token: str,
    slot_sequence: str = Form(""),
    instructor_sequence: str = Form(""),
    operation: str = Form("save"),
):
    schedule = _find_schedule_by_share_token(token)
    if not schedule:
        _flash(request, "Link de cronograma inválido ou expirado.", "error")
        return RedirectResponse("/chronograms", status_code=302)

    if operation in {"reset_ucs", "restore_default"}:
        ok, message = _apply_chronogram_operation(
            schedule_id=str(schedule.get("id")),
            operation=operation,
            updated_by="Instrutor (link)",
            mark_instrutor=True,
        )
        _flash(request, message, "success" if ok else "error")
        return RedirectResponse(f"/chronograms/shared/{token}", status_code=303)

    ok, message = _save_chronogram_distribution(
        schedule_id=str(schedule.get("id")),
        slot_sequence_raw=slot_sequence,
        instructor_sequence_raw=instructor_sequence,
        updated_by="Instrutor (link)",
        mark_instrutor=True,
    )
    _flash(request, message, "success" if ok else "error")
    return RedirectResponse(f"/chronograms/shared/{token}", status_code=303)


@app.get("/programming/{schedule_id}/pre-chronogram")
def pre_chronogram(
    request: Request,
    schedule_id: str,
    layout: str = "portrait",   # portrait | landscape
    compact: str = "1",         # 1 = compactado, 0 = normal
):
    schedule = get_schedule(schedule_id)
    if not schedule:
        _flash(request, "Programação não encontrada.", "error")
        return RedirectResponse("/programming", status_code=302)
    chronogram_data, error = _build_chronogram_data(schedule, use_saved_distribution=True)
    if error or not chronogram_data:
        _flash(request, error or "Não foi possível montar o pré-cronograma.", "error")
        return RedirectResponse("/programming", status_code=302)

    return _render(
        request,
        "pre_chronogram.html",
        schedule=schedule,
        header=chronogram_data["header"],
        sheet_title="PRE-CRONOGRAMA",
        layout="landscape" if layout == "landscape" else "portrait",
        compact=(compact != "0"),
        months_data=chronogram_data["layout_data"],
        hour_slots=chronogram_data["hour_slots"],
        units=chronogram_data["units"],
        day_uc_map=chronogram_data["day_uc_map"],
        slot_uc_map=chronogram_data["slot_uc_map"],
        day_instrutor_map=chronogram_data["day_instrutor_map"],
        uc_color_map=chronogram_data["uc_color_map"],
        pi_labels=chronogram_data["pi_labels"],
    )


@app.get("/programming/{schedule_id}/empty-chronogram")
def empty_chronogram(
    request: Request,
    schedule_id: str,
    layout: str = "portrait",
    compact: str = "1",
):
    schedule = get_schedule(schedule_id)
    if not schedule:
        _flash(request, "Programação não encontrada.", "error")
        return RedirectResponse("/programming", status_code=302)

    chronogram_data, error = _build_chronogram_data(schedule, use_saved_distribution=True)
    if error or not chronogram_data:
        _flash(request, error or "Não foi possível montar o cronograma vazio.", "error")
        return RedirectResponse("/programming", status_code=302)

    exec_dates = chronogram_data.get("exec_dates") or []
    slots_per_day = int(chronogram_data.get("slots_per_day") or 0)
    empty_slot_map: Dict[str, str] = {}
    for d in exec_dates:
        for idx in range(slots_per_day):
            empty_slot_map[_slot_key(d, idx)] = ""

    empty_day_map = {d.isoformat(): "" for d in exec_dates}

    return _render(
        request,
        "pre_chronogram.html",
        schedule=schedule,
        header=chronogram_data["header"],
        sheet_title="CRONOGRAMA VAZIO",
        layout="landscape" if layout == "landscape" else "portrait",
        compact=(compact != "0"),
        months_data=chronogram_data["layout_data"],
        hour_slots=chronogram_data["hour_slots"],
        units=chronogram_data["units"],
        day_uc_map=empty_day_map,
        slot_uc_map=empty_slot_map,
        day_instrutor_map=chronogram_data["day_instrutor_map"],
        uc_color_map=chronogram_data["uc_color_map"],
        pi_labels=chronogram_data["pi_labels"],
    )
