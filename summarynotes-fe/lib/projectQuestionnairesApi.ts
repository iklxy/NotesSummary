import { getBaseUrl, request } from "./apiClient";
import type { ProjectQuestionnaire } from "./types";

export function getProjectQuestionnaires(projectId: number): Promise<ProjectQuestionnaire[]> {
  return request<ProjectQuestionnaire[]>(`/api/projects/${projectId}/questionnaires`);
}

export function getProjectQuestionnaire(
  projectId: number,
  questionnaireId: number,
): Promise<ProjectQuestionnaire> {
  return request<ProjectQuestionnaire>(
    `/api/projects/${projectId}/questionnaires/${questionnaireId}`,
  );
}

export async function createProjectQuestionnaire(
  projectId: number,
  formData: FormData,
): Promise<ProjectQuestionnaire> {
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const url = `${baseUrl}/api/projects/${projectId}/questionnaires`;
  const resp = await fetch(url, {
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
    throw new Error(`create questionnaire failed: ${JSON.stringify(detail)}`);
  }
  return (await resp.json()) as ProjectQuestionnaire;
}

export function updateProjectQuestionnaireHotwords(
  projectId: number,
  questionnaireId: number,
  payload: { hotwords: string[] },
): Promise<ProjectQuestionnaire> {
  return request<ProjectQuestionnaire>(
    `/api/projects/${projectId}/questionnaires/${questionnaireId}/hotwords`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export function deleteProjectQuestionnaire(
  projectId: number,
  questionnaireId: number,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(
    `/api/projects/${projectId}/questionnaires/${questionnaireId}`,
    {
      method: "DELETE",
    },
  );
}
