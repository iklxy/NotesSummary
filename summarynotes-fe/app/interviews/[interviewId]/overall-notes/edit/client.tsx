"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Alert,
  Button,
  Card,
  Col,
  Input,
  InputNumber,
  Layout,
  Modal,
  message,
  Row,
  Space,
  Spin,
  Tag,
  Select,
  Typography,
} from "antd";
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import {
  createInterviewCardsItem,
  deleteInterviewCardsItem,
  getInterviewOverallNotes,
  refreshInterviewMinutes,
  refreshInterviewCards,
  updateInterviewCardsItem,
  updateInterviewOverallNotesMinutes,
} from "../../../../../lib/interviewsApi";
import {
  captureOverallNotesCardsPng,
  exportOverallNotesWordWithImage,
  OVERALL_NOTES_CARD_EXPORT_ID,
} from "../../../../../lib/overallNotesExport";
import type {
  InterviewCardItem,
  InterviewMinutesResponse,
  InterviewOverallNotesResponse,
} from "../../../../../lib/types";
import OverallNotesCardsSection from "../../../../../components/OverallNotesCardsSection";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface Props {
  interviewId: number;
}

interface MinutesDraft {
  text: string;
}

interface CardDraft {
  id?: number;
  cards_id?: number;
  card_order: number;
  card_title: string;
  card_summary: string;
  tags_text: string;
  review_status: "pending" | "approved" | "rejected" | "needs_revision";
  review_comment: string;
  generated_json: unknown;
  final_json: unknown;
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

function getCardObject(cardJson: unknown): Record<string, unknown> | null {
  if (cardJson && typeof cardJson === "object" && !Array.isArray(cardJson)) {
    return cardJson as Record<string, unknown>;
  }
  return null;
}

function normalizePointText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function extractPointsFromPayload(payload: Record<string, unknown>): string[] {
  const rawPoints = payload.points ?? payload.items ?? payload.sub_points ?? payload.bullets ?? [];
  if (Array.isArray(rawPoints)) {
    return rawPoints
      .map((point) => {
        if (typeof point === "string") {
          return point.trim();
        }
        if (point && typeof point === "object" && !Array.isArray(point)) {
          const pointObj = point as Record<string, unknown>;
          return (
            normalizePointText(pointObj.text) ||
            normalizePointText(pointObj.summary) ||
            normalizePointText(pointObj.content) ||
            normalizePointText(pointObj.title)
          );
        }
        return "";
      })
      .filter((point) => Boolean(point));
  }
  if (typeof rawPoints === "string") {
    return rawPoints
      .split(/\n+/)
      .map((point) => point.trim())
      .filter((point) => Boolean(point));
  }
  return [];
}

function joinCardPoints(points: string[]): string {
  return points.join("\n");
}

function splitCardPointsText(text: string): string[] {
  return text
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split(/\n+/)
    .map((point) => point.replace(/^\s*(?:\d+[.)]|[-*+•·])\s*/g, "").trim())
    .filter((point) => Boolean(point));
}

function normalizeCardDraft(card: InterviewCardItem): CardDraft {
  const payload = getCardObject(card.final_json) ?? getCardObject(card.generated_json) ?? {};
  const tags = Array.isArray(payload.tags)
    ? payload.tags.map((tag) => String(tag || "").trim()).filter((tag) => Boolean(tag))
    : [];
  const points = extractPointsFromPayload(payload);
  const isOverviewCard = card.card_order === 0 || String(payload.card_type || "").trim().toLowerCase() === "overview";
  return {
    id: card.id,
    cards_id: card.cards_id,
    card_order: card.card_order,
    card_title:
      card.card_title ||
      String(payload.title || "").trim() ||
      (isOverviewCard ? "全文总览" : `卡片 ${card.card_order}`),
    card_summary:
      joinCardPoints(points) ||
      card.card_summary ||
      String(payload.summary || "").trim(),
    tags_text: tags.join(", "),
    review_status: (card.review_status as CardDraft["review_status"]) || "pending",
    review_comment: card.review_comment || "",
    generated_json: card.generated_json,
    final_json: card.final_json ?? card.generated_json,
  };
}

function createEmptyCardDraft(order: number): CardDraft {
  return {
    card_order: order,
    card_title: "新卡片",
    card_summary: "",
    tags_text: "",
    review_status: "pending",
    review_comment: "",
    generated_json: {
      title: "新卡片",
      summary: "",
      points: [],
      tags: [],
      order,
    },
    final_json: {
      title: "新卡片",
      summary: "",
      points: [],
      tags: [],
      order,
    },
  };
}

function buildCardJson(draft: CardDraft): Record<string, unknown> {
  const tags = draft.tags_text
    .split(",")
    .map((tag) => tag.trim())
    .filter((tag) => Boolean(tag));
  const points = draft.card_order === 0 ? [] : splitCardPointsText(draft.card_summary);
  const cardType = draft.card_order === 0 ? "overview" : "topic";
  return {
    title: draft.card_title.trim(),
    summary: draft.card_summary.trim(),
    points,
    tags,
    order: draft.card_order,
    card_type: cardType,
    layout_span: draft.card_order === 0 ? 3 : 1,
  };
}

function buildExportCardItems(drafts: CardDraft[], interviewId: number, projectId: number): InterviewCardItem[] {
  return drafts.map((draft, index) => ({
    id: draft.id ?? draft.card_order ?? index + 1,
    cards_id: draft.cards_id ?? 0,
    project_id: projectId,
    project_interview_id: interviewId,
    card_order: draft.card_order,
    card_title: draft.card_title.trim() || (draft.card_order === 0 ? "全文总览" : `卡片 ${draft.card_order}`),
    card_summary: draft.card_summary.trim(),
    generated_json: draft.generated_json,
    final_json: draft.final_json ?? buildCardJson(draft),
    review_status: draft.review_status,
    review_comment: draft.review_comment,
  }));
}

export default function OverallNotesEditClient({ interviewId }: Props) {
  const router = useRouter();
  const [data, setData] = useState<InterviewOverallNotesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [minutesRefreshing, setMinutesRefreshing] = useState(false);
  const [cardsRefreshing, setCardsRefreshing] = useState(false);
  const [savingMinutes, setSavingMinutes] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [cardsDraft, setCardsDraft] = useState<CardDraft[]>([]);
  const [minutesDraft, setMinutesDraft] = useState<MinutesDraft>(createEmptyMinutesDraft());

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await getInterviewOverallNotes(interviewId);
        setData(resp);
        setCardsDraft((resp.cards?.items ?? []).map((item) => normalizeCardDraft(item)));
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
      const cardImage = await captureOverallNotesCardsPng();
      const resp = await exportOverallNotesWordWithImage(interviewId, cardImage);
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
        throw new Error(resp.message || "刷新智能纪要失败");
      }
      message.success("智能纪要已刷新");
      setReloadToken((value) => value + 1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "刷新智能纪要失败");
    } finally {
      setMinutesRefreshing(false);
    }
  };

  const handleRefreshCards = async () => {
    Modal.confirm({
      title: "确认重新生成卡片",
      content: "这会基于当前智能纪要重新生成卡片，并覆盖现有卡片列表，是否继续？",
      okText: "重新生成",
      cancelText: "取消",
      onOk: async () => {
        try {
          setCardsRefreshing(true);
          const resp = await refreshInterviewCards(interviewId);
          if (resp.generation?.warning) {
            message.warning(resp.generation.warning);
          }
          setData((prev) => (prev ? { ...prev, cards: resp } : prev));
          setCardsDraft((resp.items ?? []).map((item) => normalizeCardDraft(item)));
          message.success(`卡片已重新生成，共 ${resp.items?.length ?? 0} 张`);
        } catch (e) {
          message.error(e instanceof Error ? e.message : "刷新卡片失败");
        } finally {
          setCardsRefreshing(false);
        }
      },
    });
  };

  const updateCardDraft = (itemId: number, patch: Partial<CardDraft>) => {
    setCardsDraft((prev) =>
      prev.map((item) =>
        item.id === itemId
          ? {
              ...item,
              ...patch,
            }
          : item,
      ),
    );
  };

  const handleAddCard = async () => {
    try {
      const nextOrder = cardsDraft.length > 0 ? Math.max(...cardsDraft.map((item) => item.card_order)) + 1 : 1;
      const resp = await createInterviewCardsItem(interviewId, {
        card_title: "新卡片",
        card_order: nextOrder,
        card_summary: "",
        generated_json: buildCardJson(createEmptyCardDraft(nextOrder)),
        final_json: buildCardJson(createEmptyCardDraft(nextOrder)),
        review_status: "pending",
        review_comment: "",
      });
      setCardsDraft((resp.items ?? []).map((item) => normalizeCardDraft(item)));
      message.success("卡片已新增");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "新增卡片失败");
    }
  };

  const handleSaveCard = async (draft: CardDraft) => {
    if (!draft.id) {
      message.error("卡片缺少 ID");
      return;
    }
    try {
      const reviewComment = draft.review_comment.trim();
      const finalJson = buildCardJson(draft);
      const resp = await updateInterviewCardsItem(interviewId, draft.id, {
        card_order: draft.card_order,
        card_title: draft.card_title.trim() || `卡片 ${draft.card_order}`,
        card_summary: draft.card_summary.trim(),
        generated_json: draft.generated_json,
        final_json: finalJson,
        review_status: draft.review_status,
        review_comment: reviewComment || null,
        reviewed_at: draft.review_status === "pending" ? null : undefined,
      });
      setCardsDraft((resp.items ?? []).map((item) => normalizeCardDraft(item)));
      message.success("卡片已保存");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存卡片失败");
    }
  };

  const handleDeleteCard = async (draft: CardDraft) => {
    if (!draft.id) {
      message.error("卡片缺少 ID");
      return;
    }
    Modal.confirm({
      title: "确认删除卡片",
      content: `确定要删除「${draft.card_title}」吗？`,
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          const resp = await deleteInterviewCardsItem(interviewId, draft.id as number);
          setCardsDraft((resp.items ?? []).map((item) => normalizeCardDraft(item)));
          message.success("卡片已删除");
        } catch (e) {
          message.error(e instanceof Error ? e.message : "删除卡片失败");
        }
      },
    });
  };

  const handleSaveMinutes = async () => {
    setSavingMinutes(true);
    try {
      const savedMinutesJson = serializeMinutesDraft(minutesDraft);
      await updateInterviewOverallNotesMinutes(interviewId, savedMinutesJson);
      setSavingMinutes(false);
      router.push(`/interviews/${interviewId}/overall-notes`);
      message.success("智能纪要已保存，Key BQ 正在后台刷新");
      return;
    } catch (e) {
      setSavingMinutes(false);
      message.error(e instanceof Error ? e.message : "保存智能纪要失败");
    }
  };

  const exportCardItems = buildExportCardItems(cardsDraft, interviewId, data?.project_id ?? 0);

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
                这里允许编辑全文模块总结卡片和智能纪要。
              </Paragraph>
              <div className="summarynotes-hero-tags">
                <Tag color="geekblue">A 卡片</Tag>
                <Tag color="green">C 智能纪要</Tag>
              </div>
            </div>
            <Space wrap className="summarynotes-hero-actions">
              <Button icon={<ReloadOutlined />} onClick={() => setReloadToken((value) => value + 1)} loading={loading}>
                刷新页面
              </Button>
              <Button icon={<DownloadOutlined />} onClick={handleExportOverallNotesWord} loading={exporting}>
                导出全文 Notes
              </Button>
              <Button onClick={handleRefreshCards} loading={cardsRefreshing} type="primary">
                重新生成卡片
              </Button>
              <Button onClick={handleRefreshMinutes} loading={minutesRefreshing}>
                刷新智能纪要
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
              <Card
                className="summarynotes-notes-section-card"
                title="A. 全文模块总结卡片"
                extra={
                  <Button type="primary" ghost onClick={() => void handleAddCard()}>
                    新增卡片
                  </Button>
                }
              >
                {data.cards?.status === "failed" && data.cards.error_message ? (
                  <Alert
                    type="error"
                    showIcon
                    message="卡片生成失败"
                    description={data.cards.error_message}
                    style={{ marginBottom: 16 }}
                  />
                ) : null}
                {cardsDraft.length > 0 ? (
                  <Space direction="vertical" size="large" style={{ width: "100%" }}>
                    {cardsDraft.map((card) => (
                      <Card key={card.id ?? card.card_order} size="small" style={{ borderRadius: 18 }}>
                        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                          <Space style={{ width: "100%", justifyContent: "space-between" }} align="start">
                            <Text type="secondary">卡片 #{card.card_order}</Text>
                            <Space>
                              <Button size="small" danger onClick={() => void handleDeleteCard(card)}>
                                删除
                              </Button>
                              <Button size="small" type="primary" onClick={() => void handleSaveCard(card)}>
                                保存
                              </Button>
                            </Space>
                          </Space>
                          <Row gutter={12}>
                            <Col xs={24} md={8}>
                              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                <Text className="summarynotes-panel-label">卡片顺序</Text>
                                <InputNumber
                                  style={{ width: "100%" }}
                                  min={card.card_order === 0 ? 0 : 1}
                                  value={card.card_order}
                                  onChange={(value) =>
                                    updateCardDraft(card.id as number, {
                                      card_order: typeof value === "number" ? value : card.card_order,
                                    })
                                  }
                                />
                              </Space>
                            </Col>
                            <Col xs={24} md={16}>
                              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                <Text className="summarynotes-panel-label">卡片标题</Text>
                                <Input
                                  value={card.card_title}
                                  onChange={(event) =>
                                    updateCardDraft(card.id as number, { card_title: event.target.value })
                                  }
                                  placeholder="请输入卡片标题"
                                />
                              </Space>
                            </Col>
                          </Row>
                          <Space direction="vertical" size="small" style={{ width: "100%" }}>
                            <Text className="summarynotes-panel-label">卡片要点</Text>
                            <TextArea
                              value={card.card_summary}
                              onChange={(event) =>
                                updateCardDraft(card.id as number, { card_summary: event.target.value })
                              }
                              rows={6}
                              placeholder="每行一个要点"
                            />
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              建议每行一条要点，保存时会写回结构化 points 字段。
                            </Text>
                          </Space>
                          <Row gutter={12}>
                            <Col xs={24} md={12}>
                              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                <Text className="summarynotes-panel-label">标签</Text>
                                <Input
                                  value={card.tags_text}
                                  onChange={(event) =>
                                    updateCardDraft(card.id as number, { tags_text: event.target.value })
                                  }
                                  placeholder="多个标签用英文逗号分隔"
                                />
                              </Space>
                            </Col>
                            <Col xs={24} md={12}>
                              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                <Text className="summarynotes-panel-label">审核状态</Text>
                                <Select
                                  value={card.review_status}
                                  options={[
                                    { value: "pending", label: "待审核" },
                                    { value: "approved", label: "已通过" },
                                    { value: "rejected", label: "已驳回" },
                                    { value: "needs_revision", label: "待修改" },
                                  ]}
                                  onChange={(value) =>
                                    updateCardDraft(card.id as number, {
                                      review_status: value as CardDraft["review_status"],
                                    })
                                  }
                                />
                              </Space>
                            </Col>
                          </Row>
                          <Space direction="vertical" size="small" style={{ width: "100%" }}>
                            <Text className="summarynotes-panel-label">审核意见</Text>
                            <TextArea
                              value={card.review_comment}
                              onChange={(event) =>
                                updateCardDraft(card.id as number, { review_comment: event.target.value })
                              }
                              rows={3}
                              placeholder="请输入审核意见"
                            />
                          </Space>
                        </Space>
                      </Card>
                    ))}
                  </Space>
                ) : (
                  <Alert
                    type="info"
                    showIcon
                    message="暂无卡片"
                    description="可以点击右上角新增卡片，或者等待后续生成流程写入卡片。"
                  />
                )}
              </Card>

              <Card className="summarynotes-notes-section-card" title="B. 智能纪要">
                <Row gutter={[20, 20]}>
                  <Col xs={24}>
                    <div className="summarynotes-notes-editor-panel">
                      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                        <div>
                          <Text className="summarynotes-panel-label">编辑智能纪要</Text>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            直接编辑整篇智能纪要长文本，保存后会覆盖当前内容。
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
                          placeholder="请输入完整的智能纪要长文本"
                          className="summarynotes-json-editor"
                        />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          保存后会直接覆盖当前智能纪要全文。
                        </Text>

                        <div className="summarynotes-editor-actions">
                          <Button
                            type="primary"
                            icon={<SaveOutlined />}
                            onClick={() => void handleSaveMinutes()}
                            loading={savingMinutes}
                          >
                            保存智能纪要
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
      <div className="summarynotes-card-export-stage" aria-hidden="true">
        <div className="summarynotes-card-export-shell">
          <OverallNotesCardsSection
            items={exportCardItems}
            containerId={OVERALL_NOTES_CARD_EXPORT_ID}
            exportMode
          />
        </div>
      </div>
    </Layout>
  );
}
