"""
@Date: 2026-05-20
@Author: lixinyang

访谈详情字段接口。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from interview_detail_fields import INTERVIEW_DETAIL_FIELD_DEFINITIONS


router = APIRouter(prefix="/api", tags=["interview_detail_fields"])


@router.get("/interview-detail-fields", response_model=Dict[str, Any])
def list_interview_detail_fields() -> Dict[str, Any]:
    """
    返回系统级访谈细节字段定义。
    """
    return {"fields": INTERVIEW_DETAIL_FIELD_DEFINITIONS}

