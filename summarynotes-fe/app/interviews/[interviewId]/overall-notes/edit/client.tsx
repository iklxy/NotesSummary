"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Alert,
  Button,
  Card,
  Col,
  Input,
  Layout,
  message,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import {
  exportInterviewOverallNotesWord,
  getInterviewOverallNotes,
  refreshInterviewMinutes,
  updateInterviewOverallNotesMinutes,
} from "../../../../../lib/interviewsApi";
import type {
  InterviewMinutesResponse,
  InterviewOverallNotesResponse,
} from "../../../../../lib/types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface Props {
  interviewId: number;
}

interface MinutesDraft {
  text: string;
}

function getString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function getNoteObject(noteJson: unknown): Record<string, unknown> | null {
  if (noteJson && typeof noteJson === "object" && !Array.isArray(noteJson)) {
    return noteJson as Record<string, unknown>;
  }
  return null;
}

function createEmptyMinutesDraft(): MinutesDraft {
  return {
    text: "",
  };
}

function normalizeMinutesDraft(minutes: InterviewMinutesResponse | null | undefined): MinutesDraft {
  const minutesSource = getNoteObject(minutes?.minutes_json) ?? (minutes as unknown as Record<string, unknown>) ?? {};
  const rawMinutesText =
    getString(minutesSource.raw_minutes_text) ||
    getString(minutesSource.minutes_text) ||
    getString(minutes?.minutes_text) ||
    "";
  return {
    text: rawMinutesText,
  };
}

function serializeMinutesDraft(draft: MinutesDraft): string {
  return draft.text.trim();
}

export default function OverallNotesEditClient({ interviewId }: Props) {
  const router = useRouter();
  const [data, setData] = useState<InterviewOverallNotesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [minutesRefreshing, setMinutesRefreshing] = useState(false);
  const [savingMinutes, setSavingMinutes] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [minutesDraft, setMinutesDraft] = useState<MinutesDraft>(createEmptyMinutesDraft());

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await getInterviewOverallNotes(interviewId);
        setData(resp);
        setMinutesDraft(normalizeMinutesDraft(resp.minutes));
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

  const handleRefreshMinutes = async () => {
    try {
      setMinutesRefreshing(true);
      const resp = await refreshInterviewMinutes(interviewId);
      if (!resp.success) {
        throw new Error(resp.message || "刷新智能纲要失败");
      }
      message.success("智能纲要已刷新");
      setReloadToken((value) => value + 1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "刷新智能纲要失败");
    } finally {
      setMinutesRefreshing(false);
    }
  };

  const handleSaveMinutes = async () => {
    try {
      setSavingMinutes(true);
      const savedMinutesJson = serializeMinutesDraft(minutesDraft);
      const resp = await updateInterviewOverallNotesMinutes(interviewId, savedMinutesJson);
      const nextMinutesJson = resp.minutes_json ?? savedMinutesJson;
      const nextMinutesText =
        typeof resp.minutes_text === "string" && resp.minutes_text.trim() ? resp.minutes_text : savedMinutesJson;
      message.success("智能纲要已保存");
      const nextMinutes = normalizeMinutesDraft({
        ...data?.minutes,
        minutes_json: nextMinutesJson,
        minutes_text: nextMinutesText,
      } as InterviewMinutesResponse);
      setMinutesDraft(nextMinutes);
      setData((prev) =>
        prev
          ? {
              ...prev,
              minutes: {
                ...prev.minutes,
                minutes_text: nextMinutesText,
                minutes_json: nextMinutesJson,
              },
            }
          : prev,
      );
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存智能纲要失败");
    } finally {
      setSavingMinutes(false);
    }
  };

  return (
    <Layout className="min-h-screen summarynotes-notes-page">
      <Header className="summarynotes-hero summarynotes-hero-notes-edit">
        <div className="summarynotes-hero-layout">
          <div className="summarynotes-hero-inner">
            <div className="summarynotes-hero-copy">
              <Button
                icon={<ArrowLeftOutlined />}
                onClick={() => router.push(`/interviews/${interviewId}/overall-notes`)}
                ghost
                className="summarynotes-hero-back"
              >
                返回只读页
              </Button>
              <Title level={2} className="summarynotes-hero-title">
                全文 Notes 编辑 #{interviewId > 0 ? interviewId : "无效"}
              </Title>
              <Paragraph className="summarynotes-hero-description">
                这里只允许编辑智能纲要。
              </Paragraph>
              <div className="summarynotes-hero-tags">
                <Tag color="green">B 智能纲要</Tag>
              </div>
            </div>
            <Space wrap className="summarynotes-hero-actions">
              <Button icon={<ReloadOutlined />} onClick={() => setReloadToken((value) => value + 1)} loading={loading}>
                刷新页面
              </Button>
              <Button icon={<DownloadOutlined />} onClick={handleExportOverallNotesWord} loading={exporting}>
                导出全文 Notes
              </Button>
              <Button onClick={handleRefreshMinutes} loading={minutesRefreshing}>
                刷新智能纲要
              </Button>
            </Space>
          </div>
        </div>
      </Header>

      <Content className="summarynotes-notes-content">
        <div className="summarynotes-notes-frame">
          {loading ? (
            <div className="summarynotes-loading-shell">
              <Spin size="large" />
            </div>
          ) : error ? (
            <Alert
              type="error"
              showIcon
              message="加载整体 Notes 失败"
              description={error}
              action={
                <Button size="small" onClick={() => setReloadToken((value) => value + 1)}>
                  重试
                </Button>
              }
            />
          ) : data ? (
            <Space direction="vertical" size="large" style={{ width: "100%" }}>
              <Card className="summarynotes-notes-section-card" title="智能纲要">
                <Row gutter={[20, 20]}>
                  <Col xs={24}>
                    <div className="summarynotes-notes-editor-panel">
                      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                        <div>
                          <Text className="summarynotes-panel-label">编辑智能纲要</Text>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            直接编辑整篇智能纲要长文本，保存后会覆盖当前内容。
                          </Paragraph>
                        </div>
                        <TextArea
                          value={minutesDraft.text}
                          onChange={(event) => {
                            setMinutesDraft({
                              text: event.target.value,
                            });
                          }}
                          rows={28}
                          placeholder="请输入完整的智能纲要长文本"
                          className="summarynotes-json-editor"
                        />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          保存后会直接覆盖当前智能纲要全文。
                        </Text>

                        <div className="summarynotes-editor-actions">
                          <Button
                            type="primary"
                            icon={<SaveOutlined />}
                            onClick={() => void handleSaveMinutes()}
                            loading={savingMinutes}
                          >
                            保存智能纲要
                          </Button>
                        </div>
                      </Space>
                    </div>
                  </Col>
                </Row>
              </Card>
            </Space>
          ) : null}
        </div>
      </Content>
    </Layout>
  );
}
