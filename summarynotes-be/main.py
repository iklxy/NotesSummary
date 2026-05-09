"@Date: 2026-04-15"
"@Author: lixinyang"

"""
SummaryNotes 后端 BFF 入口。

该模块负责创建 FastAPI 应用、注册 CORS 和各个业务路由，
并在命令行直接运行时启动本地开发/部署服务。
"""

import sys
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
from middleware.cors import setup_cors


app = FastAPI()

setup_cors(app)

app.include_router(projects_router)
app.include_router(project_questionnaires_router)
app.include_router(project_key_bq_router)
app.include_router(project_interviews_router)
app.include_router(interview_detail_fields_router)
app.include_router(question_intents_router)
app.include_router(interviews_router)
app.include_router(auth_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=9000, reload=True)
