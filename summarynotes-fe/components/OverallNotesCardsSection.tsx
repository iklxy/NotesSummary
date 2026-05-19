"use client";

import type { CSSProperties } from "react";
import { Card, Space, Tag, Typography } from "antd";
import type { InterviewCardItem } from "../lib/types";

const { Title, Text, Paragraph } = Typography;

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
  const uniquePoints: string[] = [];
  const seen = new Set<string>();
  for (const rawText of structuredTexts) {
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

interface Props {
  items: InterviewCardItem[];
  containerId?: string;
}

export default function OverallNotesCardsSection({ items, containerId }: Props) {
  const grid = (
    <div className="summarynotes-cards-grid">
      {items.length > 0 ? (
        items.map((card, index) => {
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
                      <Paragraph className="summarynotes-card-overview-summary">{overviewSummary}</Paragraph>
                    ) : (
                      <Text className="summarynotes-card-empty">暂无总览内容。</Text>
                    )
                  ) : points.length > 0 ? (
                    <div className="summarynotes-card-points">
                      {points.map((point, pointIndex) => (
                        <div key={`${card.id}-${pointIndex}-${point}`} className="summarynotes-card-point">
                          <span className="summarynotes-card-point-dot" style={{ backgroundColor: theme.accent }} />
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
        })
      ) : (
        <div className="summarynotes-card-empty-shell">
          <Text type="secondary">暂无卡片。</Text>
        </div>
      )}
    </div>
  );

  if (!containerId) {
    return grid;
  }

  return (
    <div className="summarynotes-card-export-frame" id={containerId}>
      {grid}
    </div>
  );
}
