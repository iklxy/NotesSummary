export interface RunInterviewResponse {
  success: boolean;
  queued?: boolean | null;
  summary_inserted?: number | null;
  notes_inserted?: number | null;
  minutes_inserted?: number | null;
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

export interface GenerateMinutesResponse {
  success: boolean;
  interview_id: number;
  project_id?: number | null;
  outline_generated?: number | null;
  generated?: number | null;
  minutes_chars?: number | null;
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
  refreshed_from_project_key_bq?: boolean | null;
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

export interface InterviewDetailFieldDefinition {
  key: string;
  label: string;
  kind?: "text" | "number" | string;
}

export interface InterviewDetailFieldsResponse {
  fields: InterviewDetailFieldDefinition[];
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
  confidence?: number | null;
}

export interface InterviewSummaryResponse {
  interview_id: number;
  project_id?: number | null;
  items: InterviewSummaryItem[];
}

export interface InterviewCardItem {
  id: number;
  cards_id: number;
  project_id: number;
  project_interview_id: number;
  card_order: number;
  card_title: string;
  card_summary?: string | null;
  generated_json: unknown;
  final_json?: unknown;
  review_status?: string | null;
  review_comment?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
  updated_by?: number | null;
  updated_at?: string | null;
}

export interface InterviewCardsResponse {
  interview_id: number;
  project_id?: number | null;
  status?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  items: InterviewCardItem[];
}

export interface InterviewCardsGenerationResponse {
  success: boolean;
  interview_id: number;
  project_id?: number | null;
  cards_id?: number | null;
  generated?: number | null;
  inserted?: number | null;
  cards?: unknown;
  minutes_text_len?: number | null;
  llm_raw_output?: unknown;
  fallback?: boolean | null;
  warning?: string | null;
  message?: string | null;
}

export interface InterviewOverallNotesResponse {
  interview_id: number;
  project_id?: number | null;
  note_content?: string | null;
  cards: InterviewCardsResponse;
  kbq_notes: InterviewKbqNotesResponse;
  minutes: InterviewMinutesResponse;
  notes?: InterviewNotesResponse | null;
  summary: InterviewSummaryResponse;
}

export interface InterviewCardItemCreateRequest {
  card_title: string;
  card_order?: number | null;
  card_summary?: string | null;
  generated_json: unknown;
  final_json?: unknown;
  review_status?: string | null;
  review_comment?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
}

export interface InterviewCardItemUpdateRequest {
  card_order?: number | null;
  card_title?: string | null;
  card_summary?: string | null;
  generated_json?: unknown;
  final_json?: unknown;
  review_status?: string | null;
  review_comment?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
}

export interface OverallNotesSummaryUpdateResponse {
  success: boolean;
  interview_id: number;
  note_content?: string | null;
}

export interface OverallNotesKbqUpdateResponse {
  success: boolean;
  interview_id: number;
  kbq_id: number;
  note_json?: unknown;
}

export interface OverallNotesMinutesUpdateResponse {
  success: boolean;
  interview_id: number;
  minutes_json?: unknown;
  minutes_text?: string | null;
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

export interface InterviewMinutesItem {
  order: number;
  title: string;
  summary?: string | null;
}

export interface InterviewMinutesActionItem {
  owner?: string | null;
  time?: string | null;
  content?: string | null;
}

export interface InterviewMinutesSection {
  order: number;
  title: string;
  summary?: string | null;
  items: InterviewMinutesItem[];
}

export interface InterviewMinutesResponse {
  interview_id: number;
  project_id?: number | null;
  document_title?: string | null;
  core_summary?: string | null;
  minutes_text?: string | null;
  raw_minutes_text?: string | null;
  outline?: unknown;
  sections: InterviewMinutesSection[];
  action_items?: InterviewMinutesActionItem[];
  highlights?: string[];
  status?: string | null;
  error_message?: string | null;
  generated_at?: string | null;
  minutes_json?: unknown;
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
  interview_date?: string | null;
  core_problem?: string | null;
  detail_json?: Record<string, unknown> | null;
  city?: string | null;
  hospital_city?: string | null;
  hospital_decile?: number | null;
  doctor_level?: string | null;
  doctor_title?: string | null;
  hospital?: string | null;
  department?: string | null;
  audioFileName?: string | null;
  status?: number | null;
  questionnaire_id?: number | null;
  questionnaire_name?: string | null;
  questionnaire_status?: string | null;
  questionnaire_object_type?: string | null;
  questionnaire_role_id?: number | null;
  questionnaire_role_name?: string | null;
  questionnaire_role_type?: string | null;
  questionnaire_role_detail_schema_json?: InterviewDetailFieldDefinition[] | null;
  key_bq_id?: number | null;
  key_bq_name?: string | null;
}

export interface CreatedInterviewResponse {
  id: number;
  project_id: number;
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
  questionnaire_id?: number | null;
  questionnaire_name?: string | null;
  questionnaire_status?: string | null;
  questionnaire_object_type?: string | null;
  questionnaire_role_id?: number | null;
  questionnaire_role_name?: string | null;
  questionnaire_role_type?: string | null;
  questionnaire_role_detail_schema_json?: InterviewDetailFieldDefinition[] | null;
  key_bq_id?: number | null;
  key_bq_name?: string | null;
}

export interface Project {
  id: number;
  name: string;
  keywords?: string | null;
  core_problem?: string | null;
  guide_file_name?: string | null;
  guide_file_path?: string | null;
  guide_file_type?: string | null;
  guide_files_json?: ProjectGuideFile[] | null;
  guide_extracted_text?: string | null;
  guide_summary_text?: string | null;
  guide_status?: string | null;
  guide_error_message?: string | null;
  guide_generated_at?: string | null;
  key_bq_json?: KeyBqJson | null;
  questionnaire_count?: number | null;
  key_bq_count?: number | null;
  interview_count?: number | null;
  interviews?: Interview[];
}

export interface ProjectGuideFile {
  index?: number | null;
  original_name?: string | null;
  stored_path?: string | null;
  file_type?: string | null;
  status?: string | null;
  error_message?: string | null;
  extracted_text?: string | null;
  summary_text?: string | null;
  generated_at?: string | null;
}

export interface ProjectQuestionnaire {
  id: number;
  project_id: number;
  role_id?: number | null;
  name: string;
  object_type?: string | null;
  role_name?: string | null;
  role_type?: string | null;
  role_detail_schema_json?: InterviewDetailFieldDefinition[] | null;
  file_name?: string | null;
  docx_path?: string | null;
  md_path?: string | null;
  json_path?: string | null;
  hotwords?: string[] | null;
  status?: "hotword_review_pending" | "ready" | "failed" | string | null;
  created_at?: string | null;
  updated_at?: string | null;
  referenced_interview_count?: number | null;
  hotword_candidates?: QuestionnaireHotwordCandidate[] | null;
  review_required?: boolean | null;
  success?: boolean | null;
}

export interface ProjectRole {
  id: number;
  project_id: number;
  role_name: string;
  role_type: "doctor" | "patient" | "custom" | string;
  detail_schema_json: InterviewDetailFieldDefinition[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface KeyBqDimensionJson {
  name: string;
  description?: string | null;
}

export interface KeyBqJson {
  key_bq_list: Array<{
    order: number;
    text: string;
    user_demension?: KeyBqDimensionJson[];
    llm_demension?: KeyBqDimensionJson[];
    demension?: KeyBqDimensionJson[];
    dimensions?: KeyBqDimensionJson[];
    user_dimensions?: KeyBqDimensionJson[];
    llm_dimensions?: KeyBqDimensionJson[];
    supplemental_dimensions?: KeyBqDimensionJson[];
  }>;
}

export interface ProjectKeyBq {
  id: number;
  project_id: number;
  name: string;
  key_bq_json: KeyBqJson;
  created_at?: string | null;
  updated_at?: string | null;
  referenced_interview_count?: number | null;
  success?: boolean | null;
}

export interface ProjectKeyBqSingleton {
  success?: boolean | null;
  project_id: number;
  key_bq_json: KeyBqJson;
  updated_at?: string | null;
}

export interface ProjectDetail {
  project: Project;
  roles: ProjectRole[];
  questionnaires: ProjectQuestionnaire[];
  keyBqGroups: ProjectKeyBq[];
  interviews: Interview[];
  counts?: {
    questionnaire_count: number;
    key_bq_count: number;
    interview_count: number;
  };
}

export interface ProjectCaInterviewMeta {
  [key: string]: string | number | null | undefined;
  city?: string | null;
  hospital_city?: string | null;
  hospital_decile?: number | null;
  doctor_level?: string | null;
  doctor_title?: string | null;
  hospital?: string | null;
  department?: string | null;
}

export interface ProjectCaInterviewItem {
  interview_id: number;
  name: string;
  interview_date?: string | null;
  meta?: ProjectCaInterviewMeta | Record<string, string | number | null> | null;
  hidden?: boolean | null;
}

export interface ProjectCaColumn {
  column_id: string;
  order: number;
  question_text: string;
  display_text?: string | null;
  summary_text?: string | null;
  hidden?: boolean | null;
  question_uid?: string | null;
  group_id?: string | null;
  group?: string | null;
  group_order?: number | null;
  group_summary?: string | null;
  question_type?: "qualitative" | "quantitative" | string | null;
  interview_id?: number | null;
  name?: string | null;
  interview_date?: string | null;
  meta?: ProjectCaInterviewMeta | Record<string, string | number | null> | null;
}

export interface ProjectCaCell {
  value: string;
  answer?: string | null;
  answer_runs?: ProjectCaAnswerRun[] | null;
  evidence?: string[] | null;
  locked?: boolean | null;
  source?: string | null;
  numeric_value?: number | null;
}

export interface ProjectCaAnswerRun {
  text: string;
  highlight?: boolean | null;
}

export interface ProjectCaRow {
  interview_id: number;
  name: string;
  interview_date?: string | null;
  meta?: ProjectCaInterviewMeta | Record<string, string | number | null> | null;
  hidden?: boolean | null;
  question_uid?: string | null;
  question_text?: string | null;
  display_text?: string | null;
  order?: number | null;
  group?: string | null;
  group_order?: number | null;
  group_summary?: string | null;
  question_type?: "qualitative" | "quantitative" | string | null;
}

export interface ProjectCaGroup {
  group_id: string;
  order: number;
  title: string;
  summary?: string | null;
  row_uids?: string[] | null;
}

export interface ProjectCaSnapshot {
  schema_version?: number | null;
  project_id: number;
  questionnaire_id?: number | null;
  project_name?: string | null;
  questionnaire_name?: string | null;
  selected_interview_ids?: number[];
  interviews?: ProjectCaInterviewItem[];
  rows?: ProjectCaRow[];
  columns?: ProjectCaColumn[];
  groups?: ProjectCaGroup[];
  cells?: Record<string, Record<string, ProjectCaCell | string>>;
  diff_row?: Record<string, ProjectCaCell | string>;
  column_meta_fields?: string[];
  column_meta_field_labels?: Record<string, string>;
  status?: string | null;
  generated_at?: string | null;
  framework_generated_at?: string | null;
  final_generated_at?: string | null;
  reviewed_at?: string | null;
  error_message?: string | null;
  project_context?: Record<string, unknown> | null;
  questionnaire_json?: Record<string, unknown> | null;
  questionnaire_document?: Record<string, unknown> | null;
}

export interface ProjectCaSubPoint {
  order: number;
  title: string;
  summary?: string | null;
  cells?: Record<string, string>;
}

export interface ProjectCaDimension {
  order: number;
  title: string;
  summary?: string | null;
  sub_points: ProjectCaSubPoint[];
}

export interface ProjectCaJson {
  schema_version?: number | null;
  project_id: number;
  questionnaire_id?: number | null;
  project_name?: string | null;
  questionnaire_name?: string | null;
  column_meta_fields?: string[];
  column_meta_field_labels?: Record<string, string>;
  selected_interview_ids?: number[];
  interviews?: ProjectCaInterviewItem[];
  rows?: ProjectCaRow[];
  columns?: ProjectCaColumn[];
  groups?: ProjectCaGroup[];
  cells?: Record<string, Record<string, ProjectCaCell | string>>;
  diff_row?: Record<string, ProjectCaCell | string>;
  framework_json?: ProjectCaSnapshot | null;
  final_json?: ProjectCaSnapshot | null;
  framework_status?: string | null;
  final_status?: string | null;
  status?: string | null;
  generated_at?: string | null;
  framework_generated_at?: string | null;
  final_generated_at?: string | null;
  reviewed_at?: string | null;
  error_message?: string | null;
  project_context?: Record<string, unknown> | null;
  questionnaire_json?: Record<string, unknown> | null;
  questionnaire_document?: Record<string, unknown> | null;
  dimensions?: ProjectCaDimension[];
}

export interface ProjectCaTableResponse {
  success: boolean;
  project_id: number;
  project_name?: string | null;
  questionnaire_id?: number | null;
  ca_json?: ProjectCaJson | null;
}

export interface ProjectCaTableItem {
  project_id: number;
  questionnaire_id?: number | null;
  ca_json?: ProjectCaJson | null;
  framework_status?: string | null;
  final_status?: string | null;
  updated_at?: string | null;
  generated_at?: string | null;
  reviewed_at?: string | null;
}

export interface ProjectCaTablesResponse {
  success: boolean;
  project_id: number;
  project_name?: string | null;
  items: ProjectCaTableItem[];
}

export interface GenerateProjectCaTableRequest {
  questionnaire_id: number;
  interview_ids: number[];
  column_meta_fields: string[];
  mode?: "framework" | "final" | string;
  framework_json?: ProjectCaJson | null;
}

export interface GenerateProjectCaTableResponse {
  success: boolean;
  project_id: number;
  questionnaire_id?: number | null;
  mode?: string | null;
  generated_at?: string | null;
  framework_generated_at?: string | null;
  final_generated_at?: string | null;
  column_meta_fields?: string[] | null;
  interview_count?: number | null;
  dimension_count?: number | null;
  requested_interview_ids?: number[] | null;
  skipped_interview_ids?: number[] | null;
  ca_json?: ProjectCaJson | null;
  framework_json?: ProjectCaJson | null;
  final_json?: ProjectCaJson | null;
  ca_json_path?: string | null;
  message?: string | null;
  stage?: string | null;
  detail?: unknown;
}

export interface AuthUser {
  id: number;
  username: string;
  display_name?: string | null;
}
