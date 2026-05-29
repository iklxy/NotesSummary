"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Divider,
  Form,
  Input,
  InputNumber,
  Layout,
  List,
  Modal,
  Row,
  Select,
  Space,
  Tabs,
  Spin,
  Tag,
  Typography,
  Upload,
  Switch,
  message,
} from "antd";
import type { UploadFile } from "antd/es/upload/interface";
import type { Dayjs } from "dayjs";
import {
  ArrowLeftOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import BrandHero from "../../../components/BrandHero";
import MarkdownContent from "../../../components/MarkdownContent";
import QuestionnaireHotwordReviewModal from "../../../components/QuestionnaireHotwordReviewModal";
import { createInterview } from "../../../lib/interviewsApi";
import { deleteInterview } from "../../../lib/interviewsApi";
import {
  createProjectQuestionnaire,
  deleteProjectQuestionnaire,
  getProjectQuestionnaire,
  updateProjectQuestionnaireHotwords,
} from "../../../lib/projectQuestionnairesApi";
import {
  getInterviewDetail,
  updateInterviewDetail,
  updateInterviewName,
} from "../../../lib/interviewsApi";
import { updateProjectKeyBqCurrent } from "../../../lib/projectKeyBqApi";
import { getProjectDetail, updateProject, uploadProjectGuide } from "../../../lib/projectsApi";
import type {
  CreatedInterviewResponse,
  InterviewDetailResponse,
  InterviewDetailFieldDefinition,
  KeyBqJson,
  ProjectDetail,
  ProjectRole,
  ProjectQuestionnaire,
  QuestionnaireHotwordCandidate,
} from "../../../lib/types";

const { Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface Props {
  projectId: number;
}

interface KeyBqDimensionFormValues {
  name?: string;
  description?: string;
}

interface KeyBqDimensionJsonValue {
  name: string;
  description?: string;
}

interface KeyBqItemFormValues {
  text?: string;
  dimensions?: KeyBqDimensionFormValues[];
}

interface KeyBqFormValues {
  key_bq_list: KeyBqItemFormValues[];
}

interface InterviewFormValues {
  interview_date?: Dayjs | null;
  role_id?: number | null;
  questionnaire_id?: number | null;
}

type InterviewDetailValues = Record<string, string | number | null | undefined>;

interface InterviewDetailFieldDraft extends InterviewDetailFieldDefinition {
  uid: string;
  value?: string | number | null;
  isPreset?: boolean;
}

const DEFAULT_DOCTOR_ROLE_FIELDS: InterviewDetailFieldDefinition[] = [
  { key: "doctor_level", label: "医生级别", kind: "text" },
  { key: "doctor_title", label: "职称", kind: "text" },
  { key: "city", label: "城市", kind: "text" },
  { key: "hospital", label: "所在医院", kind: "text" },
  { key: "department", label: "科室", kind: "text" },
  { key: "hospital_decile", label: "医院Decile", kind: "number" },
];

const DEFAULT_PATIENT_ROLE_FIELDS: InterviewDetailFieldDefinition[] = [
  { key: "patient_disease_type", label: "患者疾病类型", kind: "text" },
  { key: "region", label: "地区", kind: "text" },
  { key: "hospital", label: "就诊医院", kind: "text" },
  { key: "department", label: "就诊科室", kind: "text" },
];

const DEFAULT_CUSTOM_ROLE_FIELDS: InterviewDetailFieldDefinition[] = [];

const DEFAULT_ROLE_TEMPLATE_MAP: Record<string, InterviewDetailFieldDefinition[]> = {
  doctor: DEFAULT_DOCTOR_ROLE_FIELDS,
  patient: DEFAULT_PATIENT_ROLE_FIELDS,
  custom: DEFAULT_CUSTOM_ROLE_FIELDS,
};

function cloneFieldDefinitions(fields: InterviewDetailFieldDefinition[]): InterviewDetailFieldDefinition[] {
  return fields.map((field) => ({
    key: field.key,
    label: field.label,
    kind: field.kind,
  }));
}

function normalizeRoleType(value?: string | null): "doctor" | "patient" | "custom" | null {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "doctor" || normalized === "医生") {
    return "doctor";
  }
  if (normalized === "patient" || normalized === "患者") {
    return "patient";
  }
  if (normalized === "custom" || normalized === "自定义" || normalized === "other") {
    return "custom";
  }
  return null;
}

function getRoleTypeLabel(value?: string | null): string {
  const normalized = normalizeRoleType(value);
  if (normalized === "doctor") {
    return "医生";
  }
  if (normalized === "patient") {
    return "患者";
  }
  if (normalized === "custom") {
    return "自定义角色";
  }
  return String(value || "").trim() || "角色";
}

function getDefaultRoleFields(roleType?: string | null): InterviewDetailFieldDefinition[] {
  const normalized = normalizeRoleType(roleType);
  if (!normalized) {
    return [];
  }
  return cloneFieldDefinitions(DEFAULT_ROLE_TEMPLATE_MAP[normalized] ?? []);
}

function normalizeFieldDefinitions(
  fields?: Array<Partial<InterviewDetailFieldDefinition>> | null,
): InterviewDetailFieldDefinition[] {
  if (!Array.isArray(fields)) {
    return [];
  }
  const seen = new Set<string>();
  const result: InterviewDetailFieldDefinition[] = [];
  fields.forEach((field) => {
    const key = String(field?.key || "").trim();
    const label = String(field?.label || "").trim();
    const kind = String(field?.kind || "text").trim() || "text";
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    result.push({
      key,
      label: label || key,
      kind,
    });
  });
  return result;
}

function buildInterviewFieldOptions(role?: ProjectRole | null): InterviewDetailFieldDefinition[] {
  if (!role) {
    return [];
  }
  const fields = normalizeFieldDefinitions(role.detail_schema_json);
  if (fields.length > 0) {
    return fields;
  }
  return getDefaultRoleFields(role.role_type);
}

function createInterviewDetailFieldUid(): string {
  return `field-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createInterviewDetailFieldDraft(
  field?: Partial<InterviewDetailFieldDefinition>,
  value?: string | number | null,
  options?: { isPreset?: boolean },
): InterviewDetailFieldDraft {
  return {
    uid: createInterviewDetailFieldUid(),
    key: String(field?.key || "").trim(),
    label: String(field?.label || "").trim() || String(field?.key || "").trim(),
    kind: String(field?.kind || "text").trim() || "text",
    value,
    isPreset: Boolean(options?.isPreset),
  };
}

function buildInterviewDetailFieldDraftsByType(roleType?: string | null): InterviewDetailFieldDraft[] {
  const fields = getDefaultRoleFields(normalizeRoleType(roleType));
  if (fields.length === 0) {
    return [createInterviewDetailFieldDraft(undefined, undefined, { isPreset: false })];
  }
  return fields.map((field) => createInterviewDetailFieldDraft(field, undefined, { isPreset: true }));
}

interface QuestionnaireReviewState {
  questionnaireId: number;
  questionnaireName: string;
  candidates: QuestionnaireHotwordCandidate[];
}

function normalizeKeyBqDimensionValues(value?: KeyBqDimensionFormValues | null): KeyBqDimensionJsonValue | null {
  if (!value) {
    return null;
  }
  const name = String(value.name || "").trim();
  const description = String(value.description || "").trim();
  if (!name && !description) {
    return null;
  }
  return {
    name,
    description: description || undefined,
  };
}

function pickFirstNonEmptyDimensionList(
  item?: KeyBqJson["key_bq_list"][number] | null,
): KeyBqDimensionJsonValue[] {
  if (!item) {
    return [];
  }
  const candidates = [
    item.user_demension,
    item.demension,
    item.dimensions,
    item.user_dimensions,
    item.llm_demension,
    item.llm_dimensions,
    item.supplemental_dimensions,
  ];
  for (const candidate of candidates) {
    if (!Array.isArray(candidate) || candidate.length === 0) {
      continue;
    }
    return candidate
      .map((dimension) => ({
        name: String(dimension?.name || "").trim(),
        description: String(dimension?.description || "").trim(),
      }))
      .filter((dimension) => Boolean(dimension.name));
  }
  return [];
}

function normalizeKeyBqJsonDimensions(item?: KeyBqJson["key_bq_list"][number] | null): KeyBqDimensionJsonValue[] {
  return pickFirstNonEmptyDimensionList(item);
}

function mergeKeyBqDimensions(
  userDimensions: KeyBqDimensionJsonValue[],
  llmDimensions: KeyBqDimensionJsonValue[],
): KeyBqDimensionJsonValue[] {
  const merged: KeyBqDimensionJsonValue[] = [];
  const seen = new Set<string>();
  [...userDimensions, ...llmDimensions].forEach((dimension) => {
    const name = String(dimension?.name || "").trim();
    if (!name) {
      return;
    }
    const description = String(dimension?.description || "").trim();
    const key = `${name.toLowerCase()}::${description.toLowerCase()}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    merged.push({
      name,
      description: description || undefined,
    });
  });
  return merged;
}

function buildKeyBqFormValues(value?: KeyBqJson | null): KeyBqFormValues {
  const items = value?.key_bq_list ?? [];
  if (items.length === 0) {
    return { key_bq_list: [{ text: "", dimensions: [] }] };
  }
  return {
    key_bq_list: items.map((item) => ({
      text: item.text ?? "",
      dimensions: normalizeKeyBqJsonDimensions(item).map((dimension) => ({
        name: dimension.name ?? "",
        description: dimension.description ?? "",
      })),
    })),
  };
}

function buildKeyBqJson(values: KeyBqFormValues): KeyBqJson {
  type KeyBqJsonItem = {
    text: string;
    user_demension: KeyBqDimensionJsonValue[];
    llm_demension: KeyBqDimensionJsonValue[];
    demension: KeyBqDimensionJsonValue[];
  };

  const key_bq_list = (values.key_bq_list ?? [])
    .map<KeyBqJsonItem | null>((item) => {
      const text = String(item?.text || "").trim();
      if (!text) {
        return null;
      }
      const dimensions = (item?.dimensions ?? [])
        .map(normalizeKeyBqDimensionValues)
        .filter((dimension): dimension is KeyBqDimensionJsonValue => Boolean(dimension?.name));
      return { text, user_demension: dimensions, llm_demension: [], demension: dimensions };
    })
    .filter((item): item is KeyBqJsonItem => Boolean(item))
    .map((item, index) => ({
      order: index + 1,
      text: item.text,
      user_demension: item.user_demension,
      llm_demension: item.llm_demension,
      demension: item.demension,
    }));

  if (key_bq_list.length === 0) {
    throw new Error("请至少填写一条 KBQ");
  }

  return { key_bq_list };
}

function renderKeyBqPreview(value?: KeyBqJson | null): string {
  const items = value?.key_bq_list ?? [];
  if (items.length === 0) {
    return "";
  }
  return items
    .map((item, index) => {
      const lines = [`${index + 1}. ${item.text}`];
      const userDimensions = Array.isArray(item.user_demension) ? item.user_demension : [];
      const llmDimensions = Array.isArray(item.llm_demension) ? item.llm_demension : [];
      const mergedDimensions =
        item.demension && item.demension.length > 0
          ? item.demension
          : item.dimensions && item.dimensions.length > 0
            ? item.dimensions
            : userDimensions.length > 0 && llmDimensions.length > 0
              ? mergeKeyBqDimensions(
                  userDimensions.map((dimension) => ({
                    name: String(dimension?.name || "").trim(),
                    description: String(dimension?.description || "").trim(),
                  })),
                  llmDimensions.map((dimension) => ({
                    name: String(dimension?.name || "").trim(),
                    description: String(dimension?.description || "").trim(),
                  })),
                )
              : pickFirstNonEmptyDimensionList(item);
      if (mergedDimensions.length > 0) {
        mergedDimensions.forEach((dimension) => {
          const name = String(dimension.name || "").trim();
          if (!name) {
            return;
          }
          const description = String(dimension.description || "").trim();
          lines.push(`   - ${name}${description ? `：${description}` : ""}`);
        });
      } else {
        lines.push("   - 二级维度：未填写");
      }
      return lines.join("\n");
    })
    .join("\n\n");
}

function parseHotwordCandidates(values: string[] | null | undefined): QuestionnaireHotwordCandidate[] {
  return (values ?? []).map((item) => ({
    term: item,
    normalized_term: item,
  }));
}

function formatDate(value?: string | null): string {
  if (!value) {
    return "";
  }
  return value.includes("T") ? value.split("T")[0] : value;
}

function getQuestionnaireStatusTag(status?: string | null) {
  const normalized = String(status || "").trim();
  if (normalized === "ready") {
    return <Tag color="green">已可用于访谈</Tag>;
  }
  if (normalized === "hotword_review_pending") {
    return <Tag color="orange">待热词确认</Tag>;
  }
  if (normalized === "failed") {
    return <Tag color="red">解析失败</Tag>;
  }
  return <Tag>{normalized || "未知状态"}</Tag>;
}

function getInterviewStatusTag(status?: number | null) {
  if (status === 2) {
    return <Tag color="green">已完成</Tag>;
  }
  if (status === 1) {
    return <Tag color="blue">处理中</Tag>;
  }
  return <Tag color="default">待处理</Tag>;
}

function getKeyBqCount(value?: KeyBqJson | null): number {
  return value?.key_bq_list?.length ?? 0;
}

function getGuideStatusTag(status?: string | null) {
  const normalized = String(status || "").trim().toLowerCase();
  if (!normalized) {
    return <Tag>未上传</Tag>;
  }
  if (normalized === "done") {
    return <Tag color="green">学习完成</Tag>;
  }
  if (normalized === "failed") {
    return <Tag color="red">学习失败</Tag>;
  }
  if (normalized === "extracting") {
    return <Tag color="blue">正在抽取正文</Tag>;
  }
  if (normalized === "summarizing") {
    return <Tag color="gold">正在学习总结</Tag>;
  }
  if (normalized === "queued" || normalized === "uploaded") {
    return <Tag color="orange">等待学习</Tag>;
  }
  return <Tag>{status}</Tag>;
}

function getGuideFileStatusTag(status?: string | null) {
  const normalized = String(status || "").trim().toLowerCase();
  if (!normalized || normalized === "queued" || normalized === "uploaded") {
    return <Tag color="orange">待处理</Tag>;
  }
  if (normalized === "extracting") {
    return <Tag color="blue">正在抽取</Tag>;
  }
  if (normalized === "summarizing") {
    return <Tag color="gold">正在总结</Tag>;
  }
  if (normalized === "done") {
    return <Tag color="green">已完成</Tag>;
  }
  if (normalized === "failed") {
    return <Tag color="red">失败</Tag>;
  }
  return <Tag>{status || "未知"}</Tag>;
}

function isGuideLearning(status?: string | null): boolean {
  const normalized = String(status || "").trim().toLowerCase();
  return ["queued", "uploaded", "extracting", "summarizing"].includes(normalized);
}

function normalizeInterviewDetailValues(values?: Record<string, unknown> | null): InterviewDetailValues {
  const normalized: InterviewDetailValues = {};
  if (!values) {
    return normalized;
  }
  Object.entries(values).forEach(([key, value]) => {
    if (value === null || value === undefined) {
      return;
    }
    if (typeof value === "string") {
      const text = value.trim();
      if (text) {
        normalized[key] = text;
      }
      return;
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      if (value > 0) {
        normalized[key] = value;
      }
    }
  });
  return normalized;
}

function summarizeInterviewDetail(
  fields: InterviewDetailFieldDefinition[],
  detail: InterviewDetailValues,
): string {
  const parts = fields
    .map((field) => {
      const value = detail[field.key];
      if (value === null || value === undefined || value === "") {
        return null;
      }
      return `${field.label}：${value}`;
    })
    .filter((item): item is string => Boolean(item));
  return parts.length > 0 ? parts.join("，") : "尚未填写访谈细节";
}

type DetailDraftValue = string;

function getDetailEntries(detailJson: Record<string, unknown> | null | undefined): Array<{
  key: string;
  value: unknown;
}> {
  if (!detailJson || typeof detailJson !== "object" || Array.isArray(detailJson)) {
    return [];
  }
  return Object.entries(detailJson)
    .filter(([key]) => Boolean(String(key || "").trim()))
    .map(([key, value]) => ({
      key,
      value,
    }));
}

function getDetailDisplayLabel(key: string): string {
  const safeKey = String(key || "").trim();
  if (!safeKey) {
    return "未命名字段";
  }
  return safeKey
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .replace(/^\w/, (char) => char.toUpperCase());
}

function getDetailFieldKind(value: unknown): "number" | "boolean" | "json" | "text" {
  if (typeof value === "number" && Number.isFinite(value)) {
    return "number";
  }
  if (typeof value === "boolean") {
    return "boolean";
  }
  if (value && typeof value === "object") {
    return "json";
  }
  return "text";
}

function stringifyDetailValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return "";
    }
  }
  return String(value);
}

function buildInterviewDetailDraft(
  detailJson: Record<string, unknown> | null | undefined,
): Record<string, DetailDraftValue> {
  const payload: Record<string, DetailDraftValue> = {};
  const entries = getDetailEntries(detailJson);
  for (const { key, value } of entries) {
    payload[key] = stringifyDetailValue(value);
  }
  return payload;
}

function buildInterviewDetailPayload(
  sourceDetail: Record<string, unknown> | null | undefined,
  draft: Record<string, DetailDraftValue>,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  const entries = getDetailEntries(sourceDetail);
  for (const { key, value: originalValue } of entries) {
    const rawValue = draft[key] ?? "";
    const kind = getDetailFieldKind(originalValue);
    if (kind === "number") {
      if (!rawValue.trim()) {
        continue;
      }
      const parsed = Number(rawValue);
      if (Number.isFinite(parsed)) {
        payload[key] = parsed;
      }
      continue;
    }
    if (kind === "boolean") {
      const lower = rawValue.trim().toLowerCase();
      if (!lower) {
        continue;
      }
      payload[key] = lower === "true" || lower === "1" || lower === "yes" || lower === "是";
      continue;
    }
    if (kind === "json") {
      if (!rawValue.trim()) {
        continue;
      }
      try {
        payload[key] = JSON.parse(rawValue);
      } catch {
        payload[key] = rawValue;
      }
      continue;
    }
    const text = rawValue.trim();
    if (text) {
      payload[key] = text;
    }
  }
  return payload;
}

export default function ProjectDetailClient({ projectId }: Props) {
  const router = useRouter();
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [questionnaireModalOpen, setQuestionnaireModalOpen] = useState(false);
  const [questionnaireSaving, setQuestionnaireSaving] = useState(false);
  const [questionnaireForm] = Form.useForm();
  const [questionnaireFileList, setQuestionnaireFileList] = useState<UploadFile[]>([]);
  const questionnaireObjectType = Form.useWatch("object_type", questionnaireForm);
  const [questionnaireReviewState, setQuestionnaireReviewState] =
    useState<QuestionnaireReviewState | null>(null);
  const [questionnaireReviewVisible, setQuestionnaireReviewVisible] = useState(false);
  const [questionnaireReviewSaving, setQuestionnaireReviewSaving] = useState(false);

  const [keyBqModalOpen, setKeyBqModalOpen] = useState(false);
  const [keyBqSaving, setKeyBqSaving] = useState(false);
  const [keyBqForm] = Form.useForm<KeyBqFormValues>();

  const [guideResultVisible, setGuideResultVisible] = useState(false);
  const [guideUploadFileList, setGuideUploadFileList] = useState<UploadFile[]>([]);
  const [guideUploading, setGuideUploading] = useState(false);
  const [projectNameModalOpen, setProjectNameModalOpen] = useState(false);
  const [projectNameSaving, setProjectNameSaving] = useState(false);
  const [projectNameForm] = Form.useForm<{ name: string }>();

  const [interviewModalOpen, setInterviewModalOpen] = useState(false);
  const [interviewSaving, setInterviewSaving] = useState(false);
  const [interviewDeletingId, setInterviewDeletingId] = useState<number | null>(null);
  const [interviewForm] = Form.useForm<InterviewFormValues>();
  const [interviewDetailFieldsDraft, setInterviewDetailFieldsDraft] = useState<InterviewDetailFieldDraft[]>([]);
  const [interviewDetailModalOpen, setInterviewDetailModalOpen] = useState(false);
  const [interviewFileList, setInterviewFileList] = useState<UploadFile[]>([]);
  const [rowInterviewDetailOpen, setRowInterviewDetailOpen] = useState(false);
  const [rowInterviewDetailLoading, setRowInterviewDetailLoading] = useState(false);
  const [rowInterviewDetailError, setRowInterviewDetailError] = useState<string | null>(null);
  const [rowInterviewDetailSavingDetail, setRowInterviewDetailSavingDetail] = useState(false);
  const [rowInterviewDetailSavingName, setRowInterviewDetailSavingName] = useState(false);
  const [rowInterviewDetail, setRowInterviewDetail] = useState<InterviewDetailResponse | null>(null);
  const [rowInterviewNameDraft, setRowInterviewNameDraft] = useState("");
  const [rowInterviewDetailDraft, setRowInterviewDetailDraft] = useState<Record<string, DetailDraftValue>>({});
  const [rowInterviewId, setRowInterviewId] = useState<number | null>(null);

  const loadProjectDetail = useCallback(async (options?: { silent?: boolean }) => {
    const silent = Boolean(options?.silent);
    if (!projectId || projectId <= 0) {
      setError("无效的项目 ID");
      return;
    }
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const detail = await getProjectDetail(projectId);
      setProjectDetail(detail);
    } catch (e) {
      if (!silent) {
        setError(e instanceof Error ? e.message : "加载项目详情失败");
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, [projectId]);

  const roles = useMemo(() => projectDetail?.roles ?? [], [projectDetail]);
  const questionnaires = useMemo(() => projectDetail?.questionnaires ?? [], [projectDetail]);
  const interviews = useMemo(() => projectDetail?.interviews ?? [], [projectDetail]);
  const project = useMemo(() => projectDetail?.project ?? null, [projectDetail]);
  const projectKeyBq = useMemo(() => project?.key_bq_json ?? null, [project]);
  const guideStatus = useMemo(() => project?.guide_status ?? null, [project]);
  const guideSummaryText = useMemo(() => project?.guide_summary_text ?? "", [project]);
  const guideExtractedText = useMemo(() => project?.guide_extracted_text ?? "", [project]);
  const guideFiles = useMemo(() => project?.guide_files_json ?? [], [project]);
  const guideFileNames = useMemo(
    () =>
      guideFiles
        .map((file, index) => {
          const name = String(file.original_name || "").trim();
          return name || `指南文件 ${index + 1}`;
        })
        .filter((name) => Boolean(name)),
    [guideFiles],
  );

  const openProjectNameModal = () => {
    if (!project) {
      return;
    }
    projectNameForm.setFieldsValue({
      name: project.name,
    });
    setProjectNameModalOpen(true);
  };

  const handleProjectNameModalCancel = () => {
    if (projectNameSaving) {
      return;
    }
    setProjectNameModalOpen(false);
  };

  const handleProjectNameSave = async () => {
    try {
      setProjectNameSaving(true);
      const values = await projectNameForm.validateFields();
      const updated = await updateProject(projectId, {
        name: values.name as string,
      });
      setProjectDetail((prev) =>
        prev
          ? {
              ...prev,
              project: {
                ...prev.project,
                ...updated,
              },
            }
          : prev,
      );
      message.success("项目名称已更新");
      setProjectNameModalOpen(false);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "更新项目名称失败");
    } finally {
      setProjectNameSaving(false);
    }
  };

  useEffect(() => {
    void loadProjectDetail();
  }, [loadProjectDetail]);

  useEffect(() => {
    if (!guideStatus || !isGuideLearning(guideStatus)) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadProjectDetail({ silent: true });
    }, 5000);
    return () => {
      window.clearInterval(timer);
    };
  }, [guideStatus, loadProjectDetail]);

  const roleById = useMemo(() => {
    const map = new Map<number, ProjectRole>();
    roles.forEach((role) => {
      map.set(role.id, role);
    });
    return map;
  }, [roles]);

  const questionnairesByRoleId = useMemo(() => {
    const map = new Map<number, ProjectQuestionnaire[]>();
    questionnaires.forEach((item) => {
      const roleId = item.role_id ?? null;
      if (!roleId) {
        return;
      }
      const current = map.get(roleId) ?? [];
      current.push(item);
      map.set(roleId, current);
    });
    return map;
  }, [questionnaires]);

  const questionnaireById = useMemo(() => {
    const map = new Map<number, ProjectQuestionnaire>();
    questionnaires.forEach((item) => {
      map.set(item.id, item);
    });
    return map;
  }, [questionnaires]);

  const interviewQuestionnaireOptions = useMemo(
    () =>
      questionnaires.map((item) => ({
        value: item.id,
        label: item.name,
      })),
    [questionnaires],
  );

  const interviewDetailDraft = useMemo<InterviewDetailValues>(() => {
    const values: InterviewDetailValues = {};
    interviewDetailFieldsDraft.forEach((field) => {
      const key = String(field.key || "").trim();
      const value = field.value;
      if (!key || value === null || value === undefined || value === "") {
        return;
      }
      values[key] = value;
    });
    return values;
  }, [interviewDetailFieldsDraft]);

  const rowInterviewDetailEntries = useMemo(() => {
    return getDetailEntries(rowInterviewDetail?.detail_json || null);
  }, [rowInterviewDetail]);

  const openQuestionnaireModal = (targetRoleId?: number) => {
    questionnaireForm.resetFields();
    setQuestionnaireFileList([]);
    const targetRole = targetRoleId ? roleById.get(targetRoleId) ?? null : roles[0] ?? null;
    const targetType = (normalizeRoleType(targetRole?.role_type) ?? "doctor") as "doctor" | "patient" | "custom";
    questionnaireForm.setFieldsValue({
      name: "",
      object_type: targetType,
      role_name: targetType === "custom" ? targetRole?.role_name ?? "" : undefined,
    });
    setQuestionnaireModalOpen(true);
  };

  const handleQuestionnaireModalCancel = () => {
    if (questionnaireSaving) {
      return;
    }
    setQuestionnaireModalOpen(false);
    setQuestionnaireFileList([]);
  };

  const openQuestionnaireReview = async (questionnaire: ProjectQuestionnaire) => {
    try {
      const detail = await getProjectQuestionnaire(projectId, questionnaire.id);
      const candidates =
        (detail.hotword_candidates?.length ? detail.hotword_candidates : null) ??
        parseHotwordCandidates(detail.hotwords);
      setQuestionnaireReviewState({
        questionnaireId: detail.id,
        questionnaireName: detail.name,
        candidates,
      });
      setQuestionnaireReviewVisible(true);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载 DG 详情失败");
    }
  };

  const handleQuestionnaireSubmit = async () => {
    try {
      setQuestionnaireSaving(true);
      const values = await questionnaireForm.validateFields();
      const file = questionnaireFileList[0]?.originFileObj;
      if (!file) {
        message.warning("请先选择问卷 docx 文件");
        setQuestionnaireSaving(false);
        return;
      }
      const objectType = normalizeRoleType(values.object_type);
      if (!objectType) {
        message.warning("请选择 DG 所属类型");
        setQuestionnaireSaving(false);
        return;
      }
      const roleName = String(values.role_name || "").trim();
      if (objectType === "custom" && !roleName) {
        message.warning("请选择自定义人员名称");
        setQuestionnaireSaving(false);
        return;
      }
      const formData = new FormData();
      formData.append("name", String(values.name || "").trim());
      formData.append("object_type", objectType);
      formData.append("role_type", objectType);
      if (objectType === "custom" && roleName) {
        formData.append("role_name", roleName);
      }
      formData.append("file", file as File);
      const created = await createProjectQuestionnaire(projectId, formData);
      message.success("DG 已上传");
      setQuestionnaireModalOpen(false);
      setQuestionnaireFileList([]);
      await loadProjectDetail();
      if (created.review_required) {
        setQuestionnaireReviewState({
          questionnaireId: created.id,
          questionnaireName: created.name,
          candidates: created.hotword_candidates ?? [],
        });
        setQuestionnaireReviewVisible(true);
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "上传 DG 失败");
    } finally {
      setQuestionnaireSaving(false);
    }
  };

  const handleQuestionnaireReviewCancel = () => {
    setQuestionnaireReviewVisible(false);
    setQuestionnaireReviewState(null);
  };

  const handleQuestionnaireReviewConfirm = async (hotwords: string[]) => {
    if (!questionnaireReviewState) {
      message.error("缺少问卷信息");
      return;
    }
    setQuestionnaireReviewSaving(true);
    try {
      await updateProjectQuestionnaireHotwords(projectId, questionnaireReviewState.questionnaireId, {
        hotwords,
      });
      message.success("问卷热词已确认");
      setQuestionnaireReviewVisible(false);
      setQuestionnaireReviewState(null);
      await loadProjectDetail();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存问卷热词失败");
    } finally {
      setQuestionnaireReviewSaving(false);
    }
  };

  const openKeyBqEditModal = () => {
    keyBqForm.resetFields();
    keyBqForm.setFieldsValue(buildKeyBqFormValues(projectKeyBq));
    setKeyBqModalOpen(true);
  };

  const handleKeyBqCancel = () => {
    if (keyBqSaving) {
      return;
    }
    setKeyBqModalOpen(false);
  };

  const handleKeyBqSubmit = async () => {
    try {
      setKeyBqSaving(true);
      const values = await keyBqForm.validateFields();
      await updateProjectKeyBqCurrent(projectId, {
        key_bq_json: buildKeyBqJson(values as KeyBqFormValues),
      });
      message.success("KBQ 已保存");
      setKeyBqModalOpen(false);
      await loadProjectDetail();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存 KBQ 失败");
    } finally {
      setKeyBqSaving(false);
    }
  };

  const openGuideResultModal = () => {
    setGuideResultVisible(true);
  };

  const handleGuideUpload = async () => {
    const guideFiles = guideUploadFileList
      .map((item) => item.originFileObj as File | null | undefined)
      .filter((file): file is File => Boolean(file));
    if (guideFiles.length === 0) {
      message.warning("请先选择指南文件");
      return;
    }
    try {
      setGuideUploading(true);
      const updated = await uploadProjectGuide(projectId, guideFiles);
      setProjectDetail((prev) =>
        prev
          ? {
              ...prev,
              project: {
                ...prev.project,
                ...updated,
              },
            }
          : prev,
      );
      setGuideUploadFileList([]);
      message.success("指南已上传，正在异步学习");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "上传指南失败");
    } finally {
      setGuideUploading(false);
    }
  };

  const addInterviewDetailField = () => {
    setInterviewDetailFieldsDraft((prev) => [
      ...prev,
      createInterviewDetailFieldDraft(undefined, undefined, { isPreset: false }),
    ]);
  };

  const updateInterviewDetailField = (uid: string, patch: Partial<InterviewDetailFieldDraft>) => {
    setInterviewDetailFieldsDraft((prev) =>
      prev.map((field) =>
        field.uid === uid
          ? {
              ...field,
              ...patch,
            }
          : field,
      ),
    );
  };

  const removeInterviewDetailField = (uid: string) => {
    setInterviewDetailFieldsDraft((prev) => prev.filter((field) => field.uid !== uid));
  };

  const openInterviewDetailModal = () => {
    setInterviewDetailModalOpen(true);
  };

  const handleInterviewDetailModalCancel = () => {
    if (interviewSaving) {
      return;
    }
    setInterviewDetailModalOpen(false);
  };

  const handleInterviewDetailModalOk = () => {
    setInterviewDetailModalOpen(false);
  };

  const handleQuestionnaireDelete = (item: ProjectQuestionnaire) => {
    Modal.confirm({
      title: "确认删除 DG",
      content: `确定要删除 DG「${item.name}」吗？如果已有访谈引用，将无法删除。`,
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          await deleteProjectQuestionnaire(projectId, item.id);
          message.success("DG 已删除");
          await loadProjectDetail();
        } catch (e) {
          message.error(e instanceof Error ? e.message : "删除 DG 失败");
        }
      },
    });
  };

  const openInterviewModal = () => {
    interviewForm.resetFields();
    setInterviewFileList([]);
    if (isGuideLearning(guideStatus)) {
      message.warning("项目指南仍在学习中，建议完成后再创建访谈。");
    }
    const firstQuestionnaire = questionnaires[0] ?? null;
    const firstQuestionnaireRoleType = normalizeRoleType(
      firstQuestionnaire?.object_type || firstQuestionnaire?.role_type || null,
    );
    setInterviewDetailFieldsDraft(buildInterviewDetailFieldDraftsByType(firstQuestionnaireRoleType));
    interviewForm.setFieldsValue({
      questionnaire_id: firstQuestionnaire?.id ?? undefined,
    } as Partial<InterviewFormValues>);
    setInterviewModalOpen(true);
  };

  const handleInterviewQuestionnaireChange = (questionnaireId: number) => {
    const nextQuestionnaire = questionnaireById.get(questionnaireId) ?? null;
    interviewForm.setFieldsValue({
      questionnaire_id: questionnaireId,
    });
    const nextRoleType = normalizeRoleType(
      nextQuestionnaire?.object_type || nextQuestionnaire?.role_type || null,
    );
    setInterviewDetailFieldsDraft(buildInterviewDetailFieldDraftsByType(nextRoleType));
  };

  const handleInterviewCancel = () => {
    if (interviewSaving) {
      return;
    }
    setInterviewModalOpen(false);
    setInterviewDetailModalOpen(false);
    setInterviewFileList([]);
    setInterviewDetailFieldsDraft([]);
  };

  const handleInterviewSubmit = async () => {
    try {
      setInterviewSaving(true);
      const values = await interviewForm.validateFields();
      const file = interviewFileList[0]?.originFileObj;
      if (!file) {
        message.warning("请先选择音频文件");
        setInterviewSaving(false);
        return;
      }
      const questionnaireId = Number(values.questionnaire_id || 0);
      if (!questionnaireId) {
        message.warning("请选择 DG 问卷");
        setInterviewSaving(false);
        return;
      }
      const normalizedFields = normalizeFieldDefinitions(
        interviewDetailFieldsDraft.map((field) => ({
          key: field.key,
          label: field.label,
          kind: field.kind,
        })),
      );
      const rawFieldCount = interviewDetailFieldsDraft.filter((field) => String(field.key || "").trim()).length;
      if (normalizedFields.length !== rawFieldCount) {
        message.warning("访谈细节字段的标识不能重复或为空");
        setInterviewSaving(false);
        return;
      }
      const detailPayload = normalizeInterviewDetailValues(
        Object.fromEntries(
          interviewDetailFieldsDraft
            .map((field) => [String(field.key || "").trim(), field.value] as const)
            .filter(([key]) => Boolean(key)),
        ),
      );
      const formData = new FormData();
      formData.append("questionnaire_id", String(questionnaireId));
      if (Object.keys(detailPayload).length > 0) {
        formData.append("detail_json", JSON.stringify(detailPayload));
      }
      const dateValue = values.interview_date;
      if (dateValue && typeof (dateValue as { format?: unknown }).format === "function") {
        formData.append("interview_date", (dateValue as { format: (fmt: string) => string }).format("YYYY-MM-DD"));
      }
      formData.append("file", file as File);
      const created = (await createInterview(projectId, formData)) as CreatedInterviewResponse;
      message.success("访谈已创建");
      setInterviewModalOpen(false);
      setInterviewFileList([]);
      router.push(`/interviews/${created.id}/processing`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "创建访谈失败");
    } finally {
      setInterviewSaving(false);
    }
  };

  const handleInterviewDelete = (item: { id: number; name?: string | null }) => {
    Modal.confirm({
      title: "确认删除访谈",
      content: `确定要删除访谈「${item.name || item.id}」吗？删除后会同时清理关联数据，且无法恢复。`,
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          setInterviewDeletingId(item.id);
          await deleteInterview(item.id);
          message.success("访谈已删除");
          await loadProjectDetail({ silent: true });
        } catch (e) {
          message.error(e instanceof Error ? e.message : "删除访谈失败");
        } finally {
          setInterviewDeletingId((prev) => (prev === item.id ? null : prev));
        }
      },
    });
  };

  const patchProjectInterviewDetail = useCallback((updated: InterviewDetailResponse) => {
    setProjectDetail((prev) =>
      prev
        ? {
            ...prev,
            interviews: prev.interviews.map((item) =>
              item.id === updated.id
                ? {
                    ...item,
                    name: updated.name,
                    interview_date: updated.interview_date ?? item.interview_date,
                    detail_json: updated.detail_json ?? item.detail_json,
                    city: updated.city ?? item.city,
                    hospital_city: updated.hospital_city ?? item.hospital_city,
                    hospital_decile: updated.hospital_decile ?? item.hospital_decile,
                    doctor_level: updated.doctor_level ?? item.doctor_level,
                    doctor_title: updated.doctor_title ?? item.doctor_title,
                    hospital: updated.hospital ?? item.hospital,
                    department: updated.department ?? item.department,
                    questionnaire_id: updated.questionnaire_id ?? item.questionnaire_id,
                    questionnaire_name: updated.questionnaire_name ?? item.questionnaire_name,
                    questionnaire_status: updated.questionnaire_status ?? item.questionnaire_status,
                    questionnaire_object_type: updated.questionnaire_object_type ?? item.questionnaire_object_type,
                    questionnaire_role_id: updated.questionnaire_role_id ?? item.questionnaire_role_id,
                    questionnaire_role_name: updated.questionnaire_role_name ?? item.questionnaire_role_name,
                    questionnaire_role_type: updated.questionnaire_role_type ?? item.questionnaire_role_type,
                    questionnaire_role_detail_schema_json:
                      updated.questionnaire_role_detail_schema_json ?? item.questionnaire_role_detail_schema_json,
                    key_bq_id: updated.key_bq_id ?? item.key_bq_id,
                    key_bq_name: updated.key_bq_name ?? item.key_bq_name,
                  }
                : item,
            ),
          }
        : prev,
    );
  }, []);

  const openInterviewDetailRowModal = async (item: { id: number; name?: string | null }) => {
    setRowInterviewDetailOpen(true);
    setRowInterviewId(item.id);
    setRowInterviewDetailLoading(true);
    setRowInterviewDetailError(null);
    setRowInterviewDetail(null);
    setRowInterviewNameDraft(item.name || "");
    setRowInterviewDetailDraft({});
    try {
      const detail = await getInterviewDetail(item.id);
      setRowInterviewDetail(detail);
      setRowInterviewNameDraft(detail.name || item.name || "");
      setRowInterviewDetailDraft(buildInterviewDetailDraft(detail.detail_json || null));
    } catch (e) {
      setRowInterviewDetailError(e instanceof Error ? e.message : "加载访谈基础信息失败");
    } finally {
      setRowInterviewDetailLoading(false);
    }
  };

  const closeInterviewDetailRowModal = () => {
    if (rowInterviewDetailSavingDetail || rowInterviewDetailSavingName) {
      return;
    }
    setRowInterviewDetailOpen(false);
    setRowInterviewId(null);
    setRowInterviewDetail(null);
    setRowInterviewDetailError(null);
    setRowInterviewDetailLoading(false);
    setRowInterviewNameDraft("");
    setRowInterviewDetailDraft({});
  };

  const handleRowInterviewDetailFieldChange = (key: string, value: string) => {
    setRowInterviewDetailDraft((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const saveRowInterviewDetail = async () => {
    if (!rowInterviewDetail || !rowInterviewId) {
      message.error("访谈信息尚未加载完成");
      return;
    }
    if (rowInterviewDetailEntries.length === 0) {
      message.error("当前访谈没有可编辑的细节字段");
      return;
    }
    const detailPayload = buildInterviewDetailPayload(rowInterviewDetail.detail_json || null, rowInterviewDetailDraft);
    try {
      setRowInterviewDetailSavingDetail(true);
      const updated = await updateInterviewDetail(rowInterviewId, {
        detail_json: detailPayload,
      });
      setRowInterviewDetail(updated);
      setRowInterviewNameDraft(updated.name || rowInterviewNameDraft);
      setRowInterviewDetailDraft(buildInterviewDetailDraft(updated.detail_json || null));
      patchProjectInterviewDetail(updated);
      message.success("访谈细节已保存，名称已同步更新");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存访谈细节失败");
    } finally {
      setRowInterviewDetailSavingDetail(false);
    }
  };

  const saveRowInterviewDisplayName = async () => {
    if (!rowInterviewId) {
      message.error("缺少访谈信息");
      return;
    }
    const trimmed = rowInterviewNameDraft.trim();
    if (!trimmed) {
      message.error("访谈名称不能为空");
      return;
    }
    try {
      setRowInterviewDetailSavingName(true);
      const updated = await updateInterviewName(rowInterviewId, trimmed);
      setRowInterviewDetail(updated);
      setRowInterviewNameDraft(updated.name || trimmed);
      patchProjectInterviewDetail(updated);
      message.success("访谈名称已保存");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存访谈名称失败");
    } finally {
      setRowInterviewDetailSavingName(false);
    }
  };

  const projectCounts = projectDetail?.counts ?? {
    questionnaire_count: questionnaires.length,
    key_bq_count: getKeyBqCount(projectKeyBq),
    interview_count: interviews.length,
  };

  return (
    <Layout className="min-h-screen">
      <BrandHero
        className="mb-20 lg:mb-24"
        title={project?.name || `项目 ${projectId}`}
        backButton={
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push("/")} className="summarynotes-hero-back">
            返回项目列表
          </Button>
        }
        stats={
          <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 8 }}>
            <Tag color="cyan">问卷 {projectCounts.questionnaire_count ?? 0}</Tag>
            <Tag color="geekblue">KBQ {projectCounts.key_bq_count ?? 0}</Tag>
            <Tag color="green">访谈 {projectCounts.interview_count ?? 0}</Tag>
          </div>
        }
        actions={
          <Space wrap>
            <Button icon={<EditOutlined />} onClick={openProjectNameModal} disabled={!project}>
              编辑项目名称
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => void loadProjectDetail()}>
              刷新
            </Button>
            <Button onClick={() => router.push(`/projects/${projectId}/ca`)}>CA</Button>
          </Space>
        }
      />
      <Modal
        open={projectNameModalOpen}
        title="编辑项目名称"
        onOk={() => void handleProjectNameSave()}
        onCancel={handleProjectNameModalCancel}
        okText="保存"
        cancelText="取消"
        confirmLoading={projectNameSaving}
        destroyOnHidden
      >
        <Form form={projectNameForm} layout="vertical">
          <Form.Item
            label="项目名称"
            name="name"
            rules={[{ required: true, message: "请输入项目名称" }]}
          >
            <Input placeholder="请输入项目名称" />
          </Form.Item>
        </Form>
      </Modal>
      <Content className="relative z-0 bg-slate-50 pt-20 lg:pt-4">
        <div className="relative z-0 p-6 pt-0 md:p-8 md:pt-0">
          {loading ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "72px 0" }}>
              <Spin size="large" />
            </div>
          ) : error ? (
            <Alert
              type="error"
              showIcon
              message="加载项目详情失败"
              description={error}
              action={
                <Button size="small" onClick={() => void loadProjectDetail()}>
                  重试
                </Button>
              }
            />
          ) : project ? (
            <div className="space-y-6 lg:space-y-8">
              <Card className="summarynotes-project-list-shell">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
                  <div>
                    <Title level={4} style={{ marginBottom: 4 }} className="summarynotes-section-title">
                      项目概览
                    </Title>
                    <Space wrap>
                      <Tag color="gold">项目 ID：{project.id}</Tag>
                      {getGuideStatusTag(guideStatus)}
                    </Space>
                  </div>
                </div>
                <Divider style={{ margin: "18px 0" }} />
                <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                  {project.core_problem || "暂无旧项目背景说明。"}
                </Paragraph>
              </Card>

                <Card className="summarynotes-project-list-shell">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
                    <div>
                      <Title level={4} style={{ marginBottom: 4 }} className="summarynotes-section-title">
                        项目指南学习
                      </Title>
                      <Text type="secondary">
                        上传 PDF / DOCX / MD / XLSX 指南后，系统会异步处理。这里可以随时补传指南并查看当前处理状态。
                      </Text>
                    </div>
                    <Space wrap>
                      <Button onClick={openGuideResultModal} disabled={!guideSummaryText && !guideExtractedText}>
                        查看学习结果
                      </Button>
                    </Space>
                  </div>
                  <Space direction="vertical" size={10} style={{ width: "100%" }}>
                    <Space wrap>
                      {getGuideStatusTag(guideStatus)}
                      {project.guide_file_name ? <Tag color="blue">文件：{project.guide_file_name}</Tag> : null}
                      {project.guide_generated_at ? (
                        <Tag color="green">完成时间：{formatDate(project.guide_generated_at)}</Tag>
                      ) : null}
                    </Space>
                    <Space direction="vertical" size={4} style={{ width: "100%" }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        已学习文件
                      </Text>
                      {guideFileNames.length > 0 ? (
                        <Space wrap size={[8, 8]}>
                          {guideFileNames.map((name, index) => (
                            <Tag key={`${name}-${index}`} color="cyan">
                              {name}
                            </Tag>
                          ))}
                        </Space>
                      ) : (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          目前还没有上传指南文件。
                        </Text>
                      )}
                    </Space>
                    {project.guide_error_message ? (
                      <Alert
                        type="error"
                        showIcon
                        message="指南学习失败"
                        description={project.guide_error_message}
                      />
                    ) : null}
                    {isGuideLearning(guideStatus) ? (
                      <Alert
                        type="warning"
                        showIcon
                        message="指南正在学习中"
                        description="学习完成后，你可以在这里查看总结结果；创建访谈时建议先等待学习结束。"
                      />
                    ) : null}
                    <Alert
                      type="info"
                      showIcon
                      message={project.guide_file_name ? "重新上传指南" : "上传指南并学习"}
                      description={
                        project.guide_file_name
                          ? "如果项目创建时没有上传指南，或者需要更新指南内容，可以在这里重新上传。上传后会自动触发指南学习。"
                          : "如果项目创建时没有上传指南，可以现在在项目详情页补传，上传后会自动触发指南学习。"
                      }
                    />
                    <Space direction="vertical" size={8} style={{ width: "100%" }}>
                      <Upload
                        beforeUpload={() => false}
                        multiple
                        fileList={guideUploadFileList}
                        onChange={({ fileList }) => setGuideUploadFileList(fileList)}
                        accept=".pdf,.docx,.md,.xlsx"
                      >
                        <Button icon={<UploadOutlined />}>选择指南文件</Button>
                      </Upload>
                      <Space wrap>
                        <Button
                          type="primary"
                          onClick={() => void handleGuideUpload()}
                          loading={guideUploading}
                          disabled={guideUploadFileList.length === 0}
                        >
                          上传并学习
                        </Button>
                        {guideUploadFileList.length > 0 ? (
                          <Button onClick={() => setGuideUploadFileList([])} disabled={guideUploading}>
                            清空已选文件
                          </Button>
                        ) : null}
                      </Space>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        支持一次上传多个 pdf、docx、md 或 xlsx 文件。若当前已有指南，新上传内容会覆盖当前学习结果。
                      </Text>
                    </Space>
                  </Space>
                </Card>

                <Card className="summarynotes-project-list-shell">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
                    <div>
                      <Title level={4} style={{ marginBottom: 4 }} className="summarynotes-section-title">
                        角色 / DG
                      </Title>
                      <Text type="secondary">
                        一个角色可以维护多份 DG。DG 仅绑定医生、患者或自定义人员类型，访谈细节在创建访谈时维护。
                      </Text>
                    </div>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => openQuestionnaireModal()}
                    >
                      添加 DG
                    </Button>
                  </div>
                  {roles.length > 0 ? (
                    <Space direction="vertical" size={16} style={{ width: "100%" }}>
                      {roles.map((role) => {
                        const roleQuestionnaires = questionnairesByRoleId.get(role.id) ?? [];
                        return (
                          <Card
                            key={role.id}
                            size="small"
                            className="summarynotes-project-card"
                            style={{ borderRadius: 16, background: "rgba(255,255,255,0.92)" }}
                            title={
                              <Space wrap>
                                <Tag color={role.role_type === "doctor" ? "purple" : role.role_type === "patient" ? "cyan" : "gold"}>
                                  {getRoleTypeLabel(role.role_type)}
                                </Tag>
                                <Text strong>{role.role_name}</Text>
                                <Tag color="blue">{roleQuestionnaires.length} 份 DG</Tag>
                              </Space>
                            }
                            extra={
                              <Space wrap>
                                <Button type="primary" ghost size="small" onClick={() => openQuestionnaireModal(role.id)}>
                                  追加 DG
                                </Button>
                              </Space>
                            }
                          >
                            <Space direction="vertical" size={10} style={{ width: "100%" }}>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                DG 类型：{getRoleTypeLabel(role.role_type)}，访谈细节会在创建访谈时补充。
                              </Text>
                              {roleQuestionnaires.length > 0 ? (
                                <List
                                  dataSource={roleQuestionnaires}
                                  renderItem={(item) => (
                                    <List.Item
                                      className="summarynotes-project-card"
                                      style={{ marginBottom: 12, padding: 16, borderRadius: 16 }}
                                      actions={[
                                        <Button
                                          key="review"
                                          type="link"
                                          onClick={() => void openQuestionnaireReview(item)}
                                        >
                                          {String(item.status || "") === "ready" ? "编辑热词" : "确认热词"}
                                        </Button>,
                                        <Button
                                          key="delete"
                                          type="link"
                                          danger
                                          onClick={() => handleQuestionnaireDelete(item)}
                                          disabled={(item.referenced_interview_count ?? 0) > 0}
                                        >
                                          删除
                                        </Button>,
                                      ]}
                                    >
                                      <Space direction="vertical" size={6} style={{ width: "100%" }}>
                                        <Space wrap>
                                          <Tag color={role.role_type === "doctor" ? "purple" : role.role_type === "patient" ? "cyan" : "gold"}>
                                            {getRoleTypeLabel(role.role_type)}
                                          </Tag>
                                          <Text strong>{item.name}</Text>
                                          {getQuestionnaireStatusTag(item.status)}
                                          {(item.referenced_interview_count ?? 0) > 0 ? (
                                            <Tag color="green">已被 {item.referenced_interview_count} 个访谈引用</Tag>
                                          ) : null}
                                        </Space>
                                        <Text type="secondary" style={{ fontSize: 12 }}>
                                          {item.file_name ? `文件：${item.file_name}` : "未记录原始文件名"}
                                          {item.hotwords && item.hotwords.length > 0
                                            ? `，热词 ${item.hotwords.length} 个`
                                            : ""}
                                        </Text>
                                        {item.hotwords && item.hotwords.length > 0 ? (
                                          <Space wrap size={4}>
                                            {item.hotwords.slice(0, 8).map((word) => (
                                              <Tag key={word}>{word}</Tag>
                                            ))}
                                          </Space>
                                        ) : null}
                                      </Space>
                                    </List.Item>
                                  )}
                                />
                              ) : (
                                <Text type="secondary">当前角色还没有 DG。</Text>
                              )}
                            </Space>
                          </Card>
                        );
                      })}
                    </Space>
                  ) : (
                    <Text type="secondary">当前项目还没有角色。</Text>
                  )}
                </Card>

                <Card className="summarynotes-project-list-shell">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
                    <div>
                      <Title level={4} style={{ marginBottom: 4 }} className="summarynotes-section-title">
                        项目 KBQ
                      </Title>
                      <Text type="secondary">
                        这里维护一个项目级 KBQ，所有访谈共用同一份内容。后续可以直接修改并再次保存。
                      </Text>
                    </div>
                    <Button type="primary" icon={<EditOutlined />} onClick={openKeyBqEditModal}>
                      编辑 KBQ
                    </Button>
                  </div>
                  <Space direction="vertical" size={10} style={{ width: "100%" }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {getKeyBqCount(projectKeyBq) > 0
                        ? `当前共有 ${getKeyBqCount(projectKeyBq)} 条 KBQ。`
                        : "当前还没有填写 KBQ。"}
                    </Text>
                    <Paragraph
                      style={{
                        marginBottom: 0,
                        whiteSpace: "pre-wrap",
                        background: "rgba(15, 23, 42, 0.03)",
                        borderRadius: 16,
                        padding: 16,
                        minHeight: 120,
                      }}
                    >
                      {renderKeyBqPreview(projectKeyBq) || "点击右上角按钮编辑项目 KBQ。"}
                    </Paragraph>
                  </Space>
                </Card>

                <Card className="summarynotes-project-list-shell">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
                    <div>
                      <Title level={4} style={{ marginBottom: 4 }} className="summarynotes-section-title">
                        访谈列表
                      </Title>
                      <Text type="secondary">
                        这里展示该项目下所有访谈。新建访谈时先选角色，再选对应 DG，系统会自动带上该角色的细节模板。
                      </Text>
                    </div>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={openInterviewModal}
                    >
                      创建访谈
                    </Button>
                  </div>
                  {interviews.length > 0 ? (
                    <List
                      dataSource={interviews}
                      renderItem={(item) => (
                        <List.Item
                          className="summarynotes-project-card"
                          style={{ marginBottom: 12, padding: 16, borderRadius: 16 }}
                          actions={[
                            <Button
                              key="base-info"
                              type="link"
                              onClick={() => void openInterviewDetailRowModal(item)}
                            >
                              访谈基础信息
                            </Button>,
                            <Button
                              key="detail"
                              type="link"
                              onClick={() => router.push(`/interviews/${item.id}`)}
                            >
                              详情
                            </Button>,
                            <Button
                              key="processing"
                              type="link"
                              onClick={() => router.push(`/interviews/${item.id}/processing`)}
                            >
                              处理页
                            </Button>,
                            <Button
                              key="delete"
                              type="link"
                              danger
                              loading={interviewDeletingId === item.id}
                              onClick={() => handleInterviewDelete(item)}
                            >
                              删除
                            </Button>,
                          ]}
                        >
                          <Space direction="vertical" size={6} style={{ width: "100%" }}>
                            <Space wrap>
                              <Text strong>{item.name}</Text>
                              {getInterviewStatusTag(item.status)}
                              {item.questionnaire_role_name ? (
                                <Tag
                                  color={
                                    item.questionnaire_role_type === "doctor"
                                      ? "purple"
                                      : item.questionnaire_role_type === "patient"
                                        ? "cyan"
                                        : "gold"
                                  }
                                >
                                  {item.questionnaire_role_name}
                                </Tag>
                              ) : item.questionnaire_object_type ? (
                                <Tag color={item.questionnaire_object_type === "doctor" ? "purple" : "cyan"}>
                                  {getRoleTypeLabel(item.questionnaire_object_type)}
                                </Tag>
                              ) : null}
                              {item.questionnaire_name ? (
                                <Tag color="blue">DG：{item.questionnaire_name}</Tag>
                              ) : null}
                            </Space>
                            <Space direction="vertical" size={2}>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {item.interview_date ? `访谈时间：${formatDate(item.interview_date)}` : "暂无访谈时间"}
                              </Text>
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {(() => {
                                  const interviewRole = item.questionnaire_role_id
                                    ? roleById.get(item.questionnaire_role_id) ?? null
                                    : null;
                                  return summarizeInterviewDetail(
                                    buildInterviewFieldOptions(interviewRole),
                                    (item.detail_json as InterviewDetailValues | undefined) ??
                                      (item as unknown as InterviewDetailValues),
                                  );
                                })()}
                              </Text>
                            </Space>
                          </Space>
                        </List.Item>
                      )}
                    />
                  ) : (
                    <Text type="secondary">当前项目还没有访谈。</Text>
                  )}
                </Card>
            </div>
          ) : null}
        </div>
      </Content>

      <Modal
        open={questionnaireModalOpen}
        title="添加 DG"
        onOk={() => void handleQuestionnaireSubmit()}
        onCancel={handleQuestionnaireModalCancel}
        okText="确定"
        cancelText="取消"
        confirmLoading={questionnaireSaving}
        cancelButtonProps={{ disabled: questionnaireSaving }}
        closable={!questionnaireSaving}
        maskClosable={!questionnaireSaving}
        destroyOnHidden
        width={960}
      >
        <Form form={questionnaireForm} layout="vertical">
          <Alert
            type="info"
            showIcon
            message="DG 只绑定类型"
            description="这里仅选择 DG 属于医生、患者还是自定义人员。若选择自定义人员，请同时填写人员名称。访谈细节和自定义字段会在创建访谈时填写。"
            style={{ marginBottom: 16 }}
          />

          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                label="DG 所属类型"
                name="object_type"
                rules={[{ required: true, message: "请选择 DG 所属类型" }]}
              >
                <Select
                  options={[
                    { value: "doctor", label: "医生" },
                    { value: "patient", label: "患者" },
                    { value: "custom", label: "自定义人员" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="DG 名称"
                name="name"
                rules={[{ required: true, message: "请输入 DG 名称" }]}
              >
                <Input placeholder="请输入 DG 名称" />
              </Form.Item>
            </Col>
          </Row>

          {questionnaireObjectType === "custom" ? (
            <Form.Item
              label="自定义人员名称"
              name="role_name"
              rules={[{ required: true, message: "请输入自定义人员名称" }]}
            >
              <Input placeholder="例如 甲医院主任医师 / 某品牌关键用户 / 自定义访谈对象" />
            </Form.Item>
          ) : null}

          <Form.Item label="DG 文件">
            <Upload
              beforeUpload={() => false}
              maxCount={1}
              fileList={questionnaireFileList}
              onChange={({ fileList }) => setQuestionnaireFileList(fileList)}
              accept=".docx"
            >
              <Button icon={<UploadOutlined />}>选择 docx 文件</Button>
              </Upload>
              <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: "block" }}>
                上传后会保存在项目目录的 `question/` 子目录，并自动转换成 md/json。
              </Text>
            </Form.Item>
        </Form>
      </Modal>

      <QuestionnaireHotwordReviewModal
        open={questionnaireReviewVisible}
        title={
          questionnaireReviewState
            ? `问卷热词确认 - ${questionnaireReviewState.questionnaireName}`
            : "问卷热词确认"
        }
        description="系统已从问卷中抽取候选热词。你可以修改、删除或追加条目；确认后会写回问卷热词并更新状态。"
        candidates={questionnaireReviewState?.candidates ?? []}
        loading={questionnaireReviewSaving}
        confirmText="确认保存"
        cancelText="取消"
        onCancel={handleQuestionnaireReviewCancel}
        onConfirm={handleQuestionnaireReviewConfirm}
      />

      <Modal
        open={keyBqModalOpen}
        title="编辑 KBQ"
        onOk={() => void handleKeyBqSubmit()}
        onCancel={handleKeyBqCancel}
        confirmLoading={keyBqSaving}
        cancelButtonProps={{ disabled: keyBqSaving }}
        closable={!keyBqSaving}
        maskClosable={!keyBqSaving}
        width={860}
        destroyOnHidden
      >
        <Form form={keyBqForm} layout="vertical" initialValues={buildKeyBqFormValues(projectKeyBq)}>
          <Form.List name="key_bq_list">
            {(fields, { add, remove }) => (
              <Space direction="vertical" size={16} style={{ width: "100%" }}>
                {fields.map((field, index) => (
                  <Card
                    key={field.key}
                    size="small"
                    style={{
                      borderRadius: 16,
                      background: "rgba(15, 23, 42, 0.02)",
                    }}
                  >
                    <Space style={{ width: "100%", justifyContent: "space-between" }} align="start">
                      <div>
                        <Text strong>KBQ #{index + 1}</Text>
                        <div>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            留空会在保存时自动忽略。
                          </Text>
                        </div>
                      </div>
                      <Button danger type="text" onClick={() => remove(field.name)}>
                        删除
                      </Button>
                    </Space>

                    <Form.Item
                      label="KBQ 内容"
                      name={[field.name, "text"]}
                      style={{ marginTop: 12, marginBottom: 12 }}
                    >
                      <Input.TextArea
                        rows={3}
                        placeholder="请输入 KBQ 内容"
                      />
                    </Form.Item>

                    <Divider style={{ margin: "12px 0" }}>二级维度（可选）</Divider>

                    <Form.List name={[field.name, "dimensions"]}>
                      {(dimensionFields, { add: addDimension, remove: removeDimension }) => (
                        <Space direction="vertical" size={12} style={{ width: "100%" }}>
                          {dimensionFields.map((dimensionField, dimensionIndex) => (
                            <Card
                              key={dimensionField.key}
                              size="small"
                              style={{ borderRadius: 14, background: "rgba(59, 130, 246, 0.03)" }}
                            >
                              <Space
                                style={{ width: "100%", justifyContent: "space-between" }}
                                align="start"
                              >
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  维度 #{dimensionIndex + 1}
                                </Text>
                                <Button danger type="text" onClick={() => removeDimension(dimensionField.name)}>
                                  删除
                                </Button>
                              </Space>
                              <Row gutter={12}>
                                <Col span={8}>
                                  <Form.Item
                                    label="名称"
                                    name={[dimensionField.name, "name"]}
                                    style={{ marginBottom: 0, marginTop: 8 }}
                                  >
                                    <Input placeholder="维度名称" />
                                  </Form.Item>
                                </Col>
                                <Col span={16}>
                                  <Form.Item
                                    label="描述"
                                    name={[dimensionField.name, "description"]}
                                    style={{ marginBottom: 0, marginTop: 8 }}
                                  >
                                    <Input placeholder="维度描述" />
                                  </Form.Item>
                                </Col>
                              </Row>
                            </Card>
                          ))}

                          <Button
                            type="dashed"
                            icon={<PlusOutlined />}
                            onClick={() => addDimension({ name: "", description: "" })}
                            block
                          >
                            添加维度
                          </Button>
                        </Space>
                      )}
                    </Form.List>
                  </Card>
                ))}

                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ text: "", dimensions: [] })} block>
                  添加 KBQ
                </Button>
              </Space>
            )}
          </Form.List>
        </Form>
      </Modal>

      <Modal
        open={guideResultVisible}
        title="项目指南学习结果"
        onCancel={() => setGuideResultVisible(false)}
        footer={null}
        width={1100}
        destroyOnHidden
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space wrap>
            {getGuideStatusTag(guideStatus)}
            {project?.guide_file_name ? <Tag color="blue">文件：{project.guide_file_name}</Tag> : null}
            {guideFiles.length > 0 ? <Tag color="cyan">指南文件：{guideFiles.length} 份</Tag> : null}
            {project?.guide_generated_at ? (
              <Tag color="green">完成时间：{formatDate(project.guide_generated_at)}</Tag>
            ) : null}
          </Space>
          {project?.guide_error_message ? (
            <Alert
              type="error"
              showIcon
              message="指南学习失败"
              description={project.guide_error_message}
            />
          ) : null}
          <Tabs
            items={[
              {
                key: "summary",
                label: "学习总结",
                children: guideSummaryText ? (
                  <div
                    style={{
                      maxHeight: 560,
                      overflow: "auto",
                      paddingRight: 8,
                      borderRadius: 16,
                      background: "rgba(15, 23, 42, 0.02)",
                      padding: 16,
                    }}
                  >
                    <MarkdownContent content={guideSummaryText} />
                  </div>
                ) : (
                  <Text type="secondary">暂无学习总结。</Text>
                ),
              },
              {
                key: "raw",
                label: "抽取正文",
                children: guideExtractedText ? (
                  <div
                    style={{
                      maxHeight: 560,
                      overflow: "auto",
                      whiteSpace: "pre-wrap",
                      borderRadius: 16,
                      background: "rgba(15, 23, 42, 0.02)",
                      padding: 16,
                    }}
                  >
                    {guideExtractedText}
                  </div>
                ) : (
                  <Text type="secondary">暂无抽取正文。</Text>
                ),
              },
              {
                key: "files",
                label: "文件明细",
                children: guideFiles.length > 0 ? (
                  <div style={{ display: "grid", gap: 16 ,width: "100%"}}>
                    {guideFiles.map((file, index) => {
                      const title = file.original_name || `指南文件 ${index + 1}`;
                      const fileType = String(file.file_type || "unknown").toUpperCase();
                      const displayText = String(file.summary_text || file.extracted_text || "").trim();
                      return (
                        <Card
                          key={`${file.index ?? index}-${title}`}
                          size="small"
                          style={{maxWidth: "100%",overflow:"hidden"}}
                          title={
                            <Space wrap>
                              <Text strong>{title}</Text>
                              {getGuideFileStatusTag(file.status)}
                              <Tag color="blue">{fileType}</Tag>
                            </Space>
                          }
                        >
                          {file.error_message ? (
                            <Alert
                              type="error"
                              showIcon
                              message="文件处理失败"
                              description={file.error_message}
                              style={{ marginBottom: 12 }}
                            />
                          ) : null}
                          {displayText ? (
                            <div
                              style={{
                                maxHeight: 360,
                                overflow: "auto",
                                whiteSpace: "pre-wrap",
                                borderRadius: 16,
                                background: "rgba(15, 23, 42, 0.02)",
                                padding: 16,
                              }}
                            >
                              {displayText}
                            </div>
                          ) : (
                            <Text type="secondary">暂无文件抽取内容。</Text>
                          )}
                        </Card>
                      );
                    })}
                  </div>
                ) : (
                  <Text type="secondary">暂无指南文件明细。</Text>
                ),
              },
            ]}
          />
        </Space>
      </Modal>

      <Modal
        open={interviewModalOpen}
        title="新建访谈"
        onOk={() => void handleInterviewSubmit()}
        onCancel={handleInterviewCancel}
        okText="确定"
        cancelText="取消"
        confirmLoading={interviewSaving}
        cancelButtonProps={{ disabled: interviewSaving }}
        closable={!interviewSaving}
        maskClosable={!interviewSaving}
        width={1180}
        destroyOnHidden
      >
        {questionnaires.length === 0 || getKeyBqCount(projectKeyBq) === 0 ? (
          <Alert
            type="warning"
            showIcon
            message="请先准备 DG 和 KBQ"
            description="新建访谈要求至少有一个 DG，以及项目 KBQ。"
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <Form form={interviewForm} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="访谈时间" name="interview_date">
                <DatePicker style={{ width: "100%" }} placeholder="请选择访谈时间" />
              </Form.Item>
              <Card
                size="small"
                style={{ borderRadius: 16, marginBottom: 16 }}
                title="访谈细节"
                extra={
                  <Button size="small" type="primary" ghost onClick={openInterviewDetailModal}>
                    编辑访谈细节
                  </Button>
                }
              >
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    这里展示本次访谈细节的当前状态，点击按钮可在独立窗口中填写或新增字段。
                  </Text>
                  <div
                    style={{
                      borderRadius: 16,
                      background: "rgba(15, 23, 42, 0.03)",
                      padding: 16,
                    }}
                  >
                    <Text strong style={{ display: "block", marginBottom: 8 }}>
                      {interviewDetailFieldsDraft.length > 0 ? "已配置访谈细节" : "尚未配置访谈细节"}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12, display: "block" }}>
                      {interviewDetailFieldsDraft.length > 0
                        ? `当前共 ${interviewDetailFieldsDraft.length} 个字段，点击“编辑访谈细节”可继续调整。`
                        : "点击“编辑访谈细节”开始填写本次访谈的字段。"}
                    </Text>
                    <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 8 }}>
                      {summarizeInterviewDetail(interviewDetailFieldsDraft, interviewDetailDraft)}
                    </Text>
                  </div>
                </Space>
              </Card>
            </Col>
            <Col span={12}>
              <Form.Item
                label="DG 问卷"
                name="questionnaire_id"
                rules={[{ required: true, message: "请选择 DG 问卷" }]}
              >
                <Select
                  placeholder="请选择 DG 问卷"
                  options={interviewQuestionnaireOptions}
                  disabled={interviewQuestionnaireOptions.length === 0}
                  onChange={(value) => handleInterviewQuestionnaireChange(Number(value))}
                />
              </Form.Item>
              <div style={{ marginBottom: 16 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  请选择具体 DG 问卷，系统会根据 DG 类型带出默认字段，访谈细节请在左侧独立窗口中填写。
                </Text>
              </div>
              <Form.Item label="音频文件">
                <Upload
                  beforeUpload={() => false}
                  maxCount={1}
                  fileList={interviewFileList}
                  onChange={({ fileList }) => setInterviewFileList(fileList)}
                  accept=".wav,.mp3,.m4a"
                >
                  <Button icon={<UploadOutlined />}>选择音频文件</Button>
                </Upload>
                <Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: "block" }}>
                  支持 wav、mp3、m4a 格式，上传后会进入转录流程。
                </Text>
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        open={interviewDetailModalOpen}
        title="编辑访谈细节"
        onOk={handleInterviewDetailModalOk}
        onCancel={handleInterviewDetailModalCancel}
        okText="完成"
        cancelText="取消"
        width={960}
        destroyOnHidden
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="在这里补充访谈细节"
            description={
              <Space direction="vertical" size={2} style={{ width: "100%" }}>
                <Text>
                  系统预设字段只需要填写“字段值”，不需要再填字段标识、字段名称或字段类型。
                </Text>
                <Text>
                  新增自定义字段时，请继续填写“字段标识、字段名称、字段类型、字段值”，这些内容会直接传给后端保存。
                </Text>
                <Text type="danger">
                  如果自定义字段缺少字段标识或字段名称等必要信息，可能会导致访谈创建失败。
                </Text>
              </Space>
            }
          />
          <Button type="dashed" icon={<PlusOutlined />} onClick={addInterviewDetailField} block>
            添加字段
          </Button>
          {interviewDetailFieldsDraft.length > 0 ? (
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              {interviewDetailFieldsDraft.map((field, index) => (
                <Card
                  key={field.uid}
                  size="small"
                  style={{ borderRadius: 14, background: "rgba(59, 130, 246, 0.03)" }}
                >
                  <Space style={{ width: "100%", justifyContent: "space-between" }} align="start">
                    <Space wrap size={6}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        字段 #{index + 1}
                      </Text>
                      {field.isPreset ? <Tag color="green">系统预设</Tag> : <Tag color="orange">自定义字段</Tag>}
                    </Space>
                    <Button
                      size="small"
                      danger
                      type="text"
                      onClick={() => removeInterviewDetailField(field.uid)}
                      disabled={interviewDetailFieldsDraft.length === 1}
                    >
                      删除
                    </Button>
                  </Space>
                  {field.isPreset ? (
                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        预设字段：{field.label || field.key || "未命名字段"}。这里只需要填写字段值。
                      </Text>
                    </Space>
                  ) : (
                    <Row gutter={12}>
                      <Col span={8}>
                        <Form.Item label="字段标识" style={{ marginBottom: 12 }}>
                          <Input
                            value={field.key}
                            placeholder="例如 doctor_level"
                            onChange={(event) => updateInterviewDetailField(field.uid, { key: event.target.value })}
                          />
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item label="字段名称" style={{ marginBottom: 12 }}>
                          <Input
                            value={field.label}
                            placeholder="例如 医生级别"
                            onChange={(event) =>
                              updateInterviewDetailField(field.uid, { label: event.target.value })
                            }
                          />
                        </Form.Item>
                      </Col>
                      <Col span={8}>
                        <Form.Item label="字段类型" style={{ marginBottom: 12 }}>
                          <Select
                            value={field.kind === "number" ? "number" : "text"}
                            options={[
                              { value: "text", label: "文本" },
                              { value: "number", label: "数字" },
                            ]}
                            onChange={(value) =>
                              updateInterviewDetailField(field.uid, { kind: value as "text" | "number" })
                            }
                          />
                        </Form.Item>
                      </Col>
                    </Row>
                  )}
                  <Form.Item label="字段值" style={{ marginBottom: 0 }}>
                    {field.kind === "number" ? (
                      <InputNumber
                        style={{ width: "100%" }}
                        min={0}
                        max={10}
                        value={typeof field.value === "number" ? field.value : undefined}
                        placeholder={`请输入${field.label || field.key || "字段值"}`}
                        onChange={(value) =>
                          updateInterviewDetailField(field.uid, {
                            value: typeof value === "number" ? value : null,
                          })
                        }
                      />
                    ) : (
                      <Input
                        value={typeof field.value === "string" ? field.value : ""}
                        placeholder={`请输入${field.label || field.key || "字段值"}`}
                        onChange={(event) => updateInterviewDetailField(field.uid, { value: event.target.value })}
                      />
                    )}
                  </Form.Item>
                </Card>
              ))}
            </Space>
          ) : null}
          <Text type="secondary" style={{ fontSize: 12 }}>
            {summarizeInterviewDetail(interviewDetailFieldsDraft, interviewDetailDraft)}
          </Text>
        </Space>
      </Modal>

      <Modal
        open={rowInterviewDetailOpen}
        title={
          rowInterviewId
            ? `访谈基础信息 #${rowInterviewId}${rowInterviewDetail?.name ? ` · ${rowInterviewDetail.name}` : ""}`
            : "访谈基础信息"
        }
        onCancel={closeInterviewDetailRowModal}
        footer={null}
        width={1040}
        destroyOnHidden
      >
        <Space
          direction="vertical"
          size={16}
          style={{
            width: "100%",
            maxHeight: "72vh",
            overflow: "auto",
            paddingRight: 4,
          }}
        >
          <Space style={{ width: "100%", justifyContent: "space-between" }} align="start">
            <div>
              <Title level={4} style={{ marginBottom: 4 }}>
                访谈基础信息
              </Title>
              <Text type="secondary">
                支持手动修改访谈名称和细节字段，保存细节后会按当前规则自动重算名称。
              </Text>
            </div>
            <Space>
              <Button
                onClick={() => void saveRowInterviewDisplayName()}
                loading={rowInterviewDetailSavingName}
                disabled={rowInterviewDetailLoading || !rowInterviewDetail}
              >
                保存名称
              </Button>
              <Button
                type="primary"
                onClick={() => void saveRowInterviewDetail()}
                loading={rowInterviewDetailSavingDetail}
                disabled={rowInterviewDetailLoading || !rowInterviewDetail || rowInterviewDetailEntries.length === 0}
              >
                保存细节并重算名称
              </Button>
            </Space>
          </Space>
          {rowInterviewDetailLoading ? (
            <Spin />
          ) : rowInterviewDetailError ? (
            <Alert type="error" message={rowInterviewDetailError} />
          ) : rowInterviewDetail ? (
            <Space direction="vertical" size={16} style={{ width: "100%" }}>
              <div>
                <Text strong style={{ display: "block", marginBottom: 8 }}>
                  访谈名称
                </Text>
                <Input
                  value={rowInterviewNameDraft}
                  onChange={(e) => setRowInterviewNameDraft(e.target.value)}
                  placeholder="请输入访谈名称"
                />
              </div>
              <Divider style={{ margin: "4px 0" }} />
              <div>
                <Text strong style={{ display: "block", marginBottom: 12 }}>
                  访谈细节
                </Text>
                {rowInterviewDetailEntries.length > 0 ? (
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 16,
                    }}
                  >
                    {rowInterviewDetailEntries.map(({ key, value }) => {
                      const fieldKind = getDetailFieldKind(value);
                      const draftValue = rowInterviewDetailDraft[key] ?? "";
                      return (
                        <div key={key}>
                          <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
                            {getDetailDisplayLabel(key)}
                          </Text>
                          <Text type="secondary" style={{ display: "block", marginBottom: 8, fontSize: 12 }}>
                            {key}
                          </Text>
                          {fieldKind === "number" ? (
                            <InputNumber
                              style={{ width: "100%" }}
                              value={draftValue === "" ? undefined : Number(draftValue)}
                              placeholder={`请输入${getDetailDisplayLabel(key)}`}
                              onChange={(nextValue) =>
                                handleRowInterviewDetailFieldChange(key, typeof nextValue === "number" ? String(nextValue) : "")
                              }
                            />
                          ) : fieldKind === "boolean" ? (
                            <Switch
                              checked={draftValue.trim().toLowerCase() === "true"}
                              checkedChildren="是"
                              unCheckedChildren="否"
                              onChange={(checked) => handleRowInterviewDetailFieldChange(key, checked ? "true" : "false")}
                            />
                          ) : fieldKind === "json" ? (
                            <Input.TextArea
                              value={draftValue}
                              autoSize={{ minRows: 2, maxRows: 6 }}
                              placeholder={`请输入${getDetailDisplayLabel(key)}的 JSON`}
                              onChange={(e) => handleRowInterviewDetailFieldChange(key, e.target.value)}
                            />
                          ) : (
                            <Input
                              value={draftValue}
                              placeholder={`请输入${getDetailDisplayLabel(key)}`}
                              onChange={(e) => handleRowInterviewDetailFieldChange(key, e.target.value)}
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <Alert
                    type="info"
                    showIcon
                    message="当前访谈没有可编辑的细节字段"
                    description="如果 `detail_json` 为空，请先检查后端是否已为该访谈写入细节字段。"
                  />
                )}
              </div>
            </Space>
          ) : null}
        </Space>
      </Modal>
    </Layout>
  );
}
