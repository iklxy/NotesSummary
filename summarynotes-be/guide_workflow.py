"""
@Date: 2026-05-11
@Author: lixinyang

项目指南学习任务。

负责把创建项目时上传的 PDF 指南做文本抽取、OCR 兜底和学习总结，
最终把结构化总结写回 `bh_project_guide`，供后续访谈和智能纪要复用。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from InterviewLogger import log_project
from LLMProviders import build_provider
from config import config
from db import fetch_project_by_id, fetch_project_guide_by_project_id, update_project_guide

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    fitz = None  # type: ignore


_CHUNK_MAX_CHARS = 12000
_OCR_TEXT_THRESHOLD = 30


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
            max_tokens=30000,
            temperature=0.0,
        ).strip()
    except Exception as exc:
        raise RuntimeError(f"ocr page {page_index + 1} failed: {exc}") from exc


def _render_page_to_png(page: Any) -> bytes:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)  # type: ignore[attr-defined]
    return pixmap.tobytes("png")


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
        max_tokens=30000,
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
            max_tokens=30000,
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
    处理单个项目的 PDF 指南：抽取、OCR、总结并回写数据库。
    """
    log_project("GUIDE", project_id, "guide processing start")
    guide_row = fetch_project_guide_by_project_id(project_id)
    if not guide_row:
        log_project("GUIDE", project_id, "guide processing skipped: guide row not found")
        return

    guide_path = _resolve_guide_path(guide_row.get("guide_file_path"))
    if guide_path is None or not guide_path.exists():
        update_project_guide(
            project_id,
            status="failed",
            error_message="guide file not found",
        )
        log_project("GUIDE", project_id, "guide processing failed: guide file not found")
        return

    try:
        update_project_guide(project_id, status="extracting", error_message=None)
        extracted_text, ocr_pages = _extract_pdf_text(guide_path)
        if not extracted_text.strip():
            raise RuntimeError("no text extracted from guide pdf")

        update_project_guide(
            project_id,
            extracted_text=extracted_text,
            status="summarizing",
            error_message=None,
        )
        summary_text = _build_final_summary(extracted_text)
        if not summary_text.strip():
            raise RuntimeError("guide summary generation returned empty text")

        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_project_guide(
            project_id,
            extracted_text=extracted_text,
            summary_text=summary_text,
            status="done",
            error_message=None,
            generated_at=generated_at,
        )
        log_project(
            "GUIDE",
            project_id,
            f"guide processing done extracted_chars={len(extracted_text)} summary_chars={len(summary_text)} ocr_pages={ocr_pages}",
        )
    except Exception as exc:
        update_project_guide(
            project_id,
            status="failed",
            error_message=str(exc),
        )
        log_project("GUIDE", project_id, f"guide processing failed error={exc}")
