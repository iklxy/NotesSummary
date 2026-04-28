from fastapi import APIRouter, Cookie, HTTPException, Response

from db import fetch_user_by_id, fetch_user_by_username
from schemas.auth import (
    AuthCurrentUserResponse,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthLogoutResponse,
    AuthUserItem,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])

USER_ID_COOKIE = "bh_user_id"


def _to_user_item(row: dict) -> AuthUserItem:
    """
    将数据库用户记录转换为前端需要的最小登录态结构。

    参数:
        row: 从 bh_user 表查询得到的用户字典。

    返回:
        仅包含 id 和 username 的 AuthUserItem。
    """
    return AuthUserItem(id=int(row["id"]), username=str(row["username"]))


def require_current_user_id(bh_user_id: int | None = Cookie(default=None)) -> int:
    """
    从 Cookie 中读取当前登录用户 ID；若未登录则直接抛出 401。

    参数:
        bh_user_id: 从 Cookie 中读取的用户 ID。

    返回:
        当前登录用户的数值型 ID。
    """
    if bh_user_id is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return int(bh_user_id)


@router.post("/login", response_model=AuthLoginResponse)
def login(payload: AuthLoginRequest, response: Response) -> AuthLoginResponse:
    """
    校验用户名与明文密码，成功后写入简单登录 Cookie。

    参数:
        payload: 登录请求体，包含 username 和 password。
        response: FastAPI 响应对象，用于写入 cookie。

    返回:
        登录结果。成功时包含用户信息，并在响应里设置 bh_user_id cookie。

    异常:
        HTTPException(401): 用户不存在或密码不匹配。
    """
    username = payload.username.strip()
    password = payload.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    row = fetch_user_by_username(username)
    if not row:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    stored_password = row.get("password_hash")
    if stored_password is None or str(stored_password) != password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user_item = _to_user_item(row)
    response.set_cookie(
        key=USER_ID_COOKIE,
        value=str(user_item.id),
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )
    return AuthLoginResponse(success=True, user=user_item)


@router.get("/me", response_model=AuthCurrentUserResponse)
def current_user(bh_user_id: int | None = Cookie(default=None)) -> AuthCurrentUserResponse:
    """
    查询当前 Cookie 里绑定的登录用户。

    参数:
        bh_user_id: 从 Cookie 中读取的用户 ID；如果未登录则为空。

    返回:
        authenticated=True 时携带 user；否则返回 authenticated=False。
    """
    if bh_user_id is None:
        return AuthCurrentUserResponse(authenticated=False)

    row = fetch_user_by_id(int(bh_user_id))
    if not row:
        return AuthCurrentUserResponse(authenticated=False)

    return AuthCurrentUserResponse(authenticated=True, user=_to_user_item(row))


@router.post("/logout", response_model=AuthLogoutResponse)
def logout(response: Response) -> AuthLogoutResponse:
    """
    清理当前登录 Cookie。

    参数:
        response: FastAPI 响应对象，用于删除 cookie。

    返回:
        success=True 表示已清理登录态。
    """
    response.delete_cookie(key=USER_ID_COOKIE, path="/")
    return AuthLogoutResponse(success=True)
