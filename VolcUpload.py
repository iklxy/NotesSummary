"@Date:2026-04-10"
"@author:lixinyang"

import os
import time
import json

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


def make_response(success: bool, code: int, message: str, data: dict | None = None) -> dict:
    """
    统一封装 Upload 模块的返回结构。

    参数:
        success: 是否调用成功，True 表示成功，False 表示失败。
        code: 业务错误码，0 表示成功，非 0 表示具体错误类型。
        message: 面向人类的简短说明，便于日志和排查。
        data: 业务数据或错误上下文信息，默认使用空 dict。

    返回:
        符合项目约定的 JSON 字典，包含 success/code/message/data 四个字段。
    """
    if data is None:
        data = {}
    return {
        "success": success,
        "code": code,
        "message": message,
        "data": data,
    }


def get_tos_client() -> tos.TosClientV2:
    """
    初始化并返回 TOS 客户端实例。

    参数:
        无参数，直接使用模块级别的 ak/sk/endpoint/region 配置。

    返回:
        已完成配置的 TosClientV2 客户端实例。

    说明:
        在创建客户端之前会对 AK/SK 和 endpoint/region 做最小校验，
        如果缺失或非法会直接抛出 ValueError。
    """
    if not config.TOS_ACCESS_KEY or not config.TOS_SECRET_KEY:
        raise ValueError("TOS credentials missing")
    if not config.TOS_ENDPOINT or not config.TOS_REGION:
        raise ValueError("TOS endpoint/region config invalid")
    client = tos.TosClientV2(
        config.TOS_ACCESS_KEY,
        config.TOS_SECRET_KEY,
        config.TOS_ENDPOINT,
        config.TOS_REGION,
    )
    return client


def build_local_file_path(project_id: int, interview_id: int, file_name: str) -> str:
    """
    根据项目和访谈信息构造本地音频完整路径。

    参数:
        project_id: 项目 ID，对应 bh_project.id。
        interview_id: 访谈 ID，对应 bh_project_interview.id。
        file_name: 音频文件名，例如 xxx.wav。

    返回:
        拼接后的本地音频完整路径。

    说明:
        路径结构遵循文档约定：
        LOCAL_AUDIO_ROOT/project_{project_id}/interview_{interview_id}/{file_name}
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
        project_id: 项目 ID，对应 bh_project.id。
        interview_id: 访谈 ID，对应 bh_project_interview.id。
        file_name: 音频文件名，用于组成对象 key 的最后一段。

    返回:
        对象 key 字符串，例如 audio/project_1/interview_2/xxx.wav。

    说明:
        使用统一前缀 + 项目/访谈分层，保证 TOS 中对象路径结构化，
        有利于后续按项目或访谈维度检索与排查。
    """
    return "/".join(
        [
            config.TOS_AUDIO_PREFIX.rstrip("/"),
            f"project_{project_id}",
            f"interview_{interview_id}",
            file_name,
        ]
    )


def upload_local_file(local_file_path: str, object_key: str) -> dict:
    """
    将本地音频文件上传到 TOS，并生成预签名访问 URL。

    参数:
        local_file_path: 本地音频文件的绝对或相对路径。
        object_key: 上传到 TOS 的对象 key（不包含 bucket 名）。

    返回:
        符合项目 JSON 约定的字典，包含 success/code/message/data 四个字段。

    关键逻辑:
        1. 校验本地文件是否存在且可读。
        2. 校验 TOS 基础配置是否完整。
        3. 调用 TOS SDK 完成上传并生成预签名 URL。
        4. 将结果包装为统一 JSON 返回给上层调用方。
    """
    if not local_file_path:
        return make_response(
            False,
            CODE_LOCAL_FILE_NOT_FOUND,
            "local_file_path is empty",
            {"local_file_path": local_file_path},
        )

    if not os.path.exists(local_file_path) or not os.path.isfile(local_file_path):
        return make_response(
            False,
            CODE_LOCAL_FILE_NOT_FOUND,
            "local audio file not found",
            {"local_file_path": os.path.abspath(local_file_path)},
        )

    if not os.access(local_file_path, os.R_OK):
        return make_response(
            False,
            CODE_LOCAL_FILE_NOT_READABLE,
            "local audio file not readable",
            {"local_file_path": os.path.abspath(local_file_path)},
        )

    if not config.TOS_BUCKET_NAME:
        return make_response(
            False,
            CODE_TOS_BUCKET_ACCESS_DENIED,
            "tos bucket_name is not configured",
            {},
        )

    if not config.TOS_ACCESS_KEY or not config.TOS_SECRET_KEY:
        return make_response(
            False,
            CODE_TOS_CREDENTIALS_MISSING,
            "tos credentials missing",
            {},
        )

    try:
        client = get_tos_client()
    except ValueError as e:
        return make_response(
            False,
            CODE_TOS_CONFIG_INVALID,
            "tos config invalid",
            {"detail": str(e)},
        )

    start_time = time.time()
    try:
        # 上传本地文件到 TOS，对象名为 object_key
        resp = client.put_object_from_file(config.TOS_BUCKET_NAME, object_key, local_file_path)
    except tos.exceptions.TosClientError as e:
        # 客户端异常：如网络错误、签名错误等
        return make_response(
            False,
            CODE_TOS_UPLOAD_CLIENT_ERROR,
            "tos upload client error",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "local_file_path": os.path.abspath(local_file_path),
                "tos_error_type": "TosClientError",
                "tos_error_message": getattr(e, "message", str(e)),
            },
        )
    except tos.exceptions.TosServerError as e:
        # 服务端异常：TOS 返回 5xx 或业务错误码
        return make_response(
            False,
            CODE_TOS_UPLOAD_SERVER_ERROR,
            "tos upload server error",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "local_file_path": os.path.abspath(local_file_path),
                "tos_status_code": getattr(e, "status_code", None),
                "tos_error_code": getattr(e, "code", None),
                "tos_error_message": getattr(e, "message", str(e)),
            },
        )
    except Exception as e:
        # 未知异常统一收敛为内部错误
        return make_response(
            False,
            CODE_INTERNAL_UNKNOWN_ERROR,
            "internal unknown error when uploading to tos",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "local_file_path": os.path.abspath(local_file_path),
                "detail": str(e),
            },
        )

    if not hasattr(resp, "status_code") or not (200 <= resp.status_code < 300):
        # 上传返回非 2xx 视为失败
        return make_response(
            False,
            CODE_TOS_UPLOAD_SERVER_ERROR,
            "tos upload server error: non-2xx status code",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "local_file_path": os.path.abspath(local_file_path),
                "tos_status_code": getattr(resp, "status_code", None),
            },
        )

    try:
        # 生成音频访问的预签名 URL，供后续 ASR 使用
        pre = client.pre_signed_url(
            tos.HttpMethodType.Http_Method_Get,
            bucket=config.TOS_BUCKET_NAME,
            key=object_key,
            expires=config.TOS_URL_EXPIRE_SECONDS,
        )
        audio_url = pre.signed_url
    except Exception as e:
        # 预签名 URL 生成失败，单独打一个错误码，便于排查
        return make_response(
            False,
            CODE_TOS_PRESIGNED_URL_ERROR,
            "failed to generate presigned url",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "detail": str(e),
            },
        )

    elapsed = time.time() - start_time
    data = {
        "project_id": None,
        "interview_id": None,
        "file_name": os.path.basename(local_file_path),
        "object_key": object_key,
        "bucket_name": config.TOS_BUCKET_NAME,
        "audio_url": audio_url,
        "status": "uploaded",
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(elapsed, 3),
    }

    return make_response(True, CODE_SUCCESS, "upload success", data)


def delete_remote_object(object_key: str) -> dict:
    """
    删除 TOS 上的单个音频对象。

    参数:
        object_key: TOS 对象 key，例如 audio/project_1/interview_2/xxx.wav。

    返回:
        统一 JSON 结构，success=True 表示删除成功或对象已不存在。
    """
    if not object_key:
        return make_response(True, CODE_SUCCESS, "object key empty, skip delete", {})

    if not config.TOS_BUCKET_NAME:
        return make_response(
            False,
            CODE_TOS_BUCKET_ACCESS_DENIED,
            "tos bucket_name is not configured",
            {"object_key": object_key},
        )

    if not config.TOS_ACCESS_KEY or not config.TOS_SECRET_KEY:
        return make_response(
            False,
            CODE_TOS_CREDENTIALS_MISSING,
            "tos credentials missing",
            {"object_key": object_key},
        )

    try:
        client = get_tos_client()
    except ValueError as e:
        return make_response(
            False,
            CODE_TOS_CONFIG_INVALID,
            "tos config invalid",
            {"object_key": object_key, "detail": str(e)},
        )

    try:
        client.delete_object(config.TOS_BUCKET_NAME, object_key)
    except tos.exceptions.TosClientError as e:
        return make_response(
            False,
            CODE_TOS_UPLOAD_CLIENT_ERROR,
            "tos delete client error",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "tos_error_type": "TosClientError",
                "tos_error_message": getattr(e, "message", str(e)),
            },
        )
    except tos.exceptions.TosServerError as e:
        return make_response(
            False,
            CODE_TOS_UPLOAD_SERVER_ERROR,
            "tos delete server error",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "tos_status_code": getattr(e, "status_code", None),
                "tos_error_code": getattr(e, "code", None),
                "tos_error_message": getattr(e, "message", str(e)),
            },
        )
    except Exception as e:
        return make_response(
            False,
            CODE_INTERNAL_UNKNOWN_ERROR,
            "internal unknown error when deleting from tos",
            {
                "bucket_name": config.TOS_BUCKET_NAME,
                "object_key": object_key,
                "detail": str(e),
            },
        )

    return make_response(
        True,
        CODE_SUCCESS,
        "delete success",
        {"bucket_name": config.TOS_BUCKET_NAME, "object_key": object_key},
    )
