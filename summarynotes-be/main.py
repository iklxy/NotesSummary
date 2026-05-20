"@Date: 2026-04-15"
"@Author: lixinyang"

"""
SummaryNotes 后端 BFF 入口。

该模块负责创建 FastAPI 应用、注册 CORS 和各个业务路由，
并在命令行直接运行时启动本地开发/部署服务。
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.interviews import router as interviews_router
from api.auth import router as auth_router
from api.projects import router as projects_router
from api.project_questionnaires import router as project_questionnaires_router
from api.project_key_bq import router as project_key_bq_router
from api.project_interviews import router as project_interviews_router
from api.interview_detail_fields import router as interview_detail_fields_router
from api.question_intents import router as question_intents_router
from db import list_recoverable_project_guides
from guide_workflow import process_project_guide
from InterviewLogger import log_project
from middleware.cors import setup_cors


app = FastAPI()
GUIDE_RECOVERY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="guide-recovery")

setup_cors(app)

app.include_router(projects_router)
app.include_router(project_questionnaires_router)
app.include_router(project_key_bq_router)
app.include_router(project_interviews_router)
app.include_router(interview_detail_fields_router)
app.include_router(question_intents_router)
app.include_router(interviews_router)
app.include_router(auth_router)


def _resume_pending_project_guides() -> None:
    """
    服务启动时恢复尚未完成的指南学习任务。
    """
    try:
        guides = list_recoverable_project_guides()
    except Exception as exc:
        log_project("GUIDE", None, f"startup recovery scan failed: {exc}")
        return

    if not guides:
        log_project("GUIDE", None, "startup recovery scan found no pending guide jobs")
        return

    for guide in guides:
        project_id = guide.get("project_id")
        if project_id is None:
            continue
        try:
            GUIDE_RECOVERY_EXECUTOR.submit(process_project_guide, int(project_id))
            log_project(
                "GUIDE",
                int(project_id),
                f"startup recovery queued guide_status={guide.get('guide_status')}",
            )
        except Exception as exc:
            log_project("GUIDE", int(project_id), f"startup recovery queue failed: {exc}")


@app.on_event("startup")
def _on_startup() -> None:
    """
    FastAPI 启动后恢复未完成的指南学习任务。
    """
    _resume_pending_project_guides()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=9000, reload=True)
