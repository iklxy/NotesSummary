"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Input,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import { ArrowLeftOutlined, DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import { getInterviewDetailFields } from "../../../../lib/interviewDetailFieldsApi";
import { exportProjectCaTableXlsx, generateProjectCaTable, getProjectCaTable } from "../../../../lib/projectsApi";
import { getProjectInterviews } from "../../../../lib/interviewsApi";
import type {
  GenerateProjectCaTableRequest,
  InterviewDetailFieldDefinition,
  ProjectCaDimension,
  ProjectCaJson,
  ProjectCaSubPoint,
} from "../../../../lib/types";
import { getProjects } from "../../../../lib/projectsApi";

const { Title, Text, Paragraph } = Typography;

interface Props {
  projectId: number;
}

const FALLBACK_META_FIELDS: InterviewDetailFieldDefinition[] = [
  { key: "doctor_level", label: "医生级别", kind: "text" },
  { key: "doctor_title", label: "职称", kind: "text" },
  { key: "city", label: "城市", kind: "text" },
  { key: "hospital", label: "所在医院", kind: "text" },
  { key: "department", label: "科室", kind: "text" },
  { key: "hospital_decile", label: "医院Decile", kind: "number" },
];

function cloneCaJson(value: ProjectCaJson): ProjectCaJson {
  return {
    ...value,
    column_meta_fields: [...(value.column_meta_fields ?? [])],
    column_meta_field_labels: value.column_meta_field_labels
      ? { ...value.column_meta_field_labels }
      : value.column_meta_field_labels,
    selected_interview_ids: [...(value.selected_interview_ids ?? [])],
    interviews: (value.interviews ?? []).map((item) => ({
      ...item,
      meta: item.meta ? { ...item.meta } : item.meta,
    })),
    dimensions: (value.dimensions ?? []).map((dimension) => ({
      ...dimension,
      sub_points: (dimension.sub_points ?? []).map((subPoint) => ({
        ...subPoint,
        cells: { ...(subPoint.cells ?? {}) },
      })),
    })),
    project_context:
      value.project_context && typeof value.project_context === "object"
        ? { ...value.project_context }
        : value.project_context ?? null,
  };
}

function normalizeCaJson(value: ProjectCaJson | null | undefined, projectId: number): ProjectCaJson {
  if (!value) {
    return {
      project_id: projectId,
      project_name: "",
      column_meta_fields: [...FALLBACK_META_FIELDS.map((item) => item.key)],
      column_meta_field_labels: Object.fromEntries(
        FALLBACK_META_FIELDS.map((item) => [item.key, item.label]),
      ),
      selected_interview_ids: [],
      interviews: [],
      dimensions: [],
      status: "pending",
      generated_at: "",
      error_message: "",
      project_context: null,
    };
  }
  const cloned = cloneCaJson(value);
  cloned.project_id = cloned.project_id || projectId;
  cloned.column_meta_fields = (cloned.column_meta_fields ?? []).length
    ? cloned.column_meta_fields
    : [...FALLBACK_META_FIELDS.map((item) => item.key)];
  cloned.selected_interview_ids = cloned.selected_interview_ids ?? cloned.interviews.map((item) => item.interview_id);
  cloned.interviews = cloned.interviews ?? [];
  cloned.dimensions = cloned.dimensions ?? [];
  cloned.status = cloned.status || "done";
  cloned.generated_at = cloned.generated_at || "";
  cloned.error_message = cloned.error_message || "";
  return cloned;
}

function buildInterviewLabel(item: {
  id?: number;
  interview_id?: number;
  name: string;
  interview_date?: string | null;
  status?: number | null;
}) {
  const interviewId = item.interview_id ?? item.id ?? -1;
  const parts = [
    `${interviewId}`,
    item.name,
    item.interview_date ? item.interview_date.split("T")[0] : "",
    item.status === 2 ? "已完成" : `状态 ${item.status ?? "-"}`,
  ].filter((part) => part.length > 0);
  return parts.join(" | ");
}

export default function CaProjectClient({ projectId }: Props) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string>("");
  const [metaFieldDefinitions, setMetaFieldDefinitions] = useState<InterviewDetailFieldDefinition[]>(
    FALLBACK_META_FIELDS,
  );
  const [interviews, setInterviews] = useState<Array<{
    id: number;
    name: string;
    interview_date?: string | null;
    status?: number | null;
    hospital_city?: string | null;
    hospital_decile?: number | null;
    doctor_level?: string | null;
  }>>([]);
  const [selectedInterviewIds, setSelectedInterviewIds] = useState<number[]>([]);
  const [selectedMetaFields, setSelectedMetaFields] = useState<string[]>(
    FALLBACK_META_FIELDS.map((item) => item.key),
  );
  const [caJson, setCaJson] = useState<ProjectCaJson | null>(null);

  useEffect(() => {
    const load = async () => {
      if (!projectId || projectId <= 0) {
        setError("无效的项目 ID");
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const [projectsResp, interviewsResp, caResp, fieldResp] = await Promise.all([
          getProjects(),
          getProjectInterviews(projectId),
          getProjectCaTable(projectId),
          getInterviewDetailFields(),
        ]);
        const matchedProject = projectsResp.find((item) => item.id === projectId) ?? null;
        setProjectName(matchedProject?.name || caResp.project_name || `项目 ${projectId}`);
        const fieldDefinitions = fieldResp.fields?.length > 0 ? fieldResp.fields : FALLBACK_META_FIELDS;
        setMetaFieldDefinitions(fieldDefinitions);

        const mappedInterviews = interviewsResp.map((item) => ({
          id: item.id,
          name: item.name,
          interview_date: item.interview_date ?? null,
          status: item.status ?? null,
          hospital_city: item.hospital_city ?? item.city ?? null,
          hospital_decile: item.hospital_decile ?? null,
          doctor_level: item.doctor_level ?? null,
          doctor_title: item.doctor_title ?? null,
          hospital: item.hospital ?? null,
          department: item.department ?? null,
        }));
        setInterviews(mappedInterviews);

        const existing = caResp.ca_json ? normalizeCaJson(caResp.ca_json, projectId) : null;
        if (existing) {
          setCaJson(existing);
          setSelectedInterviewIds(
            (existing.selected_interview_ids && existing.selected_interview_ids.length > 0
              ? existing.selected_interview_ids
              : existing.interviews.map((item) => item.interview_id)
            ).filter((item) => mappedInterviews.some((row) => row.id === item && row.status === 2)),
          );
          const normalizedSelectedMetaFields = (
            (existing.column_meta_fields && existing.column_meta_fields.length > 0
              ? existing.column_meta_fields
              : fieldDefinitions.map((item) => item.key)
            ).filter((item) => fieldDefinitions.some((field) => field.key === item))
          );
          setSelectedMetaFields(
            normalizedSelectedMetaFields.length > 0
              ? normalizedSelectedMetaFields
              : fieldDefinitions.map((item) => item.key),
          );
          return;
        }

        const completedIds = mappedInterviews.filter((item) => item.status === 2).map((item) => item.id);
        setSelectedInterviewIds(completedIds);
        setSelectedMetaFields(fieldDefinitions.map((item) => item.key));
        setCaJson(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载 CA 页面失败");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [projectId]);

  const completedInterviews = useMemo(() => interviews.filter((item) => item.status === 2), [interviews]);

  const selectedCompletedInterviews = useMemo(
    () => completedInterviews.filter((item) => selectedInterviewIds.includes(item.id)),
    [completedInterviews, selectedInterviewIds],
  );

  const caDraft = useMemo(() => {
    if (!caJson) {
      return null;
    }
    return caJson;
  }, [caJson]);

  const updateDimension = (
    dimensionIndex: number,
    updater: (dimension: ProjectCaDimension) => ProjectCaDimension,
  ) => {
    setCaJson((prev) => {
      if (!prev) {
        return prev;
      }
      const next = cloneCaJson(prev);
      next.dimensions = next.dimensions.map((dimension, index) =>
        index === dimensionIndex ? updater(dimension) : dimension,
      );
      return next;
    });
  };

  const updateSubPoint = (
    dimensionIndex: number,
    subPointIndex: number,
    updater: (subPoint: ProjectCaSubPoint) => ProjectCaSubPoint,
  ) => {
    setCaJson((prev) => {
      if (!prev) {
        return prev;
      }
      const next = cloneCaJson(prev);
      next.dimensions = next.dimensions.map((dimension, index) => {
        if (index !== dimensionIndex) {
          return dimension;
        }
        return {
          ...dimension,
          sub_points: dimension.sub_points.map((subPoint, subIndex) =>
            subIndex === subPointIndex ? updater(subPoint) : subPoint,
          ),
        };
      });
      return next;
    });
  };

  const handleGenerate = async () => {
    if (selectedInterviewIds.length < 2) {
      message.error("至少选择 2 个已完成访谈");
      return;
    }
    setGenerating(true);
    try {
      const payload: GenerateProjectCaTableRequest = {
        interview_ids: selectedInterviewIds,
        column_meta_fields: selectedMetaFields,
      };
      const resp = await generateProjectCaTable(projectId, payload);
      if (!resp.success) {
        throw new Error((resp as { message?: string }).message || "生成 CA 失败");
      }
      const next = normalizeCaJson(resp.ca_json, projectId);
      setCaJson(next);
      setSelectedInterviewIds(
        (next.selected_interview_ids && next.selected_interview_ids.length > 0
          ? next.selected_interview_ids
          : next.interviews.map((item) => item.interview_id)
        ).filter((item) => completedInterviews.some((row) => row.id === item)),
      );
      const normalizedSelectedMetaFields = (
        next.column_meta_fields && next.column_meta_fields.length > 0
          ? next.column_meta_fields
          : metaFieldDefinitions.map((item) => item.key)
      ).filter((item) => metaFieldDefinitions.some((field) => field.key === item));
      setSelectedMetaFields(
        normalizedSelectedMetaFields.length > 0
          ? normalizedSelectedMetaFields
          : metaFieldDefinitions.map((item) => item.key),
      );
      if (resp.skipped_interview_ids && resp.skipped_interview_ids.length > 0) {
        message.warning(`有 ${resp.skipped_interview_ids.length} 条选择访谈未纳入 CA，因为状态不是已完成`);
      }
      message.success("CA 已生成");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "生成 CA 失败");
    } finally {
      setGenerating(false);
    }
  };

  const handleExport = async () => {
    if (!caJson) {
      message.error("请先生成或加载 CA");
      return;
    }
    setExporting(true);
    try {
      const draft = normalizeCaJson(caJson, projectId);
      const resp = await exportProjectCaTableXlsx(projectId, { ca_json: draft });
      const url = URL.createObjectURL(resp.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = resp.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      message.success("CA 已导出");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "导出 CA 失败");
    } finally {
      setExporting(false);
    }
  };

  const handleMetaFieldChange = (field: string, checked: boolean) => {
    setSelectedMetaFields((prev) => {
      if (checked) {
        return prev.includes(field) ? prev : [...prev, field];
      }
      return prev.filter((item) => item !== field);
    });
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="border-b border-slate-200 bg-gradient-to-r from-slate-950 via-slate-900 to-slate-800 px-6 py-8 shadow-[0_20px_60px_-24px_rgba(15,23,42,0.55)] md:px-10 md:py-10">
        <div className="relative flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            <div className="inline-flex items-center rounded-full border border-white/10 bg-white/10 px-3 py-1 text-[11px] font-semibold tracking-[0.24em] text-slate-200">
              SUMMARYNOTES
            </div>
            <Title level={2} className="!mb-2 !mt-4 !text-white">
              CA 文档
            </Title>
            <Paragraph className="!mb-0 !max-w-2xl !text-slate-300">
              当前选择集生成、预览并导出 Excel。仅纳入状态为已完成的访谈。
            </Paragraph>
          </div>
          <div className="flex items-center gap-4">
            <div className="rounded-2xl border border-white/10 bg-white/10 px-4 py-3 text-right backdrop-blur-sm">
              <div className="text-xs text-slate-300">项目</div>
              <div className="mt-1 text-2xl font-semibold text-white">{projectName || projectId}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="px-6 py-6 md:px-8">
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Card style={{ borderRadius: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Space>
                <Button icon={<ArrowLeftOutlined />} onClick={() => router.push("/")}>
                  返回项目列表
                </Button>
                <Button icon={<ReloadOutlined />} onClick={() => window.location.reload()} loading={loading}>
                  刷新页面
                </Button>
                <Button type="primary" onClick={handleGenerate} loading={generating}>
                  生成 CA
                </Button>
                <Button icon={<DownloadOutlined />} onClick={handleExport} loading={exporting}>
                  导出 Excel
                </Button>
              </Space>

              {error ? <Alert type="error" message={error} /> : null}

              <Row gutter={[16, 16]}>
                <Col xs={24} lg={12}>
                  <Card size="small" title="选择访谈" style={{ borderRadius: 16 }}>
                    <Checkbox.Group
                      style={{ width: "100%" }}
                      value={selectedInterviewIds}
                      onChange={(values) => setSelectedInterviewIds(values.map((value) => Number(value)))}
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
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card size="small" title="列字段" style={{ borderRadius: 16 }}>
                    <Space wrap>
                      {metaFieldDefinitions.map((field) => (
                        <Checkbox
                          key={field.key}
                          checked={selectedMetaFields.includes(field.key)}
                          onChange={(e) => handleMetaFieldChange(field.key, e.target.checked)}
                        >
                          {field.label}
                        </Checkbox>
                      ))}
                    </Space>
                  </Card>
                </Col>
              </Row>
            </Space>
          </Card>

          <Card style={{ borderRadius: 20 }} title="CA 预览 / 编辑">
            {loading ? (
              <div className="flex items-center justify-center py-16">
                <Spin />
              </div>
            ) : !caDraft ? (
              <Text type="secondary">当前暂无 CA 结果，请先选择访谈并点击“生成 CA”。</Text>
            ) : (
              <Space direction="vertical" size="large" style={{ width: "100%" }}>
                <Card size="small" style={{ borderRadius: 16 }}>
                  <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    <div>
                      <Text strong>项目：</Text>
                      <Text>{caDraft.project_name || projectName || projectId}</Text>
                    </div>
                    <div>
                      <Text strong>生成时间：</Text>
                      <Text>{caDraft.generated_at || "-"}</Text>
                    </div>
                    <div>
                      <Text strong>选择访谈：</Text>
                      <Text>{(caDraft.selected_interview_ids ?? []).length}</Text>
                    </div>
                    <div>
                      <Text strong>已选访谈：</Text>
                      <Space wrap>
                        {selectedCompletedInterviews.map((item) => (
                          <Tag key={item.id}>{item.name}</Tag>
                        ))}
                      </Space>
                    </div>
                  </Space>
                </Card>

                {caDraft.dimensions.map((dimension, dimensionIndex) => (
                  <Card
                    key={`${dimension.order}-${dimension.title}-${dimensionIndex}`}
                    size="small"
                    style={{ borderRadius: 16 }}
                    title={`第${dimension.order}部分`}
                  >
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                      <Input
                        value={dimension.title}
                        onChange={(e) =>
                          updateDimension(dimensionIndex, (current) => ({
                            ...current,
                            title: e.target.value,
                          }))
                        }
                        placeholder="部分标题"
                      />
                      <Input.TextArea
                        value={dimension.summary || ""}
                        onChange={(e) =>
                          updateDimension(dimensionIndex, (current) => ({
                            ...current,
                            summary: e.target.value,
                          }))
                        }
                        rows={2}
                        placeholder="部分说明"
                      />

                      {dimension.sub_points.map((subPoint, subPointIndex) => (
                        <Card
                          key={`${dimension.order}-${subPoint.order}-${subPoint.title}-${subPointIndex}`}
                          size="small"
                          style={{ borderRadius: 14 }}
                          type="inner"
                          title={`· ${subPoint.order}. ${subPoint.title}`}
                        >
                          <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                            <Input
                              value={subPoint.title}
                              onChange={(e) =>
                                updateSubPoint(dimensionIndex, subPointIndex, (current) => ({
                                  ...current,
                                  title: e.target.value,
                                }))
                              }
                              placeholder="小点标题"
                            />
                            <Input.TextArea
                              value={subPoint.summary || ""}
                              onChange={(e) =>
                                updateSubPoint(dimensionIndex, subPointIndex, (current) => ({
                                  ...current,
                                  summary: e.target.value,
                                }))
                              }
                              rows={2}
                              placeholder="小点说明"
                            />

                            <Row gutter={[12, 12]}>
                              {interviews
                                .filter((item) => selectedInterviewIds.includes(item.id))
                                .map((item) => {
                                  const currentValue =
                                    subPoint.cells?.[String(item.id)] ??
                                    "/";
                                  return (
                                    <Col key={`${dimensionIndex}-${subPointIndex}-${item.id}`} xs={24} lg={12}>
                                      <Card size="small" style={{ borderRadius: 12 }} title={item.name}>
                                        <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                          <Text type="secondary" style={{ fontSize: 12 }}>
                                            {buildInterviewLabel(item)}
                                          </Text>
                                          <Input.TextArea
                                            value={currentValue}
                                            onChange={(e) =>
                                              updateSubPoint(dimensionIndex, subPointIndex, (current) => ({
                                                ...current,
                                                cells: {
                                                  ...(current.cells || {}),
                                                  [String(item.id)]: e.target.value,
                                                },
                                              }))
                                            }
                                            rows={5}
                                          />
                                        </Space>
                                      </Card>
                                    </Col>
                                  );
                                })}
                            </Row>
                          </Space>
                        </Card>
                      ))}
                    </Space>
                  </Card>
                ))}
              </Space>
            )}
          </Card>
        </Space>
      </div>
    </div>
  );
}
