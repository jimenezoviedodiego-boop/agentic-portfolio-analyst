import csv
import json
import os
from pathlib import Path

import yaml


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("PORTFOLIO_DATA_DIR")
    if override:
        return Path(override)
    return repo_root() / "data"


def load_portfolio(path: Path | None = None) -> list[dict]:
    path = path or (data_dir() / "portfolio.yaml")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    holdings = []
    for h in data.get("holdings", []):
        h = dict(h)
        h["is_etf"] = False
        holdings.append(h)
    for h in data.get("etfs", []):
        h = dict(h)
        h["is_etf"] = True
        holdings.append(h)
    return holdings


def append_dedup_csv(path: Path, new_rows: list[dict], key_fields: list[str], fieldnames: list[str]) -> int:
    existing: dict[tuple, dict] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = tuple(row[k] for k in key_fields)
                existing[key] = row

    added = 0
    for row in new_rows:
        row = {k: str(row.get(k, "")) for k in fieldnames}
        key = tuple(row[k] for k in key_fields)
        if key not in existing:
            added += 1
        existing[key] = row

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(existing.keys()):
            writer.writerow(existing[key])

    return added


def append_dedup_jsonl(path: Path, new_rows: list[dict], key_field: str) -> int:
    existing_keys = set()
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    existing_keys.add(json.loads(line)[key_field])

    added = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in new_rows:
            if row[key_field] in existing_keys:
                continue
            f.write(json.dumps(row) + "\n")
            existing_keys.add(row[key_field])
            added += 1
    return added


def append_yaml_list(path: Path, new_entry: dict, list_key: str) -> None:
    data = {list_key: []}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if loaded:
            data = loaded

    data.setdefault(list_key, []).append(new_entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load_yaml_list(path: Path, list_key: str) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return (data or {}).get(list_key, [])


def load_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_jsonl_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def latest_by_date(entries: list[dict], date_field: str = "date") -> dict | None:
    if not entries:
        return None
    return max(entries, key=lambda e: e[date_field])
