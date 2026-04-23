"""
@Date: 2026-04-20
@Author: lixinyang

热词 / 术语提示文件加载工具。

支持两类来源：
1. 直接从单个热词文件加载。
2. 根据统一热词包 code，从 data/hotword_manifest.json 读取并拼接对应词表。
3. 根据统一热词包 code，读取对应的兜底纠错文本文件。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, List


ROOT_DIR = Path(__file__).resolve().parent
HOTWORD_MANIFEST_PATH = ROOT_DIR / "data" / "hotword_manifest.json"
HOTWORD_STATE_DIR = ROOT_DIR / "data" / "hotword_state"


def _normalize_term(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        normalized = _normalize_term(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _load_terms_from_text_file(path: Path) -> List[str]:
    items: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            items.append(line)
    return _dedupe_keep_order(items)


def _load_terms_from_json_file(path: Path) -> List[str]:
    items: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                items.append(item)
                continue
            if isinstance(item, dict):
                for key in ("term", "alias", "from", "to", "name", "value"):
                    if key in item and item[key]:
                        if key in {"from", "to"} and item.get("from") and item.get("to"):
                            items.append(f"{item['from']} -> {item['to']}")
                        else:
                            items.append(str(item[key]))
                        break
    elif isinstance(data, dict):
        for key in ("terms", "term_hints", "hotwords", "hot_words"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        items.append(item)
                    elif isinstance(item, dict):
                        for inner_key in ("term", "alias", "from", "to", "name", "value"):
                            if inner_key in item and item[inner_key]:
                                if inner_key in {"from", "to"} and item.get("from") and item.get("to"):
                                    items.append(f"{item['from']} -> {item['to']}")
                                else:
                                    items.append(str(item[inner_key]))
                                break
                break

    return _dedupe_keep_order(items)


def _load_terms_from_csv_file(path: Path) -> List[str]:
    items: List[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            first = _normalize_term(row[0])
            if not first or first.startswith("#"):
                continue
            if len(row) >= 2 and _normalize_term(row[1]):
                items.append(f"{first} -> {_normalize_term(row[1])}")
            else:
                items.append(first)
    return _dedupe_keep_order(items)


def load_term_hints_from_file(file_path: str | None) -> List[str]:
    if not file_path:
        return []

    path = Path(file_path).expanduser()
    if not path.exists() or not path.is_file():
        return []

    suffix = path.suffix.lower()
    if suffix == ".txt":
        return _load_terms_from_text_file(path)
    if suffix == ".json":
        return _load_terms_from_json_file(path)
    if suffix == ".csv":
        return _load_terms_from_csv_file(path)

    return _load_terms_from_text_file(path)


def load_hotword_manifest() -> dict[str, list[dict[str, str]]]:
    if not HOTWORD_MANIFEST_PATH.exists():
        return {"project": [], "interview": []}
    with HOTWORD_MANIFEST_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    project = data.get("project") if isinstance(data, dict) else []
    interview = data.get("interview") if isinstance(data, dict) else []
    if not isinstance(project, list):
        project = []
    if not isinstance(interview, list):
        interview = []
    if not project and interview:
        project = []
    return {
        "project": project if isinstance(project, list) else [],
        "interview": interview if isinstance(interview, list) else [],
    }


def _build_code_map(category: str, field_name: str = "file") -> dict[str, Path]:
    manifest = load_hotword_manifest()
    options = manifest.get(category, [])
    if not options and category == "project":
        options = manifest.get("interview", [])
    mapping: dict[str, Path] = {}
    for item in options:
        if not isinstance(item, dict):
            continue
        code = _normalize_term(item.get("code"))
        file_rel = _normalize_term(item.get(field_name))
        if not file_rel and field_name == "correction_file":
            # 兼容没有显式配置 correction_file 的旧 manifest：
            # 直接按主词表文件名推导对应的兜底纠错文本。
            base_file_rel = _normalize_term(item.get("file"))
            if base_file_rel:
                base_path = Path(base_file_rel)
                file_rel = str(base_path.with_name(f"{base_path.stem}_corrections{base_path.suffix}"))
        if not code or not file_rel:
            continue
        mapping[code] = ROOT_DIR / "data" / file_rel
    return mapping


def load_term_hints_from_keys(category: str, keys: list[str] | None) -> List[str]:
    if not keys:
        return []
    mapping = _build_code_map(category, field_name="file")
    items: List[str] = []
    for key in keys:
        path = mapping.get(_normalize_term(key))
        if not path or not path.exists():
            continue
        items.extend(load_term_hints_from_file(str(path)))
    return _dedupe_keep_order(items)


def load_correction_rules_from_keys(category: str, keys: list[str] | None) -> List[str]:
    if not keys:
        return []
    mapping = _build_code_map(category, field_name="correction_file")
    items: List[str] = []
    for key in keys:
        path = mapping.get(_normalize_term(key))
        if not path or not path.exists():
            continue
        items.extend(load_term_hints_from_file(str(path)))
    return _dedupe_keep_order(items)


def _extract_state_keys(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    raw = data.get("keys")
    if raw is None:
        raw = data.get("hotword_keys")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def load_term_hints_from_state(interview_id: int | None = None) -> List[str]:
    items: List[str] = []
    if interview_id is not None:
        state_path = HOTWORD_STATE_DIR / "interview" / f"{interview_id}.json"
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                items.extend(load_term_hints_from_keys("interview", _extract_state_keys(data)))
            except Exception:
                pass
    return _dedupe_keep_order(items)


def load_correction_rules_from_state(interview_id: int | None = None) -> List[str]:
    items: List[str] = []
    if interview_id is not None:
        state_path = HOTWORD_STATE_DIR / "interview" / f"{interview_id}.json"
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                items.extend(load_correction_rules_from_keys("interview", _extract_state_keys(data)))
            except Exception:
                pass
    return _dedupe_keep_order(items)


def save_hotword_state(category: str, entity_id: int, keys: list[str] | None) -> Path:
    target_dir = HOTWORD_STATE_DIR / category
    target_dir.mkdir(parents=True, exist_ok=True)
    normalized_keys = _dedupe_keep_order(keys or [])
    payload = {
        "keys": normalized_keys,
        "hotword_keys": normalized_keys,
    }
    target_path = target_dir / f"{entity_id}.json"
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def merge_term_hints(*groups: list[str], max_total: int = 120) -> List[str]:
    merged: List[str] = []
    for group in groups:
        merged.extend(group or [])
    merged = _dedupe_keep_order(merged)
    if max_total > 0 and len(merged) > max_total:
        return merged[:max_total]
    return merged
