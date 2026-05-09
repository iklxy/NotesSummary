#!/usr/bin/env python3
"""
@Date: 2026-05-08
@Author: lixinyang

Excel 导出工具。

当前实现基于 openpyxl 生成 CA 表格导出所需的 .xlsx。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from interview_detail_fields import INTERVIEW_DETAIL_FIELD_LABELS


XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _clean_text(value: Any) -> str:
    """
    归一化单元格文本。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def _column_letter(index: int) -> str:
    """
    将 1-based 列序号转换为 Excel 列字母。
    """
    if index <= 0:
        return "A"
    letters: List[str] = []
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _cell_ref(col_index: int, row_index: int) -> str:
    """
    构造 Excel 单元格引用。
    """
    return f"{_column_letter(col_index)}{row_index}"


def _build_ca_sheet_rows(ca_payload: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    """
    将 CA JSON 转换为 Excel 行数据。
    """
    project_id = ca_payload.get("project_id")
    project_name = str(ca_payload.get("project_name") or "").strip()
    generated_at = str(ca_payload.get("generated_at") or "").strip()
    selected_interview_ids = ca_payload.get("selected_interview_ids") or []
    column_meta_fields = ca_payload.get("column_meta_fields") or []
    column_meta_field_labels = ca_payload.get("column_meta_field_labels") or {}
    if not isinstance(column_meta_field_labels, dict):
        column_meta_field_labels = {}
    interviews = ca_payload.get("interviews") or []
    dimensions = ca_payload.get("dimensions") or []

    interview_headers: List[str] = []
    interview_id_set = {str(item) for item in selected_interview_ids if item is not None}
    for item in interviews:
        if not isinstance(item, dict):
            continue
        interview_id = str(item.get("interview_id") or "").strip()
        name = str(item.get("name") or f"访谈 {interview_id}").strip()
        meta = item.get("meta") or {}
        meta_lines = [f"访谈ID：{interview_id}", f"名称：{name}"]
        if isinstance(meta, dict):
            for key in column_meta_fields:
                value = meta.get(key)
                label = str(column_meta_field_labels.get(key) or INTERVIEW_DETAIL_FIELD_LABELS.get(key) or key)
                if value is None or str(value).strip() == "":
                    meta_lines.append(f"{label}：/")
                else:
                    meta_lines.append(f"{label}：{value}")
        header_text = "\n".join(meta_lines)
        if not interview_id_set or interview_id in interview_id_set:
            interview_headers.append(header_text)

    total_cols = 2 + len(interview_headers)
    rows: List[List[Dict[str, Any]]] = []
    title_text = f"CA 表格 - {project_name or project_id}"
    rows.append([{"value": title_text, "style": 3}] + [{"value": "", "style": 3}] * (total_cols - 1))
    rows.append(
        [
            {"value": f"项目：{project_name or project_id}", "style": 1},
            {"value": f"生成时间：{generated_at or ''}", "style": 1},
        ]
        + [{"value": "", "style": 1}] * max(0, total_cols - 2)
    )
    rows.append(
        [
            {"value": f"选择访谈：{len(interview_headers)}", "style": 1},
            {
                "value": "列字段："
                + (
                    ", ".join(
                        str(column_meta_field_labels.get(item) or INTERVIEW_DETAIL_FIELD_LABELS.get(item) or item)
                        for item in column_meta_fields
                    )
                    if column_meta_fields
                    else "无"
                ),
                "style": 1,
            },
        ]
        + [{"value": "", "style": 1}] * max(0, total_cols - 2)
    )
    rows.append([])

    header_row = [
        {"value": "层级/标题", "style": 3},
        {"value": "说明", "style": 3},
    ] + [{"value": text, "style": 3} for text in interview_headers]
    rows.append(header_row)

    for dimension in dimensions:
        if not isinstance(dimension, dict):
            continue
        dim_order = dimension.get("order")
        dim_title = str(dimension.get("title") or "").strip()
        dim_summary = str(dimension.get("summary") or "").strip()
        if not dim_title and not dim_summary:
            continue
        rows.append(
            [
                {"value": f"第{dim_order}部分：{dim_title}" if dim_order is not None else dim_title, "style": 2},
                {"value": dim_summary, "style": 2},
            ]
            + [{"value": "", "style": 1}] * len(interview_headers)
        )
        sub_points = dimension.get("sub_points") or []
        if not isinstance(sub_points, list):
            continue
        for sub_point in sub_points:
            if not isinstance(sub_point, dict):
                continue
            sub_order = sub_point.get("order")
            sub_title = str(sub_point.get("title") or "").strip()
            sub_summary = str(sub_point.get("summary") or "").strip()
            if not sub_title and not sub_summary:
                continue
            cells = sub_point.get("cells") or {}
            row_cells: List[Dict[str, Any]] = [
                {
                    "value": f"· {sub_order}. {sub_title}" if sub_order is not None else f"· {sub_title}",
                    "style": 1,
                },
                {"value": sub_summary, "style": 1},
            ]
            for item in interviews:
                if not isinstance(item, dict):
                    row_cells.append({"value": "/", "style": 1})
                    continue
                interview_id = str(item.get("interview_id") or "").strip()
                if interview_id_set and interview_id not in interview_id_set:
                    continue
                cell_text = "/"
                if isinstance(cells, dict):
                    cell_text = str(cells.get(interview_id) or "").strip() or "/"
                row_cells.append({"value": cell_text, "style": 1})
            rows.append(row_cells)

    return rows


def build_ca_table_xlsx_bytes(ca_payload: Dict[str, Any]) -> bytes:
    """
    将 CA JSON 生成可下载的 Excel 二进制。
    """
    rows = _build_ca_sheet_rows(ca_payload)
    total_cols = max(2, max((len(row) for row in rows), default=2))
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "CA表格"
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "C5"

    thin_side = Side(style="thin", color="D9D9D9")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for col_index in range(1, total_cols + 1):
        letter = get_column_letter(col_index)
        sheet.column_dimensions[letter].width = 36 if col_index <= 2 else 34

    for row_index, row in enumerate(rows, start=1):
        for col_index in range(1, total_cols + 1):
            if col_index <= len(row):
                cell_spec = row[col_index - 1]
                value = cell_spec.get("value")
                style = int(cell_spec.get("style") or 1)
            else:
                value = ""
                style = 1
            cell = sheet.cell(row=row_index, column=col_index, value=_clean_text(value))
            cell.alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
            cell.border = border
            if style == 3:
                cell.font = Font(name="Calibri", size=11, bold=True)
                cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
            elif style == 2:
                cell.font = Font(name="Calibri", size=11, bold=True)
            else:
                cell.font = Font(name="Calibri", size=11)

    if total_cols > 1:
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
        sheet["A1"].alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
