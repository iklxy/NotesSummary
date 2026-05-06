import { getBaseUrl, request } from "./apiClient";
import {
  CreatedInterviewResponse,
  DeleteInterviewResponse,
  DeleteQuestionResponse,
  FewshotSampleCreateRequest,
  FewshotSampleCreateResponse,
  FewshotSampleDeleteResponse,
  InterviewFewshotSamplesResponse,
  GenerateNotesResponse,
  InterviewNotesResponse,
  InterviewOverallNotesResponse,
  InterviewQuestionsResponse,
  InterviewStatusResponse,
  RefreshKbqNotesResponse,
  QuestionCreateItem,
  QuestionCreateResponse,
  QuestionIntentItem,
  QuestionnaireHotwordLoadResponse,
  QuestionnaireHotwordReviewRequest,
  QuestionnaireHotwordReviewResponse,
  RunInterviewResponse,
} from "./types";

export function runInterview(interviewId: number): Promise<RunInterviewResponse> {
  return request<RunInterviewResponse>(`/api/interviews/${interviewId}/run`, {
    method: "POST",
  });
}

export function getInterviewStatus(interviewId: number): Promise<InterviewStatusResponse> {
  return request<InterviewStatusResponse>(`/api/interviews/${interviewId}/status`);
}

export function deleteInterview(interviewId: number): Promise<DeleteInterviewResponse> {
  return request<DeleteInterviewResponse>(`/api/interviews/${interviewId}`, {
    method: "DELETE",
  });
}

export function getQuestionIntents(): Promise<QuestionIntentItem[]> {
  return request<QuestionIntentItem[]>("/api/question-intents");
}

export function getInterviewNotes(interviewId: number): Promise<InterviewNotesResponse> {
  return request<InterviewNotesResponse>(`/api/interviews/${interviewId}/notes`);
}

export function getInterviewOverallNotes(
  interviewId: number,
): Promise<InterviewOverallNotesResponse> {
  return request<InterviewOverallNotesResponse>(`/api/interviews/${interviewId}/overall-notes`);
}

export function refreshInterviewKbqNotes(
  interviewId: number,
): Promise<RefreshKbqNotesResponse> {
  return request<RefreshKbqNotesResponse>(`/api/interviews/${interviewId}/kbq-notes/refresh`, {
    method: "POST",
  });
}

export function getInterviewQuestions(
  interviewId: number,
): Promise<InterviewQuestionsResponse> {
  return request<InterviewQuestionsResponse>(`/api/interviews/${interviewId}/questions`);
}

export function createInterviewQuestions(
  interviewId: number,
  questions: QuestionCreateItem[],
): Promise<QuestionCreateResponse> {
  return request<QuestionCreateResponse>(`/api/interviews/${interviewId}/questions`, {
    method: "POST",
    body: JSON.stringify({ questions }),
  });
}

export function generateQuestionNotes(
  interviewId: number,
  questionId: number,
): Promise<GenerateNotesResponse> {
  return request<GenerateNotesResponse>(
    `/api/interviews/${interviewId}/questions/${questionId}/generate-notes`,
    {
      method: "POST",
    },
  );
}

export function deleteQuestion(
  interviewId: number,
  questionId: number,
): Promise<DeleteQuestionResponse> {
  return request<DeleteQuestionResponse>(
    `/api/interviews/${interviewId}/questions/${questionId}`,
    {
      method: "DELETE",
    },
  );
}

export function getInterviewFewshotSamples(
  interviewId: number,
): Promise<InterviewFewshotSamplesResponse> {
  return request<InterviewFewshotSamplesResponse>(`/api/interviews/${interviewId}/fewshot-samples`);
}

export function createQuestionFewshotSample(
  interviewId: number,
  questionId: number,
  payload: FewshotSampleCreateRequest,
): Promise<FewshotSampleCreateResponse> {
  return request<FewshotSampleCreateResponse>(
    `/api/interviews/${interviewId}/questions/${questionId}/fewshot-samples`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function deleteQuestionFewshotSample(
  interviewId: number,
  sampleId: number,
): Promise<FewshotSampleDeleteResponse> {
  return request<FewshotSampleDeleteResponse>(
    `/api/interviews/${interviewId}/fewshot-samples/${sampleId}`,
    {
      method: "DELETE",
    },
  );
}

export interface ProjectInterviewDTO {
  id: number;
  parse_project_id: number;
  name: string;
  core_problem?: string | null;
  interview_date?: string | null;
  hospital_city?: string | null;
  hospital_decile?: number | null;
  doctor_level?: string | null;
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

export interface UpdateSummaryResponse {
  success: boolean;
  summary?: InterviewSummaryItem | null;
  reindex_succeeded?: boolean;
  reindex_indexed?: number | null;
  reindex_warning?: string | null;
}

export async function createInterview(
  projectId: number,
  formData: FormData,
): Promise<CreatedInterviewResponse> {
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const url = `${baseUrl}/api/projects/${projectId}/interviews`;
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
    throw new Error(`create interview failed: ${JSON.stringify(detail)}`);
  }
  return (await resp.json()) as CreatedInterviewResponse;
}

export function getQuestionnaireHotwords(
  projectId: number,
  interviewId: number,
): Promise<QuestionnaireHotwordLoadResponse> {
  return request<QuestionnaireHotwordLoadResponse>(
    `/api/projects/${projectId}/interviews/${interviewId}/questionnaire-hotwords`,
  );
}

export function saveQuestionnaireHotwords(
  projectId: number,
  interviewId: number,
  payload: QuestionnaireHotwordReviewRequest,
): Promise<QuestionnaireHotwordReviewResponse> {
  return request<QuestionnaireHotwordReviewResponse>(
    `/api/projects/${projectId}/interviews/${interviewId}/questionnaire-hotwords`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function getProjectInterviews(projectId: number): Promise<ProjectInterviewDTO[]> {
  return request<ProjectInterviewDTO[]>(`/api/projects/${projectId}/interviews`);
}

export function getInterviewSummary(interviewId: number): Promise<InterviewSummaryResponse> {
  return request<InterviewSummaryResponse>(`/api/interviews/${interviewId}/summary`);
}

export function getInterviewAudioUrl(interviewId: number): string {
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  return `${baseUrl}/api/interviews/${interviewId}/audio`;
}

export function updateInterviewSummary(
  interviewId: number,
  summaryId: number,
  text: string,
): Promise<UpdateSummaryResponse> {
  return request<UpdateSummaryResponse>(`/api/interviews/${interviewId}/summary/${summaryId}`, {
    method: "PATCH",
    body: JSON.stringify({ text }),
  });
}
