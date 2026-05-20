"""
@Date: 2026-05-06
@Author: lixinyang

Word 文稿导出工具。

该模块负责把“全文 trans”和“全文 Notes”数据渲染为标准的 .docx 二进制文件，
用于前端下载导出。
"""

from __future__ import annotations

import re
import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile
from io import BytesIO


DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _clean_text(value: Any) -> str:
    """
    将任意值规范化为适合写入 Word 的普通文本。

    参数:
        value: 任意输入值。

    返回:
        去掉首尾空白后的字符串；空值返回空字符串。
    """
    if value is None:
        return ""
    text = str(value)
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _load_json_like(value: Any) -> Any:
    """
    将 JSON 字符串、dict 或 list 统一解析为 Python 对象。
    """
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return None
    text = _clean_text(value)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _format_timestamp_mmss(value: Any) -> str:
    """
    将毫秒时间戳格式化为 mm:ss。

    参数:
        value: 原始时间戳，通常是毫秒数，可能为字符串或数字。

    返回:
        格式化后的时间字符串；如果无法解析则返回原始文本。
    """
    raw = _clean_text(value)
    if not raw:
        return ""
    match = re.match(r"^(\d+)(?:-(\d+))?$", raw)
    if match:
        start_ms = int(match.group(1))
        end_ms = int(match.group(2)) if match.group(2) else start_ms
        if start_ms < 0:
            start_ms = 0
        if end_ms < 0:
            end_ms = 0
        start_seconds = start_ms // 1000
        end_seconds = end_ms // 1000
        start_minutes = start_seconds // 60
        start_secs = start_seconds % 60
        end_minutes = end_seconds // 60
        end_secs = end_seconds % 60
        start_text = f"{start_minutes}:{start_secs:02d}"
        end_text = f"{end_minutes}:{end_secs:02d}"
        return start_text if start_text == end_text else f"{start_text} - {end_text}"
    try:
        ms = int(float(raw))
    except Exception:
        return raw
    if ms < 0:
        ms = 0
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _w_run(text: str, bold: bool = False, size: Optional[int] = None) -> str:
    """
    生成一个 Word run 的 XML 片段。

    参数:
        text: 要写入的文本。
        bold: 是否加粗。
        size: 字号，单位为 half-point；例如 28 表示 14pt。

    返回:
        run XML 字符串。
    """
    safe_text = escape(text)
    props: List[str] = []
    if bold:
        props.append("<w:b/>")
    if size is not None:
        props.append(f'<w:sz w:val="{int(size)}"/>')
        props.append(f'<w:szCs w:val="{int(size)}"/>')
    prop_xml = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f"<w:r>{prop_xml}<w:t xml:space=\"preserve\">{safe_text}</w:t></w:r>"


def _w_paragraph(
    text: str = "",
    bold: bool = False,
    size: Optional[int] = None,
    align: Optional[str] = None,
) -> str:
    """
    生成一个 Word 段落的 XML 片段。

    参数:
        text: 段落内容。
        bold: 是否加粗。
        size: 字号，单位为 half-point。
        align: 对齐方式，可选值包括 left/center/right/both。

    返回:
        paragraph XML 字符串。
    """
    ppr = ""
    if align:
        ppr = f"<w:pPr><w:jc w:val=\"{escape(align)}\"/></w:pPr>"
    if not text:
        return f"<w:p>{ppr}</w:p>"
    return f"<w:p>{ppr}{_w_run(text, bold=bold, size=size)}</w:p>"


def _w_paragraph_runs(
    runs: List[Dict[str, Any]],
    align: Optional[str] = None,
) -> str:
    """
    生成一个包含多段 run 的 Word 段落 XML。

    参数:
        runs: run 描述列表，每个元素至少包含 text；可选 bold / size。
        align: 对齐方式，可选值包括 left/center/right/both。

    返回:
        paragraph XML 字符串。
    """
    ppr = ""
    if align:
        ppr = f"<w:pPr><w:jc w:val=\"{escape(align)}\"/></w:pPr>"
    if not runs:
        return f"<w:p>{ppr}</w:p>"

    parts: List[str] = []
    for run in runs:
        text = str(run.get("text") or "")
        if not text:
            continue
        parts.append(_w_run(text, bold=bool(run.get("bold")), size=run.get("size")))
    if not parts:
        parts.append(_w_run(""))
    return f"<w:p>{ppr}{''.join(parts)}</w:p>"


def _w_image_paragraph(
    rel_id: str,
    width_emu: int,
    height_emu: int,
    name: str,
    doc_pr_id: int,
) -> str:
    """
    生成一个 Word 图片段落 XML。
    """
    return (
        "<w:p>"
        "<w:r>"
        "<w:drawing>"
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{int(width_emu)}" cy="{int(height_emu)}"/>'
        f'<wp:docPr id="{int(doc_pr_id)}" name="{escape(name)}"/>'
        '<wp:cNvGraphicFramePr>'
        '<a:graphicFrameLocks noChangeAspect="1" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'
        "</wp:cNvGraphicFramePr>"
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:nvPicPr>"
        f'<pic:cNvPr id="{int(doc_pr_id)}" name="{escape(name)}"/>'
        "<pic:cNvPicPr/>"
        "</pic:nvPicPr>"
        "<pic:blipFill>"
        f'<a:blip r:embed="{escape(rel_id)}"/>'
        '<a:stretch><a:fillRect/></a:stretch>'
        "</pic:blipFill>"
        "<pic:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{int(width_emu)}" cy="{int(height_emu)}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr>"
        "</pic:pic>"
        "</a:graphicData>"
        "</a:graphic>"
        "</wp:inline>"
        "</w:drawing>"
        "</w:r>"
        "</w:p>"
    )


def _w_table_cell(text: str, width: Optional[int] = None) -> str:
    """
    生成 Word 表格单元格 XML。

    参数:
        text: 单元格内容。
        width: 可选固定宽度，单位为 twentieths of a point。

    返回:
        table cell XML 字符串。
    """
    width_xml = f'<w:tcW w:w="{int(width)}" w:type="dxa"/>' if width is not None else ""
    cell_paragraph = _paragraph_from_text(text, size=20)
    return f"<w:tc><w:tcPr>{width_xml}</w:tcPr>{cell_paragraph}</w:tc>"


def _w_table_borders() -> str:
    """
    生成表格边框定义。

    返回:
        table borders XML 字符串。
    """
    return (
        "<w:tblBorders>"
        '<w:top w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
        '<w:left w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
        '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
        '<w:right w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
        "</w:tblBorders>"
    )


def _w_table(header: List[str], rows: List[List[str]]) -> str:
    """
    生成 Word 表格 XML。

    参数:
        header: 表头单元格列表。
        rows: 数据行，每一行是单元格列表。

    返回:
        table XML 字符串。
    """
    all_rows = [header] + rows
    col_count = max(1, max((len(row) for row in all_rows), default=1))
    col_width = int(9600 / col_count)
    grid = "".join(f'<w:gridCol w:w="{col_width}"/>' for _ in range(col_count))

    tr_parts: List[str] = []
    for row_index, row in enumerate(all_rows):
        cells: List[str] = []
        for col_index in range(col_count):
            value = row[col_index] if col_index < len(row) else ""
            cell_width = col_width
            cells.append(_w_table_cell(value, width=cell_width))
        tr_parts.append(f"<w:tr>{''.join(cells)}</w:tr>")

    return (
        '<w:tbl>'
        '<w:tblPr>'
        '<w:tblStyle w:val="TableGrid"/>'
        '<w:tblW w:w="0" w:type="auto"/>'
        f"{_w_table_borders()}"
        "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        f"{''.join(tr_parts)}"
        "</w:tbl>"
    )


def _extract_card_tags(card: Dict[str, Any]) -> List[str]:
    """
    提取卡片标签列表。
    """
    for candidate in (card.get("final_json"), card.get("generated_json")):
        payload = _load_json_like(candidate)
        if not isinstance(payload, dict):
            continue
        tags = payload.get("tags")
        if isinstance(tags, list):
            result = [str(tag).strip() for tag in tags if str(tag).strip()]
            if result:
                return result
    return []


def _resolve_card_word_payload(card: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析卡片导出所需字段。
    """
    payload = _load_json_like(card.get("final_json"))
    if not isinstance(payload, dict):
        payload = _load_json_like(card.get("generated_json"))
    if not isinstance(payload, dict):
        payload = {}

    title = _clean_text(card.get("card_title")) or _clean_text(payload.get("title")) or "卡片"
    summary = _clean_text(card.get("card_summary")) or _clean_text(payload.get("summary"))
    tags = _extract_card_tags(card)
    if not tags and isinstance(payload.get("tags"), list):
        tags = [str(tag).strip() for tag in payload.get("tags") if str(tag).strip()]
    review_status = _clean_text(card.get("review_status")) or "pending"
    order = card.get("card_order")
    return {
        "title": title,
        "summary": summary,
        "tags": tags,
        "review_status": review_status,
        "order": order,
    }


def _build_card_status_text(review_status: str) -> str:
    """
    将审核状态转换为适合展示的中文文案。
    """
    return {
        "approved": "已通过",
        "rejected": "已驳回",
        "needs_revision": "待修改",
        "pending": "待审核",
    }.get(review_status, review_status or "待审核")


def _build_overall_notes_card_block(card: Dict[str, Any], fallback_order: int) -> str:
    """
    生成一张卡片对应的 Word 表格块。
    """
    payload = _resolve_card_word_payload(card)
    order = payload["order"] or fallback_order
    status_text = _build_card_status_text(payload["review_status"])

    inner_parts: List[str] = []
    inner_parts.append(_paragraph_from_text(f"卡片 {order} · {status_text}", bold=True, size=22))
    inner_parts.append(_paragraph_from_text(payload["title"], bold=True, size=28))

    if payload["tags"]:
        inner_parts.append(_paragraph_from_text("标签：" + "、".join(payload["tags"]), size=20))

    if payload["summary"]:
        _append_markdown_text(inner_parts, payload["summary"], base_size=22)
    else:
        inner_parts.append(_paragraph_from_text("暂无摘要。", size=22))

    inner_xml = "".join(inner_parts)
    return (
        '<w:tbl>'
        '<w:tblPr>'
        '<w:tblStyle w:val="TableGrid"/>'
        '<w:tblW w:w="0" w:type="auto"/>'
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="8" w:space="0" w:color="D1D5DB"/>'
        '<w:left w:val="single" w:sz="8" w:space="0" w:color="D1D5DB"/>'
        '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="D1D5DB"/>'
        '<w:right w:val="single" w:sz="8" w:space="0" w:color="D1D5DB"/>'
        '<w:insideH w:val="single" w:sz="8" w:space="0" w:color="D1D5DB"/>'
        '<w:insideV w:val="single" w:sz="8" w:space="0" w:color="D1D5DB"/>'
        '</w:tblBorders>'
        '</w:tblPr>'
        '<w:tblGrid><w:gridCol w:w="9600"/></w:tblGrid>'
        '<w:tr>'
        '<w:tc>'
        '<w:tcPr>'
        '<w:tcW w:w="9600" w:type="dxa"/>'
        '<w:shd w:val="clear" w:color="auto" w:fill="F8FAFC"/>'
        '</w:tcPr>'
        f'{inner_xml}'
        '</w:tc>'
        '</w:tr>'
        '</w:tbl>'
    )


def _split_inline_markdown(text: str) -> List[Dict[str, Any]]:
    """
    将行内 Markdown（主要是加粗）拆成可写入 Word 的 run 列表。

    参数:
        text: 原始文本。

    返回:
        run 描述列表，每项包含 text 和 bold。
    """
    if not text:
        return []

    pattern = re.compile(r"(\*\*[\s\S]+?\*\*|__[\s\S]+?__)")
    runs: List[Dict[str, Any]] = []
    last_index = 0
    for match in pattern.finditer(text):
        start = match.start()
        if start > last_index:
            plain = text[last_index:start]
            if plain:
                runs.append({"text": plain, "bold": False})
        raw = match.group(0)
        inner = raw[2:-2]
        if inner:
            runs.append({"text": inner, "bold": True})
        last_index = match.end()
    if last_index < len(text):
        tail = text[last_index:]
        if tail:
            runs.append({"text": tail, "bold": False})
    return runs


def _paragraph_from_text(
    text: str,
    *,
    bold: bool = False,
    size: Optional[int] = None,
    align: Optional[str] = None,
) -> str:
    """
    将普通文本转换为支持 Markdown 加粗的 Word 段落 XML。

    参数:
        text: 段落文本。
        bold: 是否整段加粗。
        size: 字号，单位为 half-point。
        align: 对齐方式。

    返回:
        paragraph XML 字符串。
    """
    runs: List[Dict[str, Any]] = []
    for segment in _split_inline_markdown(text):
        segment_text = str(segment.get("text") or "")
        if not segment_text:
            continue
        runs.append(
            {
                "text": segment_text,
                "bold": bool(bold or segment.get("bold")),
                "size": size,
            }
        )
    if not runs:
        runs = [{"text": text, "bold": bold, "size": size}]
    return _w_paragraph_runs(runs, align=align)


def _append_markdown_text(
    paragraphs: List[str],
    content: str,
    *,
    base_size: int = 22,
    heading_sizes: Optional[Dict[int, int]] = None,
) -> None:
    """
    将 Markdown 风格文本追加到段落 XML 列表中。

    参数:
        paragraphs: 段落 XML 列表。
        content: Markdown 风格文本。
        base_size: 普通正文默认字号，单位为 half-point。
        heading_sizes: 标题层级到字号的映射。

    返回:
        无。
    """
    if not content:
        return
    heading_sizes = heading_sizes or {1: 32, 2: 28, 3: 26, 4: 24, 5: 22, 6: 22}
    normalized = _clean_text(content).replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    buffer: List[str] = []

    def flush_buffer() -> None:
        if not buffer:
            return
        joined = " ".join(part.strip() for part in buffer if part.strip()).strip()
        buffer.clear()
        if joined:
            paragraphs.append(_paragraph_from_text(joined, size=base_size))

    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        if not line:
            flush_buffer()
            paragraphs.append(_w_blank_paragraph())
            index += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            flush_buffer()
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            paragraphs.append(
                _paragraph_from_text(
                    heading_text,
                    bold=True,
                    size=heading_sizes.get(level, 22),
                )
            )
            index += 1
            continue

        if re.match(r"^(?:-|\*|\+)\s+", line) or re.match(r"^\d+[.)]\s+", line):
            flush_buffer()
            item_text = re.sub(r"^(?:-|\*|\+)\s+|^\d+[.)]\s+", "", line).strip()
            if item_text:
                paragraphs.append(_paragraph_from_text(f"· {item_text}", size=base_size))
            index += 1
            continue

        if "|" in line and index + 1 < len(lines):
            separator_line = lines[index + 1].strip()
            if re.match(r"^\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$", separator_line):
                flush_buffer()
                header = [
                    cell.strip()
                    for cell in line.strip().strip("|").split("|")
                ]
                index += 2
                rows: List[List[str]] = []
                while index < len(lines):
                    current = lines[index].strip()
                    if not current or "|" not in current:
                        break
                    rows.append([cell.strip() for cell in current.strip().strip("|").split("|")])
                    index += 1
                paragraphs.append(_w_table(header, rows))
                continue

        if line.startswith("·"):
            flush_buffer()
            paragraphs.append(_paragraph_from_text(line, size=base_size))
            index += 1
            continue

        if line.startswith(">"):
            flush_buffer()
            quote_text = re.sub(r"^>\s?", "", line).strip()
            if quote_text:
                paragraphs.append(_paragraph_from_text(f"“{quote_text}”", size=base_size))
            index += 1
            continue

        buffer.append(line)
        index += 1

    flush_buffer()


def _build_overall_notes_document_xml(
    title: str,
    subtitle_lines: Iterable[str],
    note_content: str,
    kbq_items: List[Dict[str, Any]],
    minutes_text: str,
    card_items: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    组装整体 Notes 的 Word 主文档 XML。

    参数:
        title: 文档标题。
        subtitle_lines: 标题下方的说明行。
        note_content: 访谈级 Summary Notes。
        kbq_items: KBQ Notes 结构化条目。
        minutes_text: 智能纪要的 Markdown 文本。
        card_items: 卡片明细列表；若条目中包含 data(bytes) 则仍按图片处理，否则按 Word 文本卡片处理。

    返回:
        `word/document.xml` 的完整 XML 文本。
    """
    paragraphs: List[str] = []
    paragraphs.append(_w_paragraph(title, bold=True, size=32, align="center"))
    paragraphs.append(_w_blank_paragraph())
    for line in subtitle_lines:
        cleaned = _clean_text(line)
        if cleaned:
            paragraphs.append(_paragraph_from_text(cleaned, size=22))
    if subtitle_lines:
        paragraphs.append(_w_blank_paragraph())

    paragraphs.append(_paragraph_from_text("A. 全文模块总结卡片", bold=True, size=28))
    if card_items:
        image_width_emu = int(6.25 * 914400)
        for index, card_item in enumerate(card_items, start=1):
            if not isinstance(card_item, dict):
                continue
            image_data = card_item.get("data")
            if isinstance(image_data, (bytes, bytearray)):
                image_name = str(card_item.get("name") or f"card_{index}.png")
                image_width = int(card_item.get("width") or 1200)
                image_height = int(card_item.get("height") or 0)
                if image_height <= 0:
                    image_height = 1
                image_height_emu = int(image_width_emu * image_height / image_width)
                rel_id = str(card_item.get("rel_id") or f"rId{index}")
                doc_pr_id = 1000 + index
                paragraphs.append(_w_image_paragraph(rel_id, image_width_emu, image_height_emu, image_name, doc_pr_id))
                paragraphs.append(_w_blank_paragraph())
                continue
            paragraphs.append(_build_overall_notes_card_block(card_item, index))
            paragraphs.append(_w_blank_paragraph())
    else:
        paragraphs.append(_paragraph_from_text("暂无卡片。", size=22))
        paragraphs.append(_w_blank_paragraph())

    paragraphs.append(_paragraph_from_text("B. KBQ Notes", bold=True, size=28))
    if kbq_items:
        for item in kbq_items:
            bq_order = item.get("bq_order")
            bq_text = _clean_text(item.get("bq_text"))
            title_text = f"{bq_order}. {bq_text}" if bq_order is not None else bq_text
            if title_text:
                paragraphs.append(_paragraph_from_text(title_text, bold=True, size=24))

            note_json = item.get("note_json")
            dimension_notes: List[Dict[str, Any]] = []
            if isinstance(note_json, dict):
                raw_dimension_notes = note_json.get("dimension_notes") or []
                if isinstance(raw_dimension_notes, list):
                    dimension_notes = [
                        dimension
                        for dimension in raw_dimension_notes
                        if isinstance(dimension, dict)
                    ]
            if dimension_notes:
                for dimension in dimension_notes:
                    dimension_name = _clean_text(dimension.get("dimension")) or "维度"
                    summary_text = _clean_text(dimension.get("summary"))
                    if dimension_name:
                        paragraphs.append(_paragraph_from_text(dimension_name, bold=True, size=22))
                    if summary_text:
                        _append_markdown_text(paragraphs, summary_text, base_size=22)
                    else:
                        paragraphs.append(_paragraph_from_text("暂无可展示的内容。", size=22))
            else:
                summary_text = ""
                if isinstance(note_json, dict):
                    summary_text = _clean_text(note_json.get("summary"))
                if summary_text:
                    _append_markdown_text(paragraphs, summary_text, base_size=22)
                else:
                    paragraphs.append(_paragraph_from_text("该条 key BQ 暂无可展示的维度 notes。", size=22))
            paragraphs.append(_w_blank_paragraph())
    else:
        paragraphs.append(_paragraph_from_text("暂无 KBQ Notes。", size=22))
        paragraphs.append(_w_blank_paragraph())

    paragraphs.append(_paragraph_from_text("C. 智能纪要", bold=True, size=28))
    _append_markdown_text(paragraphs, minutes_text, base_size=22)

    body = "".join(paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:o="urn:schemas-microsoft-com:office:office"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        ' xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
        ' xmlns:v="urn:schemas-microsoft-com:vml"'
        ' xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"'
        ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        ' xmlns:w10="urn:schemas-microsoft-com:office:word"'
        ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
        ' xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"'
        ' xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"'
        ' xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"'
        ' xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
        ' mc:Ignorable="w14 wp14">'
        "<w:body>"
        f"{body}"
        "<w:sectPr>"
        "<w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" "
        "w:header=\"708\" w:footer=\"708\" w:gutter=\"0\"/>"
        "</w:sectPr>"
        "</w:body>"
        "</w:document>"
    )


def build_overall_notes_docx_bytes(
    *,
    title: str,
    subtitle_lines: Iterable[str],
    note_content: str,
    kbq_items: List[Dict[str, Any]],
    minutes_text: str,
    card_items: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    """
    生成“全文 Notes”对应的 .docx 文件二进制。

    参数:
        title: 文档标题。
        subtitle_lines: 标题下方的说明行。
        note_content: 访谈级 Summary Notes。
        kbq_items: KBQ Notes 结构化条目。
        minutes_text: 智能纪要 Markdown 文本。
        card_items: 卡片明细列表；若条目中包含 data(bytes) 则仍按图片处理，否则按 Word 文本卡片处理。

    返回:
        可直接写入 .docx 文件的二进制内容。
    """
    document_xml = _build_overall_notes_document_xml(
        title=title,
        subtitle_lines=subtitle_lines,
        note_content=note_content,
        kbq_items=kbq_items,
        minutes_text=minutes_text,
        card_items=card_items,
    )
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:dcterms="http://purl.org/dc/terms/"'
        ' xmlns:dcmitype="http://purl.org/dc/dcmitype/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(_clean_text(title))}</dc:title>"
        f"<dc:creator>NotesSummary</dc:creator>"
        f"<cp:lastModifiedBy>NotesSummary</cp:lastModifiedBy>"
        f"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}</dcterms:created>"
        f"<dcterms:modified xsi:type=\"dcterms:W3CDTF\">{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}</dcterms:modified>"
        "</cp:coreProperties>"
    )
    app_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
        ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>NotesSummary</Application>"
        "</Properties>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    image_items = [item for item in (card_items or []) if isinstance(item, dict) and isinstance(item.get("data"), (bytes, bytearray))]
    document_rels = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    ]
    for index, _item in enumerate(image_items, start=1):
        rel_id = str(_item.get("rel_id") or f"rId{index}")
        document_rels.append(
            f'<Relationship Id="{rel_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            f'Target="media/image{index}.png"/>'
        )
        _item["rel_id"] = rel_id
        _item.setdefault("name", f"image{index}.png")
    document_rels.append("</Relationships>")
    document_rels_xml = "".join(document_rels)
    rels_root = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )

    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels_root)
        if image_items:
            archive.writestr("word/_rels/document.xml.rels", document_rels_xml)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("word/document.xml", document_xml)
        for index, item in enumerate(image_items, start=1):
            archive.writestr(f"word/media/image{index}.png", bytes(item["data"]))
    return buffer.getvalue()


def _w_blank_paragraph() -> str:
    """
    生成空白段落。

    返回:
        空段落 XML。
    """
    return "<w:p/>"


def _build_document_xml(
    title: str,
    subtitle_lines: Iterable[str],
    transcript_items: List[Dict[str, Any]],
) -> str:
    """
    组装 Word 主文档 XML。

    参数:
        title: 文档标题。
        subtitle_lines: 标题下方的说明行。
        transcript_items: 转录条目列表。

    返回:
        `word/document.xml` 的完整 XML 文本。
    """
    paragraphs: List[str] = []
    paragraphs.append(_w_paragraph(title, bold=True, size=32, align="center"))
    paragraphs.append(_w_blank_paragraph())
    for line in subtitle_lines:
        cleaned = _clean_text(line)
        if cleaned:
            paragraphs.append(_w_paragraph(cleaned, size=22))
    if subtitle_lines:
        paragraphs.append(_w_blank_paragraph())

    for item in transcript_items:
        speaker = _clean_text(item.get("speaker"))
        timestamp = _format_timestamp_mmss(item.get("timestamp"))
        text = _clean_text(item.get("text"))
        if speaker:
            paragraphs.append(_w_paragraph(speaker, bold=True, size=22))
        if timestamp:
            paragraphs.append(_w_paragraph(timestamp, bold=True, size=22))
        if text:
            for line in text.split("\n"):
                cleaned_line = line.strip()
                if cleaned_line:
                    paragraphs.append(_w_paragraph(cleaned_line, size=22))
        paragraphs.append(_w_blank_paragraph())

    body = "".join(paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"'
        ' xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
        ' xmlns:o="urn:schemas-microsoft-com:office:office"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        ' xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
        ' xmlns:v="urn:schemas-microsoft-com:vml"'
        ' xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"'
        ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        ' xmlns:w10="urn:schemas-microsoft-com:office:word"'
        ' xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"'
        ' xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"'
        ' xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"'
        ' xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"'
        ' xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
        ' mc:Ignorable="w14 wp14">'
        "<w:body>"
        f"{body}"
        "<w:sectPr>"
        "<w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" "
        "w:header=\"708\" w:footer=\"708\" w:gutter=\"0\"/>"
        "</w:sectPr>"
        "</w:body>"
        "</w:document>"
    )


def build_transcript_docx_bytes(
    *,
    title: str,
    subtitle_lines: Iterable[str],
    transcript_items: List[Dict[str, Any]],
) -> bytes:
    """
    生成“全文 trans”对应的 .docx 文件二进制。

    参数:
        title: 文档标题。
        subtitle_lines: 标题下方的说明行。
        transcript_items: 转录条目列表，每项建议包含 speaker / timestamp / text。

    返回:
        可直接写入 .docx 文件的二进制内容。
    """
    document_xml = _build_document_xml(title, subtitle_lines, transcript_items)
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:dcterms="http://purl.org/dc/terms/"'
        ' xmlns:dcmitype="http://purl.org/dc/dcmitype/"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(_clean_text(title))}</dc:title>"
        f"<dc:creator>NotesSummary</dc:creator>"
        f"<cp:lastModifiedBy>NotesSummary</cp:lastModifiedBy>"
        f"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}</dcterms:created>"
        f"<dcterms:modified xsi:type=\"dcterms:W3CDTF\">{datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}</dcterms:modified>"
        "</cp:coreProperties>"
    )
    app_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"'
        ' xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>NotesSummary</Application>"
        "</Properties>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    rels_root = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )

    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels_root)
        archive.writestr("docProps/core.xml", core_xml)
        archive.writestr("docProps/app.xml", app_xml)
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()
