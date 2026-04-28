import { request } from "./apiClient";
import type { AuthUser } from "./types";

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  success: boolean;
  user?: AuthUser | null;
  message?: string | null;
}

export interface CurrentUserResponse {
  authenticated: boolean;
  user?: AuthUser | null;
}

export interface LogoutResponse {
  success: boolean;
  message?: string | null;
}

/**
 * 发起登录请求。
 *
 * 参数:
 *   payload: 登录表单提交的数据，包含用户名和明文密码。
 *
 * 返回:
 *   后端返回的登录结果，成功时通常会设置 cookie/session。
 */
export function login(payload: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>("/api/auth/login", {
    method: "POST",
    credentials: "include",
    body: JSON.stringify(payload),
  });
}

/**
 * 查询当前浏览器会话对应的登录用户。
 *
 * 返回:
 *   包含 authenticated 标记和当前用户信息的响应。
 */
export function getCurrentUser(): Promise<CurrentUserResponse> {
  return request<CurrentUserResponse>("/api/auth/me", {
    method: "GET",
    credentials: "include",
  });
}

/**
 * 退出当前登录会话。
 *
 * 返回:
 *   退出结果。
 */
export function logout(): Promise<LogoutResponse> {
  return request<LogoutResponse>("/api/auth/logout", {
    method: "POST",
    credentials: "include",
  });
}
