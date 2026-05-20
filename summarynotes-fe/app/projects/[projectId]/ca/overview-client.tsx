"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Spin, Space, Tag, Typography, message } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import type { Interview, ProjectCaTableItem, ProjectQuestionnaire } from "../../../../lib/types";
import { getProjectCaTables, getProjectDetail } from "../../../../lib/projectsApi";
import BrandHero from "../../../../components/BrandHero";

const { Text } = Typography;

interface Props {
  projectId: number;
}

interface QuestionnaireGroup {
  questionnaire_id: number | null;
  questionnaire_name: string;
  questionnaire_status?: string | null;
  interviews: Interview[];
  ca_item?: ProjectCaTableItem | null;
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

function groupInterviews(
  questionnaires: ProjectQuestionnaire[],
  interviews: Interview[],
  caItems: ProjectCaTableItem[],
): QuestionnaireGroup[] {
  const questionnaireMap = new Map<number, ProjectQuestionnaire>();
  questionnaires.forEach((item) => {
    questionnaireMap.set(item.id, item);
  });

  const grouped = new Map<number | null, Interview[]>();
  interviews.forEach((item) => {
    const key = item.questionnaire_id ?? null;
    const current = grouped.get(key) ?? [];
    current.push(item);
    grouped.set(key, current);
  });

  const result: QuestionnaireGroup[] = [];
  grouped.forEach((items, questionnaireId) => {
    if (questionnaireId !== null && items.length === 0) {
      return;
    }
    const questionnaire = questionnaireId !== null ? questionnaireMap.get(questionnaireId) : null;
    const caItem = caItems.find((item) => item.questionnaire_id === questionnaireId) ?? null;
    result.push({
      questionnaire_id: questionnaireId,
      questionnaire_name:
        questionnaire?.name ||
        questionnaire?.role_name ||
        `DG ${questionnaireId ?? "未绑定"}`,
      questionnaire_status: questionnaire?.status ?? null,
      interviews: items,
      ca_item: caItem,
    });
  });

  result.sort((a, b) => {
    if (a.questionnaire_id === null) return 1;
    if (b.questionnaire_id === null) return -1;
    return a.questionnaire_id - b.questionnaire_id;
  });
  return result;
}

export default function CaOverviewClient({ projectId }: Props) {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const [groups, setGroups] = useState<QuestionnaireGroup[]>([]);
  const [selectedByQuestionnaire, setSelectedByQuestionnaire] = useState<Record<string, number[]>>({});

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [detailResp, caTablesResp] = await Promise.all([
          getProjectDetail(projectId),
          getProjectCaTables(projectId),
        ]);
        setProjectName(detailResp.project?.name || `项目 ${projectId}`);
        const items = caTablesResp.items ?? [];
        const nextGroups = groupInterviews(detailResp.questionnaires ?? [], detailResp.interviews ?? [], items);
        setGroups(nextGroups);
        const selectionMap: Record<string, number[]> = {};
        nextGroups.forEach((group) => {
          if (group.questionnaire_id === null) {
            return;
          }
          selectionMap[String(group.questionnaire_id)] = group.interviews.map((item) => item.id);
        });
        setSelectedByQuestionnaire(selectionMap);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载 CA 详情页失败");
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, [projectId]);

  const hasGroups = groups.length > 0;

  const handleToggleInterview = (questionnaireId: number, interviewId: number) => {
    setSelectedByQuestionnaire((prev) => {
      const key = String(questionnaireId);
      const current = prev[key] ?? [];
      const next = current.includes(interviewId)
        ? current.filter((item) => item !== interviewId)
        : [...current, interviewId];
      return {
        ...prev,
        [key]: next,
      };
    });
  };

  const openEditor = (questionnaireId: number, defaultInterviewIds: number[]) => {
    const selectedIds = selectedByQuestionnaire[String(questionnaireId)];
    const effectiveIds = selectedIds && selectedIds.length > 0 ? selectedIds : defaultInterviewIds;
    const query = effectiveIds.length > 0 ? `?interview_ids=${effectiveIds.join(",")}` : "";
    router.push(`/projects/${projectId}/ca/${questionnaireId}${query}`);
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <BrandHero
        title="CA 详情"
        description="按 DG 自动分组访谈，先确认访谈标签，再进入框架编辑页。"
        backButton={
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push(`/projects/${projectId}`)} className="summarynotes-hero-back">
            返回项目详情
          </Button>
        }
        stats={
          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-right shadow-[0_12px_28px_-20px_rgba(15,23,42,0.22)]">
            <div className="text-xs text-slate-500">项目</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">{projectName || projectId}</div>
          </div>
        }
      />

      <div className="px-6 py-6 md:px-8">
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Card style={{ borderRadius: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-slate-900">CA 链路</div>
                  <Text type="secondary">先按 DG 分组访谈，再进入对应 DG 的框架编辑页。</Text>
                </div>
              </div>
            </Space>
          </Card>

          {error ? <Alert type="error" message={error} /> : null}

          <Card style={{ borderRadius: 20 }}>
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold text-slate-900">DG 分组</div>
                  <Text type="secondary">默认勾选该 DG 下的全部访谈，进入编辑页后可继续删减和调整。</Text>
                </div>
              </div>
            </Space>
          </Card>

          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Spin />
            </div>
          ) : !hasGroups ? (
            <Card style={{ borderRadius: 20 }}>
              <Text type="secondary">当前项目还没有引用 DG 的访谈。</Text>
            </Card>
          ) : (
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              {groups.map((group) => {
                const questionnaireId = group.questionnaire_id;
                const selectedIds = questionnaireId !== null ? selectedByQuestionnaire[String(questionnaireId)] ?? [] : [];
                const caItem = group.ca_item;
                const buttonLabel =
                  caItem?.final_status === "done" || caItem?.framework_status ? "继续编辑" : "生成CA";
                return (
                  <Card key={String(questionnaireId ?? "unbound")} style={{ borderRadius: 20 }}>
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div className="text-xl font-semibold text-slate-900">{group.questionnaire_name}</div>
                          <div className="mt-1 text-sm text-slate-500">
                            {questionnaireId ? `questionnaire_id: ${questionnaireId}` : "未绑定 DG"}
                            {group.questionnaire_status ? ` · 问卷状态: ${group.questionnaire_status}` : ""}
                            {caItem?.final_status ? ` · 最终态: ${caItem.final_status}` : ""}
                            {caItem?.framework_status ? ` · 框架态: ${caItem.framework_status}` : ""}
                            {questionnaireId ? ` · 已选 ${selectedIds.length}/${group.interviews.length}` : ""}
                          </div>
                        </div>
                        {questionnaireId ? (
                          <Button type="primary" onClick={() => openEditor(questionnaireId, selectedIds)}>
                            {buttonLabel}
                          </Button>
                        ) : null}
                      </div>

                      <div>
                        <Text strong>访谈标签</Text>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {group.interviews.length > 0 ? (
                            group.interviews.map((item) => {
                              const checked = questionnaireId !== null ? selectedIds.includes(item.id) : false;
                              return (
                                <Tag.CheckableTag
                                  key={item.id}
                                  checked={checked}
                                  onChange={() => {
                                    if (questionnaireId === null) {
                                      return;
                                    }
                                    handleToggleInterview(questionnaireId, item.id);
                                  }}
                                >
                                  {buildInterviewLabel(item)}
                                </Tag.CheckableTag>
                              );
                            })
                          ) : (
                            <Text type="secondary">当前 DG 没有引用访谈。</Text>
                          )}
                        </div>
                      </div>
                    </Space>
                  </Card>
                );
              })}
            </Space>
          )}
        </Space>
      </div>
    </div>
  );
}
