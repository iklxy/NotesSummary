"@Date: 2026-04-24"
"@Author: lixinyang"

import json
from typing import Any, Callable, Dict, List, Optional


def build_interview_context_block(interview_context: Optional[Any]) -> str:
    """
    将访谈背景对象整理为统一的 prompt 区块。

    参数:
        interview_context: 访谈背景，可以是字典或纯文本字符串。

    返回:
        可直接拼接到 prompt 中的背景块；如果没有有效内容则返回空字符串。
    """
    if interview_context is None:
        return ""

    if isinstance(interview_context, dict):
        context_brief = str(interview_context.get("context_brief") or "").strip()
        key_terms = interview_context.get("key_terms") or []
        important_entities = interview_context.get("important_entities") or []
        lines: List[str] = ["【访谈背景】"]
        if context_brief:
            lines.append(f"背景说明：{context_brief}")
        if isinstance(key_terms, list) and key_terms:
            terms = ", ".join(str(item) for item in key_terms if str(item).strip())
            if terms:
                lines.append(f"高频术语：{terms}")
        if isinstance(important_entities, list) and important_entities:
            entities = ", ".join(str(item) for item in important_entities if str(item).strip())
            if entities:
                lines.append(f"关键实体：{entities}")
        if len(lines) == 1:
            return ""
        return "\n".join(lines) + "\n\n"

    cleaned = str(interview_context).strip()
    if not cleaned:
        return ""
    return f"【访谈背景】\n{cleaned}\n\n"


def build_correction_rules_block(correction_rules: Optional[List[str]]) -> str:
    """
    将兜底纠错规则列表格式化成 prompt 区块。

    参数:
        correction_rules: 规则列表，推荐格式为 `错误词 -> 正确词`。

    返回:
        可直接拼接到 prompt 中的规则块；如果没有有效规则则返回空字符串。
    """
    if not correction_rules:
        return ""

    normalized_rules = [str(item or "").strip() for item in correction_rules if str(item or "").strip()]
    if not normalized_rules:
        return ""

    lines = ["【兜底纠错文本】"]
    for rule in normalized_rules:
        lines.append(rule if "->" in rule else f"- {rule}")
    return "\n".join(lines) + "\n\n"


def strip_code_fences(text: str) -> str:
    """
    去掉模型输出最外层的 markdown code fence。

    参数:
        text: 模型原始输出文本。

    返回:
        去除首尾 code fence 后的文本。
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner_lines = [line for line in lines if not line.strip().startswith("```")]
        return "\n".join(inner_lines).strip()
    return stripped


def parse_json_payload(content: str) -> Any:
    """
    尽量从模型输出中解析 JSON 负载。

    参数:
        content: 模型返回的原始字符串。

    返回:
        JSON 解析结果，可能是字典或列表。
    """
    content_stripped = strip_code_fences(content)
    try:
        return json.loads(content_stripped)
    except json.JSONDecodeError:
        start_obj = content_stripped.find("{")
        end_obj = content_stripped.rfind("}")
        if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            try:
                return json.loads(content_stripped[start_obj : end_obj + 1])
            except json.JSONDecodeError:
                pass

        start_arr = content_stripped.find("[")
        end_arr = content_stripped.rfind("]")
        if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
            return json.loads(content_stripped[start_arr : end_arr + 1])

        raise


def coerce_int(value: Any) -> Optional[int]:
    """
    将输入安全转为整数。

    参数:
        value: 任意输入值。

    返回:
        转换成功时返回整数，否则返回 `None`。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def coerce_confidence(value: Any) -> Optional[float]:
    """
    将输入安全转为 0 到 1 之间的置信度浮点数。

    参数:
        value: 任意输入值。

    返回:
        转换成功时返回 0 到 1 之间的小数，否则返回 `None`。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return confidence


def normalize_transcript_records(
    transcript: List[Dict[str, Any]],
    text_field: str,
) -> List[Dict[str, Any]]:
    """
    将输入 transcript 统一归一化成内部处理格式。

    参数:
        transcript: 原始逐段记录列表。
        text_field: 本轮处理应读取的文本字段，例如 `text` 或 `corrected_text`。

    返回:
        归一化后的 transcript 列表，每条记录都包含 uid、speaker_id、start_time、end_time、text、confidence。
    """
    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(transcript, start=1):
        if not isinstance(item, dict):
            continue
        uid = str(item.get("uid") or item.get("id") or f"u{idx:04d}")
        speaker_id = str(item.get("speaker_id") or item.get("speaker") or "")
        start_time = item.get("start_time")
        if start_time is None:
            start_time = item.get("start_ms")
        end_time = item.get("end_time")
        if end_time is None:
            end_time = item.get("end_ms")
        normalized.append(
            {
                "uid": uid,
                "speaker_id": speaker_id,
                "speaker_role": str(item.get("speaker_role") or ""),
                "start_time": coerce_int(start_time),
                "end_time": coerce_int(end_time),
                "text": str(item.get(text_field) or item.get("text") or item.get("speaker_content") or ""),
                "confidence": coerce_confidence(item.get("confidence")),
            }
        )
    return normalized


def build_transcript_prompt_block(transcript: List[Dict[str, Any]]) -> str:
    """
    将 transcript 记录列表格式化为 prompt 中可读的 JSON 文本。

    参数:
        transcript: 已归一化的逐段记录列表。

    返回:
        缩进格式化后的 JSON 字符串。
    """
    return json.dumps({"transcript": transcript}, ensure_ascii=False, indent=2)


def extract_transcript_items(payload: Any) -> List[Dict[str, Any]]:
    """
    从模型输出 payload 中提取 transcript 列表。

    参数:
        payload: parse_json_payload 返回的对象。

    返回:
        transcript 项列表；如果结构不匹配则返回空列表。
    """
    transcript = payload.get("transcript") if isinstance(payload, dict) else payload
    if not isinstance(transcript, list):
        return []
    return [item for item in transcript if isinstance(item, dict)]


def merge_transcript_output(
    input_records: List[Dict[str, Any]],
    output_records: List[Dict[str, Any]],
    output_text_field: str,
    preserve_raw_fields: bool = False,
) -> List[Dict[str, Any]]:
    """
    将模型输出与原始输入按 uid 合并。

    参数:
        input_records: 归一化后的输入记录。
        output_records: 模型输出的 transcript 记录。
        output_text_field: 本轮处理关注的输出字段，例如 `corrected_text` 或 `clean_text`。
        preserve_raw_fields: 是否在结果中保留输入侧原始文本。

    返回:
        已合并的记录列表。
    """
    output_by_uid: Dict[str, Dict[str, Any]] = {}
    for item in output_records:
        uid = str(item.get("uid") or "").strip()
        if uid:
            output_by_uid[uid] = item

    merged: List[Dict[str, Any]] = []
    for idx, original in enumerate(input_records):
        uid = str(original.get("uid") or original.get("id") or f"u{idx+1:04d}")
        candidate = output_by_uid.get(uid)
        if candidate is None and idx < len(output_records):
            candidate = output_records[idx]
        if not isinstance(candidate, dict):
            candidate = {}

        merged_item: Dict[str, Any] = {
            "uid": uid,
            "speaker_id": str(original.get("speaker_id") or ""),
            "speaker_role": str(original.get("speaker_role") or ""),
            "start_time": coerce_int(original.get("start_time")),
            "end_time": coerce_int(original.get("end_time")),
        }
        if preserve_raw_fields:
            merged_item["speaker_content"] = str(original.get("text") or original.get("speaker_content") or "")
        confidence = coerce_confidence(candidate.get("confidence"))
        if confidence is None:
            confidence = coerce_confidence(original.get("confidence"))
        merged_item["confidence"] = confidence if confidence is not None else 0.0

        output_text = candidate.get(output_text_field)
        if not isinstance(output_text, str) or not output_text.strip():
            output_text = candidate.get("text")
        if not isinstance(output_text, str) or not output_text.strip():
            output_text = str(original.get("text") or original.get("speaker_content") or "")

        merged_item[output_text_field] = output_text
        merged_item["text"] = output_text
        merged_item["corrections"] = candidate.get("corrections") if isinstance(candidate.get("corrections"), list) else []
        merged_item["uncertain_terms"] = (
            candidate.get("uncertain_terms") if isinstance(candidate.get("uncertain_terms"), list) else []
        )
        if "corrected_text" in candidate and isinstance(candidate.get("corrected_text"), str):
            merged_item["corrected_text"] = candidate["corrected_text"]
        if "clean_text" in candidate and isinstance(candidate.get("clean_text"), str):
            merged_item["clean_text"] = candidate["clean_text"]
        merged.append(merged_item)
    return merged


def correct_transcript_batch(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    transcript: List[Dict[str, Any]],
    term_hints: Optional[List[str]] = None,
    interview_context: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    对整篇 transcript 执行主纠错。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        transcript: 输入 transcript 记录列表。
        term_hints: 专业热词提示列表。
        interview_context: 访谈背景摘要，可为字典或字符串。

    返回:
        带 `corrected_text`、`corrections`、`uncertain_terms` 的记录列表。
    """
    normalized = normalize_transcript_records(transcript, text_field="text")
    if not normalized:
        return []

    term_hint_text = f"专业术语提示: {', '.join(term_hints)}\n\n" if term_hints else ""
    interview_context_text = build_interview_context_block(interview_context)
    transcript_block = build_transcript_prompt_block(normalized)
    system_prompt = (
        "你现在是一位拥有 15 年经验的医学与医疗行业访谈转录校对专家，"
        "熟悉实体瘤、靶向药、免疫治疗、分子检测、体外诊断、临床指标、公司名称和行业术语。"
    )
    user_prompt = (
        f"{project_context_block}{interview_context_text}{term_hint_text}"
        "你的任务是：结合【全文上下文】和【待校正文档】，对整篇访谈逐条进行高保真纠错。\n\n"
        "核心目标：\n"
        "- 只修正明确可判定的 ASR 错词、术语错写、药名错写、基因位点错写、公司名错写、检测名错写、数值和单位错误。\n"
        "- 不做总结，不做润色，不改写表达，不删减信息，不合并内容，不改变说话顺序。\n\n"
        "严格规则：\n"
        "1. 必须保留原始信息顺序、说话顺序和原有语义。\n"
        "2. 只允许修正高置信度错误。\n"
        "3. 如果某个词或术语无法明确判断，不要猜测，保留原文。\n"
        "4. 不要为了“更专业”而擅自改写没有把握的内容。\n"
        "5. 不要把口语改成书面语，这一步只做纠错，不做清洗。\n"
        "6. 保留所有数字、单位、时间、剂量、百分比、分数、缩写格式。\n"
        "7. 药物名、基因位点、检测名、抗体克隆号、公司名优先按行业通用写法统一。\n"
        "8. 如果全文上下文能明确支持某个纠错结果，可以据此修正待校正文段中的同音错词。\n"
        "9. 绝不输出解释、分析、备注或修正原因。\n"
        "10. JSON字段中的confidence表示你对这一条summary准确率的置信度。\n\n"
        "特别注意：\n"
        "- 药物名要区分通用名和商品名，例如：帕博利珠单抗 / 可瑞达，奥希替尼 / 泰瑞沙。\n"
        "- 基因和突变位点必须保持标准写法，例如：EGFR exon 19 del、T790M、ALK fusion。\n"
        "- 临床指标必须保留原始数值和单位，例如：CEA、CA19-9、PD-L1 TPS。\n"
        "- 公司名称、检测平台、抗体克隆号、试剂名、医院名、项目名要尽量纠正为行业常用写法。\n"
        "- 对于“化疗 / 画了”“分子检测 / 纷子检测”这类明显同音错词，可以直接修正。\n\n"
        "输出要求：\n"
        "- 只输出合法 JSON。\n"
        "- 不要输出 markdown。\n"
        "- 不要输出多余文字。\n"
        "- 不要输出前缀、标题、解释。\n"
        "- 参考JSON格式如下，必须严格返回以下结构：\n\n"
        '{\n  "transcript": [\n    {\n      "uid": "u001",\n      "speaker_id": "speaker1",\n'
        '      "start_time": 12340,\n      "end_time": 15800,\n      "corrected_text": "纠错后的正文",\n'
        '      "confidence": 0.95,\n      "corrections": [{"original": "原词", "corrected": "修正词"}],\n      "uncertain_terms": []\n    }\n  ]\n}\n\n'
        "【待校正文档】\n"
        f"{transcript_block}\n\n"
        "请仅返回合法 JSON。"
    )
    content = generate_fn(system_prompt, user_prompt)
    try:
        parsed = parse_json_payload(content)
    except json.JSONDecodeError:
        parsed = {}
    output_records = extract_transcript_items(parsed)
    if not output_records:
        return [
            {
                "uid": item["uid"],
                "speaker_id": item["speaker_id"],
                "start_time": item["start_time"],
                "end_time": item["end_time"],
                "corrected_text": item["text"],
                "text": item["text"],
                "confidence": item.get("confidence") if item.get("confidence") is not None else 0.0,
                "corrections": [],
                "uncertain_terms": [],
            }
            for item in normalized
        ]
    merged = merge_transcript_output(normalized, output_records, output_text_field="corrected_text")
    for item in merged:
        item["corrected_text"] = item.get("corrected_text") or item.get("text", "")
        item["text"] = item["corrected_text"]
    return merged


def apply_correction_fallback_batch(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    transcript: List[Dict[str, Any]],
    correction_rules: Optional[List[str]] = None,
    term_hints: Optional[List[str]] = None,
    interview_context: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    在主纠错结果上执行兜底纠错。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        transcript: 输入 transcript 记录列表，通常来自主纠错结果。
        correction_rules: 兜底纠错规则列表。
        term_hints: 热词提示列表。
        interview_context: 访谈背景摘要。

    返回:
        带 `corrected_text`、`corrections`、`uncertain_terms` 的记录列表。
    """
    normalized = normalize_transcript_records(transcript, text_field="corrected_text")
    if not normalized:
        return []

    normalized_rules = [str(item).strip() for item in (correction_rules or []) if str(item).strip()]
    if not normalized_rules:
        return [
            {
                "uid": item["uid"],
                "speaker_id": item["speaker_id"],
                "start_time": item["start_time"],
                "end_time": item["end_time"],
                "corrected_text": item["text"],
                "text": item["text"],
                "corrections": [],
                "uncertain_terms": [],
            }
            for item in normalized
        ]

    term_hint_text = f"专业术语提示: {', '.join(term_hints)}\n\n" if term_hints else ""
    interview_context_text = build_interview_context_block(interview_context)
    correction_rules_text = build_correction_rules_block(normalized_rules)
    transcript_block = build_transcript_prompt_block(normalized)
    system_prompt = (
        "你现在是一位拥有 15 年经验的医学与医疗行业访谈转录兜底纠错专家，"
        "熟悉实体瘤、靶向药、免疫治疗、分子检测、体外诊断、临床指标、公司名称和行业术语。"
    )
    user_prompt = (
        f"{project_context_block}{interview_context_text}{term_hint_text}{correction_rules_text}"
        "你的任务是：在【主纠错结果】基础上，再依据【兜底纠错文本】做一次收敛修正。\n\n"
        "核心目标：\n"
        "- 优先把【兜底纠错文本】中的错误词纠正为对应的正确词。\n"
        "- 只修正仍然明确可判定的残余错词，不做总结，不做润色，不改写表达，不删减信息。\n"
        "- 不要调整说话顺序，不要改变原有事实，不要输出解释。\n\n"
        "严格规则：\n"
        "1. 【兜底纠错文本】中的映射是高优先级参考，能明确命中时优先执行。\n"
        "2. 如果某个词无法明确判断是否命中，不要猜测，保留原文。\n"
        "3. 只允许做词级或短语级替换，不要扩写，不要压缩。\n"
        "4. 不要把口语改成书面语，这一步不承担清洗职责。\n"
        "5. 保留所有数字、单位、时间、剂量、百分比、分数、缩写格式。\n"
        "6. 药物名、基因位点、检测名、抗体克隆号、公司名优先按行业通用写法统一。\n"
        "7. 如果上下文与兜底规则都无法明确支持修改，直接保留原文。\n"
        "8. 绝不输出解释、分析、备注或修正原因。\n"
        "9. JSON字段中的confidence表示你对这一条summary准确率的置信度。\n\n"
        "输出要求：\n"
        "- 只输出合法 JSON。\n"
        "- 不要输出 markdown。\n"
        "- 不要输出多余文字。\n"
        "- 不要输出前缀、标题、解释。\n"
        "- 参考JSON格式如下，必须严格返回以下结构：\n\n"
        '{\n  "transcript": [\n    {\n      "uid": "u001",\n      "speaker_id": "speaker1",\n'
        '      "start_time": 12340,\n      "end_time": 15800,\n      "corrected_text": "兜底纠错后的正文",\n'
        '      "confidence": 0.95,\n      "corrections": [{"original": "原词", "corrected": "修正词"}],\n      "uncertain_terms": []\n    }\n  ]\n}\n\n'
        "【主纠错结果】\n"
        f"{transcript_block}\n\n"
        "请仅返回合法 JSON。"
    )
    content = generate_fn(system_prompt, user_prompt)
    try:
        parsed = parse_json_payload(content)
    except json.JSONDecodeError:
        parsed = {}
    output_records = extract_transcript_items(parsed)
    if not output_records:
        return [
            {
                "uid": item["uid"],
                "speaker_id": item["speaker_id"],
                "start_time": item["start_time"],
                "end_time": item["end_time"],
                "corrected_text": item["text"],
                "text": item["text"],
                "confidence": item.get("confidence") if item.get("confidence") is not None else 0.0,
                "corrections": [],
                "uncertain_terms": [],
            }
            for item in normalized
        ]
    merged = merge_transcript_output(normalized, output_records, output_text_field="corrected_text")
    for item in merged:
        item["corrected_text"] = item.get("corrected_text") or item.get("text", "")
        item["text"] = item["corrected_text"]
    return merged


def clean_transcript_batch(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    transcript: List[Dict[str, Any]],
    term_hints: Optional[List[str]] = None,
    interview_context: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    对纠错后的 transcript 执行轻度清洗。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        transcript: 输入 transcript 记录列表，通常来自纠错结果。
        term_hints: 热词提示列表。
        interview_context: 访谈背景摘要。

    返回:
        带 `clean_text` 的记录列表。
    """
    normalized = normalize_transcript_records(transcript, text_field="corrected_text")
    if not normalized:
        return []

    term_hint_text = f"专业术语提示: {', '.join(term_hints)}\n\n" if term_hints else ""
    interview_context_text = build_interview_context_block(interview_context)
    transcript_block = build_transcript_prompt_block(normalized)
    system_prompt = (
        "你现在是一位拥有 15 年经验的医学与医疗行业访谈文本清洗专家，"
        "熟悉医学、药学、体外诊断、肿瘤访谈、市场调研访谈中的常见表达方式。"
    )
    user_prompt = (
        f"{project_context_block}{interview_context_text}{term_hint_text}"
        "你的任务是：对【待清洗文本】进行轻度清洗整理，使其更适合后续总结与分析，但必须保留原始事实、术语和信息粒度。\n\n"
        "核心目标：\n"
        "- 去除明显口头禅、重复赘词、无意义停顿和冗余语气。\n"
        "- 整理断裂句子、碎片化表达和明显不通顺的口语表达。\n"
        "- 保留原始信息顺序、说话顺序和事实内容。\n"
        "- 不做总结，不做扩写，不做改写，不做术语纠错。\n\n"
        "严格规则：\n"
        "1. 只能做清洗整理，不得重新纠正专业术语、药名、基因位点、公司名、检测名、数值和单位。\n"
        "2. 如果文本中已经出现纠错后的专业术语，不得再次改写这些术语。\n"
        "3. 不要把多句内容强行压缩成一句，也不要把一句话拆得过碎。\n"
        "4. 不要补充原文没有的信息，不要推断，不要发挥。\n"
        "5. 不要改变说话顺序，不要改变原意，不要改变结论。\n"
        "6. 可以删除明显的口头禅、重复词、无意义停顿词，但不能删除有实际语义作用的连接词。\n"
        "7. 对于不确定是否应删除的内容，优先保留。\n"
        "8. 只输出清洗后的正文，不要输出解释、备注、分析。\n\n"
        "9. JSON字段中的confidence表示你对这一条清洗结果准确率的置信度。\n"
        "输出要求：\n"
        "- 只输出合法 JSON。\n"
        "- 不要输出 markdown。\n"
        "- 不要输出多余文字。\n"
        "- 不要输出前缀、标题、解释。\n"
        "- 参考JSON格式如下，必须严格返回以下结构：\n\n"
        '{\n  "transcript": [\n    {\n      "uid": "u001",\n      "speaker_id": "speaker1",\n'
        '      "start_time": 12340,\n      "end_time": 15800,\n      "clean_text": "清洗后的正文",\n'
        '      "confidence": 0.95\n    }\n  ]\n}\n\n'
        "【待清洗文本】\n"
        f"{transcript_block}\n\n"
        "请仅返回合法 JSON。"
    )
    content = generate_fn(system_prompt, user_prompt)
    try:
        parsed = parse_json_payload(content)
    except json.JSONDecodeError:
        parsed = {}
    output_records = extract_transcript_items(parsed)
    if not output_records:
        return [
            {
                "uid": item["uid"],
                "speaker_id": item["speaker_id"],
                "start_time": item["start_time"],
                "end_time": item["end_time"],
                "corrected_text": item["text"],
                "clean_text": item["text"],
                "text": item["text"],
                "confidence": item.get("confidence") if item.get("confidence") is not None else 0.0,
                "corrections": item.get("corrections", []),
                "uncertain_terms": item.get("uncertain_terms", []),
            }
            for item in normalized
        ]
    merged = merge_transcript_output(normalized, output_records, output_text_field="clean_text")
    for idx, item in enumerate(merged):
        source = transcript[idx] if idx < len(transcript) and isinstance(transcript[idx], dict) else {}
        item["corrected_text"] = normalized[idx].get("text", "") if idx < len(normalized) else ""
        if not item.get("corrections"):
            item["corrections"] = source.get("corrections", [])
        if not item.get("uncertain_terms"):
            item["uncertain_terms"] = source.get("uncertain_terms", [])
        if item.get("confidence") is None:
            item["confidence"] = source.get("confidence")
        if item.get("confidence") is None:
            item["confidence"] = 0.0
        item["clean_text"] = item.get("clean_text") or item.get("text", "")
        item["text"] = item["clean_text"]
    return merged


def clean_speaker_utterance(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    speaker_text: str,
    speaker_role: Optional[str] = None,
    term_hints: Optional[List[str]] = None,
    correction_rules: Optional[List[str]] = None,
    interview_context: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    兼容旧接口的单条处理包装器。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        speaker_text: 单条转录文本。
        speaker_role: 说话人角色标签。
        term_hints: 热词提示列表。
        correction_rules: 兜底纠错规则列表。
        interview_context: 访谈背景摘要。

    返回:
        与旧接口兼容的单条结果字典。
    """
    transcript = [{
        "uid": "u001",
        "speaker_id": speaker_role or "speaker",
        "start_time": 0,
        "end_time": 0,
        "text": speaker_text,
    }]
    corrected = correct_transcript_batch(
        generate_fn=generate_fn,
        project_context_block=project_context_block,
        transcript=transcript,
        term_hints=term_hints,
        interview_context=interview_context,
    )
    fallback_corrected = apply_correction_fallback_batch(
        generate_fn=generate_fn,
        project_context_block=project_context_block,
        transcript=corrected,
        correction_rules=correction_rules,
        term_hints=term_hints,
        interview_context=interview_context,
    )
    first = fallback_corrected[0] if fallback_corrected else {}
    return {
        "clean_text": first.get("corrected_text", speaker_text),
        "term_corrections": first.get("corrections", []),
        "uncertain_terms": first.get("uncertain_terms", []),
        "corrected_text": first.get("corrected_text", speaker_text),
        "confidence": first.get("confidence") if first.get("confidence") is not None else 0.0,
    }


def extract_interview_context(
    generate_fn: Callable[[str, str], str],
    project_context_block: str,
    full_text: str,
    term_hints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    从整篇 ASR 全文中提炼纠错所需的访谈背景。

    参数:
        generate_fn: 实际执行 LLM 调用的函数。
        project_context_block: 已格式化好的项目背景块。
        full_text: ASR 全文文本。
        term_hints: 热词提示列表。

    返回:
        包含领域、背景说明、高频术语和关键实体的字典。
    """
    full_text = str(full_text or "").strip()
    if not full_text:
        return {
            "domain": "未知",
            "subdomain": "未知",
            "interview_type": "未知",
            "context_brief": "",
            "key_terms": [],
            "important_entities": [],
            "speaker_roles": {},
        }

    term_hint_text = f"专业术语提示: {', '.join(term_hints)}\n\n" if term_hints else ""
    system_prompt = (
        "你现在是一位资深医学与医疗行业访谈背景提炼专家，熟悉肿瘤、体外诊断、分子检测、市场调研、医院准入、竞品分析等访谈场景。"
    )
    user_prompt = (
        f"{project_context_block}{term_hint_text}"
        "你的任务是：阅读整篇访谈全文，提炼一段供后续“纠错 + 清洗”流程使用的访谈背景说明。\n\n"
        "核心目标：\n"
        "- 只提炼背景，不做总结报告。\n"
        "- 只提炼有助于后续术语纠错、语境理解和清洗整理的信息。\n"
        "- 必须严格基于原始文本，不要编造，不要补充未提到的业务事实。\n"
        "- 如果某些信息无法明确判断，宁可不写，不要猜测。\n\n"
        "你需要重点识别以下内容：\n"
        "1. 访谈所属的大领域或业务方向。\n"
        "2. 访谈主题或核心关注点。\n"
        "3. 文本中反复出现的高频专有词、药名、检测名、公司名、靶点名、缩写。\n"
        "4. 说话人之间大致的角色关系。\n"
        "5. 这场访谈的语境特征。\n\n"
        "输出要求：\n"
        "- 只输出合法 JSON。\n"
        "- 不要输出 markdown。\n"
        "- 不要输出多余文字。\n"
        "- 不要输出前缀、标题、解释。\n"
        "- 必须严格返回以下结构：\n\n"
        '{\n  "domain": "大领域",\n  "subdomain": "细分领域或未知",\n  "interview_type": "访谈类型",\n'
        '  "context_brief": "1 到 3 句背景说明",\n  "key_terms": ["术语1"],\n  "important_entities": ["实体1"],\n'
        '  "speaker_roles": {"speaker1": "提问方", "speaker2": "回答方"}\n}\n\n'
        "【全文转录】\n"
        f"{full_text}\n\n"
        "请仅返回合法 JSON。"
    )
    content = generate_fn(system_prompt, user_prompt)
    try:
        parsed = parse_json_payload(content)
    except json.JSONDecodeError:
        return {
            "domain": "未知",
            "subdomain": "未知",
            "interview_type": "未知",
            "context_brief": full_text[:500],
            "key_terms": [],
            "important_entities": [],
            "speaker_roles": {},
            "llm_raw_output": content,
        }
    if not isinstance(parsed, dict):
        return {
            "domain": "未知",
            "subdomain": "未知",
            "interview_type": "未知",
            "context_brief": full_text[:500],
            "key_terms": [],
            "important_entities": [],
            "speaker_roles": {},
            "llm_raw_output": content,
        }
    parsed.setdefault("domain", "未知")
    parsed.setdefault("subdomain", "未知")
    parsed.setdefault("interview_type", "未知")
    parsed.setdefault("context_brief", "")
    parsed.setdefault("key_terms", [])
    parsed.setdefault("important_entities", [])
    parsed.setdefault("speaker_roles", {})
    return parsed
