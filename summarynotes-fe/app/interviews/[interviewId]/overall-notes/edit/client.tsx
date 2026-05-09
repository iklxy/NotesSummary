"use client";

import { useEffect, useMemo, useState } from "react";
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
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  DownloadOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import MarkdownContent from "../../../../../components/MarkdownContent";
import {
  exportInterviewOverallNotesWord,
  getInterviewOverallNotes,
  refreshInterviewKbqNotes,
  refreshInterviewMinutes,
  updateInterviewOverallNotesKbq,
  updateInterviewOverallNotesMinutes,
  updateInterviewOverallNotesSummary,
} from "../../../../../lib/interviewsApi";
import type {
  InterviewMinutesResponse,
  InterviewOverallNotesResponse,
  KbqNoteItem,
} from "../../../../../lib/types";

const { Header, Content } = Layout;
const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface Props {
  interviewId: number;
}

interface KbqDimensionDraft {
  dimension: string;
  summary: string;
  analysis: string;
  evidence_text: string;
}

interface KbqDraft {
  summary: string;
  dimension_notes: KbqDimensionDraft[];
}

interface MinutesItemDraft {
  order: number;
  title: string;
  summary: string;
}

interface MinutesSectionDraft {
  order: number;
  title: string;
  summary: string;
  items: MinutesItemDraft[];
}

interface MinutesDraft {
  document_title: string;
  core_summary: string;
  sections: MinutesSectionDraft[];
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

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function evidenceToText(value: unknown): string {
  if (!Array.isArray(value)) {
    return "";
  }
  return value
    .map((item) => {
      if (typeof item === "string") {
        return item.trim();
      }
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        if (typeof record.text === "string" && record.text.trim()) {
          return record.text.trim();
        }
        if (typeof record.content === "string" && record.content.trim()) {
          return record.content.trim();
        }
      }
      return "";
    })
    .filter((item) => item.length > 0)
    .join("\n");
}

function textToEvidence(value: string): Array<{ summary_id: number; speaker: string; text: string }> {
  return splitLines(value).map((text, index) => ({
    summary_id: index + 1,
    speaker: "",
    text,
  }));
}

function createEmptyKbqDimensionDraft(index = 1): KbqDimensionDraft {
  return {
    dimension: `维度 ${index}`,
    summary: "",
    analysis: "",
    evidence_text: "",
  };
}

function createEmptyKbqDraft(): KbqDraft {
  return {
    summary: "",
    dimension_notes: [createEmptyKbqDimensionDraft(1)],
  };
}

function normalizeKbqDraft(noteJson: unknown): KbqDraft {
  const noteObj = getNoteObject(noteJson) ?? {};
  const rawDimensionNotes = noteObj.dimension_notes;
  const dimensionNotes: KbqDimensionDraft[] = [];

  if (Array.isArray(rawDimensionNotes) && rawDimensionNotes.length > 0) {
    rawDimensionNotes.forEach((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return;
      }
      const record = item as Record<string, unknown>;
      dimensionNotes.push({
        dimension: getString(record.dimension) || `维度 ${index + 1}`,
        summary: getString(record.summary),
        analysis: getString(record.analysis),
        evidence_text: evidenceToText(record.evidence),
      });
    });
  }

  if (dimensionNotes.length === 0) {
    dimensionNotes.push({
      dimension: getString(noteObj.dimension) || "维度 1",
      summary: getString(noteObj.summary),
      analysis: getString(noteObj.analysis),
      evidence_text: evidenceToText(noteObj.evidence),
    });
  }

  return {
    summary: getString(noteObj.summary),
    dimension_notes: dimensionNotes,
  };
}

function serializeKbqDraft(baseNoteJson: unknown, draft: KbqDraft): Record<string, unknown> {
  const base = getNoteObject(baseNoteJson) ?? {};
  return {
    ...base,
    summary: draft.summary.trim(),
    dimension_notes: draft.dimension_notes.map((item, index) => ({
      dimension: item.dimension.trim() || `维度 ${index + 1}`,
      summary: item.summary.trim(),
      analysis: item.analysis.trim(),
      evidence: textToEvidence(item.evidence_text),
    })),
  };
}

function createEmptyMinutesItemDraft(order = 1): MinutesItemDraft {
  return {
    order,
    title: "",
    summary: "",
  };
}

function createEmptyMinutesSectionDraft(order = 1): MinutesSectionDraft {
  return {
    order,
    title: `第 ${order} 部分`,
    summary: "",
    items: [createEmptyMinutesItemDraft(1)],
  };
}

function createEmptyMinutesDraft(order = 1): MinutesDraft {
  return {
    document_title: "",
    core_summary: "",
    sections: [createEmptyMinutesSectionDraft(order)],
  };
}

function normalizeMinutesDraft(minutes: InterviewMinutesResponse | null | undefined): MinutesDraft {
  const minutesSource = getNoteObject(minutes?.minutes_json) ?? (minutes as unknown as Record<string, unknown>) ?? {};
  const rawSections = Array.isArray(minutesSource.sections) ? minutesSource.sections : [];
  const sections: MinutesSectionDraft[] = [];

  rawSections.forEach((section, sectionIndex) => {
    if (!section || typeof section !== "object" || Array.isArray(section)) {
      return;
    }
    const record = section as Record<string, unknown>;
    const rawItems = Array.isArray(record.items) ? record.items : [];
    const items: MinutesItemDraft[] = [];
    rawItems.forEach((item, itemIndex) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return;
      }
      const itemRecord = item as Record<string, unknown>;
      items.push({
        order: Number(itemRecord.order) || itemIndex + 1,
        title: getString(itemRecord.title),
        summary: getString(itemRecord.summary),
      });
    });
    sections.push({
      order: Number(record.order) || sectionIndex + 1,
      title: getString(record.title) || `第 ${sectionIndex + 1} 部分`,
      summary: getString(record.summary),
      items: items.length > 0 ? items : [],
    });
  });

  if (sections.length === 0) {
    sections.push(createEmptyMinutesSectionDraft(1));
  }

  return {
    document_title: getString(minutesSource.document_title) || getString(minutes?.document_title),
    core_summary: getString(minutesSource.core_summary) || getString(minutes?.core_summary),
    sections,
  };
}

function serializeMinutesDraft(baseMinutes: InterviewMinutesResponse | null | undefined, draft: MinutesDraft): Record<string, unknown> {
  const base = getNoteObject(baseMinutes?.minutes_json) ?? (baseMinutes as unknown as Record<string, unknown>) ?? {};
  return {
    ...base,
    document_title: draft.document_title.trim(),
    core_summary: draft.core_summary.trim(),
    sections: draft.sections.map((section, sectionIndex) => ({
      order: sectionIndex + 1,
      title: section.title.trim(),
      summary: section.summary.trim(),
      items: section.items.map((item, itemIndex) => ({
        order: itemIndex + 1,
        title: item.title.trim(),
        summary: item.summary.trim(),
      })),
    })),
  };
}

function renderMinutesDraftMarkdown(draft: MinutesDraft): string {
  const lines: string[] = [];
  const documentTitle = draft.document_title.trim();
  if (documentTitle) {
    lines.push(`# ${documentTitle}`);
    lines.push("");
  }

  const coreSummary = draft.core_summary.trim();
  if (coreSummary) {
    lines.push("## 核心总结");
    lines.push(coreSummary);
    lines.push("");
  }

  draft.sections.forEach((section) => {
    const sectionTitle = section.title.trim();
    if (sectionTitle) {
      lines.push(`## 第${section.order}部分：${sectionTitle}`);
    } else {
      lines.push(`## 第${section.order}部分`);
    }

    const sectionSummary = section.summary.trim();
    if (sectionSummary) {
      lines.push(sectionSummary);
    }

    section.items.forEach((item) => {
      const itemTitle = item.title.trim();
      const itemSummary = item.summary.trim();
      if (itemTitle && itemSummary) {
        lines.push(`${item.order}. ${itemTitle}：${itemSummary}`);
      } else if (itemTitle) {
        lines.push(`${item.order}. ${itemTitle}`);
      } else if (itemSummary) {
        lines.push(`${item.order}. ${itemSummary}`);
      }
    });

    lines.push("");
  });

  return lines.join("\n").trim();
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

function getKbqSummary(noteJson: unknown): string {
  const noteObj = getNoteObject(noteJson);
  if (!noteObj) {
    return "";
  }
  return getString(noteObj.summary);
}

function buildKbqDraftMap(items: KbqNoteItem[]): Record<number, KbqDraft> {
  return items.reduce<Record<number, KbqDraft>>((acc, item) => {
    acc[item.id] = normalizeKbqDraft(item.note_json);
    return acc;
  }, {});
}

function updateArrayItem<T>(items: T[], index: number, updater: (value: T) => T): T[] {
  return items.map((item, itemIndex) => (itemIndex === index ? updater(item) : item));
}

function removeArrayItem<T>(items: T[], index: number): T[] {
  return items.filter((_, itemIndex) => itemIndex !== index);
}

function getKbqLabel(item: KbqNoteItem): string {
  return `${item.bq_order}. ${item.bq_text}`;
}

export default function OverallNotesEditClient({ interviewId }: Props) {
  const router = useRouter();
  const [data, setData] = useState<InterviewOverallNotesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [kbqRefreshing, setKbqRefreshing] = useState(false);
  const [minutesRefreshing, setMinutesRefreshing] = useState(false);
  const [savingSummary, setSavingSummary] = useState(false);
  const [savingKbq, setSavingKbq] = useState(false);
  const [savingMinutes, setSavingMinutes] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [summaryDraft, setSummaryDraft] = useState("");
  const [kbqDrafts, setKbqDrafts] = useState<Record<number, KbqDraft>>({});
  const [selectedKbqId, setSelectedKbqId] = useState<number | null>(null);
  const [minutesDraft, setMinutesDraft] = useState<MinutesDraft>(createEmptyMinutesDraft(1));

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await getInterviewOverallNotes(interviewId);
        setData(resp);
        setSummaryDraft(resp.note_content || "");
        setKbqDrafts(buildKbqDraftMap(resp.kbq_notes?.items ?? []));
        setSelectedKbqId(resp.kbq_notes?.items?.[0]?.id ?? null);
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

  const kbqItems = useMemo(() => data?.kbq_notes?.items ?? [], [data]);
  const selectedKbqItem = useMemo(() => {
    if (selectedKbqId === null) {
      return null;
    }
    return kbqItems.find((item) => item.id === selectedKbqId) ?? null;
  }, [kbqItems, selectedKbqId]);
  const selectedKbqDraft = useMemo(() => {
    if (!selectedKbqItem) {
      return null;
    }
    return kbqDrafts[selectedKbqItem.id] ?? normalizeKbqDraft(selectedKbqItem.note_json);
  }, [kbqDrafts, selectedKbqItem]);
  const previewKbqItems = useMemo(() => {
    return kbqItems.map((item) => {
      if (item.id !== selectedKbqId || !selectedKbqDraft) {
        return item;
      }
      return {
        ...item,
        note_json: serializeKbqDraft(item.note_json, selectedKbqDraft),
      };
    });
  }, [kbqItems, selectedKbqDraft, selectedKbqId]);
  const summaryPreview = summaryDraft.trim();
  const minutesPreviewMarkdown = useMemo(() => renderMinutesDraftMarkdown(minutesDraft), [minutesDraft]);

  const updateSelectedKbqDraft = (updater: (draft: KbqDraft) => KbqDraft) => {
    if (selectedKbqId === null) {
      return;
    }
    setKbqDrafts((prev) => {
      const current = prev[selectedKbqId] ?? createEmptyKbqDraft();
      return {
        ...prev,
        [selectedKbqId]: updater(current),
      };
    });
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

  const handleRefreshKbqNotes = async () => {
    try {
      setKbqRefreshing(true);
      const resp = await refreshInterviewKbqNotes(interviewId);
      if (!resp.success) {
        throw new Error(resp.message || "刷新 KBQ Notes 失败");
      }
      message.success("KBQ Notes 已刷新");
      setReloadToken((value) => value + 1);
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
      message.success("智能纪要已刷新");
      setReloadToken((value) => value + 1);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "刷新智能纪要失败");
    } finally {
      setMinutesRefreshing(false);
    }
  };

  const handleSaveSummary = async () => {
    try {
      setSavingSummary(true);
      const resp = await updateInterviewOverallNotesSummary(interviewId, summaryDraft);
      message.success("A 区块已保存");
      setSummaryDraft(resp.note_content ?? summaryDraft);
      setData((prev) => (prev ? { ...prev, note_content: resp.note_content ?? summaryDraft } : prev));
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存 A 区块失败");
    } finally {
      setSavingSummary(false);
    }
  };

  const handleSaveKbq = async () => {
    if (!selectedKbqItem) {
      message.info("请先选择一条 KBQ");
      return;
    }
    try {
      setSavingKbq(true);
      const draft = selectedKbqDraft ?? createEmptyKbqDraft();
      const savedNoteJson = serializeKbqDraft(selectedKbqItem.note_json, draft);
      const resp = await updateInterviewOverallNotesKbq(interviewId, selectedKbqItem.id, savedNoteJson);
      const nextNoteJson = resp.note_json ?? savedNoteJson;
      message.success(`KBQ「${selectedKbqItem.bq_order}」已保存`);
      setKbqDrafts((prev) => ({
        ...prev,
        [selectedKbqItem.id]: normalizeKbqDraft(nextNoteJson),
      }));
      setData((prev) =>
        prev
          ? {
              ...prev,
              kbq_notes: {
                ...prev.kbq_notes,
                items: prev.kbq_notes.items.map((item) =>
                  item.id === selectedKbqItem.id ? { ...item, note_json: nextNoteJson } : item,
                ),
              },
            }
          : prev,
      );
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存 KBQ Notes 失败");
    } finally {
      setSavingKbq(false);
    }
  };

  const handleSaveMinutes = async () => {
    try {
      setSavingMinutes(true);
      const savedMinutesJson = serializeMinutesDraft(data?.minutes, minutesDraft);
      const resp = await updateInterviewOverallNotesMinutes(interviewId, savedMinutesJson);
      const nextMinutesJson = resp.minutes_json ?? savedMinutesJson;
      message.success("C 区块已保存");
      const nextMinutes = normalizeMinutesDraft({
        ...data?.minutes,
        minutes_json: nextMinutesJson,
      } as InterviewMinutesResponse);
      setMinutesDraft(nextMinutes);
      setData((prev) =>
        prev
          ? {
              ...prev,
              minutes: {
                ...prev.minutes,
                document_title: nextMinutes.document_title,
                core_summary: nextMinutes.core_summary,
                minutes_text: renderMinutesDraftMarkdown(nextMinutes),
                sections: nextMinutes.sections.map((section) => ({
                  order: section.order,
                  title: section.title,
                  summary: section.summary,
                  items: section.items,
                })),
                minutes_json: nextMinutesJson,
              },
            }
          : prev,
      );
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存智能纪要失败");
    } finally {
      setSavingMinutes(false);
    }
  };

  const selectedKbqDraftValue = selectedKbqDraft ?? createEmptyKbqDraft();

  const addKbqDimension = () => {
    updateSelectedKbqDraft((draft) => ({
      ...draft,
      dimension_notes: [...draft.dimension_notes, createEmptyKbqDimensionDraft(draft.dimension_notes.length + 1)],
    }));
  };

  const removeKbqDimension = (index: number) => {
    updateSelectedKbqDraft((draft) => {
      if (draft.dimension_notes.length <= 1) {
        return draft;
      }
      return {
        ...draft,
        dimension_notes: removeArrayItem(draft.dimension_notes, index),
      };
    });
  };

  const updateKbqDimension = (index: number, field: keyof KbqDimensionDraft, value: string) => {
    updateSelectedKbqDraft((draft) => ({
      ...draft,
      dimension_notes: updateArrayItem(draft.dimension_notes, index, (item) => ({
        ...item,
        [field]: value,
      })),
    }));
  };

  const addMinutesSection = () => {
    setMinutesDraft((draft) => ({
      ...draft,
      sections: [...draft.sections, createEmptyMinutesSectionDraft(draft.sections.length + 1)],
    }));
  };

  const removeMinutesSection = (index: number) => {
    setMinutesDraft((draft) => {
      if (draft.sections.length <= 1) {
        return draft;
      }
      return {
        ...draft,
        sections: removeArrayItem(draft.sections, index).map((section, nextIndex) => ({
          ...section,
          order: nextIndex + 1,
        })),
      };
    });
  };

  const updateMinutesSection = (index: number, field: keyof Omit<MinutesSectionDraft, "items">, value: string) => {
    setMinutesDraft((draft) => ({
      ...draft,
      sections: updateArrayItem(draft.sections, index, (section) => ({
        ...section,
        [field]: value,
      })),
    }));
  };

  const addMinutesItem = (sectionIndex: number) => {
    setMinutesDraft((draft) => ({
      ...draft,
      sections: updateArrayItem(draft.sections, sectionIndex, (section) => ({
        ...section,
        items: [...section.items, createEmptyMinutesItemDraft(section.items.length + 1)],
      })),
    }));
  };

  const removeMinutesItem = (sectionIndex: number, itemIndex: number) => {
    setMinutesDraft((draft) => ({
      ...draft,
      sections: updateArrayItem(draft.sections, sectionIndex, (section) => {
        if (section.items.length <= 1) {
          return section;
        }
        return {
          ...section,
          items: removeArrayItem(section.items, itemIndex).map((item, nextIndex) => ({
            ...item,
            order: nextIndex + 1,
          })),
        };
      }),
    }));
  };

  const updateMinutesItem = (
    sectionIndex: number,
    itemIndex: number,
    field: keyof MinutesItemDraft,
    value: string,
  ) => {
    setMinutesDraft((draft) => ({
      ...draft,
      sections: updateArrayItem(draft.sections, sectionIndex, (section) => ({
        ...section,
        items: updateArrayItem(section.items, itemIndex, (item) => ({
          ...item,
          [field]: value,
        })),
      })),
    }));
  };

  return (
    <Layout className="min-h-screen summarynotes-notes-page">
      <Header className="summarynotes-hero summarynotes-hero-notes-edit">
        <div className="summarynotes-hero-layout">
          <div className="summarynotes-hero-badge">SUMMARYNOTES</div>
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
                A / B / C 三个区块都可以单独修改。这里采用表单式编辑，不需要直接接触 JSON。
              </Paragraph>
              <div className="summarynotes-hero-tags">
                <Tag color="cyan">A 访谈总览</Tag>
                <Tag color="geekblue">B KBQ Notes</Tag>
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
              <Card className="summarynotes-notes-section-card" title="A. 访谈总览 Summary Notes">
                <Row gutter={[20, 20]}>
                  <Col xs={24} lg={14}>
                    <div className="summarynotes-notes-preview-panel">
                      {summaryPreview ? (
                        <MarkdownContent content={summaryPreview} />
                      ) : (
                        <Text type="secondary">暂无整体 summary notes。</Text>
                      )}
                    </div>
                  </Col>
                  <Col xs={24} lg={10}>
                    <div className="summarynotes-notes-editor-panel">
                      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                        <div>
                          <Text className="summarynotes-panel-label">编辑 A 区块</Text>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            直接像写文档一样编辑整体 summary notes。
                          </Paragraph>
                        </div>
                        <TextArea
                          value={summaryDraft}
                          onChange={(event) => setSummaryDraft(event.target.value)}
                          rows={16}
                          placeholder="请输入整体 summary notes"
                          className="summarynotes-json-editor"
                        />
                        <div className="summarynotes-editor-actions">
                          <Button
                            type="primary"
                            icon={<SaveOutlined />}
                            onClick={() => void handleSaveSummary()}
                            loading={savingSummary}
                          >
                            保存 A 区块
                          </Button>
                        </div>
                      </Space>
                    </div>
                  </Col>
                </Row>
              </Card>

              <Card className="summarynotes-notes-section-card" title="B. KBQ Notes">
                <Row gutter={[20, 20]}>
                  <Col xs={24} lg={14}>
                    <div className="summarynotes-notes-preview-panel">
                      {previewKbqItems.length > 0 ? (
                        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                          {previewKbqItems.map((item) => {
                            const dimensionNotes = getKbqDimensionNotes(item.note_json);
                            const isSelected = item.id === selectedKbqId;
                            return (
                              <Card
                                key={item.id}
                                size="small"
                                className="summarynotes-edit-preview-card"
                                style={{
                                  borderRadius: 18,
                                  borderColor: isSelected ? "rgba(14, 165, 233, 0.58)" : undefined,
                                  boxShadow: isSelected
                                    ? "0 18px 40px -26px rgba(14,165,233,0.38)"
                                    : undefined,
                                }}
                                extra={
                                  <Button type="link" onClick={() => setSelectedKbqId(item.id)}>
                                    编辑
                                  </Button>
                                }
                              >
                                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                  <Space wrap>
                                    <Text strong>
                                      {item.bq_order}. {item.bq_text}
                                    </Text>
                                    {isSelected ? <Text type="secondary">当前编辑</Text> : null}
                                  </Space>
                                  {getKbqSummary(item.note_json) ? (
                                    <Paragraph style={{ marginBottom: 0 }}>
                                      {getKbqSummary(item.note_json)}
                                    </Paragraph>
                                  ) : null}
                                  {dimensionNotes.length > 0 ? (
                                    <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                      {dimensionNotes.map((dimensionNote, index) => {
                                        const dimensionName =
                                          typeof dimensionNote.dimension === "string"
                                            ? dimensionNote.dimension
                                            : `维度 ${index + 1}`;
                                        const summaryText =
                                          typeof dimensionNote.summary === "string" ? dimensionNote.summary : "";
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
                                              <Text type="secondary">该维度暂无可展示的摘要。</Text>
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
                    </div>
                  </Col>
                  <Col xs={24} lg={10}>
                    <div className="summarynotes-notes-editor-panel">
                      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                        <div>
                          <Text className="summarynotes-panel-label">编辑 B 区块</Text>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            先选择要修改的 Key BQ，再逐条编辑维度摘要、分析和证据。
                          </Paragraph>
                        </div>

                        <Select
                          value={selectedKbqId ?? undefined}
                          onChange={(value) => setSelectedKbqId(value)}
                          options={kbqItems.map((item) => ({
                            value: item.id,
                            label: getKbqLabel(item),
                          }))}
                          placeholder="请选择要编辑的 Key BQ"
                          disabled={kbqItems.length === 0}
                        />

                        {selectedKbqItem ? (
                          <>
                            <div className="summarynotes-edit-form-block">
                              <Text className="summarynotes-panel-label" style={{ marginBottom: 6 }}>
                                整体说明
                              </Text>
                              <TextArea
                                value={selectedKbqDraftValue.summary}
                                onChange={(event) => {
                                  const value = event.target.value;
                                  updateSelectedKbqDraft((draft) => ({
                                    ...draft,
                                    summary: value,
                                  }));
                                }}
                                rows={4}
                                placeholder="可选：填写这条 Key BQ 的整体说明"
                              />
                            </div>

                            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                              {selectedKbqDraftValue.dimension_notes.map((dimension, index) => (
                                <Card
                                  key={`${selectedKbqItem.id}-dimension-${index}`}
                                  size="small"
                                  className="summarynotes-edit-preview-card"
                                  title={`维度 ${index + 1}`}
                                  extra={
                                    <Button
                                      type="link"
                                      danger
                                      icon={<DeleteOutlined />}
                                      onClick={() => removeKbqDimension(index)}
                                      disabled={selectedKbqDraftValue.dimension_notes.length <= 1}
                                    >
                                      删除
                                    </Button>
                                  }
                                >
                                  <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                    <Input
                                      value={dimension.dimension}
                                      onChange={(event) => {
                                        updateKbqDimension(index, "dimension", event.target.value);
                                      }}
                                      placeholder="维度名称"
                                    />
                                    <TextArea
                                      value={dimension.summary}
                                      onChange={(event) => {
                                        updateKbqDimension(index, "summary", event.target.value);
                                      }}
                                      rows={4}
                                      placeholder="维度摘要"
                                    />
                                    <TextArea
                                      value={dimension.analysis}
                                      onChange={(event) => {
                                        updateKbqDimension(index, "analysis", event.target.value);
                                      }}
                                      rows={3}
                                      placeholder="补充分析说明"
                                    />
                                    <TextArea
                                      value={dimension.evidence_text}
                                      onChange={(event) => {
                                        updateKbqDimension(index, "evidence_text", event.target.value);
                                      }}
                                      rows={3}
                                      placeholder="证据说明，每行一条"
                                    />
                                  </Space>
                                </Card>
                              ))}
                            </Space>

                            <Space wrap>
                              <Button icon={<PlusOutlined />} onClick={addKbqDimension}>
                                增加维度
                              </Button>
                            </Space>

                            <Text type="secondary" style={{ fontSize: 12 }}>
                              保存后会覆盖当前 KBQ Notes，但会保留未修改的其他字段。
                            </Text>

                            <div className="summarynotes-editor-actions">
                              <Button
                                type="primary"
                                icon={<SaveOutlined />}
                                onClick={() => void handleSaveKbq()}
                                loading={savingKbq}
                              >
                                保存 B 区块
                              </Button>
                            </div>
                          </>
                        ) : (
                          <Alert type="info" showIcon message="当前没有可编辑的 KBQ" />
                        )}
                      </Space>
                    </div>
                  </Col>
                </Row>
              </Card>

              <Card className="summarynotes-notes-section-card" title="C. 智能纪要">
                <Row gutter={[20, 20]}>
                  <Col xs={24} lg={14}>
                    <div className="summarynotes-notes-preview-panel">
                      {minutesPreviewMarkdown ? (
                        <MarkdownContent content={minutesPreviewMarkdown} />
                      ) : (
                        <Text type="secondary">暂无智能纪要。</Text>
                      )}
                    </div>
                  </Col>
                  <Col xs={24} lg={10}>
                    <div className="summarynotes-notes-editor-panel">
                      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                        <div>
                          <Text className="summarynotes-panel-label">编辑 C 区块</Text>
                          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                            这里按章节和小点逐层编辑智能纪要。
                          </Paragraph>
                        </div>

                        <div className="summarynotes-edit-form-block">
                          <Text className="summarynotes-panel-label" style={{ marginBottom: 6 }}>
                            文档标题
                          </Text>
                          <Input
                            value={minutesDraft.document_title}
                            onChange={(event) => {
                              setMinutesDraft((draft) => ({
                                ...draft,
                                document_title: event.target.value,
                              }));
                            }}
                            placeholder="例如：访谈智能纪要"
                          />
                        </div>

                        <div className="summarynotes-edit-form-block">
                          <Text className="summarynotes-panel-label" style={{ marginBottom: 6 }}>
                            核心总结
                          </Text>
                          <TextArea
                            value={minutesDraft.core_summary}
                            onChange={(event) => {
                              setMinutesDraft((draft) => ({
                                ...draft,
                                core_summary: event.target.value,
                              }));
                            }}
                            rows={4}
                            placeholder="简要填写智能纪要的核心总结"
                          />
                        </div>

                        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                          {minutesDraft.sections.map((section, sectionIndex) => (
                            <Card
                              key={`minutes-section-${sectionIndex}`}
                              size="small"
                              className="summarynotes-edit-preview-card"
                              title={`章节 ${section.order}`}
                              extra={
                                <Button
                                  type="link"
                                  danger
                                  icon={<DeleteOutlined />}
                                  onClick={() => removeMinutesSection(sectionIndex)}
                                  disabled={minutesDraft.sections.length <= 1}
                                >
                                  删除
                                </Button>
                              }
                            >
                              <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                <Input
                                  value={section.title}
                                  onChange={(event) => {
                                    updateMinutesSection(sectionIndex, "title", event.target.value);
                                  }}
                                  placeholder="章节标题"
                                />
                                <TextArea
                                  value={section.summary}
                                  onChange={(event) => {
                                    updateMinutesSection(sectionIndex, "summary", event.target.value);
                                  }}
                                  rows={3}
                                  placeholder="章节摘要"
                                />

                                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                  {section.items.map((item, itemIndex) => (
                                    <Card
                                      key={`minutes-section-${sectionIndex}-item-${itemIndex}`}
                                      size="small"
                                      style={{
                                        borderRadius: 14,
                                        background: "#fafafa",
                                        borderColor: "#ececec",
                                      }}
                                      title={`小点 ${item.order}`}
                                      extra={
                                        <Button
                                          type="link"
                                          danger
                                          icon={<DeleteOutlined />}
                                          onClick={() => removeMinutesItem(sectionIndex, itemIndex)}
                                          disabled={section.items.length <= 1}
                                        >
                                          删除
                                        </Button>
                                      }
                                    >
                                      <Space direction="vertical" size="small" style={{ width: "100%" }}>
                                        <Input
                                          value={item.title}
                                          onChange={(event) => {
                                            updateMinutesItem(sectionIndex, itemIndex, "title", event.target.value);
                                          }}
                                          placeholder="小点标题"
                                        />
                                        <TextArea
                                          value={item.summary}
                                          onChange={(event) => {
                                            updateMinutesItem(sectionIndex, itemIndex, "summary", event.target.value);
                                          }}
                                          rows={3}
                                          placeholder="小点摘要"
                                        />
                                      </Space>
                                    </Card>
                                  ))}
                                </Space>

                                <Button
                                  icon={<PlusOutlined />}
                                  onClick={() => addMinutesItem(sectionIndex)}
                                  type="dashed"
                                >
                                  增加小点
                                </Button>
                              </Space>
                            </Card>
                          ))}
                        </Space>

                        <Button icon={<PlusOutlined />} onClick={addMinutesSection} type="dashed">
                          增加章节
                        </Button>

                        <Text type="secondary" style={{ fontSize: 12 }}>
                          右侧预览会实时同步当前编辑内容。
                        </Text>

                        <div className="summarynotes-editor-actions">
                          <Button
                            type="primary"
                            icon={<SaveOutlined />}
                            onClick={() => void handleSaveMinutes()}
                            loading={savingMinutes}
                          >
                            保存 C 区块
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
