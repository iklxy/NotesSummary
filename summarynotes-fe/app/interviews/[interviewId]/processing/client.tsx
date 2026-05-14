"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Layout, Spin, Typography, message } from "antd";
import BrandHero from "../../../../components/BrandHero";
import { getInterviewStatus } from "../../../../lib/interviewsApi";

const { Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface Props {
  interviewId: number;
}

export default function InterviewProcessingClient({ interviewId }: Props) {
  const router = useRouter();
  const [status, setStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState(interviewId > 0);
  const [error, setError] = useState<string | null>(interviewId > 0 ? null : "无效的访谈 ID");
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    if (interviewId <= 0) {
      return;
    }

    let timer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    const checkStatus = async () => {
      try {
        const data = await getInterviewStatus(interviewId);
        if (cancelled) {
          return;
        }
        setStatus(data.status ?? null);
        setLoading(false);

        if (data.status === 2) {
          if (timer) {
            clearInterval(timer);
          }
          router.replace(`/interviews/${interviewId}`);
          return;
        }

        if (data.status === 3) {
          if (timer) {
            clearInterval(timer);
          }
          setError("访谈工作流执行失败，请稍后重试");
        }
      } catch (e) {
        if (cancelled) {
          return;
        }
        setError(e instanceof Error ? e.message : "查询访谈状态失败");
        setLoading(false);
        if (timer) {
          clearInterval(timer);
        }
      }
    };

    void checkStatus();
    timer = setInterval(() => {
      void checkStatus();
    }, 2000);

    return () => {
      cancelled = true;
      if (timer) {
        clearInterval(timer);
      }
    };
  }, [interviewId, router, retryToken]);

  const statusText =
    status === 1
      ? "音频已上传，正在进入转录流程"
      : status === 2
        ? "处理完成，正在跳转详情页"
        : status === 3
          ? "处理失败"
          : "正在等待转录";

  return (
    <Layout className="min-h-screen bg-slate-50">
      <BrandHero
        title="正在等待转录"
        description={statusText}
        contentMaxWidthClassName="max-w-3xl"
      />
      <Content className="flex items-center justify-center p-6">
        <Card style={{ width: "100%", maxWidth: 640, borderRadius: 24, boxShadow: "0 18px 44px -28px rgba(15, 23, 42, 0.18)" }}>
          <div className="text-center">
            {loading && !error ? <Spin size="large" /> : null}
            <Title level={3} style={{ marginTop: 24 }}>
              正在等待转录
            </Title>
            <Paragraph type="secondary" style={{ marginBottom: 8 }}>
              {statusText}
            </Paragraph>
            <Paragraph type="secondary" style={{ marginBottom: 8 }}>
              处理时间可能较长，通常需要 10 分钟左右，请耐心等待。
            </Paragraph>
            <Text type="secondary">
              访谈 ID: {interviewId}
              {status !== null ? ` · 当前状态: ${status}` : ""}
            </Text>
          </div>

          {error ? (
            <div style={{ marginTop: 24 }}>
              <Alert type="error" message={error} />
              <div style={{ display: "flex", gap: 12, marginTop: 16, justifyContent: "center" }}>
                <Button onClick={() => router.push("/")}>返回列表</Button>
                <Button
                  type="primary"
                  onClick={() => {
                    setError(null);
                    setLoading(true);
                    setRetryToken((prev) => prev + 1);
                    message.info("正在重新查询状态");
                  }}
                >
                  重试
                </Button>
              </div>
            </div>
          ) : null}
        </Card>
      </Content>
    </Layout>
  );
}
