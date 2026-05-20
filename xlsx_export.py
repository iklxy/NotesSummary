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
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

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


def _build_ca_sheet_rows(ca_payload: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    """
    将 CA JSON 转换为 Excel 行数据。
    """
    project_id = ca_payload.get("project_id")
    project_name = str(ca_payload.get("project_name") or "").strip()
    questionnaire_name = str(ca_payload.get("questionnaire_name") or "").strip()
    questionnaire_id = ca_payload.get("questionnaire_id")
    generated_at = str(ca_payload.get("generated_at") or "").strip()
    selected_interview_ids = ca_payload.get("selected_interview_ids") or []
    column_meta_fields = ca_payload.get("column_meta_fields") or []
    column_meta_field_labels = ca_payload.get("column_meta_field_labels") or {}
    if not isinstance(column_meta_field_labels, dict):
        column_meta_field_labels = {}
    interviews = ca_payload.get("interviews") or []
    columns = ca_payload.get("columns") or []
    cells = ca_payload.get("cells") or {}

    def _extract_cell_text(value: Any) -> str:
        if isinstance(value, dict):
            text = value.get("value")
            if text is None:
                text = value.get("text")
            return _clean_text(text).strip() or "/"
        return _clean_text(value).strip() or "/"

    interview_columns: List[Dict[str, Any]] = []
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
        if not interview_id_set or interview_id in interview_id_set:
            interview_columns.append(
                {
                    "interview_id": interview_id,
                    "name": name,
                    "meta": meta,
                }
            )

    rows: List[List[Dict[str, Any]]] = []
    title_text = f"CA 表格 - {project_name or project_id}"
    rows.append([{"value": title_text, "style": 3}] + [{"value": "", "style": 3}] * len(interview_columns))
    rows.append(
        [
            {"value": f"项目：{project_name or project_id}", "style": 1},
            {"value": f"生成时间：{generated_at or ''}", "style": 1},
        ]
        + [{"value": "", "style": 1}] * max(0, len(interview_columns) - 2)
    )
    rows.append(
        [
            {"value": f"选择访谈：{len(interview_columns)}", "style": 1},
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
        + [{"value": "", "style": 1}] * max(0, len(interview_columns) - 2)
    )
    rows.append([])

    rows.append([{"value": "访谈细节", "style": 3}] + [{"value": "", "style": 3}] * len(interview_columns))

    detail_specs = [
        ("访谈ID", lambda interview: str(interview.get("interview_id") or "").strip() or "/"),
        ("访谈名称", lambda interview: str(interview.get("name") or "").strip() or "/"),
        (
            "访谈日期",
            lambda interview: str(interview.get("interview_date") or "").split("T")[0] if interview.get("interview_date") else "-",
        ),
    ]
    for key in column_meta_fields:
        label = str(column_meta_field_labels.get(key) or INTERVIEW_DETAIL_FIELD_LABELS.get(key) or key)

        def _extract_meta_value(interview: Dict[str, Any], meta_key: str = key) -> str:
            meta = interview.get("meta") or {}
            if not isinstance(meta, dict):
                return "/"
            value = meta.get(meta_key)
            return _clean_text(value).strip() or "/"

        detail_specs.append((label, _extract_meta_value))

    for detail_label, extractor in detail_specs:
        rows.append(
            [{"value": detail_label, "style": 2}]
            + [{"value": extractor(column), "style": 1} for column in interview_columns]
        )

    rows.append([])
    rows.append([{"value": "问题", "style": 3}] + [{"value": "", "style": 3}] * len(interview_columns))

    for item in columns:
        if not isinstance(item, dict):
            continue
        if item.get("hidden"):
            continue
        question_uid = str(item.get("question_uid") or item.get("column_id") or "").strip()
        question_order = item.get("order")
        question_text = str(item.get("display_text") or item.get("question_text") or "").strip()
        if not question_uid and not question_text:
            continue
        row_cells: List[Dict[str, Any]] = [
            {
                "value": f"{question_order}. {question_text}" if question_order is not None else question_text,
                "style": 1,
            }
        ]
        for interview in interview_columns:
            interview_id = str(interview.get("interview_id") or "").strip()
            cell_text = "/"
            if interview_id and question_uid and isinstance(cells, dict):
                row_cells_by_interview = cells.get(interview_id)
                if isinstance(row_cells_by_interview, dict):
                    cell_text = _extract_cell_text(row_cells_by_interview.get(question_uid))
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
    sheet.freeze_panes = "B6"
    sheet.sheet_view.zoomScale = 90

    thin_side = Side(style="thin", color="D9D9D9")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    for col_index in range(1, total_cols + 1):
        letter = get_column_letter(col_index)
        if col_index == 1:
            sheet.column_dimensions[letter].width = 42
        else:
            sheet.column_dimensions[letter].width = 40

    current_section = None
    for row_index, row in enumerate(rows, start=1):
        first_value = _clean_text(row[0].get("value")) if row else ""
        if first_value == "访谈细节":
            current_section = "detail"
        elif first_value == "问题":
            current_section = "question"
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
                cell.font = Font(name="Calibri", size=12, bold=True)
                cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
            elif style == 2:
                cell.font = Font(name="Calibri", size=12, bold=True)
            else:
                cell.font = Font(name="Calibri", size=12)

        if row_index == 1:
            sheet.row_dimensions[row_index].height = 32
        elif first_value in {"访谈细节", "问题"}:
            sheet.row_dimensions[row_index].height = 50
        elif current_section == "question":
            sheet.row_dimensions[row_index].height = 120
        else:
            max_lines = 1
            for cell_spec in row:
                cell_text = _clean_text(cell_spec.get("value"))
                max_lines = max(max_lines, cell_text.count("\n") + 1)
            sheet.row_dimensions[row_index].height = min(max(24, max_lines * 22), 120)

    if total_cols > 1:
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_cols)
        sheet["A1"].alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
