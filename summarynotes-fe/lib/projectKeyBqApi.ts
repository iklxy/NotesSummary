import { request } from "./apiClient";
import type { ProjectKeyBq, ProjectKeyBqSingleton } from "./types";

export function getProjectKeyBqCurrent(projectId: number): Promise<ProjectKeyBqSingleton> {
  return request<ProjectKeyBqSingleton>(`/api/projects/${projectId}/key-bq/current`);
}

export function updateProjectKeyBqCurrent(
  projectId: number,
  payload: { key_bq_json: unknown },
): Promise<ProjectKeyBqSingleton> {
  return request<ProjectKeyBqSingleton>(`/api/projects/${projectId}/key-bq/current`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function getProjectKeyBqGroups(projectId: number): Promise<ProjectKeyBq[]> {
  return request<ProjectKeyBq[]>(`/api/projects/${projectId}/key-bq`);
}

export function getProjectKeyBqGroup(
  projectId: number,
  keyBqId: number,
): Promise<ProjectKeyBq> {
  return request<ProjectKeyBq>(`/api/projects/${projectId}/key-bq/${keyBqId}`);
}

export function createProjectKeyBq(
  projectId: number,
  payload: { name: string; key_bq_json: unknown },
): Promise<ProjectKeyBq> {
  return request<ProjectKeyBq>(`/api/projects/${projectId}/key-bq`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProjectKeyBq(
  projectId: number,
  keyBqId: number,
  payload: { name?: string | null; key_bq_json?: unknown },
): Promise<ProjectKeyBq> {
  return request<ProjectKeyBq>(`/api/projects/${projectId}/key-bq/${keyBqId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteProjectKeyBq(
  projectId: number,
  keyBqId: number,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/projects/${projectId}/key-bq/${keyBqId}`, {
    method: "DELETE",
  });
}
