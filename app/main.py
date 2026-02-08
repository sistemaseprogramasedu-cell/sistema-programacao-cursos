from __future__ import annotations

import json
from datetime import date
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


def _parse_json(text: str, default: Any) -> Any:
    cleaned = text.strip()
    if not cleaned:
        return default
    return json.loads(cleaned)


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
    course_id: str = Form(...),
    nome: str = Form(...),
    nivel: str = Form(...),
    carga_horaria_total: str = Form(...),
    ativo: str = Form("true"),
):
    payload = {
        "id": course_id,
        "nome": nome,
        "nivel": nivel,
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
    return _render(request, "course_form.html", course=get_course(course_id))


@app.post("/courses/{course_id}/edit")
def courses_update(
    request: Request,
    course_id: str,
    nome: str = Form(...),
    nivel: str = Form(...),
    carga_horaria_total: str = Form(...),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
        "nivel": nivel,
        "carga_horaria_total": _parse_int(carga_horaria_total) or carga_horaria_total,
        "ativo": ativo == "true",
    }
    try:
        update_course(course_id, updates)
        _flash(request, "Curso atualizado com sucesso.")
        return RedirectResponse("/courses", status_code=303)
    except ValidationError as exc:
        updates["id"] = course_id
        _flash(request, str(exc), "error")
        return _render(request, "course_form.html", course=updates)


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
    return _render(request, "room_form.html", room=None)


@app.post("/rooms/new")
def rooms_create(
    request: Request,
    room_id: str = Form(...),
    nome: str = Form(...),
    capacidade: str = Form(...),
    recursos: str = Form(""),
    ativo: str = Form("true"),
):
    payload = {
        "id": room_id,
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
    return _render(request, "room_form.html", room=get_room(room_id))


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
        update_room(room_id, updates)
        _flash(request, "Sala atualizada com sucesso.")
        return RedirectResponse("/rooms", status_code=303)
    except ValidationError as exc:
        updates["id"] = room_id
        _flash(request, str(exc), "error")
        return _render(request, "room_form.html", room=updates)


@app.post("/rooms/{room_id}/delete")
def rooms_delete(request: Request, room_id: str):
    try:
        delete_room(room_id)
        _flash(request, "Sala removida com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/rooms", status_code=303)


@app.get("/collaborators")
def collaborators_list(request: Request):
    return _render(request, "collaborators.html", instructors=list_instructors())


@app.get("/instructors")
def instructors_redirect():
    return RedirectResponse("/collaborators", status_code=302)


@app.get("/collaborators/new")
def collaborators_new(request: Request):
    return _render(request, "collaborator_form.html", instructor=None)


@app.get("/instructors/new")
def instructors_new_redirect():
    return RedirectResponse("/collaborators/new", status_code=302)


@app.post("/collaborators/new")
@app.post("/instructors/new")
def collaborators_create(
    request: Request,
    instructor_id: str = Form(...),
    nome: str = Form(...),
    email: str = Form(...),
    telefone: str = Form(""),
    role: str = Form("Instrutor"),
    especialidades: str = Form(""),
    max_horas_semana: str = Form(""),
    ativo: str = Form("true"),
):
    payload = {
        "id": instructor_id,
        "nome": nome,
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
        return _render(request, "collaborator_form.html", instructor=payload)


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
    email: str = Form(...),
    telefone: str = Form(""),
    role: str = Form("Instrutor"),
    especialidades: str = Form(""),
    max_horas_semana: str = Form(""),
    ativo: str = Form("true"),
):
    updates = {
        "nome": nome,
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
        return _render(request, "collaborator_form.html", instructor=updates)


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
    return _render(request, "shift_form.html", shift=None)


@app.post("/shifts/new")
def shifts_create(
    request: Request,
    shift_id: str = Form(...),
    nome: str = Form(...),
    horario_inicio: str = Form(...),
    horario_fim: str = Form(...),
    dias_semana: str = Form(...),
    ativo: str = Form("true"),
):
    payload = {
        "id": shift_id,
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
    return _render(request, "shift_form.html", shift=get_shift(shift_id))


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
        update_shift(shift_id, updates)
        _flash(request, "Turno atualizado com sucesso.")
        return RedirectResponse("/shifts", status_code=303)
    except ValidationError as exc:
        updates["id"] = shift_id
        _flash(request, str(exc), "error")
        return _render(request, "shift_form.html", shift=updates)


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
    return _render(request, "calendar_form.html", calendar=None)


@app.post("/calendars/new")
def calendars_create(
    request: Request,
    ano: str = Form(...),
    periodos_json: str = Form("[]"),
    feriados_json: str = Form("[]"),
    ativo: str = Form("true"),
):
    payload = {
        "ano": _parse_int(ano) or ano,
        "periodos": _parse_json(periodos_json, []),
        "feriados": _parse_json(feriados_json, []),
        "ativo": ativo == "true",
    }
    try:
        create_calendar(payload)
        _flash(request, "Calendário cadastrado com sucesso.")
        return RedirectResponse("/calendars", status_code=303)
    except (ValidationError, json.JSONDecodeError) as exc:
        _flash(request, str(exc), "error")
        return _render(request, "calendar_form.html", calendar=payload)


@app.get("/calendars/{year}/edit")
def calendars_edit(request: Request, year: int):
    return _render(request, "calendar_form.html", calendar=get_calendar(year))


@app.post("/calendars/{year}/edit")
def calendars_update(
    request: Request,
    year: int,
    periodos_json: str = Form("[]"),
    feriados_json: str = Form("[]"),
    ativo: str = Form("true"),
):
    updates = {
        "periodos": _parse_json(periodos_json, []),
        "feriados": _parse_json(feriados_json, []),
        "ativo": ativo == "true",
    }
    try:
        update_calendar(year, updates)
        _flash(request, "Calendário atualizado com sucesso.")
        return RedirectResponse("/calendars", status_code=303)
    except (ValidationError, json.JSONDecodeError) as exc:
        updates["ano"] = year
        _flash(request, str(exc), "error")
        return _render(request, "calendar_form.html", calendar=updates)


@app.post("/calendars/{year}/delete")
def calendars_delete(request: Request, year: int):
    try:
        delete_calendar(year)
        _flash(request, "Calendário removido com sucesso.")
    except ValidationError as exc:
        _flash(request, str(exc), "error")
    return RedirectResponse("/calendars", status_code=303)


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
        items = [item for item in items if item.get("sala_id") == sala_id]
    if instrutor_id:
        items = [item for item in items if item.get("instrutor_id") == instrutor_id]
    if turno_id:
        items = [item for item in items if item.get("turno_id") == turno_id]

    return _render(
        request,
        "schedules.html",
        schedules=items,
        courses=list_courses(),
        units=list_units(),
        instructors=list_instructors(),
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
    return _render(
        request,
        "schedule_form.html",
        schedule=None,
        courses=list_courses(),
        units=list_units(),
        instructors=list_instructors(),
        rooms=list_rooms(),
        shifts=list_shifts(),
    )


@app.post("/programming/new")
@app.post("/schedules/new")
def schedules_create(
    request: Request,
    schedule_id: str = Form(...),
    curso_id: str = Form(...),
    unidade_id: str = Form(...),
    instrutor_id: str = Form(...),
    sala_id: str = Form(...),
    turno_id: str = Form(...),
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
):
    payload = {
        "id": schedule_id,
        "curso_id": curso_id,
        "unidade_id": unidade_id,
        "instrutor_id": instrutor_id,
        "sala_id": sala_id,
        "turno_id": turno_id,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
    }
    try:
        create_schedule(payload)
        _flash(request, "Oferta criada com sucesso.")
        return RedirectResponse("/programming", status_code=303)
    except ValidationError as exc:
        _flash(request, str(exc), "error")
        return _render(
            request,
            "schedule_form.html",
            schedule=payload,
            courses=list_courses(),
            units=list_units(),
            instructors=list_instructors(),
            rooms=list_rooms(),
            shifts=list_shifts(),
        )


@app.get("/programming/{schedule_id}/edit")
@app.get("/schedules/{schedule_id}/edit")
def schedules_edit(request: Request, schedule_id: str):
    return _render(
        request,
        "schedule_form.html",
        schedule=get_schedule(schedule_id),
        courses=list_courses(),
        units=list_units(),
        instructors=list_instructors(),
        rooms=list_rooms(),
        shifts=list_shifts(),
    )


@app.post("/programming/{schedule_id}/edit")
@app.post("/schedules/{schedule_id}/edit")
def schedules_update(
    request: Request,
    schedule_id: str,
    curso_id: str = Form(...),
    unidade_id: str = Form(...),
    instrutor_id: str = Form(...),
    sala_id: str = Form(...),
    turno_id: str = Form(...),
    data_inicio: str = Form(...),
    data_fim: str = Form(...),
):
    updates = {
        "curso_id": curso_id,
        "unidade_id": unidade_id,
        "instrutor_id": instrutor_id,
        "sala_id": sala_id,
        "turno_id": turno_id,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
    }
    try:
        update_schedule(schedule_id, updates)
        _flash(request, "Oferta atualizada com sucesso.")
        return RedirectResponse("/programming", status_code=303)
    except ValidationError as exc:
        updates["id"] = schedule_id
        _flash(request, str(exc), "error")
        return _render(
            request,
            "schedule_form.html",
            schedule=updates,
            courses=list_courses(),
            units=list_units(),
            instructors=list_instructors(),
            rooms=list_rooms(),
            shifts=list_shifts(),
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
    months = [
        {"value": "1", "label": "Janeiro"},
        {"value": "2", "label": "Fevereiro"},
        {"value": "3", "label": "Março"},
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
    collaborators = list_instructors()
    instructors = [item for item in collaborators if item.get("role") == "Instrutor"]
    analysts = [item for item in collaborators if item.get("role") == "Analista"]
    assistants = [item for item in collaborators if item.get("role") == "Assistente"]
    return _render(
        request,
        "chronograms.html",
        filters=filters,
        months=months,
        shifts=list_shifts(),
        instructors=instructors,
        analysts=analysts,
        assistants=assistants,
    )
