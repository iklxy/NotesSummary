import { request } from "./apiClient";
import {
  InterviewNotesResponse,
  InterviewQuestionsResponse,
  RunInterviewResponse,
} from "./types";

const defaultBaseUrl = "http://127.0.0.1:9000";

function getBaseUrl(): string {
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }
  return defaultBaseUrl;
}

export function runInterview(interviewId: number): Promise<RunInterviewResponse> {
  return request<RunInterviewResponse>(`/api/interviews/${interviewId}/run`, {
    method: "POST",
  });
}

export function getInterviewNotes(interviewId: number): Promise<InterviewNotesResponse> {
  return request<InterviewNotesResponse>(`/api/interviews/${interviewId}/notes`);
}

export function getInterviewQuestions(
  interviewId: number,
): Promise<InterviewQuestionsResponse> {
  return request<InterviewQuestionsResponse>(`/api/interviews/${interviewId}/questions`);
}

export interface CreatedInterview {
  id: number;
  project_id: number;
  name: string;
  interview_date?: string | null;
  file_name: string;
  local_path: string;
}

export interface ProjectInterviewDTO {
  id: number;
  parse_project_id: number;
  name: string;
  interview_date?: string | null;
  file_name?: string | null;
}

export interface InterviewSummaryItem {
  id: number;
  project_interview_id: number;
  timestamp?: string | null;
  speaker?: string | null;
  text?: string | null;
}

export interface InterviewSummaryResponse {
  interview_id: number;
  items: InterviewSummaryItem[];
}

export async function createInterview(
  projectId: number,
  formData: FormData,
): Promise<CreatedInterview> {
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const url = `${baseUrl}/api/projects/${projectId}/interviews`;
  const resp = await fetch(url, {
    method: "POST",
    body: formData,
  });
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text();
    }
    throw new Error(`create interview failed: ${JSON.stringify(detail)}`);
  }
  return (await resp.json()) as CreatedInterview;
}

export function getProjectInterviews(projectId: number): Promise<ProjectInterviewDTO[]> {
  return request<ProjectInterviewDTO[]>(`/api/projects/${projectId}/interviews`);
}

export function getInterviewSummary(interviewId: number): Promise<InterviewSummaryResponse> {
  return request<InterviewSummaryResponse>(`/api/interviews/${interviewId}/summary`);
}

