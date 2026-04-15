export interface RunInterviewResponse {
  success: boolean;
  summary_inserted?: number | null;
  notes_inserted?: number | null;
  message?: string | null;
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

export interface Interview {
  id: number;
  name: string;
  date?: string | null;
  audioFileName?: string | null;
}

export interface Project {
  id: number;
  name: string;
  keywords?: string | null;
  core_problem?: string | null;
  interviews?: Interview[];
}
