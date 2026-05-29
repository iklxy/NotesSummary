"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Input,
  Modal,
  Radio,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  ArrowLeftOutlined,
  CaretLeftOutlined,
  CaretRightOutlined,
  DownloadOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import BrandHero from "../../../../../components/BrandHero";
import { getInterviewDetailFields } from "../../../../../lib/interviewDetailFieldsApi";
import {
  exportProjectCaTableWord,
  exportProjectCaTableXlsx,
  generateProjectCaTable,
  getProjectCaTable,
  getProjectDetail,
  saveProjectCaFramework,
} from "../../../../../lib/projectsApi";
import type {
  Interview,
  InterviewDetailFieldDefinition,
  ProjectCaAnswerRun,
  ProjectCaCell,
  ProjectCaColumn,
  ProjectCaInterviewItem,
  ProjectCaJson,
} from "../../../../../lib/types";

const { Text, Paragraph } = Typography;

interface Props {
  projectId: number;
  questionnaireId: number;
}

const FALLBACK_META_FIELDS: InterviewDetailFieldDefinition[] = [
  { key: "doctor_level", label: "医生级别", kind: "text" },
  { key: "doctor_title", label: "职称", kind: "text" },
  { key: "city", label: "城市", kind: "text" },
  { key: "hospital", label: "所在医院", kind: "text" },
  { key: "department", label: "科室", kind: "text" },
  { key: "hospital_decile", label: "医院Decile", kind: "number" },
];

type MatrixRow =
  | {
      key: string;
      kind: "section";
      label: string;
    }
  | {
      key: string;
      kind: "meta";
      label: string;
      values: Record<string, string>;
    }
  | {
      key: string;
      kind: "question";
      groupLabel: string;
      groupSummary: string;
      groupQuestionUids: string[];
      groupRowSpan: number;
      groupQuestionCount: number;
      label: string;
      questionUid: string;
      summaryText: string;
      values: Record<string, string>;
      evidence: Record<string, string[]>;
      answerRuns: Record<string, ProjectCaAnswerRun[]>;
      order: number;
      hidden: boolean;
      column: ProjectCaColumn;
      group: string;
      questionType: "qualitative" | "quantitative";
    }
  | {
      key: string;
      kind: "diff";
      label: string;
      values: Record<string, string>;
      evidence: Record<string, string[]>;
      answerRuns: Record<string, ProjectCaAnswerRun[]>;
    };

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function parseInterviewIds(input: string | null): number[] {
  if (!input) {
    return [];
  }
  return input
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item > 0);
}

function buildInterviewLabel(item: Interview): string {
  const parts = [
    `${item.id}`,
    item.name,
    item.interview_date ? item.interview_date.split("T")[0] : "",
    item.status === 2 ? "已完成" : `状态 ${item.status ?? "-"}`,
  ].filter(Boolean);
  return parts.join(" | ");
}

function getQuestionnaireName(questionnaires: Array<{ id: number; name?: string | null; role_name?: string | null }>, questionnaireId: number): string {
  const questionnaire = questionnaires.find((item) => item.id === questionnaireId);
  return questionnaire?.name || questionnaire?.role_name || `DG ${questionnaireId}`;
}

function getQuestionKey(item: ProjectCaColumn, fallbackIndex: number): string {
  return String(item.question_uid || item.column_id || fallbackIndex + 1).trim();
}

function getQuestionLabel(item: ProjectCaColumn): string {
  return String(item.display_text ?? item.question_text ?? item.question_uid ?? item.column_id ?? "").trim();
}

function normalizeQuestionType(value: unknown): "qualitative" | "quantitative" {
  const text = String(value || "").trim().toLowerCase();
  return text === "quantitative" ? "quantitative" : "qualitative";
}

function parseNumericValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const match = value.replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
    if (match) {
      const parsed = Number(match[0]);
      return Number.isFinite(parsed) ? parsed : null;
    }
  }
  return null;
}

function toBoolish(value: unknown): boolean {
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "string") {
    const text = value.trim().toLowerCase();
    return ["1", "true", "yes", "y", "on", "highlight"].includes(text);
  }
  if (typeof value === "number") {
    return Number.isFinite(value) && value !== 0;
  }
  return false;
}

function normalizeAnswerRuns(value: unknown): ProjectCaAnswerRun[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (typeof item === "string") {
        const text = item.trim();
        return text ? { text, highlight: false } : null;
      }
      if (!item || typeof item !== "object") {
        return null;
      }
      const raw = item as Record<string, unknown>;
      const text = String(raw.text ?? raw.value ?? raw.answer ?? "").trim();
      if (!text) {
        return null;
      }
      return {
        text,
        highlight: toBoolish(raw.highlight ?? raw.emphasis),
      };
    })
    .filter(Boolean) as ProjectCaAnswerRun[];
}

function normalizeCellPayload(value: ProjectCaCell | string | null | undefined): ProjectCaCell {
  if (typeof value === "string") {
    return {
      value: value.trim() || "/",
      evidence: [],
      answer_runs: [],
      locked: false,
      source: "framework",
      numeric_value: null,
    };
  }
  if (!value || typeof value !== "object") {
    return {
      value: "/",
      evidence: [],
      answer_runs: [],
      locked: false,
      source: "framework",
      numeric_value: null,
    };
  }
  const rawValue = value as unknown as Record<string, unknown>;
  const rawEvidence = rawValue.evidence;
  const evidence =
    Array.isArray(rawEvidence)
      ? rawEvidence.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 3)
      : [];
  const answerRuns = normalizeAnswerRuns(rawValue.answer_runs ?? rawValue.answerRuns);
  const answer = String(rawValue.value ?? rawValue.answer ?? rawValue.text ?? "").trim() || "/";
  return {
    value: answerRuns.length > 0 && answer === "/" ? answerRuns.map((item) => item.text).join("").trim() || "/" : answer,
    evidence,
    answer_runs: answerRuns,
    locked: Boolean(rawValue.locked),
    source: String(rawValue.source ?? "framework"),
    numeric_value: parseNumericValue(rawValue.numeric_value ?? rawValue.numericValue),
  };
}

function getCellPayload(
  cells: ProjectCaJson["cells"],
  interviewId: number,
  questionUid: string,
): ProjectCaCell {
  const row = cells?.[String(interviewId)];
  if (!row) {
    return normalizeCellPayload(null);
  }
  return normalizeCellPayload(row[questionUid]);
}

function getInterviewMetaValue(item: ProjectCaInterviewItem, key: string): string {
  const raw = item as unknown as Record<string, unknown>;
  if (key === "interview_id") {
    return String(raw.interview_id || "");
  }
  if (key === "interview_name") {
    return String(raw.name || "");
  }
  if (key === "interview_date") {
    const date = raw.interview_date;
    return typeof date === "string" && date ? date.split("T")[0] : "-";
  }
  const meta = raw.meta && typeof raw.meta === "object" ? (raw.meta as Record<string, unknown>) : {};
  const value = meta[key];
  return value === null || value === undefined || value === "" ? "/" : String(value);
}

function normalizeMetaRecord(value: unknown): ProjectCaInterviewItem["meta"] {
  if (!value || typeof value !== "object") {
    return null;
  }
  const result: Record<string, string | number | null> = {};
  for (const [key, rawValue] of Object.entries(value as Record<string, unknown>)) {
    if (rawValue === null || rawValue === undefined) {
      result[key] = null;
    } else if (typeof rawValue === "string" || typeof rawValue === "number") {
      result[key] = rawValue;
    } else {
      result[key] = String(rawValue);
    }
  }
  return result;
}

function getCellValue(
  cells: ProjectCaJson["cells"],
  interviewId: number,
  questionUid: string,
): string {
  return getCellPayload(cells, interviewId, questionUid).value;
}

function getCellEvidence(
  cells: ProjectCaJson["cells"],
  interviewId: number,
  questionUid: string,
): string[] {
  return getCellPayload(cells, interviewId, questionUid).evidence ?? [];
}

function getCellAnswerRuns(
  cells: ProjectCaJson["cells"],
  interviewId: number,
  questionUid: string,
): ProjectCaAnswerRun[] {
  return getCellPayload(cells, interviewId, questionUid).answer_runs ?? [];
}

function getDiffValue(
  diffRow: ProjectCaJson["diff_row"],
  interviewId: number,
): string {
  const cell = diffRow?.[String(interviewId)];
  const payload = normalizeCellPayload(cell);
  return payload.value;
}

function getDiffEvidence(
  diffRow: ProjectCaJson["diff_row"],
  interviewId: number,
): string[] {
  const cell = diffRow?.[String(interviewId)];
  const payload = normalizeCellPayload(cell);
  return payload.evidence ?? [];
}

function getDiffAnswerRuns(
  diffRow: ProjectCaJson["diff_row"],
  interviewId: number,
): ProjectCaAnswerRun[] {
  const cell = diffRow?.[String(interviewId)];
  const payload = normalizeCellPayload(cell);
  return payload.answer_runs ?? [];
}

function getCellNumericValue(
  cells: ProjectCaJson["cells"],
  interviewId: number,
  questionUid: string,
): number | null {
  return getCellPayload(cells, interviewId, questionUid).numeric_value ?? null;
}

function getGroupLabel(column: ProjectCaColumn): string {
  return String(column.group || "未分组").trim() || "未分组";
}

function getGroupSummary(column: ProjectCaColumn): string {
  return String(column.group_summary || "").trim();
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return "/";
  }
  const rounded = Math.round(value * 100) / 100;
  const text = Number.isInteger(rounded) ? String(Math.trunc(rounded)) : String(rounded);
  return text.replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1");
}

function computeQuestionStats(
  snapshot: ProjectCaJson | null,
  row: ProjectCaColumn,
  visibleInterviews: ProjectCaInterviewItem[],
): { validCount: number; numericValues: number[]; summary: string } {
  if (!snapshot) {
    return { validCount: 0, numericValues: [], summary: "/" };
  }
  const questionUid = String(row.question_uid || row.column_id || "").trim();
  const numericValues: number[] = [];
  let validCount = 0;
  visibleInterviews.forEach((interview) => {
    const interviewId = interview.interview_id;
    const payload = getCellPayload(snapshot.cells, interviewId, questionUid);
    const value = String(payload.value || "").trim();
    if (value && value !== "/") {
      validCount += 1;
    }
    const numericValue = payload.numeric_value ?? parseNumericValue(payload.value);
    if (Number.isFinite(numericValue as number)) {
      numericValues.push(Number(numericValue));
    }
  });
  if (row.question_type === "quantitative" && numericValues.length > 0) {
    const mean = numericValues.reduce((sum, item) => sum + item, 0) / numericValues.length;
    const min = Math.min(...numericValues);
    const max = Math.max(...numericValues);
    return {
      validCount,
      numericValues,
      summary: `有效 ${validCount} / 均值 ${formatNumber(mean)} / 范围 ${formatNumber(min)}-${formatNumber(max)}`,
    };
  }
  return {
    validCount,
    numericValues,
    summary: `有效 ${validCount}`,
  };
}

function normalizeMetaFields(
  snapshot: ProjectCaJson | null | undefined,
  fieldDefinitions: InterviewDetailFieldDefinition[],
): string[] {
  const fields = snapshot?.column_meta_fields ?? [];
  const filtered = fields.filter((item) => fieldDefinitions.some((field) => field.key === item));
  return filtered.length > 0 ? filtered : fieldDefinitions.map((item) => item.key);
}

function normalizeSnapshot(
  value: ProjectCaJson | null | undefined,
  projectId: number,
  projectName: string,
  questionnaireId: number,
  questionnaireName: string,
  fieldDefinitions: InterviewDetailFieldDefinition[],
): ProjectCaJson {
  const base: ProjectCaJson = value ? cloneJson(value) : { project_id: projectId };
  base.project_id = base.project_id || projectId;
  base.project_name = base.project_name || projectName;
  base.questionnaire_id = base.questionnaire_id || questionnaireId;
  base.questionnaire_name = base.questionnaire_name || questionnaireName;
  base.column_meta_fields = normalizeMetaFields(base, fieldDefinitions);
  base.column_meta_field_labels =
    base.column_meta_field_labels && typeof base.column_meta_field_labels === "object"
      ? { ...base.column_meta_field_labels }
      : Object.fromEntries(fieldDefinitions.map((item) => [item.key, item.label]));

  const interviews = (base.interviews ?? [])
    .filter((item): item is ProjectCaInterviewItem => Boolean(item))
    .map((item, index) => {
      const interviewId = Number(item.interview_id || index + 1);
      return {
        interview_id: interviewId > 0 ? interviewId : index + 1,
        name: String(item.name || `访谈 ${interviewId || index + 1}`).trim(),
        interview_date: item.interview_date ?? null,
        meta: normalizeMetaRecord(item.meta),
        hidden: Boolean(item.hidden),
      };
    });
  const columns = (base.columns ?? [])
    .filter((item): item is ProjectCaColumn => Boolean(item))
    .map((item, index) => {
      const questionUid = getQuestionKey(item, index);
      const displayText =
        item.display_text !== undefined && item.display_text !== null
          ? String(item.display_text)
          : String(item.question_text || "");
      return {
        column_id: String(item.column_id || questionUid),
        order: Number.isFinite(Number(item.order)) ? Number(item.order) : index + 1,
        question_text: String(item.question_text || "").trim(),
        display_text: displayText.trim(),
        summary_text:
          item.summary_text !== undefined && item.summary_text !== null
            ? String(item.summary_text).trim() || "/"
            : "/",
        hidden: Boolean(item.hidden),
        question_uid: questionUid,
        group_id: item.group_id !== undefined && item.group_id !== null ? String(item.group_id).trim() : "",
        group: item.group !== undefined && item.group !== null ? String(item.group).trim() : "",
        group_order: Number.isFinite(Number(item.group_order)) ? Number(item.group_order) : null,
        group_summary: item.group_summary !== undefined && item.group_summary !== null ? String(item.group_summary).trim() : "",
        question_type: normalizeQuestionType(item.question_type),
        interview_id: item.interview_id ?? null,
        name: item.name ?? null,
        interview_date: item.interview_date ?? null,
        meta: item.meta ?? null,
      };
    });
  const groups = Array.isArray(base.groups)
    ? base.groups
        .filter((item): item is NonNullable<ProjectCaJson["groups"]>[number] => Boolean(item))
        .map((item, index) => ({
          group_id: String(item.group_id || `group_${index + 1}`),
          order: Number.isFinite(Number(item.order)) ? Number(item.order) : index + 1,
          title: String(item.title || "").trim(),
          summary: item.summary !== undefined && item.summary !== null ? String(item.summary).trim() : "",
          row_uids: Array.isArray(item.row_uids) ? item.row_uids.map((uid) => String(uid || "").trim()).filter(Boolean) : [],
        }))
        .filter((item) => Boolean(item.title))
    : [];

  const nextCells: Record<string, Record<string, ProjectCaCell | string>> = {};
  interviews.forEach((interview, interviewIndex) => {
    const interviewKey = String(interview.interview_id || interviewIndex + 1);
    nextCells[interviewKey] = {};
    columns.forEach((column, columnIndex) => {
      const questionKey = getQuestionKey(column, columnIndex);
      const current = base.cells?.[interviewKey]?.[questionKey];
      if (current === undefined) {
        nextCells[interviewKey][questionKey] = { value: "", evidence: [], locked: false, source: "framework" };
      } else if (typeof current === "string") {
        nextCells[interviewKey][questionKey] = normalizeCellPayload(current);
      } else {
        nextCells[interviewKey][questionKey] = normalizeCellPayload(current as ProjectCaCell);
      }
    });
  });

  base.interviews = interviews;
  base.columns = columns;
  base.groups = groups;
  base.cells = nextCells;
  base.selected_interview_ids =
    base.selected_interview_ids && base.selected_interview_ids.length > 0
      ? base.selected_interview_ids.filter((item) => interviews.some((row) => row.interview_id === item))
      : interviews.map((item) => item.interview_id);
  const nextDiffRow: Record<string, ProjectCaCell | string> = {};
  if (base.diff_row && typeof base.diff_row === "object") {
    Object.entries(base.diff_row).forEach(([key, cell]) => {
      nextDiffRow[key] = normalizeCellPayload(cell);
    });
  }
  base.diff_row = nextDiffRow;
  const hasSummaryText = columns.some((column) => Boolean(String(column.summary_text || "").trim()));
  const hasNotesFramework = groups.length > 0 || columns.some((column) => Boolean(column.group || column.group_order || column.question_type || column.group_summary));
  const baseSchemaVersion = Number(base.schema_version || 0);
  if (baseSchemaVersion >= 4 || hasSummaryText) {
    base.schema_version = 4;
  } else if (baseSchemaVersion >= 3 || hasNotesFramework) {
    base.schema_version = 3;
  } else if (baseSchemaVersion >= 2 || base.diff_row) {
    base.schema_version = 2;
  } else {
    base.schema_version = 2;
  }
  base.framework_status = base.framework_status || "reviewing";
  base.final_status = base.final_status || "pending";
  base.status = base.final_status || base.framework_status || "draft";
  return base;
}

function getSnapshotTimestamp(snapshot: ProjectCaJson | null | undefined, key: "generated_at" | "framework_generated_at" | "final_generated_at"): number {
  if (!snapshot) {
    return 0;
  }
  const raw = snapshot[key];
  if (!raw || typeof raw !== "string") {
    return 0;
  }
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? parsed : 0;
}

function getReviewTimestamp(snapshot: ProjectCaJson | null | undefined): number {
  if (!snapshot?.reviewed_at || typeof snapshot.reviewed_at !== "string") {
    return 0;
  }
  const parsed = Date.parse(snapshot.reviewed_at);
  return Number.isFinite(parsed) ? parsed : 0;
}

function isFinalSnapshotOutdated(
  frameworkSnapshot: ProjectCaJson | null,
  finalSnapshot: ProjectCaJson | null,
): boolean {
  if (!finalSnapshot) {
    return true;
  }
  const frameworkReviewTs = getReviewTimestamp(frameworkSnapshot);
  const finalReviewTs = getReviewTimestamp(finalSnapshot);
  if (frameworkReviewTs > 0) {
    return finalReviewTs <= 0 || frameworkReviewTs > finalReviewTs;
  }
  const finalTs = Math.max(
    getSnapshotTimestamp(finalSnapshot, "final_generated_at"),
    getSnapshotTimestamp(finalSnapshot, "generated_at"),
  );
  const frameworkTs = Math.max(
    getSnapshotTimestamp(frameworkSnapshot, "framework_generated_at"),
    getSnapshotTimestamp(frameworkSnapshot, "generated_at"),
  );
  if (frameworkTs <= 0 || finalTs <= 0) {
    return false;
  }
  return frameworkTs > finalTs;
}

function toCanonicalSnapshot(
  value: ProjectCaJson | null | undefined,
  projectId: number,
  projectName: string,
  questionnaireId: number,
  questionnaireName: string,
  fieldDefinitions: InterviewDetailFieldDefinition[],
  selectedInterviewIds: number[],
): ProjectCaJson {
  const snapshot = normalizeSnapshot(value, projectId, projectName, questionnaireId, questionnaireName, fieldDefinitions);
  snapshot.selected_interview_ids = selectedInterviewIds.length > 0 ? selectedInterviewIds : snapshot.selected_interview_ids;
  return snapshot;
}

export default function CaQuestionnaireClient({ projectId, questionnaireId }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const interviewIdsQuery = searchParams.get("interview_ids") || "";
  const selectedInterviewIdsFromQuery = useMemo(() => parseInterviewIds(interviewIdsQuery), [interviewIdsQuery]);

  const [loading, setLoading] = useState(true);
  const [generatingFramework, setGeneratingFramework] = useState(false);
  const [savingFramework, setSavingFramework] = useState(false);
  const [generatingContent, setGeneratingContent] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportingWord, setExportingWord] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [exportIncludeEvidenceColumns, setExportIncludeEvidenceColumns] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const [questionnaireName, setQuestionnaireName] = useState("");
  const [fieldDefinitions, setFieldDefinitions] = useState<InterviewDetailFieldDefinition[]>(FALLBACK_META_FIELDS);
  const [frameworkSnapshot, setFrameworkSnapshot] = useState<ProjectCaJson | null>(null);
  const [finalSnapshot, setFinalSnapshot] = useState<ProjectCaJson | null>(null);
  const [finalDirty, setFinalDirty] = useState(false);
  const [showEvidenceColumns, setShowEvidenceColumns] = useState(false);
  const [detailInterviews, setDetailInterviews] = useState<Interview[]>([]);
  const [selectedInterviewIds, setSelectedInterviewIds] = useState<number[]>([]);
  const [selectedMetaFields, setSelectedMetaFields] = useState<string[]>(
    FALLBACK_META_FIELDS.map((item) => item.key),
  );

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [detailResp, caResp, fieldResp] = await Promise.all([
          getProjectDetail(projectId),
          getProjectCaTable(projectId, questionnaireId),
          getInterviewDetailFields(),
        ]);
        if (cancelled) {
          return;
        }

        const fields = fieldResp.fields?.length > 0 ? fieldResp.fields : FALLBACK_META_FIELDS;
        setFieldDefinitions(fields);
        setProjectName(detailResp.project?.name || `项目 ${projectId}`);
        setDetailInterviews(detailResp.interviews ?? []);
        const questionnaireNameText = getQuestionnaireName(detailResp.questionnaires ?? [], questionnaireId);
        setQuestionnaireName(questionnaireNameText);

        const rawCaJson = caResp.ca_json ?? null;
        const existingSnapshot = rawCaJson
          ? (rawCaJson.framework_json && typeof rawCaJson.framework_json === "object"
              ? (rawCaJson.framework_json as ProjectCaJson)
              : rawCaJson)
          : null;
        const existingFinal = rawCaJson?.final_json && typeof rawCaJson.final_json === "object"
          ? (rawCaJson.final_json as ProjectCaJson)
          : null;

        if (existingSnapshot) {
          const normalizedFramework = normalizeSnapshot(
            existingSnapshot,
            projectId,
            detailResp.project?.name || `项目 ${projectId}`,
            questionnaireId,
            questionnaireNameText,
            fields,
          );
          setFrameworkSnapshot(normalizedFramework);
          setFinalSnapshot(
            existingFinal
              ? normalizeSnapshot(
                  existingFinal,
                  projectId,
                  detailResp.project?.name || `项目 ${projectId}`,
                  questionnaireId,
                  questionnaireNameText,
                  fields,
                )
              : null,
          );
          const nextSelectedInterviewIds =
            selectedInterviewIdsFromQuery.length > 0
              ? selectedInterviewIdsFromQuery
              : (normalizedFramework.selected_interview_ids ?? []);
          setSelectedInterviewIds(nextSelectedInterviewIds.length > 0 ? nextSelectedInterviewIds : normalizedFramework.interviews?.map((item) => item.interview_id) ?? []);
          setSelectedMetaFields(normalizeMetaFields(normalizedFramework, fields));
          setFinalDirty(false);
          return;
        }

        const completedIds = (detailResp.interviews ?? [])
          .filter((item) => item.status === 2)
          .map((item) => item.id);
        const defaultInterviewIds = selectedInterviewIdsFromQuery.length > 0 ? selectedInterviewIdsFromQuery : completedIds;
        setSelectedInterviewIds(defaultInterviewIds);
        setSelectedMetaFields(fields.map((item) => item.key));
        setFrameworkSnapshot(null);
        setFinalSnapshot(null);
        setFinalDirty(false);

        const generateResp = await generateProjectCaTable(projectId, {
          questionnaire_id: questionnaireId,
          interview_ids: defaultInterviewIds,
          column_meta_fields: fields.map((item) => item.key),
          mode: "framework",
        });
        if (cancelled) {
          return;
        }
        if (!generateResp.success) {
          throw new Error(generateResp.message || "生成 CA 框架失败");
        }
        const generatedCaJson = generateResp.framework_json ?? generateResp.ca_json ?? null;
        if (!generatedCaJson) {
          throw new Error("生成 CA 框架失败：返回结果为空");
        }
        const normalizedFramework = normalizeSnapshot(
          generatedCaJson,
          projectId,
          detailResp.project?.name || `项目 ${projectId}`,
          questionnaireId,
          questionnaireNameText,
          fields,
        );
        setFrameworkSnapshot(normalizedFramework);
        setSelectedInterviewIds(
          selectedInterviewIdsFromQuery.length > 0
            ? selectedInterviewIdsFromQuery
            : normalizedFramework.selected_interview_ids ?? defaultInterviewIds,
        );
        setSelectedMetaFields(normalizeMetaFields(normalizedFramework, fields));
        message.success("CA 框架已生成");
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "加载 CA 页面失败");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId, questionnaireId, selectedInterviewIdsFromQuery]);

  const completedInterviews = useMemo(() => detailInterviews.filter((item) => item.status === 2), [detailInterviews]);

  const visibleMetaFields = useMemo(() => {
    const fieldMap = new Map(fieldDefinitions.map((item) => [item.key, item]));
    const fields = selectedMetaFields
      .map((key) => fieldMap.get(key) || { key, label: frameworkSnapshot?.column_meta_field_labels?.[key] || key, kind: "text" })
      .filter(Boolean) as InterviewDetailFieldDefinition[];
    return fields.length > 0 ? fields : fieldDefinitions;
  }, [fieldDefinitions, frameworkSnapshot, selectedMetaFields]);

  const activeSnapshot = useMemo(() => {
    if (finalSnapshot && !finalDirty && !isFinalSnapshotOutdated(frameworkSnapshot, finalSnapshot)) {
      return finalSnapshot;
    }
    return frameworkSnapshot;
  }, [finalDirty, finalSnapshot, frameworkSnapshot]);

  const visibleInterviews = useMemo(() => {
    if (!activeSnapshot) {
      return [];
    }
    const interviews = (activeSnapshot.interviews ?? []).filter((item) => item.hidden !== true);
    const selected = selectedInterviewIds.length > 0 ? new Set(selectedInterviewIds) : null;
    return interviews
      .filter((item) => (selected ? selected.has(item.interview_id) : true))
      .sort((a, b) => a.interview_id - b.interview_id);
  }, [activeSnapshot, selectedInterviewIds]);

  const questionRows = useMemo(() => {
    if (!activeSnapshot) {
      return [];
    }
    return [...(activeSnapshot.columns ?? [])]
      .sort((a, b) => {
        const aGroupOrder = Number.isFinite(Number(a.group_order)) ? Number(a.group_order) : 9999;
        const bGroupOrder = Number.isFinite(Number(b.group_order)) ? Number(b.group_order) : 9999;
        if (aGroupOrder !== bGroupOrder) {
          return aGroupOrder - bGroupOrder;
        }
        return a.order - b.order;
      });
  }, [activeSnapshot]);

  const groupedQuestionRows = useMemo(() => {
    if (!activeSnapshot) {
      return [];
    }
    const groups: Array<{
      key: string;
      label: string;
      summary: string;
      questionRows: ProjectCaColumn[];
    }> = [];
    const explicitGroups = Array.isArray(activeSnapshot.groups) ? activeSnapshot.groups : [];
    if (explicitGroups.length > 0) {
      explicitGroups
        .slice()
        .sort((a, b) => (Number(a.order) || 0) - (Number(b.order) || 0))
        .forEach((group) => {
          const key = String(group.group_id || group.title || "").trim();
          const label = String(group.title || "未分组").trim() || "未分组";
          const summary = String(group.summary || "").trim();
          const rowUids = new Set(
            Array.isArray(group.row_uids) ? group.row_uids.map((uid) => String(uid || "").trim()).filter(Boolean) : [],
          );
          const matched = questionRows.filter((column) => {
            const questionKey = getQuestionKey(column, 0);
            if (rowUids.size > 0) {
              return rowUids.has(questionKey);
            }
            const columnGroup = getGroupLabel(column);
            return columnGroup === label || String(column.group_id || "").trim() === key;
          });
          if (matched.length > 0) {
            groups.push({
              key: key || label,
              label,
              summary,
              questionRows: matched,
            });
          }
        });
      const consumed = new Set(groups.flatMap((item) => item.questionRows.map((column) => getQuestionKey(column, 0))));
      const leftovers = questionRows.filter((column, index) => {
        const questionKey = getQuestionKey(column, index);
        return !consumed.has(questionKey);
      });
      if (leftovers.length > 0) {
        const fallbackLabel = getGroupLabel(leftovers[0]);
        groups.push({
          key: fallbackLabel,
          label: fallbackLabel,
          summary: getGroupSummary(leftovers[0]),
          questionRows: leftovers,
        });
      }
      return groups;
    }

    questionRows.forEach((column) => {
      const label = getGroupLabel(column);
      const lastGroup = groups[groups.length - 1];
      if (!lastGroup || lastGroup.label !== label) {
        groups.push({
          key: label,
          label,
          summary: getGroupSummary(column),
          questionRows: [column],
        });
      } else {
        lastGroup.questionRows.push(column);
      }
    });
    return groups;
  }, [activeSnapshot, questionRows]);

  const matrixRows = useMemo<MatrixRow[]>(() => {
    if (!activeSnapshot) {
      return [];
    }
    const rows: MatrixRow[] = [
      { key: "section-detail", kind: "section", label: "访谈细节" },
      {
        key: "meta-interview_id",
        kind: "meta",
        label: "访谈ID",
        values: Object.fromEntries(visibleInterviews.map((item) => [String(item.interview_id), String(item.interview_id)])),
      },
      {
        key: "meta-interview_name",
        kind: "meta",
        label: "访谈名称",
        values: Object.fromEntries(visibleInterviews.map((item) => [String(item.interview_id), String(item.name || "")])),
      },
      {
        key: "meta-interview_date",
        kind: "meta",
        label: "访谈日期",
        values: Object.fromEntries(
          visibleInterviews.map((item) => [String(item.interview_id), item.interview_date ? item.interview_date.split("T")[0] : "-"]),
        ),
      },
    ];

    visibleMetaFields.forEach((field) => {
      rows.push({
        key: `meta-${field.key}`,
        kind: "meta",
        label: field.label,
        values: Object.fromEntries(
          visibleInterviews.map((item) => [String(item.interview_id), getInterviewMetaValue(item, field.key)]),
        ),
      });
    });

    rows.push({ key: "section-question", kind: "section", label: "问题" });

    groupedQuestionRows.forEach((group, groupIndex) => {
      const groupQuestionUids = group.questionRows.map((column, index) => getQuestionKey(column, index));
      group.questionRows.forEach((column, index) => {
        const questionUid = getQuestionKey(column, index);
        rows.push({
          key: `question-${questionUid}`,
          kind: "question",
          groupLabel: group.label || "未分组",
          groupSummary: group.summary || "",
          groupQuestionUids,
          groupRowSpan: index === 0 ? group.questionRows.length : 0,
          groupQuestionCount: group.questionRows.length,
          label: getQuestionLabel(column),
          questionUid,
          summaryText: String(column.summary_text || "/").trim() || "/",
          order: Number(column.order) || index + 1,
          hidden: Boolean(column.hidden),
          column,
          group: group.label || "未分组",
          questionType: normalizeQuestionType(column.question_type),
          values: Object.fromEntries(
            visibleInterviews.map((item) => [String(item.interview_id), getCellValue(activeSnapshot.cells, item.interview_id, questionUid)]),
          ),
          evidence: Object.fromEntries(
            visibleInterviews.map((item) => [String(item.interview_id), getCellEvidence(activeSnapshot.cells, item.interview_id, questionUid)]),
          ),
          answerRuns: Object.fromEntries(
            visibleInterviews.map((item) => [String(item.interview_id), getCellAnswerRuns(activeSnapshot.cells, item.interview_id, questionUid)]),
          ),
        });
      });
    });

    rows.push({
      key: "diff-row",
      kind: "diff",
      label: "问卷未提及但访谈中出现的内容",
      values: Object.fromEntries(
        visibleInterviews.map((item) => [String(item.interview_id), getDiffValue(activeSnapshot.diff_row, item.interview_id)]),
      ),
      evidence: Object.fromEntries(
        visibleInterviews.map((item) => [String(item.interview_id), getDiffEvidence(activeSnapshot.diff_row, item.interview_id)]),
      ),
      answerRuns: Object.fromEntries(
        visibleInterviews.map((item) => [String(item.interview_id), getDiffAnswerRuns(activeSnapshot.diff_row, item.interview_id)]),
      ),
    });

    return rows;
  }, [activeSnapshot, groupedQuestionRows, questionRows, visibleInterviews, visibleMetaFields]);

  const applyFrameworkMutation = (mutator: (draft: ProjectCaJson) => void) => {
    setFrameworkSnapshot((prev) => {
      if (!prev) {
        return prev;
      }
      const next = cloneJson(prev);
      mutator(next);
      next.selected_interview_ids = selectedInterviewIds.length > 0 ? [...selectedInterviewIds] : (next.interviews ?? []).map((item) => item.interview_id);
      return normalizeSnapshot(
        next,
        projectId,
        projectName || `项目 ${projectId}`,
        questionnaireId,
        questionnaireName || `DG ${questionnaireId}`,
        fieldDefinitions,
      );
    });
    if (finalSnapshot) {
      setFinalDirty(true);
    }
  };

  const updateCell = (questionUid: string, interviewId: number, value: string) => {
    applyFrameworkMutation((draft) => {
      const cells = draft.cells ?? {};
      const rowKey = String(interviewId);
      const rowCells = cells[rowKey] && typeof cells[rowKey] === "object" ? { ...cells[rowKey] } : {};
      rowCells[questionUid] = {
        value,
        evidence: [],
        answer_runs: [],
        locked: true,
        source: "manual",
        numeric_value: null,
      };
      cells[rowKey] = rowCells;
      draft.cells = cells;
    });
  };

  const updateDiffCell = (interviewId: number, value: string) => {
    applyFrameworkMutation((draft) => {
      const diffRow = draft.diff_row && typeof draft.diff_row === "object" ? { ...draft.diff_row } : {};
      const rowKey = String(interviewId);
      diffRow[rowKey] = {
        value,
        evidence: [],
        answer_runs: [],
        locked: true,
        source: "manual",
        numeric_value: null,
      };
      draft.diff_row = diffRow;
    });
  };

  const handleRegenerateFramework = async () => {
    if (selectedInterviewIds.length < 2) {
      message.error("至少选择 2 个已完成访谈");
      return;
    }
    if (!questionnaireId) {
      message.error("请先确认当前 CA 对应的 DG");
      return;
    }
    setGeneratingFramework(true);
    try {
      const resp = await generateProjectCaTable(projectId, {
        questionnaire_id: questionnaireId,
        interview_ids: selectedInterviewIds,
        column_meta_fields: selectedMetaFields,
        mode: "framework",
      });
      if (!resp.success) {
        throw new Error(resp.message || "重新生成 CA 框架失败");
      }
      const nextFramework = resp.framework_json ?? resp.ca_json ?? null;
      if (!nextFramework) {
        throw new Error("重新生成 CA 框架失败：返回结果为空");
      }
      const normalizedFramework = normalizeSnapshot(
        nextFramework,
        projectId,
        projectName || `项目 ${projectId}`,
        questionnaireId,
        questionnaireName || `DG ${questionnaireId}`,
        fieldDefinitions,
      );
      setFrameworkSnapshot(normalizedFramework);
      setFinalSnapshot(null);
      setFinalDirty(false);
      setSelectedInterviewIds(normalizedFramework.selected_interview_ids ?? selectedInterviewIds);
      setSelectedMetaFields(normalizeMetaFields(normalizedFramework, fieldDefinitions));
      message.success("CA 框架已重新生成");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "重新生成 CA 框架失败");
    } finally {
      setGeneratingFramework(false);
    }
  };

  const handleSaveFramework = async () => {
    if (!frameworkSnapshot) {
      message.error("请先生成或加载框架");
      return;
    }
    setSavingFramework(true);
    try {
      const canonicalFramework = toCanonicalSnapshot(
        frameworkSnapshot,
        projectId,
        projectName || `项目 ${projectId}`,
        questionnaireId,
        questionnaireName || `DG ${questionnaireId}`,
        fieldDefinitions,
        selectedInterviewIds,
      );
      const canonicalFinal = finalSnapshot
        ? toCanonicalSnapshot(
            finalSnapshot,
            projectId,
            projectName || `项目 ${projectId}`,
            questionnaireId,
            questionnaireName || `DG ${questionnaireId}`,
            fieldDefinitions,
            selectedInterviewIds,
          )
        : null;
      const resp = await saveProjectCaFramework(projectId, {
        questionnaire_id: questionnaireId,
        framework_json: canonicalFramework,
        framework_status: "reviewed",
        final_status: "pending",
        generated_at: canonicalFramework.generated_at || canonicalFramework.framework_generated_at || undefined,
        framework_generated_at: canonicalFramework.framework_generated_at || canonicalFramework.generated_at || undefined,
        reviewed_at: new Date().toISOString(),
      });
      if (!resp.success) {
        throw new Error(resp.message || "保存 CA 框架失败");
      }
      const reviewedAt = new Date().toISOString();
      setFrameworkSnapshot((prev) =>
        prev
          ? normalizeSnapshot(
              {
                ...canonicalFramework,
                reviewed_at: reviewedAt,
                framework_status: "reviewed",
              },
              projectId,
              projectName || `项目 ${projectId}`,
              questionnaireId,
              questionnaireName || `DG ${questionnaireId}`,
              fieldDefinitions,
            )
          : prev,
      );
      setFinalSnapshot(null);
      setFinalDirty(false);
      message.success("CA 框架已保存");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存 CA 框架失败");
    } finally {
      setSavingFramework(false);
    }
  };

  const handleGenerateContent = async () => {
    if (!frameworkSnapshot) {
      message.error("请先生成或加载框架");
      return;
    }
    setGeneratingContent(true);
    try {
      const canonicalFramework = toCanonicalSnapshot(
        frameworkSnapshot,
        projectId,
        projectName || `项目 ${projectId}`,
        questionnaireId,
        questionnaireName || `DG ${questionnaireId}`,
        fieldDefinitions,
        selectedInterviewIds,
      );
      const resp = await generateProjectCaTable(projectId, {
        questionnaire_id: questionnaireId,
        interview_ids: canonicalFramework.selected_interview_ids ?? selectedInterviewIds,
        column_meta_fields: selectedMetaFields,
        mode: "final",
        framework_json: canonicalFramework,
      });
      if (!resp.success) {
        throw new Error(resp.message || "生成 CA 内容失败");
      }
      const nextFramework = resp.framework_json ?? resp.ca_json ?? null;
      const nextFinal = resp.final_json ?? resp.ca_json ?? null;
      if (nextFramework) {
        setFrameworkSnapshot(
          normalizeSnapshot(
            nextFramework,
            projectId,
            projectName || `项目 ${projectId}`,
            questionnaireId,
            questionnaireName || `DG ${questionnaireId}`,
            fieldDefinitions,
          ),
        );
      }
      if (nextFinal) {
        setFinalSnapshot(
          normalizeSnapshot(
            nextFinal,
            projectId,
            projectName || `项目 ${projectId}`,
            questionnaireId,
            questionnaireName || `DG ${questionnaireId}`,
            fieldDefinitions,
          ),
        );
      }
      setFinalDirty(false);
      message.success("CA 内容已生成");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "生成 CA 内容失败");
    } finally {
      setGeneratingContent(false);
    }
  };

  const handleExport = async (includeEvidenceColumns: boolean) => {
    const snapshot =
      finalSnapshot && !finalDirty && !isFinalSnapshotOutdated(frameworkSnapshot, finalSnapshot)
        ? finalSnapshot
        : frameworkSnapshot;
    if (!snapshot) {
      message.error("请先生成或加载 CA");
      return;
    }
    setExporting(true);
    try {
      const canonical = toCanonicalSnapshot(
        snapshot,
        projectId,
        projectName || `项目 ${projectId}`,
        questionnaireId,
        questionnaireName || `DG ${questionnaireId}`,
        fieldDefinitions,
        selectedInterviewIds,
      );
      const resp = await exportProjectCaTableXlsx(projectId, {
        questionnaire_id: questionnaireId,
        ca_json: canonical,
        include_evidence_columns: includeEvidenceColumns,
      });
      const url = URL.createObjectURL(resp.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = resp.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      message.success("Excel 已导出");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "导出 Excel 失败");
    } finally {
      setExporting(false);
    }
  };

  const handleExportWord = async () => {
    const snapshot =
      finalSnapshot && !finalDirty && !isFinalSnapshotOutdated(frameworkSnapshot, finalSnapshot)
        ? finalSnapshot
        : frameworkSnapshot;
    if (!snapshot) {
      message.error("请先生成或加载 CA");
      return;
    }
    setExportingWord(true);
    try {
      const canonical = toCanonicalSnapshot(
        snapshot,
        projectId,
        projectName || `项目 ${projectId}`,
        questionnaireId,
        questionnaireName || `DG ${questionnaireId}`,
        fieldDefinitions,
        selectedInterviewIds,
      );
      const resp = await exportProjectCaTableWord(projectId, {
        questionnaire_id: questionnaireId,
        ca_json: canonical,
      });
      const url = URL.createObjectURL(resp.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = resp.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      message.success("Word 已导出");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "导出 Word 失败");
    } finally {
      setExportingWord(false);
    }
  };

  const handleMetaFieldChange = (field: string, checked: boolean) => {
    setSelectedMetaFields((prev) => {
      if (checked) {
        return prev.includes(field) ? prev : [...prev, field];
      }
      return prev.filter((item) => item !== field);
    });
    if (finalSnapshot) {
      setFinalDirty(true);
    }
  };

  const addQuestionRow = () => {
    applyFrameworkMutation((draft) => {
      const columns = Array.isArray(draft.columns) ? [...draft.columns] : [];
      const interviews = draft.interviews ?? [];
      const groups = Array.isArray(draft.groups) ? [...draft.groups] : [];
      const nextOrder = columns.reduce((max, column) => {
        const order = Number(column.order) || 0;
        return Math.max(max, order);
      }, 0) + 1;
      const existingKeys = new Set(
        columns
          .map((column) => String(column.question_uid || column.column_id || "").trim())
          .filter(Boolean),
      );
      let suffix = 1;
      let questionUid = `custom_question_${Date.now()}`;
      while (existingKeys.has(questionUid)) {
        suffix += 1;
        questionUid = `custom_question_${Date.now()}_${suffix}`;
      }
      const nextColumn: ProjectCaColumn = {
        column_id: questionUid,
        order: nextOrder,
        question_text: "自定义问题",
        display_text: "自定义问题",
        summary_text: "/",
        hidden: false,
        question_uid: questionUid,
        group: "未分组",
        group_order: 9999,
        group_summary: "",
        question_type: "qualitative",
      };
      columns.push(nextColumn);
      draft.columns = columns;
      const ungroupedTitle = "未分组";
      const ungroupedGroupIndex = groups.findIndex((group) => String(group?.title || "").trim() === ungroupedTitle);
      if (ungroupedGroupIndex >= 0) {
        const targetGroup = groups[ungroupedGroupIndex];
        const rowUids = Array.isArray(targetGroup.row_uids) ? [...targetGroup.row_uids] : [];
        rowUids.push(questionUid);
        groups[ungroupedGroupIndex] = {
          ...targetGroup,
          row_uids: rowUids,
        };
      } else {
        const nextGroupOrder = groups.reduce((max, group) => Math.max(max, Number(group?.order) || 0), 0) + 1;
        groups.push({
          group_id: `group_${Date.now()}`,
          order: nextGroupOrder,
          title: ungroupedTitle,
          summary: "",
          row_uids: [questionUid],
        });
      }
      draft.groups = groups;
      const cells = draft.cells ?? {};
      interviews.forEach((interview, interviewIndex) => {
        const interviewKey = String(interview.interview_id || interviewIndex + 1);
        const rowCells = cells[interviewKey] && typeof cells[interviewKey] === "object" ? { ...cells[interviewKey] } : {};
        rowCells[questionUid] = {
          value: "",
          evidence: [],
          locked: false,
          source: "framework",
          numeric_value: null,
        };
        cells[interviewKey] = rowCells;
      });
      draft.cells = cells;
    });
  };

  const updateQuestionRow = (questionUid: string, patch: Partial<ProjectCaColumn>) => {
    applyFrameworkMutation((draft) => {
      const columns = Array.isArray(draft.columns) ? [...draft.columns] : [];
      const index = columns.findIndex((column) => String(column.question_uid || column.column_id || "") === questionUid);
      if (index < 0) {
        return;
      }
      const current = columns[index];
      const nextColumn: ProjectCaColumn = {
        ...current,
        ...patch,
        column_id: String(patch.column_id || current.column_id || questionUid),
        question_uid: String(patch.question_uid || current.question_uid || current.column_id || questionUid),
        question_text: patch.question_text !== undefined ? String(patch.question_text || "") : current.question_text,
        display_text:
          patch.display_text !== undefined
            ? String(patch.display_text || "")
            : current.display_text ?? current.question_text,
        group:
          patch.group !== undefined
            ? String(patch.group || "")
            : current.group ?? "",
        group_order:
          patch.group_order !== undefined && Number.isFinite(Number(patch.group_order))
            ? Number(patch.group_order)
            : current.group_order ?? null,
        group_summary:
          patch.group_summary !== undefined
            ? String(patch.group_summary || "")
            : current.group_summary ?? "",
        summary_text:
          patch.summary_text !== undefined
            ? String(patch.summary_text || "").trim() || "/"
            : current.summary_text ?? "/",
        question_type:
          patch.question_type !== undefined
            ? normalizeQuestionType(patch.question_type)
            : normalizeQuestionType(current.question_type),
        order:
          patch.order !== undefined && Number.isFinite(Number(patch.order))
            ? Math.max(1, Number(patch.order))
            : current.order,
        hidden: patch.hidden !== undefined ? Boolean(patch.hidden) : Boolean(current.hidden),
      };
      columns[index] = nextColumn;
      draft.columns = columns;
    });
  };

  const updateGroupRow = (questionUids: string[], groupTitle: string) => {
    applyFrameworkMutation((draft) => {
      const columns = Array.isArray(draft.columns) ? [...draft.columns] : [];
      const targetUids = new Set(questionUids.map((item) => String(item || "").trim()).filter(Boolean));
      columns.forEach((column) => {
        const questionUid = String(column.question_uid || column.column_id || "").trim();
        if (!targetUids.has(questionUid)) {
          return;
        }
        column.group = groupTitle;
      });
      draft.columns = columns;
      if (Array.isArray(draft.groups)) {
        draft.groups = draft.groups.map((group) => {
          if (!group || !Array.isArray(group.row_uids)) {
            return group;
          }
          const groupRowUids = new Set(group.row_uids.map((item) => String(item || "").trim()).filter(Boolean));
          const intersects = questionUids.some((item) => groupRowUids.has(String(item || "").trim()));
          if (!intersects) {
            return group;
          }
          return {
            ...group,
            title: groupTitle,
          };
        });
      }
    });
  };

  const deleteQuestionRow = (questionUid: string) => {
    applyFrameworkMutation((draft) => {
      const columns = Array.isArray(draft.columns) ? [...draft.columns] : [];
      draft.columns = columns.filter((column) => String(column.question_uid || column.column_id || "") !== questionUid);
      if (Array.isArray(draft.groups)) {
        draft.groups = draft.groups
          .map((group) => {
            if (!group) {
              return group;
            }
            const rowUids = Array.isArray(group.row_uids)
              ? group.row_uids.map((item) => String(item || "").trim()).filter((item) => item && item !== questionUid)
              : [];
            return {
              ...group,
              row_uids: rowUids,
            };
          })
          .filter((group) => Array.isArray(group?.row_uids) ? group.row_uids.length > 0 : true);
      }
      const cells = draft.cells ?? {};
      Object.keys(cells).forEach((interviewKey) => {
        if (cells[interviewKey] && typeof cells[interviewKey] === "object") {
          const nextRow = { ...cells[interviewKey] };
          delete nextRow[questionUid];
          cells[interviewKey] = nextRow;
        }
      });
      draft.cells = cells;
    });
  };

  const matrixColumns: any[] = useMemo(() => {
    if (!activeSnapshot) {
      return [];
    }

    const groupWidth = 160;
    const questionWidth = 260;
    const answerWidth = showEvidenceColumns ? 260 : 300;
    const evidenceWidth = 320;
    const statsWidth = 220;
    const summaryWidth = 260;
    const totalLeafColumns = 4 + visibleInterviews.length * (showEvidenceColumns ? 2 : 1);

    const renderGroupCell = (row: MatrixRow) => {
      if (row.kind === "section") {
        return {
          children: <div className="font-semibold text-slate-700">{row.label}</div>,
          props: { colSpan: totalLeafColumns },
        };
      }
      if (row.kind === "meta") {
        return <Text type="secondary">-</Text>;
      }
      if (row.kind === "diff") {
        return <Tag color="green">差异</Tag>;
      }
      if (row.kind !== "question") {
        return null;
      }
      if (row.groupRowSpan <= 0) {
        return { children: null, props: { rowSpan: 0 } };
      }
      return {
        children: (
          <Space direction="vertical" size={6} style={{ width: "100%" }}>
            <Space align="center" size={8} wrap style={{ width: "100%" }}>
              <Tag color="green">主题分组</Tag>
              <Input
                value={row.groupLabel}
                onChange={(event) => updateGroupRow(row.groupQuestionUids, event.target.value)}
                style={{ width: 110 }}
              />
              <Tag color="processing">{row.groupQuestionCount} 行</Tag>
            </Space>
            <Text type="secondary" className="text-xs">
              {row.groupSummary || "该主题下的分析行。"}
            </Text>
          </Space>
        ),
        props: { rowSpan: row.groupRowSpan },
      };
    };

    const renderQuestionCell = (row: MatrixRow) => {
      if (row.kind === "section") {
        return { children: null, props: { colSpan: 0 } };
      }
      if (row.kind === "meta") {
        return <Text className="font-medium text-slate-700">{row.label}</Text>;
      }
      if (row.kind === "diff") {
        return (
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <div className="rounded-2xl border border-emerald-100 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-900">
              {row.label}
            </div>
            <Text type="secondary" className="text-xs">
              最后一行，用来展示问卷未覆盖但访谈中提到的内容。
            </Text>
          </Space>
        );
      }
      return (
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <Input.TextArea
            value={row.column.display_text ?? row.column.question_text ?? ""}
            title={row.column.question_text || ""}
            autoSize={{ minRows: 1, maxRows: 2 }}
            style={{ width: 240, minHeight: 40, resize: "none" }}
            onChange={(event) =>
              updateQuestionRow(row.questionUid, {
                display_text: event.target.value,
              })
            }
          />
          <Space align="center" size={8} wrap style={{ width: "100%" }}>
            <Tag color={row.questionType === "quantitative" ? "gold" : "green"}>
              {row.questionType === "quantitative" ? "定量" : "定性"}
            </Tag>
            <Select
              value={row.questionType}
              style={{ width: 110 }}
              options={[
                { label: "定性", value: "qualitative" },
                { label: "定量", value: "quantitative" },
              ]}
              onChange={(value) =>
                updateQuestionRow(row.questionUid, {
                  question_type: value,
                })
              }
            />
            <Checkbox
              checked={row.hidden}
              onChange={(event) => updateQuestionRow(row.questionUid, { hidden: event.target.checked })}
            >
              隐藏
            </Checkbox>
            <Button danger size="small" onClick={() => deleteQuestionRow(row.questionUid)}>
              删除
            </Button>
          </Space>
          <Text type="secondary" className="text-xs">
            {row.hidden ? "已隐藏" : "问题行"}
          </Text>
        </Space>
      );
    };

    const renderAnswerCell = (row: MatrixRow, interviewId: number) => {
      if (row.kind === "section") {
        return { children: null, props: { colSpan: 0 } };
      }
      if (row.kind === "meta") {
        return <Text className="text-slate-700">{row.values[String(interviewId)] || "/"}</Text>;
      }
      const value = row.values[String(interviewId)] || "/";
      const placeholder = row.kind === "diff" ? "自由补充问卷未提及的内容" : "填写该问题在此访谈下的回答";
      const answerRuns = row.answerRuns[String(interviewId)] || [];
      const showRuns = value && value !== "/" && answerRuns.length > 0;
      return (
        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          {showRuns ? (
            <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 px-3 py-2 text-sm leading-6 text-slate-700">
              {answerRuns.map((run, index) => (
                <span
                  key={`${row.key}-${interviewId}-run-${index}`}
                  className={run.highlight ? "rounded bg-emerald-200/80 px-0.5 font-semibold text-emerald-900" : ""}
                >
                  {run.text}
                </span>
              ))}
            </div>
          ) : null}
          <Input.TextArea
            value={value}
            onChange={(event) =>
              row.kind === "diff"
                ? updateDiffCell(interviewId, event.target.value)
                : updateCell(row.questionUid, interviewId, event.target.value)
            }
            autoSize={{ minRows: row.kind === "diff" ? 2 : 3, maxRows: row.kind === "diff" ? 6 : 8 }}
            placeholder={placeholder}
          />
        </Space>
      );
    };

    const renderEvidenceCell = (row: MatrixRow, interviewId: number) => {
      if (row.kind === "section") {
        return { children: null, props: { colSpan: 0 } };
      }
      if (row.kind === "meta") {
        return <Text type="secondary">-</Text>;
      }
      const evidence = row.evidence[String(interviewId)] || [];
      if (evidence.length === 0) {
        return <Text type="secondary">/</Text>;
      }
      return (
        <div className="whitespace-pre-wrap text-xs leading-6 text-slate-600">
          {evidence.map((item, index) => (
            <div key={`${interviewId}-${row.key}-evidence-${index}`} className="rounded-xl border border-emerald-100 bg-emerald-50/60 px-3 py-2">
              {item}
            </div>
          ))}
        </div>
      );
    };

    const renderStatsCell = (row: MatrixRow) => {
      if (row.kind === "section") {
        return { children: null, props: { colSpan: 0 } };
      }
      if (row.kind === "meta") {
        return <Text type="secondary">-</Text>;
      }
      if (row.kind === "question") {
        const stats = computeQuestionStats(activeSnapshot, row.column, visibleInterviews);
        return <Text className="text-slate-600">{stats.summary}</Text>;
      }
      const validCount = visibleInterviews.reduce((count, item) => {
        const value = getDiffValue(activeSnapshot.diff_row, item.interview_id);
        return count + (value && value !== "/" ? 1 : 0);
      }, 0);
      return <Text className="text-slate-600">有效 {validCount}</Text>;
    };

    const renderSummaryCell = (row: MatrixRow) => {
      if (row.kind === "section") {
        return { children: null, props: { colSpan: 0 } };
      }
      if (row.kind === "meta" || row.kind === "diff") {
        return <Text type="secondary">-</Text>;
      }
      return <div className="whitespace-pre-wrap text-sm leading-6 text-slate-700">{row.summaryText || "/"}</div>;
    };

    const columns: any[] = [
      {
        key: "group",
        title: "主题分组",
        fixed: "left" as const,
        width: groupWidth,
        render: (_: unknown, row: MatrixRow) => {
          return renderGroupCell(row);
        },
      },
      {
        key: "question",
        title: "问题内容",
        dataIndex: "question",
        fixed: "left" as const,
        width: questionWidth,
        render: (_: unknown, row: MatrixRow) => {
          return renderQuestionCell(row);
        },
      },
      {
        key: "stats",
        title: "统计",
        dataIndex: "stats",
        width: statsWidth,
        render: (_: unknown, row: MatrixRow) => renderStatsCell(row),
      },
      {
        key: "summary",
        title: "总结",
        dataIndex: "summary",
        width: summaryWidth,
        render: (_: unknown, row: MatrixRow) => renderSummaryCell(row),
      },
      ...visibleInterviews.map((interview, index) => {
        const interviewId = interview.interview_id;
        const interviewTitle = (
          <div className="space-y-1 text-left">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">访谈 {index + 1}</div>
            <div className="text-sm font-semibold text-slate-900">{interview.name || `访谈 ${interviewId}`}</div>
            <div className="text-xs text-slate-500">{interview.interview_date ? interview.interview_date.split("T")[0] : "-"}</div>
          </div>
        );
        const children: any[] = [
          {
            key: `${interviewId}-answer`,
            title: "回答",
            width: answerWidth,
            render: (_: unknown, row: MatrixRow) => renderAnswerCell(row, interviewId),
          },
        ];
        if (showEvidenceColumns) {
          children.push({
            key: `${interviewId}-evidence`,
            title: "引用",
            width: evidenceWidth,
            render: (_: unknown, row: MatrixRow) => renderEvidenceCell(row, interviewId),
          });
        }
        return {
          key: String(interviewId),
          title: interviewTitle,
          children,
        };
      }),
    ];
    return columns;
  }, [activeSnapshot, groupedQuestionRows, showEvidenceColumns, updateCell, updateDiffCell, updateGroupRow, updateQuestionRow, visibleInterviews]);

  const matrixData = useMemo(() => matrixRows, [matrixRows]);

  const statusDescription = finalDirty
    ? "框架已修改，当前最终版已过期，请重新生成内容。"
    : finalSnapshot
      ? "最终版已生成，可导出 Excel。"
      : "请先 review 框架，再生成内容。";

  const selectedInterviewSummary = useMemo(() => {
    if (!frameworkSnapshot) {
      return [];
    }
    return (frameworkSnapshot.selected_interview_ids ?? []).map((id) => {
      const interview = detailInterviews.find((item) => item.id === id);
      return {
        id,
        label: interview ? buildInterviewLabel(interview) : `访谈 ${id}`,
      };
    });
  }, [detailInterviews, frameworkSnapshot]);

  return (
    <div className="min-h-screen bg-slate-50">
      <BrandHero
        title="CA 矩阵编辑"
        description="访谈细节行在前，问题行在后。先 review 框架，再生成内容并导出 Excel。"
        backButton={
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push(`/projects/${projectId}/ca`)} className="summarynotes-hero-back">
            返回上一级
          </Button>
        }
        stats={
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-right shadow-[0_12px_28px_-20px_rgba(15,23,42,0.22)]">
            <div className="text-xs text-slate-500">项目 / DG</div>
            <div className="mt-1 text-xl font-semibold text-slate-900">{projectName || projectId}</div>
            <div className="mt-1 text-sm text-slate-500">{questionnaireName || questionnaireId}</div>
          </div>
        }
      />

      <div className="px-6 py-6 md:px-8">
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Card style={{ borderRadius: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-slate-900">编辑流程</div>
                  <Text type="secondary">{statusDescription}</Text>
                </div>
                <Space wrap>
                  <Button icon={<ReloadOutlined />} loading={generatingFramework} onClick={() => void handleRegenerateFramework()}>
                    重新生成框架
                  </Button>
                  <Button icon={<SaveOutlined />} loading={savingFramework} onClick={() => void handleSaveFramework()}>
                    保存框架
                  </Button>
                  <Button type="primary" loading={generatingContent} onClick={() => void handleGenerateContent()}>
                    生成内容
                  </Button>
                  <Button icon={<DownloadOutlined />} loading={exporting} onClick={() => setExportDialogOpen(true)}>
                    导出 Excel
                  </Button>
                  <Button icon={<DownloadOutlined />} loading={exportingWord} onClick={() => void handleExportWord()}>
                    导出 Word
                  </Button>
                </Space>
              </div>
              <Paragraph className="!mb-0 text-sm text-slate-500">
                默认沿用从详情页传入的访谈选择。矩阵按主题分组展开，左侧是分组列，右侧是问题内容列，后面继续保留统计、总结与访谈回答列。
              </Paragraph>
            </Space>
          </Card>

          <Modal
            title="导出 Excel"
            open={exportDialogOpen}
            okText="导出"
            cancelText="取消"
            confirmLoading={exporting}
            onOk={() => {
              setExportDialogOpen(false);
              void handleExport(exportIncludeEvidenceColumns);
            }}
            onCancel={() => {
              if (!exporting) {
                setExportDialogOpen(false);
              }
            }}
          >
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Text type="secondary">请选择导出时是否包含原文引用列。</Text>
              <Radio.Group
                value={exportIncludeEvidenceColumns}
                onChange={(event) => {
                  setExportIncludeEvidenceColumns(event.target.value as boolean);
                }}
              >
                <Space direction="vertical" size={8}>
                  <Radio value={true}>包含原文引用列</Radio>
                  <Radio value={false}>不包含原文引用列</Radio>
                </Space>
              </Radio.Group>
            </Space>
          </Modal>

          {error ? <Alert type="error" message={error} /> : null}

          <Card style={{ borderRadius: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-slate-900">当前访谈列</div>
                  <Text type="secondary">已纳入矩阵的访谈标签。</Text>
                </div>
                <Tag color="blue">{frameworkSnapshot ? `${frameworkSnapshot.columns?.length ?? 0} 行` : "0 行"}</Tag>
              </div>
              <div className="flex flex-wrap gap-2">
                {selectedInterviewSummary.length > 0 ? (
                  selectedInterviewSummary.map((item) => (
                    <Tag key={item.id} color="geekblue">
                      {item.label}
                    </Tag>
                  ))
                ) : (
                  <Text type="secondary">尚未选择访谈。</Text>
                )}
              </div>
            </Space>
          </Card>

          <Card style={{ borderRadius: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-slate-900">访谈选择</div>
                  <Text type="secondary">只纳入状态为已完成的访谈。</Text>
                </div>
                <Tag color="cyan">{selectedInterviewIds.length} 已选</Tag>
              </div>
              <Checkbox.Group
                style={{ width: "100%" }}
                value={selectedInterviewIds}
                onChange={(values) => {
                  setSelectedInterviewIds(values.map((value) => Number(value)));
                  if (finalSnapshot) {
                    setFinalDirty(true);
                  }
                }}
              >
                <Space direction="vertical" style={{ width: "100%" }}>
                  {completedInterviews.length > 0 ? (
                    completedInterviews.map((item) => (
                      <Checkbox key={item.id} value={item.id}>
                        {buildInterviewLabel(item)}
                      </Checkbox>
                    ))
                  ) : (
                    <Text type="secondary">当前项目下暂无状态为“已完成”的访谈。</Text>
                  )}
                </Space>
              </Checkbox.Group>
            </Space>
          </Card>

          <Card style={{ borderRadius: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-slate-900">细节字段</div>
                  <Text type="secondary">这些字段会成为矩阵前半部分的行头。</Text>
                </div>
                <Tag color="gold">{selectedMetaFields.length} 字段</Tag>
              </div>
              <Space wrap>
                {fieldDefinitions.map((field) => (
                  <Checkbox
                    key={field.key}
                    checked={selectedMetaFields.includes(field.key)}
                    onChange={(event) => handleMetaFieldChange(field.key, event.target.checked)}
                  >
                    {field.label}
                  </Checkbox>
                ))}
              </Space>
            </Space>
          </Card>

          <Card
            style={{ borderRadius: 20 }}
            title="CA 矩阵"
            extra={
              <Space>
                <Button
                  icon={showEvidenceColumns ? <CaretLeftOutlined /> : <CaretRightOutlined />}
                  onClick={() => setShowEvidenceColumns((prev) => !prev)}
                >
                  {showEvidenceColumns ? "隐藏引用列" : "显示引用列"}
                </Button>
                <Button onClick={addQuestionRow}>新增问题行</Button>
              </Space>
            }
          >
            {loading ? (
              <div className="flex items-center justify-center py-16">
                <Spin />
              </div>
            ) : !activeSnapshot ? (
              <Text type="secondary">当前暂无 CA 结果，请先选择访谈并点击“生成 CA”。</Text>
            ) : (
              <div className="overflow-auto">
                <Paragraph className="!mb-3 text-sm text-slate-500">
                  主题分组会以左侧纵向合并单元格展示；问题内容列保留题目编辑、定性/定量切换与删除操作，点击右上角箭头可展开或收起每个访谈右侧的引用列。
                </Paragraph>
                <Table
                  rowKey="key"
                  columns={matrixColumns}
                  dataSource={matrixData}
                  pagination={false}
                  bordered
                  size="middle"
                  scroll={{ x: "max-content", y: 760 }}
                  rowClassName={(record) =>
                    record.kind === "section"
                      ? "bg-slate-100 font-semibold"
                      : record.kind === "diff"
                        ? "bg-emerald-50/50"
                        : record.kind === "question" && record.hidden
                        ? "bg-slate-50 text-slate-400"
                        : ""
                  }
                />
              </div>
            )}
          </Card>
        </Space>
      </div>
    </div>
  );
}
