import json
from pathlib import Path
from typing import Callable, Any


def _default_key(item: dict, key_fields: tuple[str, ...]) -> str | None:
    for f in key_fields:
        v = item.get(f)
        if isinstance(v, str) and v.strip():
            return v
    for f in key_fields:
        v = item.get(f)
        if v is not None:
            return str(v)
    return None


def load_jsonl_map(
    path: Path,
    *,
    key_fields: tuple[str, ...] = ("source", "date"),
    key_fn: Callable[[dict], str | None] | None = None,
) -> dict[str, dict]:
    m: dict[str, dict] = {}
    if not path.exists():
        return m

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            key = key_fn(item) if key_fn else _default_key(item, key_fields)
            if key:
                m[key] = item
    return m


def write_jsonl_map(path: Path, m: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in m.values():
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def upsert_jsonl(
    path: Path,
    item: dict,
    *,
    key_fields: tuple[str, ...] = ("source", "date"),
    key_fn: Callable[[dict], str | None] | None = None,
) -> str:
    if not isinstance(item, dict):
        raise ValueError("item must be a dict")
    key = key_fn(item) if key_fn else _default_key(item, key_fields)
    if not key:
        raise ValueError(f"item missing key fields: {key_fields}")

    m = load_jsonl_map(path, key_fields=key_fields, key_fn=key_fn)
    m[key] = item
    write_jsonl_map(path, m)
    return key
