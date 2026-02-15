from __future__ import annotations

import calendar as calendar_module
import json
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
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


@app.get("/")
def dashboard(request: Request):

    return _render(
        request,
        "dashboard.html",
        counts={
            "courses": len(list_courses()),
            "units": len(list_units()),
            "instructors": len(list_instructors()),
            "rooms": len(list_rooms()),
            "shifts": len(list_shifts()),
            "calendars": len(list_calendars()),
            "schedules": len(list_schedules()),
        },
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
    return _render(
        request,
        "schedule_form.html",
        schedule=None,
        schedule_id=_next_id(list_schedules()),
        courses=list_courses(),
        instructors=instructors,
        analysts=analysts,
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
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
    ch_total: str = Form(...),
    turma: str = Form(...),
    hora_inicio: str = Form(...),
    hora_fim: str = Form(...),
    analista_id: str = Form(...),
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
        "sala_id": sala_id,
        "pavimento": floor_value,
        "qtd_alunos": _parse_int(qtd_alunos) or capacity_value,
        "turno_id": turno_id,
        "recurso_tipo": recurso_tipo,
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

        return _render(
            request,
            "schedule_form.html",
            schedule=payload,
            schedule_id=payload.get("id"),
            courses=list_courses(),
            instructors=instructors,
            analysts=analysts,
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
    return _render(
        request,
        "schedule_form.html",
        schedule=get_schedule(schedule_id),
        schedule_id=schedule_id,
        courses=list_courses(),
        instructors=instructors,
        analysts=analysts,
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
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
    ch_total: str = Form(...),
    turma: str = Form(...),
    hora_inicio: str = Form(...),
    hora_fim: str = Form(...),
    analista_id: str = Form(...),
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
        "sala_id": sala_id,
        "pavimento": floor_value,
        "qtd_alunos": _parse_int(qtd_alunos) or capacity_value,
        "turno_id": turno_id,
        "recurso_tipo": recurso_tipo,
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
        return _render(
            request,
            "schedule_form.html",
            schedule=updates,
            schedule_id=schedule_id,
            courses=list_courses(),
            instructors=instructors,
            analysts=analysts,
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
    ano: str = "",
    mes: str = "",
    turno_id: str = "",
    instrutor_id: str = "",
    analista_id: str = "",
    assistente_id: str = "",
):
    current_year = str(date.today().year)
    filters = {
        "ano": ano or current_year,
        "mes": mes,
        "turno_id": turno_id,
        "instrutor_id": instrutor_id,
        "analista_id": analista_id,
        "assistente_id": assistente_id,
    }
    collaborators = list_instructors()
    instructors = [item for item in collaborators if item.get("role") == "Instrutor"]
    analysts = [item for item in collaborators if item.get("role") == "Analista"]
    assistants = [item for item in collaborators if item.get("role") == "Assistente"]
    return _render(
        request,
        "chronograms.html",
        filters=filters,
        months=MONTHS,
        shifts=list_shifts(),
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
        label = "PI" if _is_pi_unit(unit) else f"UC{i}"

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
        label = "PI" if _is_pi_unit(unit) else f"UC{i}"

        if label == "PI":
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


@app.get("/programming/{schedule_id}/pre-chronogram")
def pre_chronogram(
    request: Request,
    schedule_id: str,
    layout: str = "portrait",   # portrait | landscape
    compact: str = "1",         # 1 = compactado, 0 = normal
):
    schedule = get_schedule(schedule_id)
    if not schedule:
        _flash(request, "ProgramaÃ§Ã£o nÃ£o encontrada.", "error")
        return RedirectResponse("/programming", status_code=302)

    # entidades
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

    # datas
    start_date = _parse_date_br(schedule.get("data_inicio") or "")
    end_date = _parse_date_br(schedule.get("data_fim") or "")
    if not start_date or not end_date:
        _flash(request, "Datas invÃ¡lidas para gerar prÃ©-cronograma.", "error")
        return RedirectResponse("/programming", status_code=302)

    year_value = _parse_int(str(schedule.get("ano") or start_date.year)) or start_date.year
    calendario = get_calendar(year_value) or {}
    dias_letivos = calendario.get("dias_letivos_por_mes", [[] for _ in range(12)])
    letivos_sets = [set(_sanitize_days_list(m)) for m in dias_letivos]

    selected_weekdays = _weekday_set_from_execucao(schedule.get("dias_execucao") or [])
    if not selected_weekdays:
        _flash(request, "Dias de execuÃ§Ã£o nÃ£o definidos.", "error")
        return RedirectResponse("/programming", status_code=302)

    # hs_dia
    hs_dia = _calc_hs_dia_from_shift(shift)
    if hs_dia <= 0:
        # ainda dÃ¡ pra mostrar, mas sem distribuiÃ§Ã£o por carga horÃ¡ria
        hs_dia = 0.0
    hour_slots = _build_hour_slots(schedule.get("hora_inicio") or "", schedule.get("hora_fim") or "")
    slots_per_day = len(hour_slots)
    if slots_per_day <= 0 and hs_dia > 0:
        slots_per_day = max(1, int(round(hs_dia)))

    # monta lista de datas executÃ¡veis (seg-sab, conforme dias_execucao + letivos)
    exec_dates: List[date] = []
    cur = start_date
    while cur <= end_date:
        if cur.year == year_value and cur.weekday() in selected_weekdays:
            month_idx = cur.month - 1
            if cur.day in letivos_sets[month_idx]:
                exec_dates.append(cur)
        cur += timedelta(days=1)

    # UCs
    units = _get_course_units_for_pre(schedule.get("curso_id") or "")

    # distribui UCs por dia (mantem o mesmo label em todos os horarios do dia, quando possivel)
    day_uc_map = _map_dates_to_uc_label(exec_dates, units, slots_per_day) if slots_per_day > 0 else {}
    instructor_names = [
        (item.get("nome") or item.get("nome_sobrenome") or "")
        for item in instructor_items
    ]
    day_instrutor_map = _build_day_instructor_sigla_map(exec_dates, day_uc_map, instructor_names)

    # agrupa por mÃªs (somente meses do intervalo)
    months_data: List[Dict[str, Any]] = []
    month_cursor = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)

    while month_cursor <= end_month:
        y = month_cursor.year
        m = month_cursor.month
        label = next((x["label"] for x in MONTHS if int(x["value"]) == m), f"M\u00eas {m}")

        # colunas = dias Ãºteis (SEG-SÃB) que estÃ£o na lista exec_dates e sÃ£o deste mÃªs
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

        # prÃ³ximo mÃªs
        if m == 12:
            month_cursor = date(y + 1, 1, 1)
        else:
            month_cursor = date(y, m + 1, 1)

    header = {
        "curso": course.get("nome") if course else "â€”",
        "tipo": course.get("tipo_curso") if course else "â€”",
        "ch_total": course.get("carga_horaria_total") if course else schedule.get("ch_total") or "â€”",
        "turma": schedule.get("turma") or "â€”",
        "instrutor": (
            ", ".join(
                [(item.get("nome_sobrenome") or item.get("nome") or "—") for item in instructor_items]
            )
            if instructor_items
            else "â€”"
        ),
        "analista": (analyst.get("nome_sobrenome") or analyst.get("nome")) if analyst else "â€”",
        "ambiente": room.get("nome") if room else "â€”",
        "pavimento": schedule.get("pavimento") or (room.get("pavimento") if room else "â€”"),
        "periodo": f"{schedule.get('data_inicio') or 'â€”'} a {schedule.get('data_fim') or 'â€”'}",
        "horario": f"{schedule.get('hora_inicio') or 'â€”'} Ã s {schedule.get('hora_fim') or 'â€”'}",
        "dias": ", ".join(schedule.get("dias_execucao") or []),
        "turno": shift.get("nome") if shift else "â€”",
        "hs_dia": f"{hs_dia:.2f}".replace(".00", "") if hs_dia else "â€”",
    }
    header["instrutor_sigla"] = _sigla_nome(
        (instructor.get("nome") or instructor.get("nome_sobrenome") or "") if instructor else ""
    ) or "â€”"

    return _render(
        request,
        "pre_chronogram.html",
        schedule=schedule,
        header=header,
        layout="landscape" if layout == "landscape" else "portrait",
        compact=(compact != "0"),
        months_data=months_data,
        hour_slots=hour_slots,
        units=units,
        day_uc_map=day_uc_map,
        day_instrutor_map=day_instrutor_map,
    )
