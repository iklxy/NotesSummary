export interface RunInterviewResponse {
  success: boolean;
  queued?: boolean | null;
  summary_inserted?: number | null;
  notes_inserted?: number | null;
  message?: string | null;
}

export interface GenerateNotesResponse {
  success: boolean;
  interview_id: number;
  question_id?: number | null;
  project_id?: number | null;
  total_questions?: number | null;
  generated?: number | null;
  inserted?: number | null;
  warnings?: string[] | null;
  message?: string | null;
}

export interface DeleteQuestionResponse {
  success: boolean;
  interview_id: number;
  question_id: number;
  question_deleted?: boolean | null;
  fewshot_deleted?: number | null;
  notes_deleted?: number | null;
  message?: string | null;
}

export interface InterviewStatusResponse {
  interview_id: number;
  status?: number | null;
}

export interface DeleteInterviewResponse {
  success: boolean;
  interview_id: number;
  db_deleted?: boolean;
  audio_deleted?: boolean;
  local_audio_deleted?: boolean;
  cloud_audio_deleted?: boolean;
  qdrant_deleted?: boolean;
  message?: string | null;
}

export interface RefreshKbqNotesResponse {
  success: boolean;
  interview_id: number;
  project_id?: number | null;
  key_bq_inserted?: number | null;
  generated?: number | null;
  inserted?: number | null;
  warnings?: string[] | null;
  refreshed_from_core_problem?: boolean | null;
  message?: string | null;
}

export interface QuestionnaireHotwordCandidate {
  term: string;
  normalized_term: string;
  reason?: string | null;
  confidence?: number | null;
}

export interface QuestionnaireHotwordLoadResponse {
  interview_id: number;
  project_id: number;
  review_required?: boolean | null;
  candidates?: QuestionnaireHotwordCandidate[] | null;
  reviewed_hotwords?: string[] | null;
}

export interface QuestionnaireHotwordReviewRequest {
  hotwords: string[];
}

export interface QuestionnaireHotwordReviewResponse {
  success: boolean;
  interview_id: number;
  project_id: number;
  reviewed_count?: number | null;
  reviewed_path?: string | null;
  reviewed_json_path?: string | null;
  workflow_started?: boolean | null;
  message?: string | null;
}

export interface DeleteProjectResponse {
  success: boolean;
  project_id: number;
  project_name?: string | null;
  deleted_interviews?: number | null;
  warnings?: string[] | null;
}

export interface QuestionIntentItem {
  id: number;
  code: string;
  name?: string | null;
  description?: string | null;
  schema_name?: string | null;
  status?: number | null;
}

export interface NoteItem {
  notes_id: number;
  intent_id?: number | null;
  note_json: unknown;
  confidence?: number | null;
  status?: number | null;
}

export interface QuestionWithNotes {
  question_id: number;
  question_order: number;
  question_text: string;
  question_type?: string | null;
  intent_id?: number | null;
  research_phase?: string | null;
  notes: NoteItem[];
}

export interface InterviewNotesResponse {
  interview_id: number;
  project_id?: number | null;
  questions: QuestionWithNotes[];
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

export interface InterviewOverallNotesResponse {
  interview_id: number;
  project_id?: number | null;
  note_content?: string | null;
  kbq_notes: InterviewKbqNotesResponse;
  notes: InterviewNotesResponse;
  summary: InterviewSummaryResponse;
}

export interface KbqDimensionItem {
  name: string;
  description?: string | null;
}

export interface KbqDimensionNoteItem {
  dimension: string;
  summary?: string | null;
  analysis?: string | null;
  evidence?: FewshotEvidenceItem[];
}

export interface KbqNoteItem {
  id: number;
  project_id: number;
  project_interview_id: number;
  bq_order: number;
  bq_text: string;
  dimension_json?: unknown;
  note_json?: unknown;
  status?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface InterviewKbqNotesResponse {
  interview_id: number;
  project_id?: number | null;
  items: KbqNoteItem[];
}

export interface QuestionItem {
  id: number;
  project_interview_id: number;
  question_order: number;
  question_text: string;
  question_type?: string | null;
  research_phase?: string | null;
  intent_id?: number | null;
}

export interface InterviewQuestionsResponse {
  interview_id: number;
  questions: QuestionItem[];
}

export interface QuestionCreateItem {
  question_text: string;
}

export interface QuestionCreateResponse {
  success: boolean;
  interview_id: number;
  inserted: number;
}

export interface FewshotEvidenceItem {
  summary_id: number;
  speaker?: string | null;
  text: string;
}

export interface FewshotSampleCreateRequest {
  intent_id: number;
  summary: string;
  analysis: string;
  evidence: FewshotEvidenceItem[];
  confidence?: number | null;
  quality_score?: number | null;
  source_kind?: string | null;
  notes_result_id?: number | null;
}

export interface FewshotSampleCreateResponse {
  success: boolean;
  interview_id: number;
  question_id: number;
  sample_id: number;
}

export interface FewshotSampleDeleteResponse {
  success: boolean;
  interview_id: number;
  sample_id: number;
  question_id?: number | null;
  deleted?: boolean | null;
  message?: string | null;
}

export interface FewshotSampleItem {
  id: number;
  project_id: number;
  project_interview_id: number;
  question_id: number;
  question_order?: number | null;
  question_text?: string | null;
  question_type?: string | null;
  research_phase?: string | null;
  intent_id: number;
  notes_result_id?: number | null;
  sample_json: unknown;
  sample_summary?: string | null;
  sample_analysis?: string | null;
  evidence_count?: number | null;
  quality_score?: number | null;
  source_kind?: string | null;
  created_time?: string | null;
}

export interface InterviewFewshotSamplesResponse {
  interview_id: number;
  samples: FewshotSampleItem[];
}

export interface Interview {
  id: number;
  name: string;
  date?: string | null;
  core_problem?: string | null;
  hospital_city?: string | null;
  hospital_decile?: number | null;
  doctor_level?: string | null;
  audioFileName?: string | null;
}

export interface CreatedInterviewResponse {
  id: number;
  project_id: number;
  name: string;
  core_problem?: string | null;
  interview_date?: string | null;
  hospital_city?: string | null;
  hospital_decile?: number | null;
  doctor_level?: string | null;
  file_name: string;
  local_path: string;
  audio_backup_path?: string | null;
  questionnaire_file_name?: string | null;
  questionnaire_backup_path?: string | null;
  questionnaire_md_path?: string | null;
  questionnaire_json_path?: string | null;
  questionnaire_hotword_review_required?: boolean | null;
  questionnaire_hotword_candidates?: QuestionnaireHotwordCandidate[] | null;
  questionnaire_hotword_candidates_path?: string | null;
  workflow_started?: boolean | null;
}

export interface Project {
  id: number;
  name: string;
  keywords?: string | null;
  core_problem?: string | null;
  interviews?: Interview[];
}

export interface AuthUser {
  id: number;
  username: string;
  display_name?: string | null;
}
