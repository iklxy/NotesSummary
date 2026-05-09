import { request } from "./apiClient";
import type { InterviewDetailFieldsResponse } from "./types";

export function getInterviewDetailFields(): Promise<InterviewDetailFieldsResponse> {
  return request<InterviewDetailFieldsResponse>("/api/interview-detail-fields");
}

