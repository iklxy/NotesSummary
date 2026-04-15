"use client";

import { useEffect, useMemo, useState } from "react";
import { Layout, Row, Col, Divider, Typography, Spin, Alert, Card } from "antd";
import {
  getInterviewNotes,
  getInterviewSummary,
} from "../../../lib/interviewsApi";
import type {
  InterviewSummaryResponse,
} from "../../../lib/interviewsApi";
import type { InterviewNotesResponse } from "../../../lib/types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface Props {
  interviewId: number;
}

export default function InterviewDetailClient({ interviewId }: Props) {
  const interviewIdNum = interviewId;

  const [summary, setSummary] = useState<InterviewSummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [notes, setNotes] = useState<InterviewNotesResponse | null>(null);
  const [notesLoading, setNotesLoading] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);

  useEffect(() => {
    const loadSummary = async () => {
      try {
        setSummaryLoading(true);
        setSummaryError(null);
        const data = await getInterviewSummary(interviewIdNum);
        setSummary(data);
      } catch (e) {
        setSummaryError(e instanceof Error ? e.message : "加载录音原文失败");
      } finally {
        setSummaryLoading(false);
      }
    };

    const loadNotes = async () => {
      try {
        setNotesLoading(true);
        setNotesError(null);
        const data = await getInterviewNotes(interviewIdNum);
        setNotes(data);
      } catch (e) {
        setNotesError(e instanceof Error ? e.message : "加载 QS & Notes 失败");
      } finally {
        setNotesLoading(false);
      }
    };

    if (interviewIdNum > 0) {
      void loadSummary();
      void loadNotes();
    } else {
      setSummaryError("无效的访谈 ID");
      setNotesError("无效的访谈 ID");
    }
  }, [interviewIdNum]);

  const speakerSideMap = useMemo(() => {
    const map: Record<string, "left" | "right"> = {};
    if (!summary?.items) {
      return map;
    }
    let assignedCount = 0;
    for (const item of summary.items) {
      const speaker = (item.speaker || "").trim();
      if (!speaker) {
        continue;
      }
      if (map[speaker]) {
        continue;
      }
      if (assignedCount === 0) {
        map[speaker] = "left";
      } else if (assignedCount === 1) {
        map[speaker] = "right";
      } else {
        map[speaker] = "left";
      }
      assignedCount += 1;
      if (assignedCount >= 2) {
        break;
      }
    }
    return map;
  }, [summary]);

  return (
    <Layout className="min-h-screen">
      <Header className="flex items-center justify之间 bg-slate-900 shadow px-6">
        <Title level={3} className="mb-0" style={{ color: "#ffffff" }}>
          访谈详情 #{interviewIdNum > 0 ? interviewIdNum : "无效"}
        </Title>
      </Header>
      <Content className="p-6 bg-slate-50">
        <Row gutter={24}>
          <Col span={11}>
            <Title level={4}>录音原文</Title>
            {summaryLoading ? (
              <Spin />
            ) : summaryError ? (
              <Alert type="error" message={summaryError} />
            ) : (
              <div
                style={{
                  maxHeight: "70vh",
                  overflowY: "auto",
                  paddingRight: 8,
                }}
              >
                {summary?.items && summary.items.length > 0 ? (
                  summary.items.map((item) => {
                    const speaker = (item.speaker || "").trim() || "未知角色";
                    const side = speakerSideMap[speaker] || "left";
                    const timestamp = item.timestamp || "";
                    const text = item.text || "";
                    return (
                      <div
                        key={item.id}
                        style={{
                          display: "flex",
                          justifyContent:
                            side === "left" ? "flex-start" : "flex-end",
                          marginBottom: 8,
                        }}
                      >
                        <Card
                          size="small"
                          style={{
                            maxWidth: "80%",
                            backgroundColor:
                              side === "left" ? "#ffffff" : "#e6f4ff",
                          }}
                        >
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {speaker}
                            {timestamp ? ` · ${timestamp}` : ""}
                          </Text>
                          <Paragraph style={{ marginBottom: 0 }}>{text}</Paragraph>
                        </Card>
                      </div>
                    );
                  })
                ) : (
                  <Text type="secondary">暂无原文数据。</Text>
                )}
              </div>
            )}
          </Col>
          <Col span={2} className="flex justify-center">
            <Divider type="vertical" style={{ height: "100%" }} />
          </Col>
          <Col span={11}>
            <Title level={4}>QS &amp; Notes</Title>
            {notesLoading ? (
              <Spin />
            ) : notesError ? (
              <Alert type="error" message={notesError} />
            ) : (
              <div
                style={{
                  maxHeight: "70vh",
                  overflowY: "auto",
                  paddingRight: 8,
                }}
              >
                {notes?.questions && notes.questions.length > 0 ? (
                  notes.questions.map((q) => {
                    const primaryNote = q.notes?.[0];
                    let summaryText = "";
                    let analysisText = "";
                    if (
                      primaryNote &&
                      primaryNote.note_json &&
                      typeof primaryNote.note_json === "object"
                    ) {
                      const obj = primaryNote
                        .note_json as Record<string, unknown>;
                      if (typeof obj.summary === "string") {
                        summaryText = obj.summary;
                      }
                      if (typeof obj.analysis === "string") {
                        analysisText = obj.analysis;
                      }
                    }
                    return (
                      <Card
                        key={q.question_id}
                        style={{ marginBottom: 12 }}
                      >
                        <Title level={5}>
                          {q.question_order}. {q.question_text}
                        </Title>
                        {summaryText && (
                          <>
                            <Text strong>Summary</Text>
                            <Paragraph>{summaryText}</Paragraph>
                          </>
                        )}
                        {analysisText && (
                          <>
                            <Text strong>Analysis</Text>
                            <Paragraph>{analysisText}</Paragraph>
                          </>
                        )}
                        {!summaryText && !analysisText && (
                          <Text type="secondary">该题暂无可展示的 Notes。</Text>
                        )}
                      </Card>
                    );
                  })
                ) : (
                  <Text type="secondary">暂无 QS &amp; Notes 数据。</Text>
                )}
              </div>
            )}
          </Col>
        </Row>
      </Content>
    </Layout>
  );
}

