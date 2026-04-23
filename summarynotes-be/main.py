"@Date: 2026-04-15"
"@Author: lixinyang"

import sys
from pathlib import Path

from fastapi import FastAPI

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from api.interviews import router as interviews_router
from api.projects import router as projects_router
from api.project_interviews import router as project_interviews_router
from api.question_intents import router as question_intents_router
from middleware.cors import setup_cors


app = FastAPI()

setup_cors(app)

app.include_router(projects_router)
app.include_router(project_interviews_router)
app.include_router(question_intents_router)
app.include_router(interviews_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=9000, reload=True)
