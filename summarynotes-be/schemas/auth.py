from typing import Optional

from pydantic import BaseModel


class AuthUserItem(BaseModel):
    """
    系统登录用户的最小返回结构。

    字段:
        id: 用户主键 ID。
        username: 登录用户名。
    """

    id: int
    username: str


class AuthLoginRequest(BaseModel):
    """
    登录接口请求体。

    字段:
        username: 登录用户名。
        password: 明文密码。
    """

    username: str
    password: str


class AuthLoginResponse(BaseModel):
    """
    登录接口返回体。

    字段:
        success: 是否登录成功。
        user: 登录成功后返回的用户信息。
        message: 登录失败时的提示信息。
    """

    success: bool
    user: Optional[AuthUserItem] = None
    message: Optional[str] = None


class AuthCurrentUserResponse(BaseModel):
    """
    当前登录用户查询接口返回体。

    字段:
        authenticated: 当前请求是否已经处于登录状态。
        user: 当前登录用户信息。
    """

    authenticated: bool
    user: Optional[AuthUserItem] = None


class AuthLogoutResponse(BaseModel):
    """
    退出登录接口返回体。

    字段:
        success: 是否成功清理登录态。
    """

    success: bool
