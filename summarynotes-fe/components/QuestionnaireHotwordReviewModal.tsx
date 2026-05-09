"use client";

import { useMemo, useState } from "react";
import { Button, Input, Modal, Space, Typography } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import type { QuestionnaireHotwordCandidate } from "../lib/types";

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  title?: string;
  description?: string;
  interviewName?: string;
  candidates: QuestionnaireHotwordCandidate[];
  loading?: boolean;
  confirmText?: string;
  cancelText?: string;
  onCancel: () => void;
  onConfirm: (hotwords: string[]) => Promise<void> | void;
}

export default function QuestionnaireHotwordReviewModal({
  open,
  title,
  description,
  interviewName,
  candidates,
  loading,
  confirmText,
  cancelText,
  onCancel,
  onConfirm,
}: Props) {
  const initialItems = useMemo(() => {
    return (candidates.length > 0 ? candidates : [{ term: "", normalized_term: "" } as QuestionnaireHotwordCandidate]).map(
      (item) => (item.normalized_term || item.term || "").trim(),
    );
  }, [candidates]);

  return (
    <HotwordReviewEditor
      key={`${open ? "open" : "closed"}-${initialItems.join("|")}`}
      open={open}
      title={title}
      description={description}
      interviewName={interviewName}
      candidates={candidates}
      initialItems={initialItems}
      loading={loading}
      confirmText={confirmText}
      cancelText={cancelText}
      onCancel={onCancel}
      onConfirm={onConfirm}
    />
  );
}

interface EditorProps {
  open: boolean;
  title?: string;
  description?: string;
  interviewName?: string;
  candidates: QuestionnaireHotwordCandidate[];
  initialItems: string[];
  loading?: boolean;
  confirmText?: string;
  cancelText?: string;
  onCancel: () => void;
  onConfirm: (hotwords: string[]) => Promise<void> | void;
}

function HotwordReviewEditor({
  open,
  title,
  description,
  interviewName,
  candidates,
  initialItems,
  loading,
  confirmText,
  cancelText,
  onCancel,
  onConfirm,
}: EditorProps) {
  const [items, setItems] = useState<string[]>(initialItems);

  const updateItem = (index: number, value: string) => {
    setItems((prev) => prev.map((item, idx) => (idx === index ? value : item)));
  };

  const addItem = () => {
    setItems((prev) => [...prev, ""]);
  };

  const deleteItem = (index: number) => {
    setItems((prev) => prev.filter((_, idx) => idx !== index));
  };

  const submit = async () => {
    const normalized = Array.from(
      new Set(
        items
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    );
    await onConfirm(normalized);
  };

  return (
    <Modal
      open={open}
      title={title || `问卷热词确认${interviewName ? ` - ${interviewName}` : ""}`}
      width={960}
      onCancel={onCancel}
      onOk={() => {
        void submit();
      }}
      okText={confirmText || "确认并启动"}
      cancelText={cancelText || "稍后处理"}
      confirmLoading={loading}
      destroyOnHidden
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Paragraph style={{ marginBottom: 0 }}>
          {description ||
            "系统已从问卷中抽取候选热词。你可以直接修改、删除或追加条目；确认后将保存并继续后续处理。"}
        </Paragraph>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 420, overflow: "auto" }}>
          {items.map((item, index) => {
            const candidate = candidates[index];
            return (
              <div
                key={`${index}-${candidate?.normalized_term ?? candidate?.term ?? "draft"}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto",
                  gap: 8,
                  alignItems: "start",
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <Input
                    value={item}
                    onChange={(e) => updateItem(index, e.target.value)}
                    placeholder="请输入热词"
                  />
                  {(candidate?.reason || candidate?.confidence != null) && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {candidate?.reason ? `原因：${candidate.reason}` : ""}
                      {candidate?.reason && candidate?.confidence != null ? "，" : ""}
                      {candidate?.confidence != null ? `置信度：${candidate.confidence}` : ""}
                    </Text>
                  )}
                </div>
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => deleteItem(index)}
                  disabled={items.length <= 1}
                >
                  删除
                </Button>
              </div>
            );
          })}
        </div>
        <Button icon={<PlusOutlined />} onClick={addItem}>
          增加一个词
        </Button>
      </Space>
    </Modal>
  );
}
