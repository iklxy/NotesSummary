"@Date: 2026-04-15"
"@Author: lixinyang"

from fastapi import FastAPI

from api.interviews import router as interviews_router
from api.projects import router as projects_router
from api.project_interviews import router as project_interviews_router
from middleware.cors import setup_cors


app = FastAPI()

setup_cors(app)

app.include_router(projects_router)
app.include_router(project_interviews_router)
app.include_router(interviews_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=9000, reload=True)
