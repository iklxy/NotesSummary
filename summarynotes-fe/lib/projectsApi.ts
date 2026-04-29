import { request } from "./apiClient";
import type { DeleteProjectResponse, Project } from "./types";

interface CreateProjectPayload {
  name: string;
  keywords?: string;
  core_problem?: string;
}

export function createProject(payload: CreateProjectPayload): Promise<Project> {
  return request<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export function deleteProject(projectId: number): Promise<DeleteProjectResponse> {
  return request<DeleteProjectResponse>(`/api/projects/${projectId}`, {
    method: "DELETE",
  });
}
