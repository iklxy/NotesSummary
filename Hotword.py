"""
@Date: 2026-04-20
@Author: lixinyang

热词 / 术语提示文件加载工具。

当前文件在单文件内按职责分层：
1. 基础字符串规范化与去重
2. 不同文件格式的词表加载
3. manifest 映射与 code -> 文件解析
4. state 文件读写
5. 热词与纠错规则合并策略
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, List


ROOT_DIR = Path(__file__).resolve().parent
HOTWORD_MANIFEST_PATH = ROOT_DIR / "data" / "hotword_manifest.json"
HOTWORD_STATE_DIR = ROOT_DIR / "data" / "hotword_state"


# ----------------------------------------------------------------------
# 基础规范化与去重
# ----------------------------------------------------------------------
def _normalize_term(value: Any) -> str:
    """
    将任意输入值标准化为去首尾空白后的字符串。

    参数:
        value: 原始输入值。允许为字符串、数字、None 或其他可转字符串对象。

    返回:
        标准化后的字符串。
        当输入为 `None` 时，返回空字符串。
    """
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_keep_order(items: Iterable[str]) -> List[str]:
    """
    对词条列表按出现顺序去重，并过滤空值。

    参数:
        items: 原始词条可迭代对象，元素通常为热词、术语或纠错规则字符串。

    返回:
        去重后的字符串列表，保留首次出现顺序。
    """
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        normalized = _normalize_term(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


# ----------------------------------------------------------------------
# 文件加载
# ----------------------------------------------------------------------
def _load_terms_from_text_file(path: Path) -> List[str]:
    """
    从纯文本文件中读取热词或纠错规则。

    参数:
        path: 文本文件路径。每行代表一个词条，支持以 `#` 或 `//` 开头的注释行。

    返回:
        去重后的词条列表。
    """
    items: List[str] = []
    with path.open("r", encoding="utf-8") as file_obj:
        for raw_line in file_obj:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            items.append(line)
    return _dedupe_keep_order(items)


def _load_terms_from_json_file(path: Path) -> List[str]:
    """
    从 JSON 文件中读取热词或纠错规则。

    参数:
        path: JSON 文件路径。支持以下结构：
            - 字符串列表
            - 对象列表
            - 包含 `terms` / `term_hints` / `hotwords` / `hot_words` 的字典

    返回:
        去重后的词条列表。
        若 JSON 内包含 `{from, to}` 结构，则会转成 `from -> to` 字符串。
    """
    items: List[str] = []
    with path.open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)

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
    """
    从 CSV 文件中读取热词或纠错规则。

    参数:
        path: CSV 文件路径。默认读取第一列作为词条；若存在第二列，则按
            `第一列 -> 第二列` 解释为纠错规则。

    返回:
        去重后的词条列表。
    """
    items: List[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.reader(file_obj)
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
    """
    根据文件后缀自动加载热词或纠错规则。

    参数:
        file_path: 待加载文件路径。支持 `.txt`、`.json`、`.csv`；
            当为 `None`、空字符串或文件不存在时，直接返回空列表。

    返回:
        去重后的词条列表。
    """
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


# ----------------------------------------------------------------------
# manifest 映射与 code -> 文件解析
# ----------------------------------------------------------------------
def load_hotword_manifest() -> dict[str, list[dict[str, str]]]:
    """
    读取统一热词 manifest 配置。

    参数:
        无。默认从 `data/hotword_manifest.json` 读取。

    返回:
        一个包含 `project` 和 `interview` 两个键的字典。
        当前项目主要使用 `interview`，但返回结构保留兼容性。
    """
    if not HOTWORD_MANIFEST_PATH.exists():
        return {"project": [], "interview": []}

    with HOTWORD_MANIFEST_PATH.open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)

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
    """
    根据 manifest 构建 `code -> 文件路径` 映射。

    参数:
        category: manifest 分类名称，通常为 `interview`。
        field_name: 需要读取的文件字段名：
            - `file`: 主热词文件
            - `correction_file`: 对应的兜底纠错文件

    返回:
        一个字典，键为热词包 code，值为对应的绝对文件路径。
        若某项配置缺失或不合法，则自动跳过。
    """
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
            base_file_rel = _normalize_term(item.get("file"))
            if base_file_rel:
                base_path = Path(base_file_rel)
                file_rel = str(base_path.with_name(f"{base_path.stem}_corrections{base_path.suffix}"))

        if not code or not file_rel:
            continue
        mapping[code] = ROOT_DIR / "data" / file_rel
    return mapping


def load_term_hints_from_keys(category: str, keys: list[str] | None) -> List[str]:
    """
    根据热词包 key 列表加载主热词内容。

    参数:
        category: manifest 分类名称，通常为 `interview`。
        keys: 热词包 code 列表，通常来自前端选择结果或 state 文件。

    返回:
        合并并去重后的热词列表。
    """
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
    """
    根据热词包 key 列表加载对应的兜底纠错规则。

    参数:
        category: manifest 分类名称，通常为 `interview`。
        keys: 热词包 code 列表，通常与主热词使用同一组 key。

    返回:
        合并并去重后的纠错规则列表。
        规则通常采用 `错误词 -> 正确词` 的字符串格式。
    """
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


# ----------------------------------------------------------------------
# state 文件读写
# ----------------------------------------------------------------------
def _extract_state_keys(data: Any) -> list[str]:
    """
    从 state JSON 对象中提取热词包 key 列表。

    参数:
        data: 已反序列化的 state JSON 数据，通常应为字典。

    返回:
        热词包 key 列表。
        同时兼容 `keys` 与旧字段 `hotword_keys`。
    """
    if not isinstance(data, dict):
        return []
    raw = data.get("keys")
    if raw is None:
        raw = data.get("hotword_keys")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _load_state_json(category: str, entity_id: int | None) -> Any:
    """
    读取指定实体的热词 state 文件。

    参数:
        category: state 分类名称，通常为 `interview`。
        entity_id: 实体 ID，例如访谈 ID；若为 `None`，直接返回 `None`。

    返回:
        解析后的 JSON 对象；若文件不存在或读取失败，则返回 `None`。
    """
    if entity_id is None:
        return None

    state_path = HOTWORD_STATE_DIR / category / f"{entity_id}.json"
    if not state_path.exists():
        return None

    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_term_hints_from_state(interview_id: int | None = None) -> List[str]:
    """
    根据访谈 state 文件加载热词列表。

    参数:
        interview_id: 访谈主键 ID，用于读取 `data/hotword_state/interview/{id}.json`。

    返回:
        state 中所选热词包对应的合并热词列表。
    """
    data = _load_state_json("interview", interview_id)
    return load_term_hints_from_keys("interview", _extract_state_keys(data))


def load_correction_rules_from_state(interview_id: int | None = None) -> List[str]:
    """
    根据访谈 state 文件加载兜底纠错规则列表。

    参数:
        interview_id: 访谈主键 ID，用于读取 `data/hotword_state/interview/{id}.json`。

    返回:
        state 中所选热词包对应的合并纠错规则列表。
    """
    data = _load_state_json("interview", interview_id)
    return load_correction_rules_from_keys("interview", _extract_state_keys(data))


def save_hotword_state(category: str, entity_id: int, keys: list[str] | None) -> Path:
    """
    将热词选择结果写入本地 state 文件。

    参数:
        category: state 分类名称，例如 `interview`。
        entity_id: 实体 ID，例如访谈 ID。
        keys: 需要保存的热词包 code 列表；内部会自动去重并过滤空值。

    返回:
        实际写入的 state 文件路径。
    """
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


# ----------------------------------------------------------------------
# 合并策略
# ----------------------------------------------------------------------
def merge_term_hints(*groups: list[str], max_total: int = 120) -> List[str]:
    """
    将多组热词或规则合并成一个列表，并按顺序去重。

    参数:
        *groups: 任意数量的词条列表，通常分别对应主热词、纠错规则或兜底词库。
        max_total: 合并后的最大词条数量。大于 0 时会进行截断；小于等于 0 时不截断。

    返回:
        合并、去重并按上限截断后的词条列表。
    """
    merged: List[str] = []
    for group in groups:
        merged.extend(group or [])

    merged = _dedupe_keep_order(merged)
    if max_total > 0 and len(merged) > max_total:
        return merged[:max_total]
    return merged
