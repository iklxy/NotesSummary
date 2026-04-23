from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import fetch_projects, insert_project


class ProjectCreate(BaseModel):
    """
    创建项目的请求体结构。

    字段:
        name:             项目名称，必填。
        keywords:         项目关键词，可空。
        core_problem:   访谈核心描述，可空。
    """

    name: str
    keywords: Optional[str] = None
    core_problem: Optional[str] = None


router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=Dict[str, Any])
def create_project(payload: ProjectCreate) -> Dict[str, Any]:
    """
    创建新项目，对应在 bh_project 表中插入一条记录。

    参数:
        payload: 前端传入的项目信息，包括 name、keywords、core_problem。

    返回:
        新创建项目的基础信息字典，至少包含:
            - id
            - name
            - keywords
            - core_problem

    异常:
        HTTPException(400): name 为空或非法。
        HTTPException(500): 数据库插入失败。
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")

    try:
        new_id = insert_project(
            name=name,
            keywords=(payload.keywords.strip() if payload.keywords else None),
            core_problem=(payload.core_problem.strip() if payload.core_problem else None),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"insert project failed: {e}")

    return {
        "id": new_id,
        "name": name,
        "keywords": payload.keywords,
        "core_problem": payload.core_problem,
    }


@router.get("", response_model=list[Dict[str, Any]])
def list_projects() -> list[Dict[str, Any]]:
    """
    查询所有项目列表。

    返回:
        项目字典列表，每个元素至少包含:
            - id
            - name
            - keywords
            - core_problem
    """
    rows = fetch_projects()
    return rows
