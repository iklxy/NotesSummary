"""
@Date: 2026-04-20
@Author: lixinyang

热词 / 术语提示文件加载工具。

支持的文件格式:
    - .txt  : 每行一个热词，支持 # 注释行
    - .json : 字符串列表，或包含 term / alias / from / to 等字段的对象列表
    - .csv  : 第一列作为热词；如果存在第二列，会拼成 "第一列 -> 第二列"
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, List


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


def load_term_hints_from_file(file_path: str | None) -> List[str]:
    """
    从热词文件加载术语提示列表。

    参数:
        file_path: 热词文件路径；为空或文件不存在时返回空列表。

    返回:
        术语提示字符串列表，可直接传给 clean_speaker_utterance / clean_file_content_json。
    """
    if not file_path:
        return []

    path = Path(file_path).expanduser()
    if not path.exists() or not path.is_file():
        return []

    suffix = path.suffix.lower()
    items: List[str] = []

    if suffix == ".txt":
        with path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                items.append(line)
        return _dedupe_keep_order(items)

    if suffix == ".json":
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

    if suffix == ".csv":
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

    # 兜底：按 txt 处理
    with path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            items.append(line)
    return _dedupe_keep_order(items)
