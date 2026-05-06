"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Collapse, Layout, message, Space, Spin, Tag, Typography } from "antd";
import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";
import { getInterviewOverallNotes, refreshInterviewKbqNotes } from "../../../../lib/interviewsApi";
import type {
  InterviewOverallNotesResponse,
  QuestionWithNotes,
} from "../../../../lib/types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface Props {
  interviewId: number;
}

function getNoteObject(noteJson: unknown): Record<string, unknown> | null {
  if (noteJson && typeof noteJson === "object" && !Array.isArray(noteJson)) {
    return noteJson as Record<string, unknown>;
  }
  return null;
}

function getEvidenceItems(noteJson: unknown): Array<Record<string, unknown>> {
  const noteObj = getNoteObject(noteJson);
  if (!noteObj) {
    return [];
  }
  const evidence = noteObj.evidence;
  if (!Array.isArray(evidence)) {
    return [];
  }
  return evidence.filter((item): item is Record<string, unknown> => {
    return item !== null && typeof item === "object" && !Array.isArray(item);
  });
}

function getNoteStringField(noteJson: unknown, fieldName: "summary" | "analysis"): string {
  const noteObj = getNoteObject(noteJson);
  if (!noteObj) {
    return "";
  }
  const value = noteObj[fieldName];
  return typeof value === "string" ? value : "";
}

function getSummaryIds(item: Record<string, unknown>): string[] {
  const raw = item.summary_id;
  if (typeof raw === "number" || typeof raw === "string") {
    return [String(raw)];
  }
  if (Array.isArray(raw)) {
    return raw
      .filter((value) => typeof value === "number" || typeof value === "string")
      .map((value) => String(value));
  }
  return [];
}

function getKbqObject(noteJson: unknown): Record<string, unknown> | null {
  if (noteJson && typeof noteJson === "object" && !Array.isArray(noteJson)) {
    return noteJson as Record<string, unknown>;
  }
  return null;
}

function getKbqDimensionNotes(noteJson: unknown): Array<Record<string, unknown>> {
  const noteObj = getKbqObject(noteJson);
  if (!noteObj) {
    return [];
  }
  const dimensionNotes = noteObj.dimension_notes;
  if (!Array.isArray(dimensionNotes)) {
    return [];
  }
  return dimensionNotes.filter((item): item is Record<string, unknown> => {
    return item !== null && typeof item === "object" && !Array.isArray(item);
  });
}

export default function OverallNotesClient({ interviewId }: Props) {
  const router = useRouter();
  const [data, setData] = useState<InterviewOverallNotesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [kbqRefreshing, setKbqRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await getInterviewOverallNotes(interviewId);
        setData(resp);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载整体 Notes 失败");
      } finally {
        setLoading(false);
      }
    };
    if (interviewId > 0) {
      void load();
    } else {
      setError("无效的访谈 ID");
    }
  }, [interviewId, reloadToken]);

  const handleRefreshKbqNotes = async () => {
    try {
      setKbqRefreshing(true);
      const resp = await refreshInterviewKbqNotes(interviewId);
      if (!resp.success) {
        throw new Error(resp.message || "刷新 KBQ Notes 失败");
      }
      message.success(
        `KBQ Notes 已刷新：回填 ${resp.key_bq_inserted ?? 0} 条，生成 ${resp.generated ?? 0} 条，写入 ${resp.inserted ?? 0} 条`,
      );
      setReloadToken((v) => v + 1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "刷新 KBQ Notes 失败");
    } finally {
      setKbqRefreshing(false);
    }
  };

  const notesQuestions = useMemo(() => data?.notes?.questions ?? [], [data]);

  return (
    <Layout className="min-h-screen bg-slate-50">
      <Header className="flex items-center justify-between bg-slate-900 px-6 shadow">
        <Space>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => router.push(`/interviews/${interviewId}`)}
          >
            返回访谈
          </Button>
          <Title level={3} className="mb-0" style={{ color: "#fff" }}>
            整体 Notes #{interviewId > 0 ? interviewId : "无效"}
          </Title>
        </Space>
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => setReloadToken((v) => v + 1)}
            loading={loading}
          >
            刷新页面
          </Button>
          <Button onClick={handleRefreshKbqNotes} loading={kbqRefreshing} type="primary">
            刷新 KBQ Notes
          </Button>
        </Space>
      </Header>
      <Content>
        <div style={{ maxWidth: 1680, margin: "0 auto", padding: "24px" }}>
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Spin />
            </div>
          ) : error ? (
            <Alert type="error" message={error} />
          ) : (
            <Space direction="vertical" size="large" style={{ width: "100%" }}>
              <Card style={{ borderRadius: 20 }} title="A. 访谈总览 Summary Notes">
                {data?.note_content ? (
                  <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                    {data.note_content}
                  </Paragraph>
                ) : (
                  <Text type="secondary">暂无整体 summary notes。</Text>
                )}
              </Card>

              <Card style={{ borderRadius: 20 }} title="B. KBQ Notes">
                {data?.kbq_notes?.items?.length ? (
                  <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    {data.kbq_notes.items.map((item) => {
                      const noteObj = getKbqObject(item.note_json);
                      const dimensionNotes = getKbqDimensionNotes(item.note_json);
                      const confidenceText =
                        typeof noteObj?.confidence === "number"
                          ? `置信度：${noteObj.confidence.toFixed(2)}`
                          : typeof noteObj?.confidence === "string"
                            ? `置信度：${noteObj.confidence}`
                            : "";
                      return (
                        <Card key={item.id} size="small" style={{ borderRadius: 16 }}>
                          <Space direction="vertical" size="small" style={{ width: "100%" }}>
                            <Title level={5} style={{ marginBottom: 0 }}>
                              {item.bq_order}. {item.bq_text}
                            </Title>
                            {confidenceText ? (
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {confidenceText}
                              </Text>
                            ) : null}
                            {dimensionNotes.length > 0 ? (
                              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                {dimensionNotes.map((dimensionNote, index) => {
                                  const dimensionName =
                                    typeof dimensionNote.dimension === "string"
                                      ? dimensionNote.dimension
                                      : `维度 ${index + 1}`;
                                  const summaryText = getNoteStringField(dimensionNote, "summary");
                                  return (
                                    <Card
                                      key={`${item.id}-${index}-${dimensionName}`}
                                      size="small"
                                      style={{
                                        borderRadius: 14,
                                        background: "#fafafa",
                                        borderColor: "#ececec",
                                      }}
                                      title={dimensionName}
                                    >
                                      {summaryText ? (
                                        <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                                          {summaryText}
                                        </Paragraph>
                                      ) : (
                                        <Text type="secondary">该维度暂无可展示的 Summary。</Text>
                                      )}
                                    </Card>
                                  );
                                })}
                              </Space>
                            ) : (
                              <Text type="secondary">该条 key BQ 暂无可展示的维度 notes。</Text>
                            )}
                          </Space>
                        </Card>
                      );
                    })}
                  </Space>
                ) : (
                  <Text type="secondary">暂无 KBQ Notes。</Text>
                )}
              </Card>

              <Card style={{ borderRadius: 20 }} title="C. 问题级 Delivery Notes">
                {notesQuestions.length > 0 ? (
                  <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    {notesQuestions.map((question: QuestionWithNotes) => {
                      const primaryNote = question.notes?.[0];
                      const noteJson = primaryNote?.note_json;
                      const summaryText = getNoteStringField(noteJson, "summary");
                      const analysisText = getNoteStringField(noteJson, "analysis");
                      const evidenceItems = getEvidenceItems(noteJson);
                      return (
                        <Card key={question.question_id} size="small" style={{ borderRadius: 16 }}>
                          <Space direction="vertical" size="small" style={{ width: "100%" }}>
                            <Title level={5} style={{ marginBottom: 0 }}>
                              {question.question_order}. {question.question_text}
                            </Title>
                            {summaryText ? (
                              <div>
                                <Text strong>Summary</Text>
                                <Paragraph style={{ marginBottom: 0 }}>{summaryText}</Paragraph>
                              </div>
                            ) : (
                              <Text type="secondary">该题暂无可展示的 Summary。</Text>
                            )}
                            {analysisText ? (
                              <Collapse
                                ghost
                                items={[
                                  {
                                    key: "analysis",
                                    label: "展开分析",
                                    children: (
                                      <div>
                                        <Paragraph style={{ marginBottom: 12 }}>
                                          {analysisText}
                                        </Paragraph>
                                        {evidenceItems.length > 0 ? (
                                          <div>
                                            <Text strong>证据</Text>
                                            <div style={{ marginTop: 8 }}>
                                              <Space size={[8, 8]} wrap>
                                                {evidenceItems.map((item, index) => {
                                                  const summaryIds = getSummaryIds(item);
                                                  const evidenceText =
                                                    typeof item.text === "string" ? item.text : "";
                                                  if (summaryIds.length === 0) {
                                                    return (
                                                      <Tag
                                                        key={`unknown-${index}`}
                                                        color="default"
                                                        style={{ whiteSpace: "normal" }}
                                                      >
                                                        summary_id: 未知
                                                        {evidenceText ? ` · ${evidenceText}` : ""}
                                                      </Tag>
                                                    );
                                                  }
                                                  return summaryIds.map((summaryId) => (
                                                    <Tag
                                                      key={`${summaryId}-${index}`}
                                                      color="geekblue"
                                                      style={{ whiteSpace: "normal" }}
                                                    >
                                                      summary_id: {summaryId}
                                                      {evidenceText ? ` · ${evidenceText}` : ""}
                                                    </Tag>
                                                  ));
                                                })}
                                              </Space>
                                            </div>
                                          </div>
                                        ) : null}
                                      </div>
                                    ),
                                  },
                                ]}
                              />
                            ) : (
                              <Text type="secondary">该题暂无可展示的 Analysis。</Text>
                            )}
                          </Space>
                        </Card>
                      );
                    })}
                  </Space>
                ) : (
                  <Text type="secondary">暂无自动或手工生成的 Notes。</Text>
                )}
              </Card>

            </Space>
          )}
        </div>
      </Content>
    </Layout>
  );
}
