"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Layout,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";
import { getInterviewOverallNotes } from "../../../../lib/interviewsApi";
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

function formatSummaryClock(timestamp?: string | null): string {
  if (!timestamp) {
    return "";
  }
  const match = timestamp.trim().match(/^(\d+)(?:-(\d+))?$/);
  if (!match) {
    return timestamp.trim();
  }
  const startMs = Number(match[1]);
  const endMs = match[2] ? Number(match[2]) : startMs;
  const toClock = (ms: number) => {
    const totalSeconds = Math.floor(Math.max(0, Math.floor(ms)) / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  };
  const start = toClock(startMs);
  const end = toClock(endMs);
  return start === end ? start : `${start} - ${end}`;
}

export default function OverallNotesClient({ interviewId }: Props) {
  const router = useRouter();
  const [data, setData] = useState<InterviewOverallNotesResponse | null>(null);
  const [loading, setLoading] = useState(false);
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

  const notesQuestions = useMemo(() => data?.notes?.questions ?? [], [data]);
  const summaryItems = useMemo(() => data?.summary?.items ?? [], [data]);

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
        <Button
          icon={<ReloadOutlined />}
          onClick={() => setReloadToken((v) => v + 1)}
          loading={loading}
        >
          刷新
        </Button>
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

              <Card style={{ borderRadius: 20 }} title="B. 问题级 Delivery Notes">
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

              <Card style={{ borderRadius: 20 }} title="C. Summary 对话流">
                {summaryItems.length > 0 ? (
                  <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    {summaryItems.map((item) => (
                      <Card key={item.id} size="small" style={{ background: "#fafafa" }}>
                        <Space direction="vertical" size={4} style={{ width: "100%" }}>
                          <Space size={8} wrap>
                            <Tag color="blue">{item.speaker || "unknown"}</Tag>
                            <Tag color="default">{formatSummaryClock(item.timestamp)}</Tag>
                          </Space>
                          <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                            {item.text}
                          </Paragraph>
                        </Space>
                      </Card>
                    ))}
                  </Space>
                ) : (
                  <Text type="secondary">暂无 summary 对话内容。</Text>
                )}
              </Card>
            </Space>
          )}
        </div>
      </Content>
    </Layout>
  );
}
