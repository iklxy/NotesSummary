import os
import socket
import subprocess

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _detect_primary_ip() -> str | None:
    """
    尝试探测当前机器的主网卡 IP。

    返回:
        探测到的 IPv4 字符串；如果探测失败则返回 None。
    """
    env_ip = os.getenv("PRIMARY_IP")
    if env_ip:
        return env_ip.strip() or None

    try:
        output = subprocess.check_output(["hostname", "-I"], text=True).strip()
        if output:
            return output.split()[0]
    except Exception:
        pass

    try:
        host_ip = socket.gethostbyname(socket.gethostname())
        if host_ip and not host_ip.startswith("127."):
            return host_ip
    except Exception:
        pass

    return None


def setup_cors(app: FastAPI) -> None:
    """
    为 FastAPI 应用注册跨域中间件。

    参数:
        app: 需要安装 CORS 的 FastAPI 实例。
    """
    origins = {
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:9000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:9000",
    }

    primary_ip = _detect_primary_ip()
    if primary_ip:
        origins.add(f"http://{primary_ip}:3000")
        origins.add(f"http://{primary_ip}:3001")
        origins.add(f"http://{primary_ip}:9000")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
