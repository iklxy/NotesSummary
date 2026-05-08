import { request } from "./apiClient";
import type {
  DeleteProjectResponse,
  GenerateProjectCaTableRequest,
  GenerateProjectCaTableResponse,
  Project,
  ProjectCaTableResponse,
} from "./types";

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

export function getProjectCaTable(projectId: number): Promise<ProjectCaTableResponse> {
  return request<ProjectCaTableResponse>(`/api/projects/${projectId}/ca-table`);
}

export function generateProjectCaTable(
  projectId: number,
  payload: GenerateProjectCaTableRequest,
): Promise<GenerateProjectCaTableResponse> {
  return request<GenerateProjectCaTableResponse>(`/api/projects/${projectId}/ca-table/generate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function exportProjectCaTableXlsx(
  projectId: number,
  payload: Record<string, unknown>,
): Promise<{ blob: Blob; filename: string }> {
  const resp = await fetch(`/api/projects/${projectId}/ca/export-xlsx`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    credentials: "include",
  });
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text();
    }
    throw new Error(`export ca xlsx failed: ${JSON.stringify(detail)}`);
  }
  const contentDisposition = resp.headers.get("content-disposition") || "";
  const filenameStarMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  let filename = `project_${projectId}_CA.xlsx`;
  if (filenameStarMatch?.[1]) {
    try {
      filename = decodeURIComponent(filenameStarMatch[1]);
    } catch {
      filename = filenameStarMatch[1];
    }
  } else if (filenameMatch?.[1]) {
    filename = filenameMatch[1];
  }
  return {
    blob: await resp.blob(),
    filename,
  };
}
