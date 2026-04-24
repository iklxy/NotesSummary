"@Date:2026-04-10"
"@author:lixinyang"

import os
import time
from typing import Any, Dict

import tos

from config import config

# JSON错误码约定
CODE_SUCCESS = 0  # 调用成功
CODE_INVALID_INTERVIEW_ID = 1001  # interview_id 参数缺失或格式非法
CODE_INTERVIEW_NOT_FOUND = 1002  # 数据库中找不到对应的访谈记录
CODE_INVALID_PROJECT_ID = 1003  # 访谈记录中的项目 ID 非法或为空
CODE_LOCAL_FILE_NOT_FOUND = 1004  # 本地音频文件不存在
CODE_LOCAL_FILE_NOT_READABLE = 1005  # 本地音频文件存在但不可读

CODE_TOS_CREDENTIALS_MISSING = 2001  # TOS 访问密钥未配置（AK/SK 缺失）
CODE_TOS_CONFIG_INVALID = 2002  # TOS endpoint/region 等基础配置非法
CODE_TOS_BUCKET_ACCESS_DENIED = 2003  # TOS bucket 不存在或当前凭证无访问权限

CODE_TOS_UPLOAD_CLIENT_ERROR = 3001  # TOS 上传时发生客户端异常（网络、签名等）
CODE_TOS_UPLOAD_SERVER_ERROR = 3002  # TOS 上传时服务端返回错误（5xx 或业务错误码）
CODE_TOS_PRESIGNED_URL_ERROR = 3003  # 预签名 URL 生成失败

CODE_DB_CONNECTION_ERROR = 4001  # 数据库连接失败
CODE_DB_QUERY_INTERVIEW_ERROR = 4002  # 查询访谈记录 SQL 失败
CODE_DB_UPDATE_INTERVIEW_ERROR = 4003  # 上传后回写访谈状态失败

CODE_INTERNAL_UNKNOWN_ERROR = 5000  # 其他未归类的内部未知错误


# ----------------------------------------------------------------------
# 响应封装
# ----------------------------------------------------------------------
def make_response(success: bool, code: int, message: str, data: dict | None = None) -> dict:
    """
    统一封装上传模块的返回结构。

    参数:
        success: 当前调用是否成功。
        code: 业务错误码，0 表示成功，非 0 表示具体错误类型。
        message: 面向日志与排查的简短说明。
        data: 附带的业务数据或错误上下文；为空时自动补成空字典。

    返回:
        包含 `success`、`code`、`message`、`data` 四个字段的响应字典。
    """
    if data is None:
        data = {}
    return {
        "success": success,
        "code": code,
        "message": message,
        "data": data,
    }


# ----------------------------------------------------------------------
# 配置校验与客户端初始化
# ----------------------------------------------------------------------
def _validate_tos_config() -> None:
    """
    校验 TOS 访问所需的关键配置项是否完整。

    参数:
        无。所有配置均从 `config` 中读取。

    返回:
        无返回值。若配置不合法则直接抛出 `ValueError`。

    异常:
        ValueError: 当访问密钥、endpoint 或 region 缺失时抛出。
    """
    if not config.TOS_ACCESS_KEY or not config.TOS_SECRET_KEY:
        raise ValueError("TOS credentials missing")
    if not config.TOS_ENDPOINT or not config.TOS_REGION:
        raise ValueError("TOS endpoint/region config invalid")


def _validate_bucket_config() -> None:
    """
    校验 TOS bucket 配置是否存在。

    参数:
        无。bucket 名称统一从 `config.TOS_BUCKET_NAME` 读取。

    返回:
        无返回值。若 bucket 未配置则抛出 `ValueError`。
    """
    if not config.TOS_BUCKET_NAME:
        raise ValueError("TOS bucket_name is not configured")


def _validate_local_file(local_file_path: str) -> None:
    """
    校验本地待上传音频文件是否存在且可读。

    参数:
        local_file_path: 本地音频文件路径，允许为绝对路径或相对路径。

    返回:
        无返回值。若文件路径非法则抛出 `ValueError` 或 `FileNotFoundError`。

    异常:
        ValueError: 当路径为空时抛出。
        FileNotFoundError: 当文件不存在时抛出。
        PermissionError: 当文件存在但不可读时抛出。
    """
    if not local_file_path:
        raise ValueError("local_file_path is empty")
    if not os.path.exists(local_file_path) or not os.path.isfile(local_file_path):
        raise FileNotFoundError(local_file_path)
    if not os.access(local_file_path, os.R_OK):
        raise PermissionError(local_file_path)


def get_tos_client() -> tos.TosClientV2:
    """
    初始化并返回 TOS 客户端实例。

    参数:
        无。客户端初始化所需配置统一从 `config` 中读取。

    返回:
        已完成初始化的 `tos.TosClientV2` 实例。

    异常:
        ValueError: 当访问凭证、endpoint 或 region 缺失时抛出。
    """
    _validate_tos_config()
    return tos.TosClientV2(
        config.TOS_ACCESS_KEY,
        config.TOS_SECRET_KEY,
        config.TOS_ENDPOINT,
        config.TOS_REGION,
    )


# ----------------------------------------------------------------------
# 路径与对象 key 构造
# ----------------------------------------------------------------------
def build_local_file_path(project_id: int, interview_id: int, file_name: str) -> str:
    """
    根据项目和访谈信息构造本地音频文件路径。

    参数:
        project_id: 项目主键 ID，对应 `bh_project.id`。
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
        file_name: 音频文件名，例如 `xxx.wav`。

    返回:
        本地音频完整路径，格式遵循：
        `LOCAL_AUDIO_ROOT/project_{project_id}/interview_{interview_id}/{file_name}`。
    """
    return os.path.join(
        config.LOCAL_AUDIO_ROOT,
        f"project_{project_id}",
        f"interview_{interview_id}",
        file_name,
    )


def build_object_key(project_id: int, interview_id: int, file_name: str) -> str:
    """
    根据项目和访谈信息构造 TOS 对象 key。

    参数:
        project_id: 项目主键 ID，对应 `bh_project.id`。
        interview_id: 访谈主键 ID，对应 `bh_project_interview.id`。
        file_name: 音频文件名，将作为对象 key 的最后一段。

    返回:
        TOS 对象 key，例如 `audio/project_1/interview_2/xxx.wav`。
    """
    return "/".join(
        [
            config.TOS_AUDIO_PREFIX.rstrip("/"),
            f"project_{project_id}",
            f"interview_{interview_id}",
            file_name,
        ]
    )


# ----------------------------------------------------------------------
# TOS 操作
# ----------------------------------------------------------------------
def _put_object_from_file(
    client: tos.TosClientV2,
    object_key: str,
    local_file_path: str,
) -> Any:
    """
    调用 TOS SDK 上传本地文件。

    参数:
        client: 已初始化完成的 TOS 客户端。
        object_key: 上传目标对象 key。
        local_file_path: 本地待上传文件路径。

    返回:
        TOS SDK 返回的上传响应对象。
    """
    return client.put_object_from_file(config.TOS_BUCKET_NAME, object_key, local_file_path)


def _build_presigned_audio_url(client: tos.TosClientV2, object_key: str) -> str:
    """
    为已上传的音频对象生成预签名访问 URL。

    参数:
        client: 已初始化完成的 TOS 客户端。
        object_key: 已上传对象的 key。

    返回:
        可供 ASR 服务拉取音频的预签名 URL。
    """
    signed = client.pre_signed_url(
        tos.HttpMethodType.Http_Method_Get,
        bucket=config.TOS_BUCKET_NAME,
        key=object_key,
        expires=config.TOS_URL_EXPIRE_SECONDS,
    )
    return signed.signed_url


def upload_local_file(local_file_path: str, object_key: str) -> dict:
    """
    将本地音频文件上传到 TOS，并生成后续 ASR 可用的预签名 URL。

    参数:
        local_file_path: 本地音频文件路径。
        object_key: 上传到 TOS 的对象 key，不包含 bucket 名。

    返回:
        统一响应字典。成功时 `data` 至少包含：
            - file_name
            - object_key
            - bucket_name
            - audio_url
            - status
            - uploaded_at
            - elapsed_seconds
    """
    try:
        _validate_local_file(local_file_path)
    except ValueError:
        return make_response(
            False,
            CODE_LOCAL_FILE_NOT_FOUND,
            "local_file_path is empty",
            {"local_file_path": local_file_path},
        )
    except FileNotFoundError:
        return make_response(
            False,
            CODE_LOCAL_FILE_NOT_FOUND,
            "local audio file not found",
            {"local_file_path": os.path.abspath(local_file_path)},
        )
    except PermissionError:
        return make_response(
            False,
            CODE_LOCAL_FILE_NOT_READABLE,
            "local audio file not readable",
            {"local_file_path": os.path.abspath(local_file_path)},
        )

    try:
        _validate_bucket_config()
        client = get_tos_client()
    except ValueError as error:
        message = str(error)
        if "bucket" in message.lower():
            return make_response(False, CODE_TOS_BUCKET_ACCESS_DENIED, message, {})
        if "credentials" in message.lower():
            return make_response(False, CODE_TOS_CREDENTIALS_MISSING, message, {})
        return make_response(False, CODE_TOS_CONFIG_INVALID, "tos config invalid", {"detail": message})

    started_at = time.time()
    try:
        response = _put_object_from_file(client, object_key, local_file_path)
    except tos.exceptions.TosClientError as error:
        return make_response(
            False,
            CODE_TOS_UPLOAD_CLIENT_ERROR,
            "tos upload client error",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "local_file_path": os.path.abspath(local_file_path),
                "tos_error_type": "TosClientError",
                "tos_error_message": getattr(error, "message", str(error)),
            },
        )
    except tos.exceptions.TosServerError as error:
        return make_response(
            False,
            CODE_TOS_UPLOAD_SERVER_ERROR,
            "tos upload server error",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "local_file_path": os.path.abspath(local_file_path),
                "tos_status_code": getattr(error, "status_code", None),
                "tos_error_code": getattr(error, "code", None),
                "tos_error_message": getattr(error, "message", str(error)),
            },
        )
    except Exception as error:
        return make_response(
            False,
            CODE_INTERNAL_UNKNOWN_ERROR,
            "internal unknown error when uploading to tos",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "local_file_path": os.path.abspath(local_file_path),
                "detail": str(error),
            },
        )

    if not hasattr(response, "status_code") or not (200 <= response.status_code < 300):
        return make_response(
            False,
            CODE_TOS_UPLOAD_SERVER_ERROR,
            "tos upload server error: non-2xx status code",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "local_file_path": os.path.abspath(local_file_path),
                "tos_status_code": getattr(response, "status_code", None),
            },
        )

    try:
        audio_url = _build_presigned_audio_url(client, object_key)
    except Exception as error:
        return make_response(
            False,
            CODE_TOS_PRESIGNED_URL_ERROR,
            "failed to generate presigned url",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "detail": str(error),
            },
        )

    elapsed = time.time() - started_at
    return make_response(
        True,
        CODE_SUCCESS,
        "upload success",
        {
            "project_id": None,
            "interview_id": None,
            "file_name": os.path.basename(local_file_path),
            "object_key": object_key,
            "bucket_name": config.TOS_BUCKET_NAME,
            "audio_url": audio_url,
            "status": "uploaded",
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(elapsed, 3),
        },
    )


def delete_remote_object(object_key: str) -> dict:
    """
    删除 TOS 上的单个对象。

    参数:
        object_key: TOS 对象 key，例如 `audio/project_1/interview_2/xxx.wav`。

    返回:
        统一响应字典。`success=True` 表示删除成功，或因空 key 被主动跳过。
    """
    if not object_key:
        return make_response(True, CODE_SUCCESS, "object key empty, skip delete", {})

    try:
        _validate_bucket_config()
        client = get_tos_client()
    except ValueError as error:
        message = str(error)
        if "bucket" in message.lower():
            return make_response(False, CODE_TOS_BUCKET_ACCESS_DENIED, message, {"object_key": object_key})
        if "credentials" in message.lower():
            return make_response(False, CODE_TOS_CREDENTIALS_MISSING, message, {"object_key": object_key})
        return make_response(
            False,
            CODE_TOS_CONFIG_INVALID,
            "tos config invalid",
            {"object_key": object_key, "detail": message},
        )

    try:
        client.delete_object(config.TOS_BUCKET_NAME, object_key)
    except tos.exceptions.TosClientError as error:
        return make_response(
            False,
            CODE_TOS_UPLOAD_CLIENT_ERROR,
            "tos delete client error",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "tos_error_type": "TosClientError",
                "tos_error_message": getattr(error, "message", str(error)),
            },
        )
    except tos.exceptions.TosServerError as error:
        return make_response(
            False,
            CODE_TOS_UPLOAD_SERVER_ERROR,
            "tos delete server error",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "tos_status_code": getattr(error, "status_code", None),
                "tos_error_code": getattr(error, "code", None),
                "tos_error_message": getattr(error, "message", str(error)),
            },
        )
    except Exception as error:
        return make_response(
            False,
            CODE_INTERNAL_UNKNOWN_ERROR,
            "internal unknown error when deleting from tos",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "detail": str(error),
            },
        )

    return make_response(
        True,
        CODE_SUCCESS,
        "delete success",
        {"bucket_name": config.TOS_BUCKET_NAME, "object_key": object_key},
    )
