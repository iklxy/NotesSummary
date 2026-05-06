"""
@Date: 2026-04-29
@Author: lixinyang

问卷热词抽取、候选持久化与人工 review 结果保存工具。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from Model import ModelClient
from ModelTranscript import parse_json_payload
from Hotword import load_term_hints_from_file


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
MAX_MARKDOWN_CHARS = 20000


def _dedupe_keep_order(items: List[str]) -> List[str]:
    """
    按首次出现顺序去重。

    参数:
        items: 待去重的字符串列表。

    返回:
        去重后的字符串列表。
    """
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_term(value: Any) -> str:
    """
    归一化单个候选词。

    参数:
        value: 任意输入值。

    返回:
        去掉首尾空白后的字符串。
    """
    return str(value or "").strip()


def _normalize_confidence(value: Any) -> Optional[float]:
    """
    将置信度字段安全归一化为 0 到 1 的浮点数。

    参数:
        value: 模型返回的任意置信度值。

    返回:
        归一化后的浮点数；若无效则返回 None。
    """
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric


def _get_interview_backup_dir(project_id: int, interview_id: int) -> Path:
    """
    获取单个访谈在 data 目录下的备份目录。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        访谈备份目录路径。
    """
    return DATA_DIR / f"project_{project_id}" / f"interview_{interview_id}"


def _get_candidates_path(project_id: int, interview_id: int) -> Path:
    """
    获取问卷热词候选文件路径。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        候选热词 JSON 文件路径。
    """
    return _get_interview_backup_dir(project_id, interview_id) / "questionnaire_hotword_candidates.json"


def _get_reviewed_txt_path(project_id: int, interview_id: int) -> Path:
    """
    获取问卷热词 review 结果的文本文件路径。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        已审核热词 txt 文件路径。
    """
    return _get_interview_backup_dir(project_id, interview_id) / "questionnaire_hotwords.txt"


def _get_reviewed_json_path(project_id: int, interview_id: int) -> Path:
    """
    获取问卷热词 review 结果的 JSON 文件路径。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        已审核热词 JSON 文件路径。
    """
    return _get_interview_backup_dir(project_id, interview_id) / "questionnaire_hotwords.json"


def _extract_seed_terms(markdown_text: str) -> List[str]:
    """
    通过规则先抽取一批问卷热词种子，用于辅助 LLM 过滤和补全。

    参数:
        markdown_text: 问卷 Markdown 文本。

    返回:
        规则抽取得到的种子词列表。
    """
    text = markdown_text or ""
    patterns = [
        r"\b(?:[A-Z]{2,}[A-Z0-9/-]{0,}|[A-Z]+\d+[A-Z0-9/-]*)\b",
        r"\b(?:[A-Z]+(?:/[A-Z]+)+)\b",
        r"\b(?:[A-Z]+(?:-[A-Z0-9]+)+)\b",
        r"[\u4e00-\u9fffA-Za-z0-9]+(?:单抗|抑制剂|融合|突变|检测|试剂|方案|疗法|药|基因|标志物|靶点|分型|亚型|受体|蛋白|抗体)",
    ]
    raw_terms: List[str] = []
    for pattern in patterns:
        raw_terms.extend(re.findall(pattern, text))

    cleaned: List[str] = []
    stop_words = {
        "warm-up",
        "warm up",
        "warm-up问题",
        "访谈",
        "问题",
        "背景",
        "目的",
        "说明",
        "指导语",
        "谢谢",
        "您好",
        "请问",
        "您",
        "我们",
    }
    for item in raw_terms:
        term = _normalize_term(item)
        if not term:
            continue
        normalized = term.replace(" ", "")
        if len(normalized) < 2:
            continue
        if normalized.lower() in stop_words:
            continue
        cleaned.append(normalized)
    return _dedupe_keep_order(cleaned)


def _build_project_context_block(project_context: Optional[str]) -> str:
    """
    将项目背景整理成 prompt 区块。

    参数:
        project_context: 可选项目背景文本。

    返回:
        可直接拼接到 prompt 的文本块。
    """
    if not project_context:
        return ""
    cleaned = str(project_context).strip()
    if not cleaned:
        return ""
    return f"【项目背景】\n{cleaned}\n\n"


def extract_questionnaire_hotword_candidates(
    markdown_text: str,
    project_context: Optional[str] = None,
) -> Dict[str, Any]:
    """
    从问卷 Markdown 中抽取用于 ASR/纠错的候选热词。

    参数:
        markdown_text: 问卷 Markdown 文本。
        project_context: 可选项目背景文本，用于帮助模型理解领域。

    返回:
        包含 hotword_candidates 的字典，每个候选词条包含 term、normalized_term、reason、confidence。
    """
    markdown_text = (markdown_text or "")[:MAX_MARKDOWN_CHARS]
    seed_terms = _extract_seed_terms(markdown_text)
    seed_lines = "\n".join(f"- {item}" for item in seed_terms[:120]) or "- 无"
    project_context_block = _build_project_context_block(project_context)
    system_prompt = (
        "你现在是一位资深医学与医疗行业问卷热词抽取专家，熟悉肿瘤、伴随诊断、体外诊断、"
        "药物、检测、公司名、缩写和临床术语。"
    )
    user_prompt = (
        f"{project_context_block}"
        "你的任务是：阅读一份访谈问卷 Markdown，抽取适合用于 ASR 纠错与后续文本纠错的候选热词。\n\n"
        "抽取原则：\n"
        "1. 优先保留专业名词、疾病名、靶点名、药物名、检测名、公司名、缩写、基因位点、科室/病种相关术语。\n"
        "2. 明显的普通表达、泛化问题句、空话不要输出。\n"
        "3. 允许对明显错写或规范写法进行归一化，例如 PDL1 -> PD-L1。\n"
        "4. 输出结果尽量去重，按专业性和重要性排序。\n"
        "5. 不要输出背景描述，不要输出解释性长句，不要输出问卷原文。\n\n"
        "可参考的种子词（可补充、可纠正，但不要机械照抄）：\n"
        f"{seed_lines}\n\n"
        "【问卷 Markdown】\n"
        f"{markdown_text}\n\n"
        "输出要求：\n"
        "- 只输出合法 JSON。\n"
        "- 不要输出 markdown。\n"
        "- 不要输出多余文字。\n"
        "- 必须严格返回以下结构：\n\n"
        '{\n  "hotword_candidates": [\n'
        '    {\n      "term": "候选词原始写法",\n      "normalized_term": "标准写法",\n'
        '      "reason": "简短原因",\n      "confidence": 0.95\n    }\n  ]\n}\n\n'
        "请仅返回合法 JSON。"
    )
    client = ModelClient()
    raw_output = ""
    try:
        raw_output = client.generate_transcript(system_prompt, user_prompt)
    except Exception:
        raw_output = ""
    try:
        parsed = parse_json_payload(raw_output)
    except Exception:
        parsed = {}

    candidates_raw = parsed.get("hotword_candidates") if isinstance(parsed, dict) else []
    candidates: List[Dict[str, Any]] = []
    if isinstance(candidates_raw, list):
        for item in candidates_raw:
            if not isinstance(item, dict):
                continue
            term = _normalize_term(item.get("term") or item.get("normalized_term"))
            normalized_term = _normalize_term(item.get("normalized_term") or term)
            if not normalized_term:
                continue
            reason = _normalize_term(item.get("reason"))
            confidence = _normalize_confidence(item.get("confidence"))
            candidates.append(
                {
                    "term": term or normalized_term,
                    "normalized_term": normalized_term,
                    "reason": reason,
                    "confidence": confidence,
                }
            )

    if not candidates:
        for term in seed_terms:
            candidates.append(
                {
                    "term": term,
                    "normalized_term": term,
                    "reason": "seed_term",
                    "confidence": 0.6,
                }
            )

    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        normalized_term = _normalize_term(item.get("normalized_term"))
        if not normalized_term or normalized_term in seen:
            continue
        seen.add(normalized_term)
        deduped.append(
            {
                "term": _normalize_term(item.get("term") or normalized_term),
                "normalized_term": normalized_term,
                "reason": _normalize_term(item.get("reason")),
                "confidence": _normalize_confidence(item.get("confidence")),
            }
        )

    return {
        "hotword_candidates": deduped,
        "seed_terms": seed_terms,
        "raw_output": raw_output,
    }


def save_questionnaire_hotword_candidates(
    project_id: int,
    interview_id: int,
    payload: Dict[str, Any],
) -> Path:
    """
    将解析出的问卷热词候选写入访谈备份目录。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。
        payload: extract_questionnaire_hotword_candidates 的返回值。

    返回:
        候选热词 JSON 的写入路径。
    """
    target_path = _get_candidates_path(project_id, interview_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = {
        "project_id": project_id,
        "interview_id": interview_id,
        "hotword_candidates": payload.get("hotword_candidates") or [],
        "seed_terms": payload.get("seed_terms") or [],
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    target_path.write_text(json.dumps(safe_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target_path


def load_questionnaire_hotword_candidates(project_id: int, interview_id: int) -> Dict[str, Any]:
    """
    读取已经保存的问卷热词候选 JSON。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        候选热词 JSON；不存在时返回空结构。
    """
    target_path = _get_candidates_path(project_id, interview_id)
    if not target_path.exists():
        return {
            "project_id": project_id,
            "interview_id": interview_id,
            "hotword_candidates": [],
            "seed_terms": [],
        }
    try:
        data = json.loads(target_path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "project_id": project_id,
            "interview_id": interview_id,
            "hotword_candidates": [],
            "seed_terms": [],
        }
    if not isinstance(data, dict):
        return {
            "project_id": project_id,
            "interview_id": interview_id,
            "hotword_candidates": [],
            "seed_terms": [],
        }
    return data


def save_reviewed_questionnaire_hotwords(
    project_id: int,
    interview_id: int,
    hotwords: List[str],
) -> Path:
    """
    保存人工 review 后的问卷热词 txt 和 JSON。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。
        hotwords: review 后的最终热词列表。

    返回:
        txt 文件写入路径。
    """
    target_txt = _get_reviewed_txt_path(project_id, interview_id)
    target_json = _get_reviewed_json_path(project_id, interview_id)
    target_txt.parent.mkdir(parents=True, exist_ok=True)

    normalized = _dedupe_keep_order([_normalize_term(item) for item in hotwords])
    target_txt.write_text("\n".join(normalized), encoding="utf-8")
    target_json.write_text(
        json.dumps(
            {
                "project_id": project_id,
                "interview_id": interview_id,
                "hotwords": normalized,
                "updated_at": datetime.utcnow().isoformat() + "Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return target_txt


def load_reviewed_questionnaire_hotwords(project_id: int, interview_id: int) -> List[str]:
    """
    读取人工 review 后保存的问卷热词 txt。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        经过去重后的热词列表；不存在时返回空列表。
    """
    target_txt = _get_reviewed_txt_path(project_id, interview_id)
    if not target_txt.exists():
        return []
    return load_term_hints_from_file(str(target_txt))


def has_reviewed_questionnaire_hotwords(project_id: int, interview_id: int) -> bool:
    """
    判断指定访谈是否已经完成问卷热词 review。

    参数:
        project_id: 项目 ID。
        interview_id: 访谈 ID。

    返回:
        只要已审核热词文本文件存在，就视为 review 已完成。
    """
    return _get_reviewed_txt_path(project_id, interview_id).exists()
