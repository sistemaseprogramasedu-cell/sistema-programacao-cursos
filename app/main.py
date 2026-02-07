from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
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
from src.storage import ValidationError

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


def _parse_days_numbers(value: str) -> List[int]:
    days = []
    for item in value.split(","):
        cleaned = item.strip()
        if not cleaned:
            continue
        if cleaned.isdigit():
            days.append(int(cleaned))
    return days


def _parse_json(text: str, default: Any) -> Any:
    cleaned = text.strip()
    if not cleaned:
        return default
    return json.loads(cleaned)


def _collaborators_by_type(tipo: str) -> List[Dict[str, Any]]:
    return [item for item in list_instructors() if item.get("tipo") == tipo]


def _filter_by_date_range(
    items: List[Dict[str, Any]], start_date: str, end_date: str
) -> List[Dict[str, Any]]:
    filtered = items
    if start_date:
        filtered = [item for item in filtered if item.get("data_fim", "") >= start_date]
    if end_date:
        filtered = [item for item in filtered if item.get("data_inicio", "") <= end_date]
    return filtered


def _month_range(reference: datetime, months: int) -> tuple[str, str]:
    start_month = reference.month
    start_year = reference.year
    end_month = start_month + months - 1
    end_year = start_year + (end_month - 1) // 12
    end_month = ((end_month - 1) % 12) + 1
    start = datetime(start_year, start_month, 1)
    if end_month == 12:
        end = datetime(end_year + 1, 1, 1)
    else:
        end = datetime(end_year, end_month + 1, 1)
    end = end - timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


MONTHS = [
    {"key": "jan", "label": "Jan"},
    {"key": "fev", "label": "Fev"},
    {"key": "mar", "label": "Mar"},
    {"key": "abr", "label": "Abr"},
    {"key": "mai", "label": "Mai"},
    {"key": "jun", "label": "Jun"},
    {"key": "jul", "label": "Jul"},
    {"key": "ago", "label": "Ago"},
    {"key": "set", "label": "Set"},
    {"key": "out", "label": "Out"},
    {"key": "nov", "label": "Nov"},
    {"key": "dez", "label": "Dez"},
]


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
    return _render(request, "course_form.html", course=None)


@app.post("/courses/new")
def courses_create(
    request: Request,
    nome: str = Form(...),
    segmento: str = Form(...),
    carga_horaria_total: str = Form(...),
    ativo: str = Form("true"),
):
    payload = {
        "nome": nome,
        "segmento": segmento,
        "carga_horaria_total": _parse_int(carga_horaria_total) or carga_horaria_total,
        "ativo": ativo == "true",
    }
    try:
        create_course(payload)
        _flash(request, "Curso cadastrado com sucesso.")
        return RedirectResponse("/courses", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(request, "course_form.html", course=payload)


@app.get("/courses/{course_id}/edit")
def courses_edit(request: Request, course_id: str):
    units = [unit for unit in list_units() if unit.get("curso_id") == int(course_id)]
    return _render(request, "course_form.html", course=get_course(int(course_id)), units=units)


@app.post("/courses/{course_id}/edit")
def courses_update(
    request: Request,
    course_id: str,
    nome: str = Form(...),
    segmento: str = Form(...),
    carga_horaria_total: str = Form(...),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
        "segmento": segmento,
        "carga_horaria_total": _parse_int(carga_horaria_total) or carga_horaria_total,
        "ativo": ativo == "true",
    }
    try:
        update_course(int(course_id), updates)
        _flash(request, "Curso atualizado com sucesso.")
        return RedirectResponse("/courses", status_code=303)
    except ValidationError as exc:
        updates["id"] = int(course_id)
        _flash(request, str(exc), "error")
        units = [unit for unit in list_units() if unit.get("curso_id") == int(course_id)]
        return _render(request, "course_form.html", course=updates, units=units)


@app.post("/courses/{course_id}/delete")
def courses_delete(request: Request, course_id: str):
    try:
        delete_course(int(course_id))
        _flash(request, "Curso removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/courses", status_code=303)


@app.post("/courses/{course_id}/units")
def courses_add_unit(
    request: Request,
    course_id: str,
    nome: str = Form(...),
    carga_horaria: str = Form(""),
    ativo: str = Form("true"),
):
    payload: Dict[str, Any] = {
        "curso_id": int(course_id),
        "nome": nome,
        "ativo": ativo == "true",
    }
    if carga_horaria.strip():
        payload["carga_horaria"] = _parse_float(carga_horaria) or carga_horaria
    try:
        create_unit(payload)
        _flash(request, "UC adicionada ao curso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse(f"/courses/{course_id}/edit", status_code=303)


@app.post("/courses/{course_id}/units/batch")
def courses_add_units_batch(
    request: Request,
    course_id: str,
    linhas: str = Form(...),
):
    try:
        created = create_units_batch_from_lines(int(course_id), linhas)
        _flash(request, f"{len(created)} UCs cadastradas.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse(f"/courses/{course_id}/edit", status_code=303)


@app.get("/rooms")
def rooms_list(request: Request):
    return _render(request, "rooms.html", rooms=list_rooms())


@app.get("/rooms/new")
def rooms_new(request: Request):
    return _render(request, "room_form.html", room=None)


@app.post("/rooms/new")
def rooms_create(
    request: Request,
    nome: str = Form(...),
    capacidade: str = Form(...),
    recursos: str = Form(""),
    ativo: str = Form("true"),
):
    payload = {
        "nome": nome,
        "capacidade": _parse_int(capacidade) or capacidade,
        "recursos": [item.strip() for item in recursos.split(",") if item.strip()],
        "ativo": ativo == "true",
    }
    try:
        create_room(payload)
        _flash(request, "Sala cadastrada com sucesso.")
        return RedirectResponse("/rooms", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(request, "room_form.html", room=payload)


@app.get("/rooms/{room_id}/edit")
def rooms_edit(request: Request, room_id: str):
    return _render(request, "room_form.html", room=get_room(int(room_id)))


@app.post("/rooms/{room_id}/edit")
def rooms_update(
    request: Request,
    room_id: str,
    nome: str = Form(...),
    capacidade: str = Form(...),
    recursos: str = Form(""),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
        "capacidade": _parse_int(capacidade) or capacidade,
        "recursos": [item.strip() for item in recursos.split(",") if item.strip()],
        "ativo": ativo == "true",
    }
    try:
        update_room(int(room_id), updates)
        _flash(request, "Sala atualizada com sucesso.")
        return RedirectResponse("/rooms", status_code=303)
    except ValidationError as exc:
        updates["id"] = int(room_id)
        _flash(request, str(exc), "error")
        return _render(request, "room_form.html", room=updates)


@app.post("/rooms/{room_id}/delete")
def rooms_delete(request: Request, room_id: str):
    try:
        delete_room(int(room_id))
        _flash(request, "Sala removida com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/rooms", status_code=303)


@app.get("/instructors")
def instructors_redirect():
    return RedirectResponse("/collaborators", status_code=303)


@app.get("/collaborators")
def instructors_list(request: Request, tipo: str = ""):
    collaborators = list_instructors()
    if tipo:
        collaborators = [item for item in collaborators if item.get("tipo") == tipo]
    return _render(
        request,
        "instructors.html",
        instructors=collaborators,
        filtro_tipo=tipo,
    )


@app.get("/collaborators/new")
def instructors_new(request: Request):
    return _render(request, "instructor_form.html", instructor=None)


@app.post("/collaborators/new")
def instructors_create(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    tipo: str = Form(...),
    telefone: str = Form(""),
    especialidades: str = Form(""),
    max_horas_semana: str = Form(""),
    ativo: str = Form("true"),
):
    payload = {
        "nome": nome,
        "email": email,
        "tipo": tipo,
        "telefone": telefone,
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
        return _render(request, "instructor_form.html", instructor=payload)


@app.get("/collaborators/{instructor_id}/edit")
def instructors_edit(request: Request, instructor_id: str):
    return _render(request, "instructor_form.html", instructor=get_instructor(int(instructor_id)))


@app.post("/collaborators/{instructor_id}/edit")
def instructors_update(
    request: Request,
    instructor_id: str,
    nome: str = Form(...),
    email: str = Form(...),
    tipo: str = Form(...),
    telefone: str = Form(""),
    especialidades: str = Form(""),
    max_horas_semana: str = Form(""),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
        "email": email,
        "tipo": tipo,
        "telefone": telefone,
        "especialidades": [item.strip() for item in especialidades.split(",") if item.strip()],
        "max_horas_semana": _parse_float(max_horas_semana),
        "ativo": ativo == "true",
    }
    try:
        update_instructor(int(instructor_id), updates)
        _flash(request, "Colaborador atualizado com sucesso.")
        return RedirectResponse("/collaborators", status_code=303)
    except ValidationError as exc:
        updates["id"] = int(instructor_id)
        _flash(request, str(exc), "error")
        return _render(request, "instructor_form.html", instructor=updates)


@app.post("/collaborators/{instructor_id}/delete")
def instructors_delete(request: Request, instructor_id: str):
    try:
        delete_instructor(int(instructor_id))
        _flash(request, "Colaborador removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/instructors", status_code=303)


@app.get("/shifts")
def shifts_list(request: Request):
    return _render(request, "shifts.html", shifts=list_shifts())


@app.get("/shifts/new")
def shifts_new(request: Request):
    return _render(request, "shift_form.html", shift=None)


@app.post("/shifts/new")
def shifts_create(
    request: Request,
    nome: str = Form(...),
    horario_inicio: str = Form(...),
    horario_fim: str = Form(...),
    dias_semana: str = Form(...),
    ativo: str = Form("true"),
):
    payload = {
        "nome": nome,
        "horario_inicio": horario_inicio,
        "horario_fim": horario_fim,
        "dias_semana": _parse_days(dias_semana),
        "ativo": ativo == "true",
    }
    try:
        create_shift(payload)
        _flash(request, "Turno cadastrado com sucesso.")
        return RedirectResponse("/shifts", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(request, "shift_form.html", shift=payload)


@app.get("/shifts/{shift_id}/edit")
def shifts_edit(request: Request, shift_id: str):
    return _render(request, "shift_form.html", shift=get_shift(int(shift_id)))


@app.post("/shifts/{shift_id}/edit")
def shifts_update(
    request: Request,
    shift_id: str,
    nome: str = Form(...),
    horario_inicio: str = Form(...),
    horario_fim: str = Form(...),
    dias_semana: str = Form(...),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
        "horario_inicio": horario_inicio,
        "horario_fim": horario_fim,
        "dias_semana": _parse_days(dias_semana),
        "ativo": ativo == "true",
    }
    try:
        update_shift(int(shift_id), updates)
        _flash(request, "Turno atualizado com sucesso.")
        return RedirectResponse("/shifts", status_code=303)
    except ValidationError as exc:
        updates["id"] = int(shift_id)
        _flash(request, str(exc), "error")
        return _render(request, "shift_form.html", shift=updates)


@app.post("/shifts/{shift_id}/delete")
def shifts_delete(request: Request, shift_id: str):
    try:
        delete_shift(int(shift_id))
        _flash(request, "Turno removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/shifts", status_code=303)


@app.get("/calendars")
def calendars_list(request: Request):
    return _render(request, "calendars.html", calendars=list_calendars())


@app.get("/calendars/new")
def calendars_new(request: Request):
    months = [{**month, "value": ""} for month in MONTHS]
    return _render(request, "calendar_form.html", calendar=None, months=months, feriados="")


@app.post("/calendars/new")
def calendars_create(
    request: Request,
    ano: str = Form(...),
    feriados: str = Form(""),
    dias_jan: str = Form(""),
    dias_fev: str = Form(""),
    dias_mar: str = Form(""),
    dias_abr: str = Form(""),
    dias_mai: str = Form(""),
    dias_jun: str = Form(""),
    dias_jul: str = Form(""),
    dias_ago: str = Form(""),
    dias_set: str = Form(""),
    dias_out: str = Form(""),
    dias_nov: str = Form(""),
    dias_dez: str = Form(""),
    ativo: str = Form("true"),
):
    payload = {
        "ano": _parse_int(ano) or ano,
        "dias_letivos": {
            "jan": _parse_days_numbers(dias_jan),
            "fev": _parse_days_numbers(dias_fev),
            "mar": _parse_days_numbers(dias_mar),
            "abr": _parse_days_numbers(dias_abr),
            "mai": _parse_days_numbers(dias_mai),
            "jun": _parse_days_numbers(dias_jun),
            "jul": _parse_days_numbers(dias_jul),
            "ago": _parse_days_numbers(dias_ago),
            "set": _parse_days_numbers(dias_set),
            "out": _parse_days_numbers(dias_out),
            "nov": _parse_days_numbers(dias_nov),
            "dez": _parse_days_numbers(dias_dez),
        },
        "feriados": [item.strip() for item in feriados.split(",") if item.strip()],
        "ativo": ativo == "true",
    }
    try:
        create_calendar(payload)
        _flash(request, "Calendário cadastrado com sucesso.")
        return RedirectResponse("/calendars", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        months = [
            {**month, "value": ", ".join(str(day) for day in payload["dias_letivos"].get(month["key"], []))}
            for month in MONTHS
        ]
        return _render(request, "calendar_form.html", calendar=payload, months=months, feriados=feriados)


@app.get("/calendars/{calendar_id}/edit")
def calendars_edit(request: Request, calendar_id: int):
    calendar = get_calendar(calendar_id)
    months = []
    for month in MONTHS:
        days = calendar.get("dias_letivos", {}).get(month["key"], []) if calendar else []
        months.append({**month, "value": ", ".join(str(day) for day in days)})
    feriados = ", ".join(calendar.get("feriados", [])) if calendar else ""
    return _render(request, "calendar_form.html", calendar=calendar, months=months, feriados=feriados)


@app.post("/calendars/{calendar_id}/edit")
def calendars_update(
    request: Request,
    calendar_id: int,
    ano: str = Form(...),
    feriados: str = Form(""),
    dias_jan: str = Form(""),
    dias_fev: str = Form(""),
    dias_mar: str = Form(""),
    dias_abr: str = Form(""),
    dias_mai: str = Form(""),
    dias_jun: str = Form(""),
    dias_jul: str = Form(""),
    dias_ago: str = Form(""),
    dias_set: str = Form(""),
    dias_out: str = Form(""),
    dias_nov: str = Form(""),
    dias_dez: str = Form(""),
    ativo: str = Form("true"),
):
    updates = {
        "ano": _parse_int(ano) or ano,
        "dias_letivos": {
            "jan": _parse_days_numbers(dias_jan),
            "fev": _parse_days_numbers(dias_fev),
            "mar": _parse_days_numbers(dias_mar),
            "abr": _parse_days_numbers(dias_abr),
            "mai": _parse_days_numbers(dias_mai),
            "jun": _parse_days_numbers(dias_jun),
            "jul": _parse_days_numbers(dias_jul),
            "ago": _parse_days_numbers(dias_ago),
            "set": _parse_days_numbers(dias_set),
            "out": _parse_days_numbers(dias_out),
            "nov": _parse_days_numbers(dias_nov),
            "dez": _parse_days_numbers(dias_dez),
        },
        "feriados": [item.strip() for item in feriados.split(",") if item.strip()],
        "ativo": ativo == "true",
    }
    try:
        update_calendar(calendar_id, updates)
        _flash(request, "Calendário atualizado com sucesso.")
        return RedirectResponse("/calendars", status_code=303)
    except ValidationError as exc:
        updates["id"] = calendar_id
        _flash(request, str(exc), "error")
        months = [
            {**month, "value": ", ".join(str(day) for day in updates["dias_letivos"].get(month["key"], []))}
            for month in MONTHS
        ]
        return _render(request, "calendar_form.html", calendar=updates, months=months, feriados=feriados)


@app.post("/calendars/{calendar_id}/delete")
def calendars_delete(request: Request, calendar_id: int):
    try:
        delete_calendar(calendar_id)
        _flash(request, "Calendário removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/calendars", status_code=303)


@app.get("/curricular-units")
def units_list(request: Request):
    return _render(
        request,
        "curricular_units.html",
        units=list_units(),
        courses=list_courses(),
    )


@app.get("/curricular-units/new")
def units_new(request: Request):
    return _render(request, "curricular_unit_form.html", unit=None, courses=list_courses())


@app.post("/curricular-units/new")
def units_create(
    request: Request,
    curso_id: str = Form(...),
    nome: str = Form(...),
    carga_horaria: str = Form(""),
    modulo: str = Form(""),
    ativo: str = Form("true"),
):
    payload: Dict[str, Any] = {
        "curso_id": int(curso_id),
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
        unit=get_unit(int(unit_id)),
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
        "curso_id": int(curso_id),
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
        update_unit(int(unit_id), updates)
        _flash(request, "Unidade curricular atualizada com sucesso.")
        return RedirectResponse("/curricular-units", status_code=303)
    except ValidationError as exc:
        updates["id"] = int(unit_id)
        _flash(request, str(exc), "error")
        return _render(request, "curricular_unit_form.html", unit=updates, courses=list_courses())


@app.post("/curricular-units/{unit_id}/delete")
def units_delete(request: Request, unit_id: str):
    try:
        delete_unit(int(unit_id))
        _flash(request, "Unidade curricular removida com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/curricular-units", status_code=303)


@app.get("/curricular-units/batch")
def units_batch(request: Request):
    return _render(request, "curricular_unit_batch.html", courses=list_courses())


@app.post("/curricular-units/batch")
def units_batch_create(
    request: Request,
    curso_id: str = Form(...),
    linhas: str = Form(...),
):
    try:
        created = create_units_batch_from_lines(int(curso_id), linhas)
        _flash(request, f"{len(created)} unidades curriculares cadastradas.")
        return RedirectResponse("/curricular-units", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(request, "curricular_unit_batch.html", courses=list_courses(), linhas=linhas)


@app.get("/schedules")
def schedules_list(
    request: Request,
    data_inicio: str = "",
    data_fim: str = "",
    sala_id: str = "",
    instrutor_id: str = "",
    turno_id: str = "",
):
    items = list_schedules()

    if data_inicio:
        items = [item for item in items if item.get("data_fim", "") >= data_inicio]
    if data_fim:
        items = [item for item in items if item.get("data_inicio", "") <= data_fim]
    if sala_id:
        sala_val = _parse_int(sala_id) or sala_id
        items = [item for item in items if item.get("sala_id") == sala_val]
    if instrutor_id:
        instrutor_val = _parse_int(instrutor_id) or instrutor_id
        items = [item for item in items if item.get("instrutor_id") == instrutor_val]
    if turno_id:
        turno_val = _parse_int(turno_id) or turno_id
        items = [item for item in items if item.get("turno_id") == turno_val]

    instrutores = _collaborators_by_type("instrutor")
    return _render(
        request,
        "schedules.html",
        schedules=items,
        courses=list_courses(),
        units=list_units(),
        instructors=instrutores,
        rooms=list_rooms(),
        shifts=list_shifts(),
        filters={
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "sala_id": sala_id,
            "instrutor_id": instrutor_id,
            "turno_id": turno_id,
        },
    )


@app.get("/schedules/new")
def schedules_new(request: Request):
    current_year = datetime.now().year
    rooms = list_rooms()
    default_quantidade = rooms[0].get("capacidade") if rooms else ""
    return _render(
        request,
        "schedule_form.html",
        schedule=None,
        courses=list_courses(),
        units=list_units(),
        instrutores=_collaborators_by_type("instrutor"),
        analistas=_collaborators_by_type("analista"),
        assistentes=_collaborators_by_type("assistente"),
        rooms=rooms,
        shifts=list_shifts(),
        status_options=["confirmada", "adiada", "em execução", "cancelada"],
        default_ano=current_year,
        default_quantidade=default_quantidade,
    )


@app.post("/schedules/new")
def schedules_create(
    request: Request,
    curso_id: str = Form(...),
    unidade_id: str = Form(...),
    instrutor_id: str = Form(...),
    analista_id: str = Form(...),
    assistente_id: str = Form(...),
    sala_id: str = Form(...),
    turno_id: str = Form(...),
    unidade_cep: str = Form(...),
    mes: str = Form(...),
    ano: str = Form(...),
    quantidade_alunos: str = Form(...),
    recurso: str = Form(...),
    programa_parceria: str = Form(...),
    numero_turma: str = Form(...),
    carga_horaria: str = Form(...),
    horario: str = Form(...),
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
    status: str = Form(...),
    observacoes: str = Form(""),
):
    payload = {
        "curso_id": int(curso_id),
        "unidade_id": int(unidade_id),
        "instrutor_id": int(instrutor_id),
        "analista_id": int(analista_id),
        "assistente_id": int(assistente_id),
        "sala_id": int(sala_id),
        "turno_id": int(turno_id),
        "unidade_cep": unidade_cep,
        "mes": mes,
        "ano": _parse_int(ano) or ano,
        "quantidade_alunos": _parse_int(quantidade_alunos) or quantidade_alunos,
        "recurso": recurso,
        "programa_parceria": programa_parceria,
        "numero_turma": numero_turma,
        "carga_horaria": _parse_float(carga_horaria) or carga_horaria,
        "horario": horario,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "status": status,
        "observacoes": observacoes,
    }
    try:
        create_schedule(payload)
        _flash(request, "Programação criada com sucesso.")
        return RedirectResponse("/schedules", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(
            request,
            "schedule_form.html",
            schedule=payload,
            courses=list_courses(),
            units=list_units(),
            instrutores=_collaborators_by_type("instrutor"),
            analistas=_collaborators_by_type("analista"),
            assistentes=_collaborators_by_type("assistente"),
            rooms=list_rooms(),
            shifts=list_shifts(),
            status_options=["confirmada", "adiada", "em execução", "cancelada"],
            default_ano=datetime.now().year,
            default_quantidade=payload.get("quantidade_alunos", ""),
        )


@app.get("/schedules/{schedule_id}/edit")
def schedules_edit(request: Request, schedule_id: str):
    return _render(
        request,
        "schedule_form.html",
        schedule=get_schedule(int(schedule_id)),
        courses=list_courses(),
        units=list_units(),
        instrutores=_collaborators_by_type("instrutor"),
        analistas=_collaborators_by_type("analista"),
        assistentes=_collaborators_by_type("assistente"),
        rooms=list_rooms(),
        shifts=list_shifts(),
        status_options=["confirmada", "adiada", "em execução", "cancelada"],
        default_ano=datetime.now().year,
        default_quantidade="",
    )


@app.post("/schedules/{schedule_id}/edit")
def schedules_update(
    request: Request,
    schedule_id: str,
    curso_id: str = Form(...),
    unidade_id: str = Form(...),
    instrutor_id: str = Form(...),
    analista_id: str = Form(...),
    assistente_id: str = Form(...),
    sala_id: str = Form(...),
    turno_id: str = Form(...),
    unidade_cep: str = Form(...),
    mes: str = Form(...),
    ano: str = Form(...),
    quantidade_alunos: str = Form(...),
    recurso: str = Form(...),
    programa_parceria: str = Form(...),
    numero_turma: str = Form(...),
    carga_horaria: str = Form(...),
    horario: str = Form(...),
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
    status: str = Form(...),
    observacoes: str = Form(""),
):
    updates = {
        "curso_id": int(curso_id),
        "unidade_id": int(unidade_id),
        "instrutor_id": int(instrutor_id),
        "analista_id": int(analista_id),
        "assistente_id": int(assistente_id),
        "sala_id": int(sala_id),
        "turno_id": int(turno_id),
        "unidade_cep": unidade_cep,
        "mes": mes,
        "ano": _parse_int(ano) or ano,
        "quantidade_alunos": _parse_int(quantidade_alunos) or quantidade_alunos,
        "recurso": recurso,
        "programa_parceria": programa_parceria,
        "numero_turma": numero_turma,
        "carga_horaria": _parse_float(carga_horaria) or carga_horaria,
        "horario": horario,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "status": status,
        "observacoes": observacoes,
    }
    try:
        update_schedule(int(schedule_id), updates)
        _flash(request, "Programação atualizada com sucesso.")
        return RedirectResponse("/schedules", status_code=303)
    except ValidationError as exc:
        updates["id"] = int(schedule_id)
        _flash(request, str(exc), "error")
        return _render(
            request,
            "schedule_form.html",
            schedule=updates,
            courses=list_courses(),
            units=list_units(),
            instrutores=_collaborators_by_type("instrutor"),
            analistas=_collaborators_by_type("analista"),
            assistentes=_collaborators_by_type("assistente"),
            rooms=list_rooms(),
            shifts=list_shifts(),
            status_options=["confirmada", "adiada", "em execução", "cancelada"],
            default_ano=datetime.now().year,
            default_quantidade=updates.get("quantidade_alunos", ""),
        )


@app.post("/schedules/{schedule_id}/delete")
def schedules_delete(request: Request, schedule_id: str):
    try:
        delete_schedule(int(schedule_id))
        _flash(request, "Programação removida com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/schedules", status_code=303)


@app.get("/reports")
def schedules_report(
    request: Request,
    tipo: str = "mensal",
    data_inicio: str = "",
    data_fim: str = "",
):
    items = list_schedules()
    today = datetime.now()
    if tipo == "mensal":
        data_inicio, data_fim = _month_range(today, 1)
    elif tipo == "trimestral":
        data_inicio, data_fim = _month_range(today, 3)
    elif tipo == "semestral":
        data_inicio, data_fim = _month_range(today, 6)
    elif tipo == "anual":
        data_inicio = f"{today.year}-01-01"
        data_fim = f"{today.year}-12-31"
    items = _filter_by_date_range(items, data_inicio, data_fim)
    return _render(
        request,
        "reports.html",
        schedules=items,
        tipo=tipo,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )


@app.get("/cronogramas")
def cronogramas_list(
    request: Request,
    ano: str = "",
    mes: str = "",
    turno_id: str = "",
    instrutor_id: str = "",
    analista_id: str = "",
    assistente_id: str = "",
):
    items = list_schedules()
    ano_filter = ano or str(datetime.now().year)
    items = [item for item in items if str(item.get("ano")) == ano_filter]
    if mes:
        items = [item for item in items if str(item.get("mes")) == mes]
    if turno_id:
        turno_val = _parse_int(turno_id) or turno_id
        items = [item for item in items if item.get("turno_id") == turno_val]
    if instrutor_id:
        instrutor_val = _parse_int(instrutor_id) or instrutor_id
        items = [item for item in items if item.get("instrutor_id") == instrutor_val]
    if analista_id:
        analista_val = _parse_int(analista_id) or analista_id
        items = [item for item in items if item.get("analista_id") == analista_val]
    if assistente_id:
        assistente_val = _parse_int(assistente_id) or assistente_id
        items = [item for item in items if item.get("assistente_id") == assistente_val]
    return _render(
        request,
        "cronogramas.html",
        schedules=items,
        shifts=list_shifts(),
        instrutores=_collaborators_by_type("instrutor"),
        analistas=_collaborators_by_type("analista"),
        assistentes=_collaborators_by_type("assistente"),
        filtros={
            "ano": ano_filter,
            "mes": mes,
            "turno_id": turno_id,
            "instrutor_id": instrutor_id,
            "analista_id": analista_id,
            "assistente_id": assistente_id,
        },
    )


@app.get("/cronogramas/{schedule_id}")
def cronograma_detail(request: Request, schedule_id: str):
    schedule = get_schedule(int(schedule_id))
    return _render(request, "cronograma_detail.html", schedule=schedule)
