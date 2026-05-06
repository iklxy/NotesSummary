from fastapi import APIRouter


router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check() -> dict:
    """
    健康检查接口，供部署探活和快速确认服务可用性。

    返回:
        仅包含 `status=ok` 的简单 JSON。
    """
    return {"status": "ok"}
