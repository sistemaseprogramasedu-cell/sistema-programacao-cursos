from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class ValidationError(ValueError):
    pass


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


def load_items(filename: str) -> List[Dict[str, Any]]:
    data = _read_json(DATA_DIR / filename)
    return data.get("items", [])


def save_items(filename: str, items: List[Dict[str, Any]]) -> None:
    path = DATA_DIR / filename
    data = _read_json(path)
    data["items"] = items
    _write_json(path, data)


def require_fields(payload: Dict[str, Any], fields: List[str]) -> None:
    missing = [field for field in fields if not payload.get(field)]
    if missing:
        raise ValidationError(f"Campos obrigatórios ausentes: {', '.join(missing)}")


def ensure_unique_id(items: List[Dict[str, Any]], item_id: str, id_field: str = "id") -> None:
    if any(item.get(id_field) == item_id for item in items):
        raise ValidationError(f"ID já cadastrado: {item_id}")


def find_item(items: List[Dict[str, Any]], item_id: str, id_field: str = "id") -> Dict[str, Any] | None:
    return next((item for item in items if item.get(id_field) == item_id), None)


def next_sequential_id(items: List[Dict[str, Any]], prefix: str, id_field: str = "id") -> str:
    highest = 0
    for item in items:
        value = str(item.get(id_field, ""))
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix) :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{prefix}{highest + 1:03d}"
