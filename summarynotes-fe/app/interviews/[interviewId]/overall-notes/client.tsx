"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Layout, message, Space, Spin, Typography } from "antd";
import { ArrowLeftOutlined, DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import MarkdownContent from "../../../../components/MarkdownContent";
import {
  exportInterviewOverallNotesWord,
  getInterviewOverallNotes,
  refreshInterviewKbqNotes,
  refreshInterviewMinutes,
} from "../../../../lib/interviewsApi";
import type { InterviewOverallNotesResponse } from "../../../../lib/types";

const { Header, Content } = Layout;
const { Title, Text } = Typography;

interface Props {
  interviewId: number;
}

function getNoteObject(noteJson: unknown): Record<string, unknown> | null {
  if (noteJson && typeof noteJson === "object" && !Array.isArray(noteJson)) {
    return noteJson as Record<string, unknown>;
  }
  return null;
}

function getKbqDimensionNotes(noteJson: unknown): Array<Record<string, unknown>> {
  const noteObj = getNoteObject(noteJson);
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

function getNoteSummary(noteJson: unknown): string {
  const noteObj = getNoteObject(noteJson);
  if (!noteObj) {
    return "";
  }
  const value = noteObj.summary;
  return typeof value === "string" ? value : "";
}

function getMinutesHighlights(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0);
}

function getMinutesActionItems(
  value: unknown,
): Array<{ owner: string; time: string; content: string }> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => {
      return item !== null && typeof item === "object" && !Array.isArray(item);
    })
    .map((item) => ({
      owner: typeof item.owner === "string" ? item.owner : "",
      time: typeof item.time === "string" ? item.time : "",
      content: typeof item.content === "string" ? item.content : "",
    }))
    .filter((item) => item.owner.length > 0 || item.time.length > 0 || item.content.length > 0);
}

function stripMinutesHighlightsSection(text: string): string {
  const marker = "## 关键高亮";
  const startIndex = text.indexOf(marker);
  if (startIndex < 0) {
    return text;
  }
  const afterMarker = text.slice(startIndex + marker.length);
  const nextHeadingMatch = afterMarker.match(/\n##\s+/);
  if (!nextHeadingMatch || nextHeadingMatch.index === undefined) {
    return text.slice(0, startIndex).trim();
  }
  const endIndex = startIndex + marker.length + nextHeadingMatch.index;
  const before = text.slice(0, startIndex).trimEnd();
  const after = text.slice(endIndex).trimStart();
  return [before, after].filter((part) => part.length > 0).join("\n\n");
}

export default function OverallNotesClient({ interviewId }: Props) {
  const router = useRouter();
  const [data, setData] = useState<InterviewOverallNotesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [kbqRefreshing, setKbqRefreshing] = useState(false);
  const [minutesRefreshing, setMinutesRefreshing] = useState(false);
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

  const handleRefreshMinutes = async () => {
    try {
      setMinutesRefreshing(true);
      const resp = await refreshInterviewMinutes(interviewId);
      if (!resp.success) {
        throw new Error(resp.message || "刷新智能纪要失败");
      }
      message.success(
        `智能纪要已刷新：大纲 ${resp.outline_generated ?? 0} 条，生成 ${resp.generated ?? 0} 条，写入 ${resp.inserted ?? 0} 条`,
      );
      setReloadToken((v) => v + 1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "刷新智能纪要失败");
    } finally {
      setMinutesRefreshing(false);
    }
  };

  const handleExportOverallNotesWord = async () => {
    try {
      setExporting(true);
      const resp = await exportInterviewOverallNotesWord(interviewId);
      const url = URL.createObjectURL(resp.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = resp.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "导出全文 Notes 失败");
    } finally {
      setExporting(false);
    }
  };

  const minutesText = useMemo(() => {
    const rawText = data?.minutes?.minutes_text?.trim() || "";
    return rawText ? stripMinutesHighlightsSection(rawText) : "";
  }, [data]);
  const minutesSections = useMemo(() => data?.minutes?.sections ?? [], [data]);

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
          <Button icon={<DownloadOutlined />} onClick={handleExportOverallNotesWord} loading={exporting}>
            导出全文 Notes
          </Button>
          <Button onClick={handleRefreshMinutes} loading={minutesRefreshing}>
            刷新智能纪要
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
                  <MarkdownContent content={data.note_content} />
                ) : (
                  <Text type="secondary">暂无整体 summary notes。</Text>
                )}
              </Card>

              <Card style={{ borderRadius: 20 }} title="B. KBQ Notes">
                {data?.kbq_notes?.items?.length ? (
                  <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                    {data.kbq_notes.items.map((item) => {
                      const dimensionNotes = getKbqDimensionNotes(item.note_json);
                      return (
                        <Card key={item.id} size="small" style={{ borderRadius: 16 }}>
                          <Space direction="vertical" size="small" style={{ width: "100%" }}>
                            <Title level={5} style={{ marginBottom: 0 }}>
                              {item.bq_order}. {item.bq_text}
                            </Title>
                            {dimensionNotes.length > 0 ? (
                              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                {dimensionNotes.map((dimensionNote, index) => {
                                  const dimensionName =
                                    typeof dimensionNote.dimension === "string"
                                      ? dimensionNote.dimension
                                      : `维度 ${index + 1}`;
                                  const summaryText = getNoteSummary(dimensionNote);
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
                                        <MarkdownContent content={summaryText} />
                                      ) : (
                                        <Text type="secondary">该维度暂无可展示的内容。</Text>
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

              <Card style={{ borderRadius: 20 }} title="C. 智能纪要">
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  {minutesText ? (
                    <MarkdownContent content={minutesText} />
                  ) : minutesSections.length > 0 ? (
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                      {minutesSections.map((section) => {
                        const sectionTitle =
                          section.title && section.title.trim()
                            ? `第${section.order}部分：${section.title.trim()}`
                            : `第${section.order}部分`;
                        return (
                          <Card key={section.order} size="small" style={{ borderRadius: 16 }}>
                            <Space direction="vertical" size="small" style={{ width: "100%" }}>
                              <Title level={5} style={{ marginBottom: 0 }}>
                                {sectionTitle}
                              </Title>
                              {section.summary ? (
                                <MarkdownContent content={section.summary} />
                              ) : null}
                              {section.items?.length ? (
                                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                  {section.items.map((item) => {
                                    const itemTitle =
                                      item.title && item.title.trim()
                                        ? `${item.order}. ${item.title.trim()}`
                                        : `${item.order}`;
                                    return (
                                      <Card
                                        key={`${section.order}-${item.order}-${item.title}`}
                                        size="small"
                                        style={{
                                          borderRadius: 14,
                                          background: "#fafafa",
                                          borderColor: "#ececec",
                                        }}
                                        title={itemTitle}
                                      >
                                        {item.summary ? (
                                          <MarkdownContent content={item.summary} />
                                        ) : (
                                          <Text type="secondary">暂无可展示内容。</Text>
                                        )}
                                      </Card>
                                    );
                                  })}
                                </Space>
                              ) : (
                                <Text type="secondary">该部分暂无小点可展示。</Text>
                              )}
                            </Space>
                          </Card>
                        );
                      })}
                    </Space>
                  ) : (
                    <Text type="secondary">暂无智能纪要。</Text>
                  )}
                </Space>
              </Card>
            </Space>
          )}
        </div>
      </Content>
    </Layout>
  );
}
