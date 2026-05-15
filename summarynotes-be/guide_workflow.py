"""
@Date: 2026-05-11
@Author: lixinyang

项目指南学习任务。

负责把创建项目时上传的 PDF 指南做文本抽取、OCR 兜底和学习总结，
最终把结构化总结写回 `bh_project_guide`，供后续访谈和智能纪要复用。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET
import zipfile
import traceback
from typing import Any, Dict, Iterable, List, Optional, Sequence

from InterviewLogger import log_project
from LLMProviders import build_provider
from config import config
from db import fetch_project_by_id, fetch_project_guide_by_project_id, update_project, update_project_guide

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    fitz = None  # type: ignore


_CHUNK_MAX_CHARS = 12000
_OCR_TEXT_THRESHOLD = 30
_CORE_PROBLEM_MAX_CHARS = 400


def _get_data_root() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def _resolve_guide_path(raw_path: str | None) -> Optional[Path]:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        path = _get_data_root() / path
    return path


def _load_guide_files_manifest(raw_value: Any, manifest_path: Path | None = None) -> List[Dict[str, Any]]:
    if isinstance(raw_value, list):
        files = [item for item in raw_value if isinstance(item, dict)]
        if files:
            return files
    if isinstance(raw_value, dict):
        candidate = raw_value.get("files")
        if isinstance(candidate, list):
            files = [item for item in candidate if isinstance(item, dict)]
            if files:
                return files
    if manifest_path and manifest_path.exists() and manifest_path.is_file():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            candidate = payload.get("files")
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    return []


def _normalize_guide_file_item(item: Dict[str, Any], fallback_index: int) -> Dict[str, Any]:
    index = int(item.get("index") or fallback_index)
    original_name = str(item.get("original_name") or item.get("guide_file_name") or f"guide_{index}").strip()
    stored_path = str(item.get("stored_path") or item.get("guide_file_path") or "").strip()
    file_type = str(item.get("file_type") or "").strip().lower()
    if not file_type and original_name:
        file_type = Path(original_name).suffix.lower().lstrip(".")
    if file_type not in {"pdf", "docx", "md", "xlsx"}:
        file_type = "unknown"
    return {
        "index": index,
        "original_name": original_name,
        "stored_path": stored_path,
        "file_type": file_type,
        "status": str(item.get("status") or "queued"),
        "error_message": item.get("error_message"),
        "extracted_text": item.get("extracted_text"),
        "summary_text": item.get("summary_text"),
        "generated_at": item.get("generated_at"),
    }


def _normalize_guide_files(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        normalized.append(_normalize_guide_file_item(item, index))
    normalized.sort(key=lambda row: (row.get("index") or 0, row.get("original_name") or ""))
    return normalized


def _build_guide_display_name(file_names: List[str]) -> str:
    if not file_names:
        return "项目指南"
    if len(file_names) == 1:
        return file_names[0]
    return f"{len(file_names)} 个指南文件"


def _compact_text_for_summary(text: str) -> str:
    return _normalize_text(text)


def _normalize_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _split_text_chunks(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> List[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    if not paragraphs:
        return [normalized]

    chunks: List[str] = []
    buffer: List[str] = []
    buffer_length = 0

    def flush() -> None:
        nonlocal buffer_length
        if not buffer:
            return
        chunks.append("\n\n".join(buffer).strip())
        buffer.clear()
        buffer_length = 0

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            flush()
            start = 0
            while start < len(paragraph):
                chunks.append(paragraph[start : start + max_chars].strip())
                start += max_chars
            continue

        next_length = buffer_length + len(paragraph) + (2 if buffer else 0)
        if buffer and next_length > max_chars:
            flush()
        buffer.append(paragraph)
        buffer_length += len(paragraph) + (2 if len(buffer) > 1 else 0)

    flush()
    return [chunk for chunk in chunks if chunk.strip()]


def _build_guide_chunk_prompt(chunk_index: int, total_chunks: int) -> tuple[str, str]:
    system_prompt = (
        "你是一名专业的项目指南分析助手，擅长把 PDF 指南内容提炼成可供后续访谈和智能纪要使用的项目背景资料。"
    )
    user_prompt = f"""
请对下面这份项目指南的第 {chunk_index + 1}/{total_chunks} 个片段进行提炼，输出可用于后续总总结的事实要点。

要求：
1. 只提炼原文明确提到的信息，不要加入外部知识或主观推断。
2. 保留关键术语、疾病/适应症、诊疗路径、研究目标、用药/器械/流程约束、注意事项。
3. 语言尽量简洁但完整，使用 Markdown 分段。
4. 不要输出标题以外的额外解释。

【片段内容】
{chunk_index + 1}/{total_chunks}:
""".strip()
    return system_prompt, user_prompt


def _build_guide_summary_prompt(chunk_count: int) -> tuple[str, str]:
    system_prompt = (
        "你是一名专业的项目指南学习总结助手，擅长把多段指南提炼成面向后续访谈和智能纪要的项目背景总结。"
    )
    user_prompt = f"""
请基于下面 {chunk_count} 段项目指南提炼结果，生成一份完整、详细、可供后续访谈和智能纪要直接使用的学习总结。

要求：
1. 只使用材料中明确提到的信息，不要补充外部知识、行业常识或主观推断。
2. 总结应覆盖项目背景、适用人群/疾病/领域、关键诊疗路径、核心关注点、术语边界、访谈时的注意事项。
3. 输出 Markdown，建议使用若干层级清晰的小标题。
4. 尽量写得详细，便于后续作为项目背景输入模型。
5. 不要输出“根据上述内容”等过程性话语，直接输出最终总结。

【各片段总结】
    """.strip()
    return system_prompt, user_prompt


def _build_core_problem_prompt(project_name: str, keywords: str, summary_text: str) -> tuple[str, str]:
    system_prompt = (
        "你是一名严谨的医疗项目背景摘要助手，擅长把项目指南学习总结压缩成可直接写入项目表的核心问题描述。"
    )
    user_prompt = f"""
请基于下面的项目指南学习总结，为项目生成一段可写入数据库 `core_problem` 字段的核心问题描述。

要求：
1. 只能基于给定总结，不要引入新信息或主观推断。
2. 只输出一段中文自然语言，长度严格控制在 400 个汉字。
3. 重点概括项目要解决的核心问题、适用场景和主要关注点。
4. 不要输出标题、列表、引号或额外解释，只输出正文。
5. 生成结果要适合直接在项目详情页展示。

【项目名称】
{project_name or "未命名项目"}

【项目关键词】
{keywords or "无"}

【项目指南学习总结】
{summary_text}
""".strip()
    return system_prompt, user_prompt


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", _normalize_text(text)).strip()


def _normalize_core_problem_text(text: str) -> str:
    compact = _compact_text(text)
    if not compact:
        return ""
    if len(compact) > _CORE_PROBLEM_MAX_CHARS:
        compact = compact[:_CORE_PROBLEM_MAX_CHARS].rstrip("，,；;。:：、 ")
    return compact


def _fallback_core_problem(summary_text: str) -> str:
    return _normalize_core_problem_text(summary_text)


def _generate_core_problem_from_summary(summary_text: str, project_name: str, keywords: str) -> str:
    provider, model_name = _build_provider()
    system_prompt, user_prompt = _build_core_problem_prompt(
        project_name=project_name,
        keywords=keywords,
        summary_text=summary_text,
    )
    return _normalize_core_problem_text(
        provider.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model_name=model_name,
        max_tokens=2048,
        temperature=0.2,
        )
    )


def _build_provider() -> tuple[Any, str]:
    provider_name = (config.NOTES_LLM_PROVIDER or config.LLM_PROVIDER or "openai").strip().lower() or "openai"
    api_key = config.NOTES_LLM_API_KEY or config.LLM_API_KEY
    base_url = config.NOTES_LLM_BASE_URL or config.LLM_BASE_URL
    model_name = config.NOTES_LLM_MODEL_NAME or config.LLM_MODEL_NAME
    if not api_key or not model_name:
        raise RuntimeError("NOTES_LLM_PROVIDER / NOTES_LLM_API_KEY / NOTES_LLM_MODEL_NAME 未正确配置")
    provider = build_provider(provider_name, api_key, base_url)
    return provider, model_name


def _ocr_page_text(
    provider: Any,
    model_name: str,
    page_image_bytes: bytes,
    page_index: int,
    total_pages: int,
) -> str:
    system_prompt = (
        "你是一名严格的 OCR 识别助手，只负责把图片中的可见文字逐字转写出来，不要总结、不要解释、不要改写。"
    )
    user_prompt = (
        f"请识别这张 PDF 页面图片中的全部可见文字。"
        f"这是第 {page_index + 1}/{total_pages} 页。"
        "请尽量保留标题、列表、表格结构和原始顺序，仅输出文本。"
    )
    try:
        return provider.generate_with_images(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_name=model_name,
            images=[{"mime_type": "image/png", "data": page_image_bytes}],
            max_tokens=130000,
            temperature=0.0,
        ).strip()
    except Exception as exc:
        raise RuntimeError(
            f"ocr page {page_index + 1} failed:\n"
            f"{traceback.format_exc()}"
        ) from exc


def _render_page_to_png(page: Any) -> bytes:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)  # type: ignore[attr-defined]
    return pixmap.tobytes("png")


def _extract_docx_text(docx_path: Path) -> str:
    if not zipfile.is_zipfile(docx_path):
        raise RuntimeError("docx file is not a valid zip archive")

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: List[str] = []
    with zipfile.ZipFile(docx_path) as docx_zip:
        try:
            document_xml = docx_zip.read("word/document.xml")
        except KeyError as exc:
            raise RuntimeError("docx missing word/document.xml") from exc
    root = ET.fromstring(document_xml)
    for paragraph in root.iter(f"{namespace}p"):
        parts: List[str] = []
        for node in paragraph.iter():
            if node.tag == f"{namespace}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{namespace}tab":
                parts.append("\t")
            elif node.tag in {f"{namespace}br", f"{namespace}cr"}:
                parts.append("\n")
        text = _normalize_text("".join(parts))
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs).strip()


def _extract_markdown_text(md_path: Path) -> str:
    try:
        return _normalize_text(md_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"read markdown failed: {exc}") from exc


def _xlsx_column_index(cell_ref: str) -> int:
    match = re.match(r"^([A-Za-z]+)", str(cell_ref or "").strip())
    if not match:
        return 0
    result = 0
    for ch in match.group(1).upper():
        if not ("A" <= ch <= "Z"):
            return 0
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


def _extract_xlsx_shared_strings(doc_zip: zipfile.ZipFile) -> List[str]:
    try:
        shared_strings_xml = doc_zip.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    try:
        root = ET.fromstring(shared_strings_xml)
    except Exception as exc:
        raise RuntimeError(f"parse xlsx shared strings failed: {exc}") from exc

    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared_strings: List[str] = []
    for si in root.iter(f"{namespace}si"):
        parts: List[str] = []
        for node in si.iter():
            if node.tag == f"{namespace}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{namespace}tab":
                parts.append("\t")
            elif node.tag in {f"{namespace}br", f"{namespace}cr"}:
                parts.append("\n")
        shared_strings.append(_normalize_text("".join(parts)))
    return shared_strings


def _extract_xlsx_sheet_entries(doc_zip: zipfile.ZipFile) -> List[tuple[str, str]]:
    workbook_namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_namespace = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    entries: List[tuple[str, str]] = []

    try:
        workbook_root = ET.fromstring(doc_zip.read("xl/workbook.xml"))
        rels_root = ET.fromstring(doc_zip.read("xl/_rels/workbook.xml.rels"))
        rel_map: Dict[str, str] = {}
        for rel in rels_root.iter(f"{rel_namespace}Relationship"):
            rel_id = str(rel.get("Id") or "").strip()
            target = str(rel.get("Target") or "").strip()
            if rel_id and target:
                rel_map[rel_id] = target

        for sheet in workbook_root.iter(f"{workbook_namespace}sheet"):
            sheet_name = str(sheet.get("name") or "Sheet").strip() or "Sheet"
            rel_id = str(sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") or "").strip()
            target = rel_map.get(rel_id, "")
            if not target:
                continue
            target_path = target.lstrip("/")
            if not target_path.startswith("xl/"):
                target_path = f"xl/{target_path.lstrip('./')}"
            entries.append((sheet_name, target_path))
    except Exception:
        entries = []

    if entries:
        return entries

    for info in sorted(doc_zip.infolist(), key=lambda item: item.filename):
        if info.filename.startswith("xl/worksheets/") and info.filename.endswith(".xml"):
            entries.append((Path(info.filename).stem, info.filename))
    return entries


def _extract_xlsx_cell_value(
    cell: ET.Element,
    shared_strings: List[str],
) -> str:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    cell_type = str(cell.get("t") or "").strip().lower()
    value_node = cell.find(f"{namespace}v")
    if cell_type == "s" and value_node is not None and value_node.text is not None:
        try:
            shared_index = int(value_node.text)
        except Exception:
            return _normalize_text(value_node.text)
        if 0 <= shared_index < len(shared_strings):
            return _normalize_text(shared_strings[shared_index])
        return ""
    if cell_type == "inlineStr":
        inline_node = cell.find(f"{namespace}is")
        if inline_node is None:
            return ""
        parts: List[str] = []
        for node in inline_node.iter():
            if node.tag == f"{namespace}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{namespace}tab":
                parts.append("\t")
            elif node.tag in {f"{namespace}br", f"{namespace}cr"}:
                parts.append("\n")
        return _normalize_text("".join(parts))
    if cell_type == "b":
        return "TRUE" if value_node is not None and str(value_node.text or "").strip() == "1" else "FALSE"
    if value_node is not None and value_node.text is not None:
        return _normalize_text(value_node.text)
    formula_node = cell.find(f"{namespace}f")
    if formula_node is not None and formula_node.text:
        return _normalize_text(formula_node.text)
    return ""


def _extract_xlsx_sheet_text(
    doc_zip: zipfile.ZipFile,
    sheet_path: str,
    sheet_name: str,
    shared_strings: List[str],
) -> str:
    try:
        sheet_xml = doc_zip.read(sheet_path)
    except KeyError as exc:
        raise RuntimeError(f"xlsx missing sheet file: {sheet_path}") from exc

    try:
        root = ET.fromstring(sheet_xml)
    except Exception as exc:
        raise RuntimeError(f"parse xlsx sheet failed: {sheet_name}: {exc}") from exc

    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    sheet_data = root.find(f"{namespace}sheetData")
    if sheet_data is None:
        return ""

    lines: List[str] = [f"## 工作表：{sheet_name}"]
    for row in sheet_data.iter(f"{namespace}row"):
        row_values: Dict[int, str] = {}
        max_index = 0
        for cell in row.iter(f"{namespace}c"):
            ref = str(cell.get("r") or "").strip()
            cell_index = _xlsx_column_index(ref)
            if cell_index <= 0:
                continue
            value = _extract_xlsx_cell_value(cell, shared_strings)
            if not value.strip():
                continue
            row_values[cell_index] = value.strip()
            max_index = max(max_index, cell_index)

        if max_index <= 0:
            continue

        ordered_values = [row_values.get(index, "") for index in range(1, max_index + 1)]
        row_text = "\t".join(ordered_values).strip()
        if row_text:
            lines.append(row_text)

    if len(lines) <= 1:
        return ""
    return "\n".join(lines).strip()


def _extract_xlsx_text(xlsx_path: Path) -> tuple[str, Dict[str, Any]]:
    if not zipfile.is_zipfile(xlsx_path):
        raise RuntimeError("xlsx file is not a valid zip archive")

    with zipfile.ZipFile(xlsx_path) as doc_zip:
        shared_strings = _extract_xlsx_shared_strings(doc_zip)
        sheet_entries = _extract_xlsx_sheet_entries(doc_zip)
        if not sheet_entries:
            raise RuntimeError("xlsx workbook contains no worksheets")

        sheet_texts: List[str] = []
        text_sheet_count = 0
        for sheet_name, sheet_path in sheet_entries:
            sheet_text = _extract_xlsx_sheet_text(doc_zip, sheet_path, sheet_name, shared_strings)
            if sheet_text:
                sheet_texts.append(sheet_text)
                text_sheet_count += 1

    extracted_text = "\n\n".join(sheet_texts).strip()
    if not extracted_text:
        raise RuntimeError("no text extracted from xlsx file")
    return extracted_text, {"sheet_count": len(sheet_entries), "text_sheet_count": text_sheet_count}


def _extract_guide_text_by_type(file_path: Path, file_type: str) -> tuple[str, Dict[str, Any]]:
    normalized_type = str(file_type or "").strip().lower()
    if normalized_type == "pdf":
        extracted_text, ocr_pages = _extract_pdf_text(file_path)
        return extracted_text, {"ocr_pages": ocr_pages}
    if normalized_type == "docx":
        return _extract_docx_text(file_path), {}
    if normalized_type == "md":
        return _extract_markdown_text(file_path), {}
    if normalized_type == "xlsx":
        return _extract_xlsx_text(file_path)
    raise RuntimeError(f"unsupported guide file type: {file_type}")


def _extract_pdf_text(pdf_path: Path) -> tuple[str, int]:
    if fitz is None:
        raise RuntimeError("pymupdf 未安装，无法解析 PDF 指南")

    provider, model_name = _build_provider()
    doc = fitz.open(str(pdf_path))  # type: ignore[operator]
    page_texts: List[str] = []
    ocr_pages = 0
    try:
        total_pages = int(doc.page_count or 0)
        for page_index in range(total_pages):
            page = doc.load_page(page_index)
            text = _normalize_text(page.get_text("text"))
            if len(text) >= _OCR_TEXT_THRESHOLD:
                page_texts.append(f"## 第 {page_index + 1} 页\n{text}")
                continue

            page_image = _render_page_to_png(page)
            ocr_text = _normalize_text(_ocr_page_text(provider, model_name, page_image, page_index, total_pages))
            if ocr_text:
                page_texts.append(f"## 第 {page_index + 1} 页\n{ocr_text}")
                ocr_pages += 1
            elif text:
                page_texts.append(f"## 第 {page_index + 1} 页\n{text}")
    finally:
        doc.close()

    return "\n\n".join(page_texts).strip(), ocr_pages


def _summarize_chunks(chunk_summaries: Sequence[str]) -> str:
    provider, model_name = _build_provider()
    if not chunk_summaries:
        return ""

    if len(chunk_summaries) == 1:
        return chunk_summaries[0].strip()

    system_prompt, user_prompt = _build_guide_summary_prompt(len(chunk_summaries))
    combined = "\n\n".join(
        f"【片段 {index + 1}】\n{_normalize_text(summary)}"
        for index, summary in enumerate(chunk_summaries)
        if _normalize_text(summary)
    )
    if not combined:
        return ""
    return provider.generate(
        system_prompt=system_prompt,
        user_prompt=f"{user_prompt}\n\n{combined}",
        model_name=model_name,
        max_tokens=130000,
        temperature=0.2,
    ).strip()


def _build_final_summary(extracted_text: str) -> str:
    chunks = _split_text_chunks(extracted_text)
    if not chunks:
        return ""

    provider, model_name = _build_provider()
    chunk_summaries: List[str] = []
    total_chunks = len(chunks)
    for index, chunk in enumerate(chunks):
        system_prompt, user_prompt = _build_guide_chunk_prompt(index, total_chunks)
        prompt = f"{user_prompt}\n{chunk}"
        summary = provider.generate(
            system_prompt=system_prompt,
            user_prompt=prompt,
            model_name=model_name,
            max_tokens=130000,
            temperature=0.2,
        ).strip()
        if summary:
            chunk_summaries.append(summary)

    if not chunk_summaries:
        return ""

    if len(chunk_summaries) == 1:
        return chunk_summaries[0].strip()

    return _summarize_chunks(chunk_summaries)


def process_project_guide(project_id: int) -> None:
    """
    处理项目的多份指南文件：抽取、并行解析、汇总并回写数据库。
    """
    log_project("GUIDE", project_id, "guide processing start")
    guide_row = fetch_project_guide_by_project_id(project_id)
    if not guide_row:
        log_project("GUIDE", project_id, "guide processing skipped: guide row not found")
        return

    guide_manifest_path = _resolve_guide_path(guide_row.get("guide_file_path"))
    guide_files = _load_guide_files_manifest(guide_row.get("guide_files_json"), guide_manifest_path)
    guide_files = _normalize_guide_files(guide_files)
    if not guide_files:
        fallback_name = str(guide_row.get("guide_file_name") or "").strip()
        fallback_path = _resolve_guide_path(guide_row.get("guide_file_path"))
        if fallback_name and fallback_path and fallback_path.exists():
            guide_files = [
                _normalize_guide_file_item(
                    {
                        "index": 1,
                        "original_name": fallback_name,
                        "stored_path": str(fallback_path.relative_to(_get_data_root())),
                        "file_type": str(guide_row.get("file_type") or "pdf").strip().lower() or "pdf",
                        "status": "queued",
                    },
                    1,
                )
            ]

    if not guide_files:
        update_project_guide(project_id, status="failed", error_message="no guide files found")
        log_project("GUIDE", project_id, "guide processing failed: no guide files found")
        return

    manifest_path = guide_manifest_path
    if manifest_path is None:
        manifest_path = _get_data_root() / f"project_{project_id}" / "guide" / "manifest.json"

    def _persist_manifest(
        *,
        status: str,
        extracted_text: str | None = None,
        summary_text: str | None = None,
        error_message: str | None = None,
        generated_at: str | None = None,
    ) -> None:
        display_names = [item.get("original_name") or f"guide_{idx}" for idx, item in enumerate(guide_files, start=1)]
        guide_file_name = _build_guide_display_name([str(name) for name in display_names])
        file_type = "mixed" if len(guide_files) > 1 else str(guide_files[0].get("file_type") or "pdf")
        manifest_payload = {
            "project_id": project_id,
            "file_count": len(guide_files),
            "files": guide_files,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        if manifest_path is not None:
            try:
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                log_project("GUIDE", project_id, f"write guide manifest failed error={exc}")
        update_project_guide(
            project_id,
            guide_file_name=guide_file_name,
            guide_file_path=str(manifest_path.relative_to(_get_data_root())) if manifest_path else None,
            file_type=file_type,
            guide_files_json=guide_files,
            extracted_text=extracted_text,
            summary_text=summary_text,
            status=status,
            error_message=error_message,
            generated_at=generated_at,
        )

    try:
        _persist_manifest(status="extracting", error_message=None)
        project_row = fetch_project_by_id(project_id)
        project_name = str(project_row.get("name") or "").strip() if project_row else ""
        project_keywords = str(project_row.get("keywords") or "").strip() if project_row else ""

        results_by_index: dict[int, Dict[str, Any]] = {}
        max_workers = min(4, len(guide_files)) or 1

        def _process_single_file(item: Dict[str, Any]) -> Dict[str, Any]:
            file_path = _resolve_guide_path(item.get("stored_path"))
            if file_path is None or not file_path.exists():
                raise RuntimeError("guide file not found")
            file_type = str(item.get("file_type") or "").strip().lower()
            extracted_text, meta = _extract_guide_text_by_type(file_path, file_type)
            normalized_text = _compact_text_for_summary(extracted_text)
            if not normalized_text:
                raise RuntimeError("no text extracted from guide file")
            return {
                **item,
                "status": "done",
                "error_message": None,
                "extracted_text": normalized_text,
                "summary_text": None,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "extract_meta": meta,
            }

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_process_single_file, item): item.get("index") or idx for idx, item in enumerate(guide_files, start=1)}
            for future in as_completed(future_map):
                index = int(future_map[future])
                try:
                    processed_item = future.result()
                except Exception as exc:
                    source_item = next((item for item in guide_files if int(item.get("index") or 0) == index), None)
                    processed_item = {
                        **(source_item or {}),
                        "index": index,
                        "status": "failed",
                        "error_message": str(exc),
                        "extracted_text": "",
                        "summary_text": None,
                        "generated_at": None,
                    }
                for pos, item in enumerate(guide_files):
                    if int(item.get("index") or 0) == index:
                        guide_files[pos] = processed_item
                        break
                _persist_manifest(status="extracting", error_message=None)

        success_items = [item for item in guide_files if str(item.get("status") or "").lower() == "done"]
        failed_items = [item for item in guide_files if str(item.get("status") or "").lower() == "failed"]
        if not success_items:
            raise RuntimeError("no guide file extracted successfully")

        combined_extracted_text = "\n\n".join(
            f"【文件 {item.get('index') or idx}：{item.get('original_name') or ''}】\n{str(item.get('extracted_text') or '').strip()}"
            for idx, item in enumerate(success_items, start=1)
            if str(item.get("extracted_text") or "").strip()
        ).strip()
        if not combined_extracted_text:
            raise RuntimeError("combined guide extracted text is empty")

        _persist_manifest(status="summarizing", extracted_text=combined_extracted_text, error_message=None)
        summary_text = _build_final_summary(combined_extracted_text)
        if not summary_text.strip():
            raise RuntimeError("guide summary generation returned empty text")

        try:
            core_problem_text = _generate_core_problem_from_summary(
                summary_text=summary_text,
                project_name=project_name,
                keywords=project_keywords,
            )
        except Exception:
            core_problem_text = ""
            log_project(
                "GUIDE",
                project_id,
                f"core problem generation failed error=\n{traceback.format_exc()}",
            )
        if not core_problem_text.strip():
            core_problem_text = _fallback_core_problem(summary_text)

        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        error_message = None
        if failed_items:
            error_message = "部分指南解析失败：" + "；".join(
                f"{str(item.get('original_name') or '')}:{str(item.get('error_message') or 'unknown error')}"
                for item in failed_items
            )

        _persist_manifest(
            status="done",
            extracted_text=combined_extracted_text,
            summary_text=summary_text,
            error_message=error_message,
            generated_at=generated_at,
        )

        if core_problem_text.strip():
            try:
                update_project(project_id=project_id, core_problem=core_problem_text.strip())
            except Exception:
                log_project(
                    "GUIDE",
                    project_id,
                    f"update project core_problem failed error=\n{traceback.format_exc()}",
                )
        log_project(
            "GUIDE",
            project_id,
            "guide processing done "
            f"file_count={len(guide_files)} "
            f"success_count={len(success_items)} "
            f"failed_count={len(failed_items)} "
            f"extracted_chars={len(combined_extracted_text)} "
            f"summary_chars={len(summary_text)} "
            f"core_problem_chars={len(core_problem_text)}",
        )
    except Exception:
        error_detail = traceback.format_exc()
        try:
            _persist_manifest(status="failed", error_message=error_detail)
        except Exception:
            update_project_guide(
                project_id,
                status="failed",
                error_message=error_detail,
            )
        log_project("GUIDE", project_id, f"guide processing failed error=\n{error_detail}")
