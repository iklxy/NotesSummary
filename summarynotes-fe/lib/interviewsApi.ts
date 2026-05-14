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
  GenerateMinutesResponse,
  InterviewNotesResponse,
  InterviewOverallNotesResponse,
  InterviewQuestionsResponse,
  InterviewStatusResponse,
  OverallNotesKbqUpdateResponse,
  OverallNotesMinutesUpdateResponse,
  OverallNotesSummaryUpdateResponse,
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

export function updateInterviewOverallNotesSummary(
  interviewId: number,
  text: string,
): Promise<OverallNotesSummaryUpdateResponse> {
  return request<OverallNotesSummaryUpdateResponse>(
    `/api/interviews/${interviewId}/overall-notes/summary`,
    {
      method: "PUT",
      body: JSON.stringify({ text }),
    },
  );
}

export function updateInterviewOverallNotesKbq(
  interviewId: number,
  kbqId: number,
  noteJson: unknown,
): Promise<OverallNotesKbqUpdateResponse> {
  return request<OverallNotesKbqUpdateResponse>(
    `/api/interviews/${interviewId}/overall-notes/kbq/${kbqId}`,
    {
      method: "PUT",
      body: JSON.stringify({ note_json: noteJson }),
    },
  );
}

export function updateInterviewOverallNotesMinutes(
  interviewId: number,
  minutesJson: unknown,
): Promise<OverallNotesMinutesUpdateResponse> {
  return request<OverallNotesMinutesUpdateResponse>(
    `/api/interviews/${interviewId}/overall-notes/minutes`,
    {
      method: "PUT",
      body: JSON.stringify({ minutes_json: minutesJson }),
    },
  );
}

export function refreshInterviewKbqNotes(
  interviewId: number,
): Promise<RefreshKbqNotesResponse> {
  return request<RefreshKbqNotesResponse>(`/api/interviews/${interviewId}/kbq-notes/refresh`, {
    method: "POST",
  });
}

export function refreshInterviewDeliveryNotes(
  interviewId: number,
): Promise<GenerateNotesResponse> {
  return request<GenerateNotesResponse>(`/api/interviews/${interviewId}/notes/refresh`, {
    method: "POST",
  });
}

export function refreshInterviewMinutes(
  interviewId: number,
): Promise<GenerateMinutesResponse> {
  return request<GenerateMinutesResponse>(`/api/interviews/${interviewId}/minutes/refresh`, {
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
  city?: string | null;
  hospital_city?: string | null;
  hospital_decile?: number | null;
  doctor_level?: string | null;
  doctor_title?: string | null;
  hospital?: string | null;
  department?: string | null;
  status?: number | null;
  file_name?: string | null;
  questionnaire_object_type?: string | null;
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
  project_id?: number | null;
  items: InterviewSummaryItem[];
}

export interface UpdateSummaryResponse {
  success: boolean;
  summary?: InterviewSummaryItem | null;
  reindex_succeeded?: boolean;
  reindex_indexed?: number | null;
  reindex_warning?: string | null;
  corrections_inserted?: number | null;
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

export async function exportInterviewTransWord(
  interviewId: number,
): Promise<{ blob: Blob; filename: string }> {
  const url = `/api/interviews/${interviewId}/trans/export-word`;
  const resp = await fetch(url, {
    method: "GET",
    credentials: "include",
  });
  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = await resp.text();
    }
    throw new Error(`export trans word failed: ${JSON.stringify(detail)}`);
  }
  const contentDisposition = resp.headers.get("content-disposition") || "";
  const filenameStarMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  let filename = `interview_${interviewId}_trans.docx`;
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

export async function exportInterviewOverallNotesWord(
  interviewId: number,
): Promise<{ blob: Blob; filename: string }> {
  const url = `/api/interviews/${interviewId}/overall-notes/export-word`;
  const resp = await fetch(url, {
    method: "GET",
    credentials: "include",
  });
  if (!resp.ok) {
    const detailText = await resp.text();
    let detail: unknown = detailText;
    try {
      detail = detailText ? JSON.parse(detailText) : detailText;
    } catch {
      detail = detailText;
    }
    throw new Error(`export overall notes word failed: ${JSON.stringify(detail)}`);
  }
  const contentDisposition = resp.headers.get("content-disposition") || "";
  const filenameStarMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  let filename = `interview_${interviewId}_overall_notes.docx`;
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
