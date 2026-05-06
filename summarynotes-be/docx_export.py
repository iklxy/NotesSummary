"""
@Date: 2026-05-06
@Author: lixinyang

Word 文稿导出工具。

该模块负责把“全文 trans”数据渲染为一个标准的 .docx 二进制文件，
用于前端下载导出。
"""

from __future__ import annotations

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
        speaker = _clean_text(item.get("speaker")) or "未知角色"
        timestamp = _clean_text(item.get("timestamp"))
        text = _clean_text(item.get("text"))
        header = speaker
        if timestamp:
            header = f"{speaker} [{timestamp}]"
        paragraphs.append(_w_paragraph(header, bold=True, size=22))
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
