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
import {
  createProjectQuestionnaire,
  deleteProjectQuestionnaire,
  getProjectQuestionnaire,
  updateProjectQuestionnaireHotwords,
} from "../../../lib/projectQuestionnairesApi";
import { updateProjectKeyBqCurrent } from "../../../lib/projectKeyBqApi";
import { getProjectDetail } from "../../../lib/projectsApi";
import type {
  CreatedInterviewResponse,
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

function buildRoleTemplateFields(roleType?: string | null): InterviewDetailFieldDefinition[] {
  const normalized = normalizeRoleType(roleType);
  if (!normalized) {
    return [];
  }
  return getDefaultRoleFields(normalized);
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

export default function ProjectDetailClient({ projectId }: Props) {
  const router = useRouter();
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [questionnaireModalOpen, setQuestionnaireModalOpen] = useState(false);
  const [questionnaireSaving, setQuestionnaireSaving] = useState(false);
  const [questionnaireForm] = Form.useForm();
  const [questionnaireFileList, setQuestionnaireFileList] = useState<UploadFile[]>([]);
  const [questionnaireRoleMode, setQuestionnaireRoleMode] = useState<"existing" | "new">("existing");
  const [questionnaireRoleType, setQuestionnaireRoleType] = useState<"doctor" | "patient" | "custom">("doctor");
  const [questionnaireRoleId, setQuestionnaireRoleId] = useState<number | null>(null);
  const [questionnaireRoleFields, setQuestionnaireRoleFields] = useState<InterviewDetailFieldDefinition[]>(
    cloneFieldDefinitions(DEFAULT_DOCTOR_ROLE_FIELDS),
  );
  const [questionnaireReviewState, setQuestionnaireReviewState] =
    useState<QuestionnaireReviewState | null>(null);
  const [questionnaireReviewVisible, setQuestionnaireReviewVisible] = useState(false);
  const [questionnaireReviewSaving, setQuestionnaireReviewSaving] = useState(false);

  const [keyBqModalOpen, setKeyBqModalOpen] = useState(false);
  const [keyBqSaving, setKeyBqSaving] = useState(false);
  const [keyBqForm] = Form.useForm<KeyBqFormValues>();

  const [guideResultVisible, setGuideResultVisible] = useState(false);

  const [interviewModalOpen, setInterviewModalOpen] = useState(false);
  const [interviewSaving, setInterviewSaving] = useState(false);
  const [interviewForm] = Form.useForm<InterviewFormValues>();
  const [interviewDetailModalOpen, setInterviewDetailModalOpen] = useState(false);
  const [interviewDetailForm] = Form.useForm<InterviewDetailValues>();
  const [interviewDetailDraft, setInterviewDetailDraft] = useState<InterviewDetailValues>({});
  const [interviewFileList, setInterviewFileList] = useState<UploadFile[]>([]);
  const [selectedInterviewRoleId, setSelectedInterviewRoleId] = useState<number | null>(null);

  const loadProjectDetail = useCallback(async () => {
    if (!projectId || projectId <= 0) {
      setError("无效的项目 ID");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const detail = await getProjectDetail(projectId);
      setProjectDetail(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载项目详情失败");
    } finally {
      setLoading(false);
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

  useEffect(() => {
    void loadProjectDetail();
  }, [loadProjectDetail]);

  useEffect(() => {
    if (!guideStatus || !isGuideLearning(guideStatus)) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadProjectDetail();
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

  const selectedInterviewRole = useMemo(() => {
    if (!selectedInterviewRoleId) {
      return null;
    }
    return roleById.get(selectedInterviewRoleId) ?? null;
  }, [roleById, selectedInterviewRoleId]);

  const interviewDetailFields = useMemo(() => {
    if (!selectedInterviewRole) {
      return [];
    }
    const fields = buildInterviewFieldOptions(selectedInterviewRole);
    return fields.length > 0 ? fields : getDefaultRoleFields(selectedInterviewRole.role_type);
  }, [selectedInterviewRole]);

  const interviewQuestionnaires = useMemo(() => {
    if (!selectedInterviewRoleId) {
      return [];
    }
    return questionnairesByRoleId.get(selectedInterviewRoleId) ?? [];
  }, [questionnairesByRoleId, selectedInterviewRoleId]);

  const questionnaireRoleOptions = useMemo(
    () =>
      roles.map((role) => ({
        value: role.id,
        label: `${getRoleTypeLabel(role.role_type)} · ${role.role_name}`,
      })),
    [roles],
  );

  const interviewRoleOptions = useMemo(
    () =>
      roles.map((role) => ({
        value: role.id,
        label: `${getRoleTypeLabel(role.role_type)} · ${role.role_name}（${questionnairesByRoleId.get(role.id)?.length ?? 0} 份 DG）`,
      })),
    [questionnairesByRoleId, roles],
  );

  const openQuestionnaireModal = (targetRoleId?: number) => {
    questionnaireForm.resetFields();
    setQuestionnaireFileList([]);
    const firstRole = targetRoleId ? roleById.get(targetRoleId) ?? roles[0] ?? null : roles[0] ?? null;
    setQuestionnaireRoleMode("existing");
    setQuestionnaireRoleId(firstRole?.id ?? null);
    setQuestionnaireRoleType((normalizeRoleType(firstRole?.role_type) ?? "doctor") as "doctor" | "patient" | "custom");
    setQuestionnaireRoleFields(
      firstRole ? buildInterviewFieldOptions(firstRole) : cloneFieldDefinitions(DEFAULT_DOCTOR_ROLE_FIELDS),
    );
    questionnaireForm.setFieldsValue({
      role_mode: "existing",
      role_id: firstRole?.id ?? undefined,
      role_type: firstRole?.role_type ?? "doctor",
      role_name: firstRole?.role_name ?? "",
      object_type: firstRole?.role_type ?? "doctor",
      role_detail_schema_json: firstRole ? buildInterviewFieldOptions(firstRole) : cloneFieldDefinitions(DEFAULT_DOCTOR_ROLE_FIELDS),
    });
    setQuestionnaireModalOpen(true);
  };

  const handleQuestionnaireRoleModeChange = (mode: "existing" | "new") => {
    setQuestionnaireRoleMode(mode);
    if (mode === "existing") {
      const firstRole = (questionnaireRoleId ? roleById.get(questionnaireRoleId) : null) ?? roles[0] ?? null;
      setQuestionnaireRoleId(firstRole?.id ?? null);
      setQuestionnaireRoleType((normalizeRoleType(firstRole?.role_type) ?? "doctor") as "doctor" | "patient" | "custom");
      setQuestionnaireRoleFields(
        firstRole ? buildInterviewFieldOptions(firstRole) : cloneFieldDefinitions(DEFAULT_DOCTOR_ROLE_FIELDS),
      );
      questionnaireForm.setFieldsValue({
        role_mode: "existing",
        role_id: firstRole?.id ?? undefined,
        role_type: firstRole?.role_type ?? "doctor",
        role_name: firstRole?.role_name ?? "",
        object_type: firstRole?.role_type ?? "doctor",
        role_detail_schema_json: firstRole ? buildInterviewFieldOptions(firstRole) : cloneFieldDefinitions(DEFAULT_DOCTOR_ROLE_FIELDS),
      });
      return;
    }
    const nextFields = buildRoleTemplateFields(questionnaireRoleType);
    setQuestionnaireRoleFields(nextFields);
    questionnaireForm.setFieldsValue({
      role_mode: "new",
      role_id: undefined,
      role_type: questionnaireRoleType,
      role_name: "",
      object_type: questionnaireRoleType,
      role_detail_schema_json: nextFields,
    });
  };

  const handleQuestionnaireRoleTypeChange = (roleType: "doctor" | "patient" | "custom") => {
    setQuestionnaireRoleType(roleType);
    const nextFields = buildRoleTemplateFields(roleType);
    setQuestionnaireRoleFields(nextFields);
    questionnaireForm.setFieldsValue({
      role_type: roleType,
      object_type: roleType,
      role_detail_schema_json: nextFields,
    });
  };

  const handleQuestionnaireExistingRoleChange = (roleId: number) => {
    const nextRole = roleById.get(roleId) ?? null;
    setQuestionnaireRoleId(roleId);
    if (!nextRole) {
      return;
    }
    const nextType = (normalizeRoleType(nextRole.role_type) ?? "doctor") as "doctor" | "patient" | "custom";
    setQuestionnaireRoleType(nextType);
    const nextFields = buildInterviewFieldOptions(nextRole);
    setQuestionnaireRoleFields(nextFields);
    questionnaireForm.setFieldsValue({
      role_id: roleId,
      role_type: nextType,
      object_type: nextType,
      role_name: nextRole.role_name,
      role_detail_schema_json: nextFields,
    });
  };

  const handleQuestionnaireModalCancel = () => {
    if (questionnaireSaving) {
      return;
    }
    setQuestionnaireModalOpen(false);
    setQuestionnaireFileList([]);
    setQuestionnaireRoleMode("existing");
    setQuestionnaireRoleType("doctor");
    setQuestionnaireRoleId(null);
    setQuestionnaireRoleFields(cloneFieldDefinitions(DEFAULT_DOCTOR_ROLE_FIELDS));
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
      const roleMode = String(values.role_mode || questionnaireRoleMode || "existing").trim();
      const objectType = normalizeRoleType(values.object_type || values.role_type);
      if (!objectType) {
        message.warning("请选择角色模板类型");
        setQuestionnaireSaving(false);
        return;
      }
      const formData = new FormData();
      formData.append("name", String(values.name || "").trim());
      formData.append("object_type", objectType);
      if (roleMode === "existing") {
        const existingRoleId = Number(values.role_id || questionnaireRoleId || 0);
        if (!existingRoleId) {
          message.warning("请选择已有角色");
          setQuestionnaireSaving(false);
          return;
        }
        formData.append("role_id", String(existingRoleId));
      } else {
        const roleName = String(values.role_name || "").trim();
        if (!roleName) {
          message.warning("请输入角色名称");
          setQuestionnaireSaving(false);
          return;
        }
        const roleFields = normalizeFieldDefinitions(values.role_detail_schema_json || questionnaireRoleFields);
        formData.append("role_name", roleName);
        formData.append("role_type", objectType);
        formData.append("detail_schema_json", JSON.stringify(roleFields));
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
    setInterviewDetailDraft({});
    interviewDetailForm.resetFields();
    if (isGuideLearning(guideStatus)) {
      message.warning("项目指南仍在学习中，建议完成后再创建访谈。");
    }
    const firstRole =
      roles.find((role) => (questionnairesByRoleId.get(role.id)?.length ?? 0) > 0) ?? roles[0] ?? null;
    const firstQuestionnaire = firstRole ? questionnairesByRoleId.get(firstRole.id)?.[0] ?? null : null;
    setSelectedInterviewRoleId(firstRole?.id ?? null);
    interviewForm.setFieldsValue({
      role_id: firstRole?.id ?? undefined,
      questionnaire_id: firstQuestionnaire?.id ?? undefined,
    } as Partial<InterviewFormValues>);
    setInterviewModalOpen(true);
  };

  const handleInterviewRoleChange = (roleId: number) => {
    const nextRole = roleById.get(roleId) ?? null;
    setSelectedInterviewRoleId(roleId);
    setInterviewDetailDraft({});
    interviewDetailForm.resetFields();
    const roleQuestionnaires = questionnairesByRoleId.get(roleId) ?? [];
    const nextQuestionnaireId = roleQuestionnaires[0]?.id ?? null;
    interviewForm.setFieldsValue({
      role_id: roleId,
      questionnaire_id: nextQuestionnaireId ?? undefined,
    });
    if (!nextRole) {
      return;
    }
    if (nextQuestionnaireId) {
      setSelectedInterviewRoleId(roleId);
    }
  };

  const handleInterviewQuestionnaireChange = (questionnaireId: number) => {
    const nextQuestionnaire = questionnaireById.get(questionnaireId) ?? null;
    interviewForm.setFieldsValue({
      questionnaire_id: questionnaireId,
    });
    if (nextQuestionnaire?.role_id) {
      setSelectedInterviewRoleId(nextQuestionnaire.role_id);
      interviewForm.setFieldsValue({
        role_id: nextQuestionnaire.role_id,
      });
    }
  };

  const openInterviewDetailModal = () => {
    interviewDetailForm.resetFields();
    interviewDetailForm.setFieldsValue(interviewDetailDraft);
    setInterviewDetailModalOpen(true);
  };

  const handleInterviewDetailCancel = () => {
    if (interviewSaving) {
      return;
    }
    setInterviewDetailModalOpen(false);
  };

  const handleInterviewDetailSubmit = async () => {
    try {
      const values = await interviewDetailForm.validateFields();
      const normalized = normalizeInterviewDetailValues(values);
      setInterviewDetailDraft(normalized);
      setInterviewDetailModalOpen(false);
      message.success("访谈细节已保存");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存访谈细节失败");
    }
  };

  const handleInterviewCancel = () => {
    if (interviewSaving) {
      return;
    }
    setInterviewModalOpen(false);
    setInterviewFileList([]);
    setInterviewDetailModalOpen(false);
    setInterviewDetailDraft({});
    interviewDetailForm.resetFields();
    setSelectedInterviewRoleId(null);
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
      const roleId = Number(values.role_id || selectedInterviewRoleId || 0);
      const questionnaireId = Number(values.questionnaire_id || 0);
      if (!roleId) {
        message.warning("请选择角色");
        setInterviewSaving(false);
        return;
      }
      if (!questionnaireId) {
        message.warning("请选择对应 DG");
        setInterviewSaving(false);
        return;
      }
      const formData = new FormData();
      formData.append("questionnaire_id", String(questionnaireId));
      const detailPayload = normalizeInterviewDetailValues(interviewDetailDraft);
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
        description="在这里维护项目 KBQ、角色对应的 DG，以及访谈入口。新建访谈时会先选角色，再选择对应 DG，并自动套用该角色的访谈细节模板。"
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
            <Button icon={<ReloadOutlined />} onClick={() => void loadProjectDetail()}>
              刷新
            </Button>
            <Button onClick={() => router.push(`/projects/${projectId}/ca`)}>CA</Button>
          </Space>
        }
      />
      <Content className="relative z-0 bg-slate-50 pt-20 lg:pt-24">
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
            <Row gutter={[16, 16]}>
              <Col span={24}>
                <Card className="summarynotes-project-list-shell summarynotes-project-overview-shell mt-2 lg:mt-4">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                    <div>
                      <Title level={4} style={{ marginBottom: 8 }} className="summarynotes-section-title">
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
              </Col>

              <Col span={24}>
                <Card className="summarynotes-project-list-shell">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
                    <div>
                      <Title level={4} style={{ marginBottom: 4 }} className="summarynotes-section-title">
                        项目指南学习
                      </Title>
                      <Text type="secondary">
                        上传 PDF 指南后，系统会异步处理。这里仅展示当前处理状态，详情可点击右侧按钮查看。
                      </Text>
                    </div>
                    <Space>
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
                  </Space>
                </Card>
              </Col>

              <Col span={24}>
                <Card className="summarynotes-project-list-shell">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
                    <div>
                      <Title level={4} style={{ marginBottom: 4 }} className="summarynotes-section-title">
                        角色 / DG
                      </Title>
                      <Text type="secondary">
                        一个角色可以维护多份 DG。角色会同时决定该角色下访谈细节模板，创建访谈时会先选角色，再选对应 DG。
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
                                访谈细节模板：
                                {role.detail_schema_json.length > 0
                                  ? role.detail_schema_json.map((field) => field.label).join("、")
                                  : "暂无模板字段"}
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
              </Col>

              <Col span={24}>
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
              </Col>

              <Col span={24}>
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
              </Col>
            </Row>
          ) : null}
        </div>
      </Content>

      <Modal
        open={questionnaireModalOpen}
        title="添加 DG"
        onOk={() => void handleQuestionnaireSubmit()}
        onCancel={handleQuestionnaireModalCancel}
        confirmLoading={questionnaireSaving}
        cancelButtonProps={{ disabled: questionnaireSaving }}
        closable={!questionnaireSaving}
        maskClosable={!questionnaireSaving}
        destroyOnHidden
        width={960}
      >
        <Form form={questionnaireForm} layout="vertical" initialValues={{ role_mode: "existing" }}>
          <Form.Item
            label="角色模式"
            name="role_mode"
            rules={[{ required: true, message: "请选择角色模式" }]}
          >
            <Select
              options={[
                { value: "existing", label: "已有角色" },
                { value: "new", label: "新建角色" },
              ]}
              onChange={(value) => handleQuestionnaireRoleModeChange(value as "existing" | "new")}
            />
          </Form.Item>

          {questionnaireRoleMode === "existing" ? (
            <>
              <Form.Item
                label="选择角色"
                name="role_id"
                rules={[{ required: true, message: "请选择角色" }]}
              >
                <Select
                  placeholder="请选择角色"
                  options={questionnaireRoleOptions}
                  onChange={(value) => handleQuestionnaireExistingRoleChange(Number(value))}
                />
              </Form.Item>
              {questionnaireRoleId ? (
                <Alert
                  type="info"
                  showIcon
                  message="当前角色模板"
                  description={
                    <Space direction="vertical" size={4}>
                      <Text>
                        {roleById.get(questionnaireRoleId)?.role_name || "未命名角色"} ·{" "}
                        {getRoleTypeLabel(roleById.get(questionnaireRoleId)?.role_type)}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {questionnaireRoleFields.length > 0
                          ? questionnaireRoleFields.map((field) => field.label).join("、")
                          : "暂无访谈字段模板"}
                      </Text>
                    </Space>
                  }
                  style={{ marginBottom: 16 }}
                />
              ) : null}
            </>
          ) : (
            <>
              <Row gutter={12}>
                <Col span={12}>
                  <Form.Item
                    label="角色类型"
                    name="role_type"
                    rules={[{ required: true, message: "请选择角色类型" }]}
                  >
                    <Select
                      options={[
                        { value: "doctor", label: "医生模板" },
                        { value: "patient", label: "患者模板" },
                        { value: "custom", label: "自定义模板" },
                      ]}
                      onChange={(value) =>
                        handleQuestionnaireRoleTypeChange(value as "doctor" | "patient" | "custom")
                      }
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="角色名称"
                    name="role_name"
                    rules={[{ required: true, message: "请输入角色名称" }]}
                  >
                    <Input placeholder="例如：患者家属、护士、药师" />
                  </Form.Item>
                </Col>
              </Row>

              <Divider style={{ margin: "8px 0 16px" }}>访谈字段模板</Divider>
              <Form.List name="role_detail_schema_json">
                {(fields, { add, remove }) => (
                  <Space direction="vertical" size={12} style={{ width: "100%" }}>
                    {fields.map((field, index) => (
                      <Card
                        key={field.key}
                        size="small"
                        style={{
                          borderRadius: 14,
                          background: "rgba(59, 130, 246, 0.03)",
                        }}
                      >
                        <Space style={{ width: "100%", justifyContent: "space-between" }} align="start">
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            字段 #{index + 1}
                          </Text>
                          <Button danger type="text" onClick={() => remove(field.name)}>
                            删除
                          </Button>
                        </Space>
                        <Row gutter={12}>
                          <Col span={8}>
                            <Form.Item label="key" name={[field.name, "key"]} style={{ marginBottom: 0, marginTop: 8 }}>
                              <Input placeholder="字段 key，例如 region" />
                            </Form.Item>
                          </Col>
                          <Col span={8}>
                            <Form.Item label="label" name={[field.name, "label"]} style={{ marginBottom: 0, marginTop: 8 }}>
                              <Input placeholder="字段名称" />
                            </Form.Item>
                          </Col>
                          <Col span={8}>
                            <Form.Item label="kind" name={[field.name, "kind"]} style={{ marginBottom: 0, marginTop: 8 }}>
                              <Select
                                options={[
                                  { value: "text", label: "文本" },
                                  { value: "number", label: "数字" },
                                ]}
                              />
                            </Form.Item>
                          </Col>
                        </Row>
                      </Card>
                    ))}
                    <Button
                      type="dashed"
                      icon={<PlusOutlined />}
                      onClick={() => add({ key: "", label: "", kind: "text" })}
                      block
                    >
                      添加字段
                    </Button>
                  </Space>
                )}
              </Form.List>
            </>
          )}

          <Divider style={{ margin: "16px 0" }} />

          <Form.Item
            label="DG 名称"
            name="name"
            rules={[{ required: true, message: "请输入 DG 名称" }]}
          >
            <Input placeholder="请输入 DG 名称" />
          </Form.Item>
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
            ]}
          />
        </Space>
      </Modal>

      <Modal
        open={interviewModalOpen}
        title="新建访谈"
        onOk={() => void handleInterviewSubmit()}
        onCancel={handleInterviewCancel}
        confirmLoading={interviewSaving}
        cancelButtonProps={{ disabled: interviewSaving }}
        closable={!interviewSaving}
        maskClosable={!interviewSaving}
        width={1040}
        destroyOnHidden
      >
        {roles.length === 0 || questionnaires.length === 0 || getKeyBqCount(projectKeyBq) === 0 ? (
          <Alert
            type="warning"
            showIcon
            message="请先准备角色、DG 和 KBQ"
            description="新建访谈要求至少有一个角色及其对应 DG，以及项目 KBQ。"
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
                  <Button size="small" type="primary" onClick={openInterviewDetailModal}>
                    填写 / 修改
                  </Button>
                }
              >
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {summarizeInterviewDetail(interviewDetailFields, interviewDetailDraft)}
                </Text>
              </Card>
            </Col>
            <Col span={12}>
              <Form.Item
                label="访谈角色"
                name="role_id"
                rules={[{ required: true, message: "请选择访谈角色" }]}
              >
                <Select
                  options={interviewRoleOptions}
                  placeholder="请选择访谈角色"
                  disabled={interviewRoleOptions.length === 0}
                  onChange={(value) => handleInterviewRoleChange(Number(value))}
                />
              </Form.Item>
              <Form.Item
                label="对应 DG"
                name="questionnaire_id"
                rules={[{ required: true, message: "请选择对应 DG" }]}
              >
                <Select
                  placeholder="请选择对应 DG"
                  options={interviewQuestionnaires.map((item) => ({
                    value: item.id,
                    label: item.name,
                  }))}
                  disabled={interviewQuestionnaires.length === 0}
                  onChange={(value) => handleInterviewQuestionnaireChange(Number(value))}
                />
              </Form.Item>
              <div style={{ marginBottom: 16 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  角色会决定访谈细节模板和可选 DG 列表。
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
        title="访谈细节"
        onOk={() => void handleInterviewDetailSubmit()}
        onCancel={handleInterviewDetailCancel}
        closable={!interviewSaving}
        maskClosable={!interviewSaving}
        destroyOnHidden
        width={860}
      >
        <Form form={interviewDetailForm} layout="vertical">
          <Row gutter={16}>
            {interviewDetailFields.map((field) => (
              <Col key={field.key} span={12}>
                <Form.Item label={field.label} name={field.key}>
                  {field.kind === "number" || field.key === "hospital_decile" ? (
                    <InputNumber
                      style={{ width: "100%" }}
                      min={0}
                      max={10}
                      placeholder={`请输入${field.label}`}
                    />
                  ) : (
                    <Input placeholder={`请输入${field.label}`} />
                  )}
                </Form.Item>
              </Col>
            ))}
          </Row>
          <Alert
            type="info"
            showIcon
            message="这些字段都不是必填项。你可以只填写当前访谈需要的部分。"
          />
        </Form>
      </Modal>
    </Layout>
  );
}
