import os
import time

import dotenv
import tos


dotenv.load_dotenv()

ak = os.getenv("TOS_ACCESS_KEY")
sk = os.getenv("TOS_SECRET_KEY")
endpoint = os.getenv("TOS_ENDPOINT", "https://tos-cn-shanghai.volces.com")
region = os.getenv("TOS_REGION", "cn-shanghai")
bucket_name = os.getenv("TOS_BUCKET_NAME", "benhealth")

CODE_SUCCESS = 0
CODE_TOS_CREDENTIALS_MISSING = 2001
CODE_TOS_CONFIG_INVALID = 2002
CODE_TOS_BUCKET_ACCESS_DENIED = 2003
CODE_TOS_UPLOAD_CLIENT_ERROR = 3001
CODE_TOS_UPLOAD_SERVER_ERROR = 3002
CODE_INTERNAL_UNKNOWN_ERROR = 5000


def make_response(success: bool, code: int, message: str, data: dict | None = None) -> dict:
    """
    构造统一的 TOS 存储层返回结果。

    参数:
        success: 是否成功。
        code: 业务返回码。
        message: 对结果的简短说明。
        data: 附加数据；为空时自动归一化为空字典。

    返回:
        标准化的结果字典，方便上层 API 直接透传。
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
    创建并返回一个 TOS 客户端。

    返回:
        已初始化的 TosClientV2 实例。

    异常:
        ValueError: 当 AK/SK、endpoint 或 region 未配置时抛出。
    """
    if not ak or not sk:
        raise ValueError("TOS credentials missing")
    if not endpoint or not region:
        raise ValueError("TOS endpoint/region config invalid")
    return tos.TosClientV2(ak, sk, endpoint, region)


def delete_remote_object(object_key: str) -> dict:
    """
    删除 TOS 上的单个音频对象。
    """
    if not object_key:
        return make_response(True, CODE_SUCCESS, "object key empty, skip delete", {})

    if not bucket_name:
        return make_response(
            False,
            CODE_TOS_BUCKET_ACCESS_DENIED,
            "tos bucket_name is not configured",
            {"object_key": object_key},
        )

    if not ak or not sk:
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
        client.delete_object(bucket_name, object_key)
    except tos.exceptions.TosClientError as e:
        return make_response(
            False,
            CODE_TOS_UPLOAD_CLIENT_ERROR,
            "tos delete client error",
            {
                "bucket_name": bucket_name,
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
                "bucket_name": bucket_name,
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
                "bucket_name": bucket_name,
                "object_key": object_key,
                "detail": str(e),
            },
        )

    return make_response(
        True,
        CODE_SUCCESS,
        "delete success",
        {"bucket_name": bucket_name, "object_key": object_key},
    )
