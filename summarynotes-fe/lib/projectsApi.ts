import { getBaseUrl, request } from "./apiClient";
import type {
  DeleteProjectResponse,
  GenerateProjectCaTableRequest,
  GenerateProjectCaTableResponse,
  Project,
  ProjectDetail,
  ProjectCaTableResponse,
  ProjectCaTablesResponse,
} from "./types";

interface CreateProjectPayload {
  name: string;
  guide_files?: File[] | null;
}

interface UpdateProjectPayload {
  name: string;
}

async function submitProjectGuideUpload(
  url: string,
  guideFiles: File[],
): Promise<Project> {
  const formData = new FormData();
  guideFiles.forEach((file) => {
    formData.append("guide_file", file);
  });
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const resp = await fetch(`${baseUrl}${url}`, {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text();
    }
    throw new Error(`guide upload failed: ${JSON.stringify(detail)}`);
  }
  return (await resp.json()) as Project;
}

export async function createProject(payload: CreateProjectPayload): Promise<Project> {
  const formData = new FormData();
  formData.append("name", payload.name);
  if (payload.guide_files) {
    payload.guide_files.forEach((file) => {
      formData.append("guide_file", file);
    });
  }
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const resp = await fetch(`${baseUrl}/api/projects`, {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text();
    }
    throw new Error(`create project failed: ${JSON.stringify(detail)}`);
  }
  return (await resp.json()) as Project;
}

export function getProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export function getProjectDetail(projectId: number): Promise<ProjectDetail> {
  return request<ProjectDetail>(`/api/projects/${projectId}`);
}

export function updateProject(projectId: number, payload: UpdateProjectPayload): Promise<Project> {
  return request<Project>(`/api/projects/${projectId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function uploadProjectGuide(
  projectId: number,
  guideFiles: File[],
): Promise<Project> {
  return submitProjectGuideUpload(`/api/projects/${projectId}/guide`, guideFiles);
}

export function deleteProject(projectId: number): Promise<DeleteProjectResponse> {
  return request<DeleteProjectResponse>(`/api/projects/${projectId}`, {
    method: "DELETE",
  });
}

export function getProjectCaTable(projectId: number, questionnaireId?: number): Promise<ProjectCaTableResponse> {
  const query = questionnaireId && questionnaireId > 0 ? `?questionnaire_id=${questionnaireId}` : "";
  return request<ProjectCaTableResponse>(`/api/projects/${projectId}/ca-table${query}`);
}

export function getProjectCaTables(projectId: number): Promise<ProjectCaTablesResponse> {
  return request<ProjectCaTablesResponse>(`/api/projects/${projectId}/ca-tables`);
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

export function saveProjectCaFramework(
  projectId: number,
  payload: Record<string, unknown>,
): Promise<GenerateProjectCaTableResponse> {
  return request<GenerateProjectCaTableResponse>(`/api/projects/${projectId}/ca-table/framework`, {
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

export async function exportProjectCaTableWord(
  projectId: number,
  payload: Record<string, unknown>,
): Promise<{ blob: Blob; filename: string }> {
  const resp = await fetch(`/api/projects/${projectId}/ca/export-word`, {
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
    throw new Error(`export ca word failed: ${JSON.stringify(detail)}`);
  }
  const contentDisposition = resp.headers.get("content-disposition") || "";
  const filenameStarMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  let filename = `project_${projectId}_CA_单行总结.docx`;
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
