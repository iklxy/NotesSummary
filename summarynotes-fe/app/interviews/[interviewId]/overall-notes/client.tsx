"use client";

import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Layout, message, Space, Spin, Tag, Typography } from "antd";
import { ArrowLeftOutlined, DownloadOutlined, EditOutlined, ReloadOutlined } from "@ant-design/icons";
import MarkdownContent from "../../../../components/MarkdownContent";
import {
  getInterviewOverallNotes,
  refreshInterviewCards,
  refreshInterviewKbqNotes,
  refreshInterviewMinutes,
} from "../../../../lib/interviewsApi";
import {
  captureOverallNotesCardsPng,
  exportOverallNotesWordWithImage,
  OVERALL_NOTES_CARD_EXPORT_ID,
} from "../../../../lib/overallNotesExport";
import type { InterviewOverallNotesResponse, InterviewCardItem } from "../../../../lib/types";
import OverallNotesCardsSection from "../../../../components/OverallNotesCardsSection";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;

interface Props {
  interviewId: number;
}

type CardTheme = {
  accent: string;
  accentSoft: string;
  accentPale: string;
  accentInk: string;
  border: string;
  glow: string;
  surface: string;
  surfaceStrong: string;
  pointBg: string;
  tagBg: string;
};

const CARD_THEMES: CardTheme[] = [
  {
    accent: "#2563eb",
    accentSoft: "#dbeafe",
    accentPale: "#eff6ff",
    accentInk: "#1d4ed8",
    border: "#bfdbfe",
    glow: "rgba(37, 99, 235, 0.18)",
    surface: "#ffffff",
    surfaceStrong: "#f8fbff",
    pointBg: "#eff6ff",
    tagBg: "#dbeafe",
  },
  {
    accent: "#ea580c",
    accentSoft: "#ffedd5",
    accentPale: "#fff7ed",
    accentInk: "#c2410c",
    border: "#fed7aa",
    glow: "rgba(234, 88, 12, 0.16)",
    surface: "#ffffff",
    surfaceStrong: "#fff8f2",
    pointBg: "#fff1e6",
    tagBg: "#ffedd5",
  },
  {
    accent: "#0f766e",
    accentSoft: "#ccfbf1",
    accentPale: "#f0fdfa",
    accentInk: "#0f766e",
    border: "#99f6e4",
    glow: "rgba(15, 118, 110, 0.16)",
    surface: "#ffffff",
    surfaceStrong: "#f8fffd",
    pointBg: "#e6fffb",
    tagBg: "#ccfbf1",
  },
  {
    accent: "#be185d",
    accentSoft: "#fce7f3",
    accentPale: "#fdf2f8",
    accentInk: "#be185d",
    border: "#f9a8d4",
    glow: "rgba(190, 24, 93, 0.15)",
    surface: "#ffffff",
    surfaceStrong: "#fff7fb",
    pointBg: "#fdf2f8",
    tagBg: "#fce7f3",
  },
  {
    accent: "#7c3aed",
    accentSoft: "#ede9fe",
    accentPale: "#f5f3ff",
    accentInk: "#6d28d9",
    border: "#c4b5fd",
    glow: "rgba(124, 58, 237, 0.16)",
    surface: "#ffffff",
    surfaceStrong: "#faf7ff",
    pointBg: "#f5f3ff",
    tagBg: "#ede9fe",
  },
  {
    accent: "#ca8a04",
    accentSoft: "#fef3c7",
    accentPale: "#fffbeb",
    accentInk: "#a16207",
    border: "#fde68a",
    glow: "rgba(202, 138, 4, 0.16)",
    surface: "#ffffff",
    surfaceStrong: "#fffaf0",
    pointBg: "#fff7d6",
    tagBg: "#fef3c7",
  },
];

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

function getCardObject(cardJson: unknown): Record<string, unknown> | null {
  if (cardJson && typeof cardJson === "object" && !Array.isArray(cardJson)) {
    return cardJson as Record<string, unknown>;
  }
  return null;
}

function cleanText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function normalizePointSource(value: unknown): string {
  if (typeof value === "string") {
    return value.trim();
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "";
  }
  const obj = value as Record<string, unknown>;
  return (
    cleanText(obj.title) ||
    cleanText(obj.name) ||
    cleanText(obj.summary) ||
    cleanText(obj.content) ||
    cleanText(obj.description) ||
    cleanText(obj.text)
  );
}

function getCardDisplayPoints(card: InterviewCardItem): string[] {
  const payload = (getCardObject(card.final_json) ?? getCardObject(card.generated_json) ?? {}) as Record<
    string,
    unknown
  >;
  const pointSources: unknown[] = [];
  for (const key of ["points", "items", "sub_points", "highlights", "bullets", "children"]) {
    const raw = payload[key];
    if (Array.isArray(raw)) {
      pointSources.push(...raw);
    }
  }

  const structuredTexts = pointSources.map((item) => normalizePointSource(item)).filter(Boolean);
  const rawTexts = structuredTexts;
  const uniquePoints: string[] = [];
  const seen = new Set<string>();

  for (const rawText of rawTexts) {
    const cleaned = rawText.replace(/^\s*(?:\d+[.)]|[-*+•·])\s*/g, "").trim();
    if (!cleaned) {
      continue;
    }
    const normalizedKey = cleaned.replace(/\s+/g, "");
    if (!normalizedKey || seen.has(normalizedKey)) {
      continue;
    }
    seen.add(normalizedKey);
    uniquePoints.push(cleaned);
    if (uniquePoints.length >= 5) {
      break;
    }
  }
  return uniquePoints;
}

function getCardOverviewSummary(card: InterviewCardItem): string {
  const payload = (getCardObject(card.final_json) ?? getCardObject(card.generated_json) ?? {}) as Record<
    string,
    unknown
  >;
  return (
    cleanText(card.card_summary) ||
    cleanText(payload.summary) ||
    cleanText(payload.content) ||
    cleanText(payload.description)
  );
}

function isOverviewCard(card: InterviewCardItem): boolean {
  const payload = (getCardObject(card.final_json) ?? getCardObject(card.generated_json) ?? {}) as Record<
    string,
    unknown
  >;
  return card.card_order === 0 || String(payload.card_type || "").trim().toLowerCase() === "overview";
}

function getCardTheme(index: number): CardTheme {
  return CARD_THEMES[index % CARD_THEMES.length];
}

type CardThemeStyle = CSSProperties & Record<`--${string}`, string>;

function getCardThemeStyle(theme: CardTheme): CardThemeStyle {
  return {
    "--card-accent": theme.accent,
    "--card-accent-soft": theme.accentSoft,
    "--card-accent-pale": theme.accentPale,
    "--card-accent-ink": theme.accentInk,
    "--card-border": theme.border,
    "--card-glow": theme.glow,
    "--card-surface": theme.surface,
    "--card-surface-strong": theme.surfaceStrong,
    "--card-point-bg": theme.pointBg,
    "--card-tag-bg": theme.tagBg,
  };
}

function getCardTags(card: InterviewCardItem): string[] {
  const payload = getCardObject(card.final_json) ?? getCardObject(card.generated_json);
  if (!payload) {
    return [];
  }
  const rawTags = payload.tags;
  if (!Array.isArray(rawTags)) {
    return [];
  }
  return rawTags
    .map((tag) => String(tag || "").trim())
    .filter((tag) => Boolean(tag));
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
  const [cardsRefreshing, setCardsRefreshing] = useState(false);
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

  const handleRefreshCards = async () => {
    try {
      setCardsRefreshing(true);
      const resp = await refreshInterviewCards(interviewId);
      if (resp.generation?.warning) {
        message.warning(resp.generation.warning);
      }
      if (resp.status === "failed") {
        throw new Error(resp.error_message || "刷新卡片失败");
      }
      message.success(`卡片已刷新，共 ${resp.items?.length ?? 0} 张`);
      setReloadToken((v) => v + 1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "刷新卡片失败");
    } finally {
      setCardsRefreshing(false);
    }
  };

  const handleRefreshMinutes = async () => {
    try {
      setMinutesRefreshing(true);
      const resp = await refreshInterviewMinutes(interviewId);
      if (!resp.success) {
        throw new Error(resp.message || "刷新智能纪要失败");
      }
      const minutesChars = resp.minutes_chars ?? 0;
      message.success(
        `智能纪要已刷新：文本长度 ${minutesChars} 字，写入 ${resp.inserted ?? 0} 条`,
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

  const minutesText = useMemo(() => {
    const rawText = data?.minutes?.minutes_text?.trim() || "";
    return rawText ? stripMinutesHighlightsSection(rawText) : "";
  }, [data]);
  const minutesSections = useMemo(() => data?.minutes?.sections ?? [], [data]);

  return (
    <Layout className="min-h-screen summarynotes-notes-page">
      <Header className="summarynotes-hero">
        <div className="summarynotes-hero-layout">
          <div className="summarynotes-hero-inner">
            <div className="summarynotes-hero-copy">
              <Button
                icon={<ArrowLeftOutlined />}
                onClick={() => router.push(`/interviews/${interviewId}`)}
                ghost
                className="summarynotes-hero-back"
              >
                返回访谈
              </Button>
              <Title level={2} className="summarynotes-hero-title">
                全文 Notes #{interviewId > 0 ? interviewId : "无效"}
              </Title>
              <Paragraph className="summarynotes-hero-description">
                这里展示 A / B / C 三段全文 Notes，可直接跳转到编辑页进行修改。
              </Paragraph>
              <div className="summarynotes-hero-tags">
                <Tag color="geekblue">A 卡片</Tag>
                <Tag color="blue">B KBQ Notes</Tag>
                <Tag color="green">C 智能纪要</Tag>
              </div>
            </div>
            <Space wrap className="summarynotes-hero-actions">
              <Button
                icon={<ReloadOutlined />}
                onClick={() => setReloadToken((v) => v + 1)}
                loading={loading}
              >
                刷新页面
              </Button>
              <Button
                icon={<EditOutlined />}
                onClick={() => router.push(`/interviews/${interviewId}/overall-notes/edit`)}
              >
                编辑全文 Notes
              </Button>
              <Button icon={<DownloadOutlined />} onClick={handleExportOverallNotesWord} loading={exporting}>
                导出全文 Notes
              </Button>
              <Button onClick={handleRefreshCards} loading={cardsRefreshing} type="primary">
                刷新卡片
              </Button>
              <Button onClick={handleRefreshMinutes} loading={minutesRefreshing}>
                刷新智能纪要
              </Button>
              <Button onClick={handleRefreshKbqNotes} loading={kbqRefreshing} type="primary">
                刷新 KBQ Notes
              </Button>
            </Space>
          </div>
        </div>
      </Header>
      <Content className="summarynotes-notes-content">
        <div className="summarynotes-notes-frame">
          {loading ? (
            <div className="summarynotes-loading-shell">
              <Spin />
            </div>
          ) : error ? (
            <Alert type="error" message={error} />
          ) : (
            <Space direction="vertical" size="large" style={{ width: "100%" }}>
              <Card className="summarynotes-notes-section-card" title="A. 全文模块总结卡片">
                {data?.cards?.status === "failed" && data?.cards?.error_message ? (
                  <Alert
                    type="error"
                    showIcon
                    message="卡片生成失败"
                    description={data.cards?.error_message}
                    style={{ marginBottom: 16 }}
                  />
                ) : null}
                {data?.cards?.items?.length ? (
                  <div className="summarynotes-cards-grid">
                    {data.cards.items.map((card, index) => {
                      const theme = getCardTheme(index);
                      const overviewCard = isOverviewCard(card);
                      const points = overviewCard ? [] : getCardDisplayPoints(card);
                      const overviewSummary = overviewCard ? getCardOverviewSummary(card) : "";
                      const tags = getCardTags(card);
                      return (
                        <Card
                          key={card.id}
                          size="small"
                          style={{
                            ...getCardThemeStyle(theme),
                            gridColumn: overviewCard ? "1 / -1" : undefined,
                          }}
                          className={`summarynotes-card-preview${overviewCard ? " summarynotes-card-overview" : ""}`}
                        >
                          <div className="summarynotes-card-shell">
                            <div className="summarynotes-card-accent" />
                            <div className="summarynotes-card-body">
                              <div className="summarynotes-card-header">
                                <Title level={5} className="summarynotes-card-title">
                                  {card.card_title}
                                </Title>
                                {tags.length > 0 ? (
                                  <Space wrap size={[8, 8]} className="summarynotes-card-tag-row">
                                    {tags.map((tag) => (
                                      <Tag
                                        key={`${card.id}-${tag}`}
                                        className="summarynotes-card-tag"
                                        style={{
                                          backgroundColor: theme.tagBg,
                                          borderColor: theme.border,
                                          color: theme.accentInk,
                                        }}
                                      >
                                        {tag}
                                      </Tag>
                                  ))}
                                </Space>
                              ) : null}
                            </div>
                              {overviewCard ? (
                                overviewSummary ? (
                                  <Paragraph className="summarynotes-card-overview-summary">
                                    {overviewSummary}
                                  </Paragraph>
                                ) : (
                                  <Text className="summarynotes-card-empty">暂无总览内容。</Text>
                                )
                              ) : points.length > 0 ? (
                                <div className="summarynotes-card-points">
                                  {points.map((point, pointIndex) => (
                                    <div key={`${card.id}-${pointIndex}-${point}`} className="summarynotes-card-point">
                                      <span
                                        className="summarynotes-card-point-dot"
                                        style={{ backgroundColor: theme.accent }}
                                      />
                                      <Text className="summarynotes-card-point-text">{point}</Text>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <Text className="summarynotes-card-empty">暂无可展示要点。</Text>
                              )}
                            </div>
                          </div>
                        </Card>
                      );
                    })}
                  </div>
                ) : (
                  <Text type="secondary">暂无卡片。</Text>
                )}
              </Card>

              <Card className="summarynotes-notes-section-card" title="B. KBQ Notes">
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

              <Card className="summarynotes-notes-section-card" title="C. 智能纪要">
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
      {data?.cards ? (
        <div className="summarynotes-card-export-stage" aria-hidden="true">
          <div className="summarynotes-card-export-shell">
            <OverallNotesCardsSection items={data.cards.items} containerId={OVERALL_NOTES_CARD_EXPORT_ID} />
          </div>
        </div>
      ) : null}
    </Layout>
  );
}
