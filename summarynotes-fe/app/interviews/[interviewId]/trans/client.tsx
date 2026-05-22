"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Layout, Space, Spin, Tag, Typography, message } from "antd";
import { ArrowLeftOutlined, DownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import BrandHero from "../../../../components/BrandHero";
import { exportInterviewTransWord, getInterviewSummary } from "../../../../lib/interviewsApi";
import type { InterviewSummaryResponse } from "../../../../lib/interviewsApi";

const { Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface Props {
  interviewId: number;
}

function formatAudioClock(ms: number): string {
  const safeMs = Math.max(0, Math.floor(ms));
  const totalSeconds = Math.floor(safeMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatAudioTimestampRange(timestamp?: string | null): string {
  if (!timestamp) {
    return "";
  }
  const match = timestamp.trim().match(/^(\d+)(?:-(\d+))?$/);
  if (!match) {
    return timestamp.trim();
  }
  const startMs = Number(match[1]);
  const endMs = match[2] ? Number(match[2]) : startMs;
  const start = formatAudioClock(startMs);
  const end = formatAudioClock(endMs);
  return start === end ? start : `${start} - ${end}`;
}

export default function TransClient({ interviewId }: Props) {
  const router = useRouter();
  const [data, setData] = useState<InterviewSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await getInterviewSummary(interviewId);
        setData(resp);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载全文 trans 失败");
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

  const speakerLabelMap = useMemo(() => {
    const map = new Map<string, string>();
    let index = 0;
    for (const item of data?.items ?? []) {
      const speaker = (item.speaker || "").trim() || "unknown";
      if (map.has(speaker)) {
        continue;
      }
      index += 1;
      map.set(speaker, `speaker${index}`);
    }
    return map;
  }, [data]);

  const handleExportWord = async () => {
    try {
      setExporting(true);
      const resp = await exportInterviewTransWord(interviewId);
      const url = URL.createObjectURL(resp.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = resp.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "导出 Word 失败");
    } finally {
      setExporting(false);
    }
  };

  return (
    <Layout className="min-h-screen bg-slate-50">
      <BrandHero
        className="mb-14 lg:mb-16"
        title={`全文 trans #${interviewId > 0 ? interviewId : "无效"}`}
        description="这里展示全文转写内容，并支持导出 Word。"
        backButton={
          <Button icon={<ArrowLeftOutlined />} onClick={() => router.push(`/interviews/${interviewId}`)}>
            返回访谈
          </Button>
        }
        actions={
          <Space>
            <Button icon={<DownloadOutlined />} onClick={handleExportWord} loading={exporting}>
              导出 Word
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => setReloadToken((v) => v + 1)} loading={loading}>
              刷新
            </Button>
          </Space>
        }
      />
      <Content className="pt-10 lg:pt-4">
        <div style={{ maxWidth: 1680, margin: "0 auto", padding: "24px" }}>
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Spin />
            </div>
          ) : error ? (
            <Alert type="error" message={error} />
          ) : (
            <Card style={{ borderRadius: 20 }} title="全文 trans">
              {data?.items && data.items.length > 0 ? (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  {data.items.map((item) => {
                    const speaker = (item.speaker || "").trim() || "未知角色";
                    const speakerLabel = speakerLabelMap.get(speaker) || speaker;
                    const timestamp = item.timestamp || "";
                    const text = item.text || "";
                    const confidence = typeof item.confidence === "number" ? item.confidence : null;
                    return (
                      <Card key={item.id} size="small" style={{ borderRadius: 16 }}>
                        <Space direction="vertical" size="small" style={{ width: "100%" }}>
                          <Space size={8} wrap>
                            <Tag color="blue">{speakerLabel}</Tag>
                            {timestamp ? (
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {formatAudioTimestampRange(timestamp)}
                              </Text>
                            ) : null}
                            {confidence !== null ? (
                              <Tag color={confidence < 0.7 ? "orange" : "green"}>
                                confidence {confidence.toFixed(2)}
                              </Tag>
                            ) : null}
                          </Space>
                          <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                            {text}
                          </Paragraph>
                        </Space>
                      </Card>
                    );
                  })}
                </Space>
              ) : (
                <Text type="secondary">暂无可展示的全文 trans。</Text>
              )}
            </Card>
          )}
        </div>
      </Content>
    </Layout>
  );
}
