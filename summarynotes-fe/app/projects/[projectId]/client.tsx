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
import { getInterviewDetailFields } from "../../../lib/interviewDetailFieldsApi";
import { getProjectDetail } from "../../../lib/projectsApi";
import type {
  CreatedInterviewResponse,
  InterviewDetailFieldDefinition,
  KeyBqJson,
  ProjectDetail,
  ProjectQuestionnaire,
  QuestionnaireHotwordCandidate,
} from "../../../lib/types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface Props {
  projectId: number;
}

interface KeyBqFormValues {
  key_bq_text: string;
}

interface InterviewFormValues {
  interview_date?: Dayjs | null;
  object_type: string;
}

type InterviewDetailValues = Record<string, string | number | null | undefined>;

const FALLBACK_INTERVIEW_DETAIL_FIELDS: InterviewDetailFieldDefinition[] = [
  { key: "doctor_level", label: "医生级别", kind: "text" },
  { key: "doctor_title", label: "职称", kind: "text" },
  { key: "city", label: "城市", kind: "text" },
  { key: "hospital", label: "所在医院", kind: "text" },
  { key: "department", label: "科室", kind: "text" },
  { key: "hospital_decile", label: "医院Decile", kind: "number" },
];

interface QuestionnaireReviewState {
  questionnaireId: number;
  questionnaireName: string;
  candidates: QuestionnaireHotwordCandidate[];
}

function parseKeyBqJson(value?: KeyBqJson | null): string {
  const items = value?.key_bq_list ?? [];
  return items.map((item) => item.text).join("\n");
}

function buildKeyBqJson(rawValue: string): string {
  const items = rawValue
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((text, index) => ({ order: index + 1, text }));
  return JSON.stringify({ key_bq_list: items }, null, 2);
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

function getObjectTypeLabel(value?: string | null): string {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "patient" || normalized === "患者") {
    return "患者";
  }
  if (normalized === "doctor" || normalized === "医生") {
    return "医生";
  }
  return "未配置类型";
}

function normalizeObjectType(value?: string | null): "patient" | "doctor" | null {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "patient" || normalized === "患者") {
    return "patient";
  }
  if (normalized === "doctor" || normalized === "医生") {
    return "doctor";
  }
  return null;
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
  const [interviewDetailFields, setInterviewDetailFields] = useState<InterviewDetailFieldDefinition[]>(
    FALLBACK_INTERVIEW_DETAIL_FIELDS,
  );
  const [interviewDetailDraft, setInterviewDetailDraft] = useState<InterviewDetailValues>({});
  const [interviewFileList, setInterviewFileList] = useState<UploadFile[]>([]);

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

  useEffect(() => {
    const loadFields = async () => {
      try {
        const resp = await getInterviewDetailFields();
        if (resp.fields && resp.fields.length > 0) {
          setInterviewDetailFields(resp.fields);
        }
      } catch {
        setInterviewDetailFields(FALLBACK_INTERVIEW_DETAIL_FIELDS);
      }
    };
    void loadFields();
  }, []);

  const questionnaireByObjectType = useMemo(() => {
    const map = new Map<string, ProjectQuestionnaire>();
    questionnaires.forEach((item) => {
      const objectType = normalizeObjectType(item.object_type);
      if (!objectType) {
        return;
      }
      if (!map.has(objectType)) {
        map.set(objectType, item);
      }
    });
    return map;
  }, [questionnaires]);

  const objectTypeOptions = useMemo(
    () =>
      ["patient", "doctor"]
        .filter((type) => questionnaireByObjectType.has(type))
        .map((type) => ({
          value: type,
          label: `${getObjectTypeLabel(type)} · ${questionnaireByObjectType.get(type)?.name || "DG"}`,
        })),
    [questionnaireByObjectType],
  );

  const availableObjectTypeOptions = useMemo(
    () =>
      ["patient", "doctor"]
        .filter((type) => !questionnaireByObjectType.has(type))
        .map((type) => ({
          value: type,
          label: getObjectTypeLabel(type),
        })),
    [questionnaireByObjectType],
  );

  const openQuestionnaireModal = () => {
    if (availableObjectTypeOptions.length === 0) {
      message.info("患者和医生两个对象类型都已配置，无需继续新增 DG");
      return;
    }
    questionnaireForm.resetFields();
    setQuestionnaireFileList([]);
    questionnaireForm.setFieldsValue({ object_type: availableObjectTypeOptions[0].value });
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
      const objectType = normalizeObjectType(values.object_type);
      if (!objectType) {
        message.warning("请选择对象类型");
        setQuestionnaireSaving(false);
        return;
      }
      const formData = new FormData();
      formData.append("name", String(values.name || "").trim());
      formData.append("object_type", objectType);
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
    keyBqForm.setFieldsValue({
      key_bq_text: parseKeyBqJson(projectKeyBq),
    });
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
      const keyBqText = String(values.key_bq_text || "").trim();
      await updateProjectKeyBqCurrent(projectId, {
        key_bq_json: buildKeyBqJson(keyBqText),
      });
      message.success("Key BQ 已保存");
      setKeyBqModalOpen(false);
      await loadProjectDetail();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存 Key BQ 失败");
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
    if (objectTypeOptions.length > 0) {
      interviewForm.setFieldsValue({
        object_type: objectTypeOptions[0].value,
      } as Partial<InterviewFormValues>);
    }
    setInterviewModalOpen(true);
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
      const objectType = normalizeObjectType(values.object_type);
      if (!objectType) {
        message.warning("请选择访谈对象类型");
        setInterviewSaving(false);
        return;
      }
      const formData = new FormData();
      formData.append("object_type", objectType);
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
      <Header
        style={{
          height: "auto",
          padding: 0,
          background: "transparent",
        }}
      >
        <div className="relative overflow-hidden border-b border-slate-200 bg-gradient-to-r from-slate-950 via-slate-900 to-slate-800 px-6 py-8 shadow-[0_20px_60px_-24px_rgba(15,23,42,0.55)] md:px-10 md:py-10">
          <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-sky-400/15 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-12 left-1/3 h-44 w-44 rounded-full bg-cyan-300/10 blur-3xl" />
          <div className="relative flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div className="max-w-4xl">
              <Button
                icon={<ArrowLeftOutlined />}
                onClick={() => router.push("/")}
                ghost
                style={{ marginBottom: 14 }}
              >
                返回项目列表
              </Button>
              <div className="inline-flex items-center rounded-full border border-white/10 bg-white/10 px-3 py-1 text-[11px] font-semibold tracking-[0.24em] text-slate-200">
                SUMMARYNOTES
              </div>
              <Title level={2} className="!mb-2 !mt-4 !text-white">
                {project?.name || `项目 ${projectId}`}
              </Title>
              <Paragraph className="!mb-0 !max-w-3xl !text-slate-300">
                在这里维护项目 Key BQ、访谈对象类型对应的 DG，以及访谈入口。新建访谈时只需要选择对象类型，系统会自动对应 DG 和共享的 Key BQ。
              </Paragraph>
              <div style={{ marginTop: 16, display: "flex", flexWrap: "wrap", gap: 8 }}>
                <Tag color="cyan">问卷 {projectCounts.questionnaire_count ?? 0}</Tag>
                <Tag color="geekblue">Key BQ {projectCounts.key_bq_count ?? 0}</Tag>
                <Tag color="green">访谈 {projectCounts.interview_count ?? 0}</Tag>
              </div>
            </div>
            <Space wrap>
              <Button icon={<ReloadOutlined />} onClick={() => void loadProjectDetail()}>
                刷新
              </Button>
              <Button onClick={() => router.push(`/projects/${projectId}/ca`)}>CA</Button>
            </Space>
          </div>
        </div>
      </Header>

      <Content className="bg-slate-50">
        <div className="p-6 md:p-8">
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
                <Card className="summarynotes-project-list-shell">
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
                        访谈对象类型 / DG
                      </Title>
                      <Text type="secondary">
                        每一行左侧选择访谈对象类型，右侧上传对应的 DG 问卷。创建访谈时只需要选择对象类型，系统会自动匹配对应 DG。
                      </Text>
                    </div>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={openQuestionnaireModal}
                      disabled={availableObjectTypeOptions.length === 0}
                    >
                      添加 DG
                    </Button>
                  </div>
                  {questionnaires.length > 0 ? (
                    <List
                      dataSource={questionnaires}
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
                              <Tag color={item.object_type === "doctor" ? "purple" : "cyan"}>
                                {getObjectTypeLabel(item.object_type)}
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
                    <Text type="secondary">当前项目还没有 DG。</Text>
                  )}
                </Card>
              </Col>

              <Col span={24}>
                <Card className="summarynotes-project-list-shell">
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
                    <div>
                      <Title level={4} style={{ marginBottom: 4 }} className="summarynotes-section-title">
                        项目 Key BQ
                      </Title>
                      <Text type="secondary">
                        这里维护一个项目级 Key BQ，所有访谈共用同一份内容。后续可以直接修改并再次保存。
                      </Text>
                    </div>
                    <Button type="primary" icon={<EditOutlined />} onClick={openKeyBqEditModal}>
                      编辑 Key BQ
                    </Button>
                  </div>
                  <Space direction="vertical" size={10} style={{ width: "100%" }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {getKeyBqCount(projectKeyBq) > 0
                        ? `当前共有 ${getKeyBqCount(projectKeyBq)} 条 Key BQ。`
                        : "当前还没有填写 Key BQ。"}
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
                      {parseKeyBqJson(projectKeyBq) || "点击右上角按钮编辑项目 Key BQ。"}
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
                        这里展示该项目下所有访谈。新建访谈时只需要选择对象类型，系统会自动使用对应 DG 和项目 Key BQ。
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
                              {item.questionnaire_object_type ? (
                                <Tag color={item.questionnaire_object_type === "doctor" ? "purple" : "cyan"}>
                                  {getObjectTypeLabel(item.questionnaire_object_type)}
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
                                {summarizeInterviewDetail(
                                  interviewDetailFields,
                                  item as unknown as InterviewDetailValues,
                                )}
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
      >
        <Form form={questionnaireForm} layout="vertical">
          <Form.Item
            label="对象类型"
            name="object_type"
            rules={[{ required: true, message: "请选择对象类型" }]}
          >
            <Select
              placeholder="请选择对象类型"
              options={[
                { value: "patient", label: "患者" },
                { value: "doctor", label: "医生" },
              ]}
            />
          </Form.Item>
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
        title="编辑 Key BQ"
        onOk={() => void handleKeyBqSubmit()}
        onCancel={handleKeyBqCancel}
        confirmLoading={keyBqSaving}
        cancelButtonProps={{ disabled: keyBqSaving }}
        closable={!keyBqSaving}
        maskClosable={!keyBqSaving}
        width={860}
        destroyOnHidden
      >
        <Form form={keyBqForm} layout="vertical">
          <Form.Item
            label="Key BQ 内容"
            name="key_bq_text"
            rules={[{ required: true, message: "请输入 Key BQ 内容" }]}
          >
            <Input.TextArea
              rows={10}
              placeholder={`每行一个 Key BQ，例如：
该访谈主要关注哪些伴随诊断靶点？
国产和进口产品在当前市场中的竞争情况如何？
未来市场布局和准入障碍有哪些？`}
            />
          </Form.Item>
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
        {questionnaires.length === 0 || objectTypeOptions.length === 0 || getKeyBqCount(projectKeyBq) === 0 ? (
          <Alert
            type="warning"
            showIcon
            message="请先准备 DG 和 Key BQ"
            description="新建访谈要求至少有一个已配置对象类型对应的 DG，以及项目 Key BQ。"
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
                label="访谈对象类型"
                name="object_type"
                rules={[{ required: true, message: "请选择访谈对象类型" }]}
              >
                <Select
                  options={objectTypeOptions}
                  placeholder="请选择访谈对象类型"
                  disabled={objectTypeOptions.length === 0}
                />
              </Form.Item>
              <div style={{ marginBottom: 16 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  选中对象类型后，系统会自动对应到同类型 DG 和项目 Key BQ。
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
